#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Generate or verify the private calibration corpus ``calib-v1`` (``docs/CALIB_V1.md``).

A dedicated script: ``scripts/select_sources.py`` and every existing corpus regenerate exactly as
before. Selection takes its own seed and excludes the patients of review sets 1 and 2. T1 patients
are not excluded: T1's source list also carries strata and diagnoses, so it is not read.

Examples::

    python scripts/generate_calib_corpus.py --set2-sources <file> --nstdb-dir <dir> --out <dir>
    python scripts/generate_calib_corpus.py --set2-sources <file> --out <dir> --verify
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import tempfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np
import wfdb

from artefaux.benchmark import NOISE_TYPES, NSTDB_RESAMPLED_LEN
from artefaux.build import DEFAULT_NSTDB_DIR, DEFAULT_PTBXL_DIR
from artefaux.calib import (
    CALIB_ID,
    CALIB_VERSION,
    MASTER_SEED,
    NSTDB_CHANNEL,
    NSTDB_MIN_START,
    OFFSET_SEED,
    SELECTION_SEED,
    bind_parents,
    calib_plan,
    development_patients,
    labels_csv_text,
    segment_provider,
    select_calib_sources,
    verify_labels_file,
    verify_record,
)
from artefaux.constants import TARGET_FS
from artefaux.loaders import load_nstdb_noise, load_wfdb_parent
from artefaux.manifest import Manifest, ManifestEntry
from artefaux.provenance import Provenance, sha256_file
from artefaux.ptbxl_curator import record_classes
from artefaux.recipes import build_record
from artefaux.writer import write_wfdb

REPO = Path(__file__).resolve().parents[1]
SET1_ID_FILES = (
    REPO / "recipes" / "source_ids" / "ptbxl_clean.csv",
    REPO / "recipes" / "source_ids" / "ptbxl_noisy.csv",
)
INT16_LIMIT_MV = 32.766
#: sha256 of ``checksums.csv`` as frozen in ``docs/CALIB_V1.md``: the corpus's identity.
FROZEN_CHECKSUMS_SHA256 = "db07d86d0e1f7e26162d8aee9769e6f1766c73c0e0d58d92e5a8ef9357a01405"
BANDS_HZ = {"<0.5": (0.0, 0.5), "0.5-15": (0.5, 15.0), "15-40": (15.0, 40.0), ">40": (40.0, 250.0)}
RECORD_COLUMNS = (
    "record_id",
    "split",
    "family",
    "stratum",
    "cell",
    "reader_evidence",
    "source_record_id",
    "patient_id",
    "scp_classes",
    "ptbxl_quality_flags",
)


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, columns, rows) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _bound_plan(args, metadata):
    excluded = development_patients(metadata, SET1_ID_FILES, args.set2_sources)
    clean, natural = select_calib_sources(metadata, excluded_patients=excluded, seed=SELECTION_SEED)
    return bind_parents(calib_plan(), clean, natural, seed=SELECTION_SEED), excluded


def _git_commit() -> str:
    out = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain", "src", "scripts"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return out + ("+dirty" if dirty else "")


def _noise_band_power(nstdb_dir: Path) -> dict:
    """Median per-10-s power fractions by band, on the basis the SNR is set (median removed).

    Compares the region and channel calib-v1 draws from with what set 1 drew from, because a
    nominal SNR means less in-band noise when more of the power sits below 0.5 Hz.
    """
    regions = {
        "ch0_below_100000": (0, 0, 100_000),
        "ch1_from_300000": (NSTDB_CHANNEL, NSTDB_MIN_START, NSTDB_RESAMPLED_LEN),
    }
    freqs = np.fft.rfftfreq(5000, 1.0 / TARGET_FS)
    masks = {band: (freqs > lo) & (freqs <= hi) for band, (lo, hi) in BANDS_HZ.items()}
    masks["<0.5"] = freqs <= 0.5
    out = {}
    for noise in NOISE_TYPES:
        for name, (channel, low, high) in regions.items():
            x = load_nstdb_noise(
                nstdb_dir / noise, noise, NSTDB_RESAMPLED_LEN, channel=channel
            ).signal
            spectra = []
            for start in range(low, high - 5000 + 1, 5000):
                seg = x[start : start + 5000]
                power = np.abs(np.fft.rfft(seg - np.median(seg))) ** 2
                spectra.append({band: power[m].sum() / power.sum() for band, m in masks.items()})
            out[f"{noise}/{name}"] = {
                band: round(float(np.median([s[band] for s in spectra])), 3) for band in masks
            }
    return out


def generate(args) -> None:
    out = args.out
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; refusing to overwrite a frozen corpus")
    records, labels = out / "records", out / "labels"
    labels.mkdir(parents=True)
    metadata = _read_csv(args.ptbxl_dir / "ptbxl_database.csv")
    plan, excluded = _bound_plan(args, metadata)
    by_file = {r["filename_hr"]: r for r in metadata}

    # Frozen before anything else runs, and independent of any signal.
    (out / "labels.csv").write_text(labels_csv_text(plan), newline="")
    (out / "recipes.json").write_text(
        json.dumps([asdict(e.spec) for e in plan], indent=2, sort_keys=True) + "\n"
    )

    provenance = Provenance(master_seed=MASTER_SEED)
    provenance.sources = [s for s in provenance.sources if s.dataset in ("ptbxl", "nstdb")]
    for name, path in (
        ("ptbxl_metadata", args.ptbxl_dir / "ptbxl_database.csv"),
        ("set1_clean_ids", SET1_ID_FILES[0]),
        ("set1_noisy_ids", SET1_ID_FILES[1]),
        ("set2_sources", args.set2_sources),
        ("calib_definition", REPO / "src/artefaux/calib.py"),
        ("recipe_interpreter", REPO / "src/artefaux/recipes.py"),
        ("generation_script", Path(__file__)),
    ):
        provenance.record_source_hash(name, path)
    for noise in NOISE_TYPES:
        for suffix in (".hea", ".dat"):
            provenance.record_source_hash(
                f"nstdb/{noise}{suffix}", args.nstdb_dir / f"{noise}{suffix}"
            )

    def load(noise_type: str, channel: int) -> np.ndarray:
        return load_nstdb_noise(
            args.nstdb_dir / noise_type, noise_type, NSTDB_RESAMPLED_LEN, channel=channel
        ).signal

    provider = segment_provider(load)
    manifest = Manifest()
    index_rows, sums, checks = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for count, entry in enumerate(plan, start=1):
            spec = entry.spec
            source_path = args.ptbxl_dir / spec.source.record_id
            parent = load_wfdb_parent(source_path, "ptbxl").signal
            if parent.shape != (12, 5000):
                raise ValueError(f"{source_path}: expected a 10 s, 12-lead, 500 Hz parent")
            for suffix in (".hea", ".dat"):
                provenance.record_source_hash(
                    f"ptbxl/{spec.source.record_id}{suffix}", source_path.with_suffix(suffix)
                )
            signal, label = build_record(
                parent, spec, MASTER_SEED, TARGET_FS, noise_provider=provider
            )
            if not np.isfinite(signal).all() or np.max(np.abs(signal)) > INT16_LIMIT_MV:
                raise ValueError(f"{spec.record_id}: non-finite samples or int16 overload")
            write_wfdb(spec.record_id, signal, TARGET_FS, records)
            write_wfdb("parent", parent, TARGET_FS, tmp_dir)
            saved = wfdb.rdrecord(str(records / spec.record_id)).p_signal.T
            clean_saved = wfdb.rdrecord(str(tmp_dir / "parent")).p_signal.T
            checks.append(verify_record(entry, label, saved, clean_saved))
            label.write(labels / f"{spec.record_id}.json")
            manifest.add(ManifestEntry.from_label(label))
            row = by_file[spec.source.record_id]
            index_rows.append(
                {
                    "record_id": spec.record_id,
                    "split": entry.split,
                    "family": entry.family,
                    "stratum": entry.stratum,
                    "cell": entry.cell,
                    "reader_evidence": entry.reader_evidence,
                    "source_record_id": spec.source.record_id,
                    "patient_id": row["patient_id"],
                    "scp_classes": ";".join(record_classes(row)),
                    "ptbxl_quality_flags": "|".join(spec.source.ptbxl_quality_flags),
                }
            )
            for suffix in (".hea", ".dat"):
                sums.append(
                    {
                        "file": f"records/{spec.record_id}{suffix}",
                        "sha256": sha256_file(records / f"{spec.record_id}{suffix}"),
                    }
                )
            if count % 50 == 0 or count == len(plan):
                print(f"Generated and verified {count}/{len(plan)}", flush=True)
    manifest.write_json(out / "manifest.json")
    manifest.write_csv(out / "manifest.csv")
    provenance.write(out / "provenance.json")
    _write_csv(out / "records.csv", RECORD_COLUMNS, index_rows)
    _write_csv(out / "checksums.csv", ("file", "sha256"), sums)
    patients = [r["patient_id"] for r in index_rows]
    if len(set(patients)) != len(plan) or set(patients) & excluded:
        raise ValueError("a patient repeats or belongs to a development set")
    segments = [
        (e.split, s["noise_type"], s["noise_source"]["start_sample"])
        for e in plan
        for s in e.spec.steps
        if s["op"] == "nstdb_mix"
    ]
    (out / "verification.json").write_text(
        json.dumps(
            {
                "calib_id": CALIB_ID,
                "calib_version": CALIB_VERSION,
                "git_commit": _git_commit(),
                "master_seed": MASTER_SEED,
                "selection_seed": SELECTION_SEED,
                "offset_seed": OFFSET_SEED,
                "labels_sha256": sha256_file(out / "labels.csv"),
                "n_records": len(plan),
                "n_distinct_patients": len(set(patients)),
                "patient_overlap_with_review_sets": len(set(patients) & excluded),
                "t1_patients_excluded": False,
                "split_counts": Counter(e.split for e in plan),
                "all_untargeted_samples_bit_identical": True,
                "max_post_storage_snr_error_db": max(c["snr_error_db"] for c in checks),
                "max_electrode_rms_error": max(c["electrode_rms_error"] for c in checks),
                "max_pairwise_noise_corr": max(c["max_noise_corr"] for c in checks),
                "median_pairwise_noise_corr_max": float(
                    np.median([c["max_noise_corr"] for c in checks if c["max_noise_corr"]])
                ),
                "n_noise_segments": len(segments),
                "n_distinct_noise_offsets": len(set(segments)),
                "noise_band_power_median_per_10s": _noise_band_power(args.nstdb_dir),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"{len(plan)} records -> {out}; labels.csv {sha256_file(out / 'labels.csv')}")


def verify_checksums(out: Path, record_ids) -> int:
    """Check the manifest against its frozen digest, then every record file against the manifest.

    The manifest must list exactly the plan's files, each once, and ``records/`` must hold no
    others. Returns the number of files checked; raises ``SystemExit`` on any departure.
    """
    digest = sha256_file(out / "checksums.csv")
    if digest != FROZEN_CHECKSUMS_SHA256:
        raise SystemExit(f"checksums.csv differs from its frozen digest: {digest}")
    sums = _read_csv(out / "checksums.csv")
    expected = sorted(f"records/{rid}{suffix}" for rid in record_ids for suffix in (".hea", ".dat"))
    if sorted(row["file"] for row in sums) != expected:
        raise SystemExit("checksums.csv does not list exactly the plan's record files, each once")
    on_disk = sorted(f"records/{p.name}" for p in (out / "records").iterdir())
    if on_disk != expected:
        raise SystemExit(f"unlisted record files: {sorted(set(on_disk) - set(expected))}")
    for row in sums:
        if sha256_file(out / row["file"]) != row["sha256"]:
            raise SystemExit(f"checksum mismatch: {row['file']}")
    return len(sums)


def verify(args) -> None:
    """Re-check a generated corpus against the definition, the sources and its checksums."""
    out = args.out
    metadata = _read_csv(args.ptbxl_dir / "ptbxl_database.csv")
    plan, excluded = _bound_plan(args, metadata)
    sha = verify_labels_file(out / "labels.csv", plan)
    index = _read_csv(out / "records.csv")
    if [r["record_id"] for r in index] != [e.spec.record_id for e in plan]:
        raise SystemExit("records.csv does not list the plan's records")
    for row, entry in zip(index, plan, strict=True):
        if (row["source_record_id"], row["split"]) != (entry.spec.source.record_id, entry.split):
            raise SystemExit(f"{row['record_id']}: parent or split differs from the definition")
    patients = {r["patient_id"] for r in index}
    if len(patients) != len(plan) or patients & excluded:
        raise SystemExit("a patient repeats or belongs to a development set")
    n_files = verify_checksums(out, [entry.spec.record_id for entry in plan])
    print(f"OK: {len(plan)} records, {n_files} files, labels.csv {sha}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ptbxl-dir", type=Path, default=DEFAULT_PTBXL_DIR)
    parser.add_argument("--nstdb-dir", type=Path, default=DEFAULT_NSTDB_DIR)
    parser.add_argument("--set2-sources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="check an existing corpus and exit")
    args = parser.parse_args(argv)
    (verify if args.verify else generate)(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
