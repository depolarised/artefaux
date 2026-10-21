#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Generate the blinded T1 noise benchmark: signals, reader packs, tool inputs, commitment.

Local tooling: requires ecg-io, signalpaper, xlwt==1.3.0, xlrd==2.0.2, local PTB-XL and
NSTDB, the v2 corpus manifest and the review-set-2 source list (for patient exclusion).

Outputs
-------
``out/artefaux-bench-v1/T1/`` (private, gitignored)
    records + clean parents, labels, manifest, provenance, generation audit, verification,
    ``PRIVATE_seeds.json`` and ``PRIVATE_blind_key.csv``.
``reports/review_packs/bench_T1/`` (handoffs, gitignored)
    reader PDF + coded PWM/DTC sheets + README (one ZIP per reader, no signals), and a
    separate tool-input ZIP (blinded WFDB + GRIASCII + ``inputs.csv``) for the program runs.
``bench/v1/T1/`` (public, committed at freeze)
    ``inputs.csv`` (blind codes and file hashes) and ``commitment.json`` (SHA-256 of the
    private seeds and key, the definition files and the code commit; revealed at unblinding).

The master and blind-order seeds are drawn from ``secrets`` unless given explicitly
(``--master-seed``/``--blind-seed``, dry runs only). They protect the record-to-code
mapping from casual recovery and make commit-reveal verification possible. They are not a
cryptographic guarantee: unmodified records and untouched leads are bit-identical to their
PTB-XL sources at 1000 LSB/mV, so anyone with the full PTB-XL mirror can hash-match those
leads to recover some codes. Blinding of the tools is procedural; see the Trust model in
``docs/BENCHMARK.md``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import wfdb

from artefaux.benchmark import (
    BENCH_ID,
    BENCH_VERSION,
    BLOCK,
    N_RECORDS,
    SCHEMA_VERSION,
    UNIG_HEADER_LINES,
    build_bench_specs,
    select_bench_sources,
    stratum_of,
)
from artefaux.build import DEFAULT_NSTDB_DIR, DEFAULT_PTBXL_DIR, make_noise_provider
from artefaux.constants import CANONICAL_LEAD_ORDER, LEAD_INDEX, TARGET_FS
from artefaux.loaders import load_wfdb_parent
from artefaux.manifest import Manifest, ManifestEntry
from artefaux.mixing import _dc_removed_power, measured_snr_db
from artefaux.provenance import Provenance, sha256_file
from artefaux.recipes import SourceSpec, build_record
from artefaux.review import BENCH_ALLOWED, write_bench_review_files
from artefaux.selection import quality_flags
from artefaux.writer import write_wfdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_review_set import compress_review, load_converter, read_csv, write_csv  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
REAL_OUT = REPO / f"out/artefaux-bench-v1/{BLOCK}"
REAL_SHARE = REPO / f"reports/review_packs/bench_{BLOCK}"
REAL_PUBLIC = REPO / f"bench/v1/{BLOCK}"
SNR_TOLERANCE_DB = 0.5


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True
        )
        dirty = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "src", "scripts"],
            capture_output=True,
            text=True,
        ).stdout.strip()
        return out.stdout.strip() + ("+dirty" if dirty else "")
    except OSError:
        return "unknown"


def excluded_patients(args, metadata: list[dict]) -> set[str]:
    """Every patient behind the development sets (v2 = set 1, and set 2)."""
    v2 = json.loads((args.v2_corpus / "manifest.json").read_text())["records"]
    v2_ids = {r["source_record_id"] for r in v2}
    patients = {r["patient_id"] for r in metadata if r["filename_hr"] in v2_ids}
    patients |= {r["patient_id"] for r in read_csv(args.set2_sources)}
    if len(patients) != 170:
        raise ValueError(f"expected 170 development patients, found {len(patients)}")
    return patients


def check_patients(selected: list[str], excluded: set[str]) -> dict[str, int]:
    """Recompute patient independence from the selected records, not from the selector."""
    distinct = set(selected)
    overlap = distinct & excluded
    if len(distinct) != N_RECORDS:
        raise ValueError(f"expected {N_RECORDS} distinct patients, found {len(distinct)}")
    if overlap:
        raise ValueError(f"{len(overlap)} selected patients also appear in development sets")
    return {
        "n_distinct_patients": len(distinct),
        "patient_overlap_with_development_sets": len(overlap),
    }


def _source(row: dict) -> SourceSpec:
    codes = ast.literal_eval(row["scp_codes"])
    rhythm = next(
        (
            label
            for code, label in (("AFIB", "afib"), ("AFLT", "flutter"), ("SR", "sinus"))
            if code in codes
        ),
        "unknown",
    )
    return SourceSpec(
        "ptbxl",
        row["filename_hr"],
        rhythm_class=rhythm,
        age_years=float(row["age"]) if row["age"] else None,
        ptbxl_quality_flags=quality_flags(row),
    )


def _mask_and_checks(spec, label, saved: np.ndarray, clean: np.ndarray) -> tuple[np.ndarray, dict]:
    """Allowed lead/time mask from the truth log, and SNR checks against the readback."""
    allowed = np.zeros(saved.shape, dtype=bool)
    snr = {}
    for step in label.corruption_truth.steps:
        start, stop = (0, saved.shape[1])
        if step.interval_s is not None:
            start, stop = (int(round(t * TARGET_FS)) for t in step.interval_s)
        for lead in step.leads_affected:
            allowed[LEAD_INDEX[lead], start:stop] = True
        if step.op == "nstdb_mix":
            for lead in step.params["leads"]:
                i = LEAD_INDEX[lead]
                snr[lead] = measured_snr_db(
                    clean[i, start:stop], saved[i, start:stop] - clean[i, start:stop]
                )
        elif step.op == "electrode_nstdb":
            ref = [LEAD_INDEX[ld] for ld in step.params["snr_reference_leads"]]
            px = np.mean([_dc_removed_power(clean[i, start:stop]) for i in ref])
            pn = np.mean(
                [_dc_removed_power(saved[i, start:stop] - clean[i, start:stop]) for i in ref]
            )
            snr["electrode_ref"] = float(10 * np.log10(px / pn))
    requested = next((s["snr_db"] for s in spec.steps if "snr_db" in s), None)
    for key, value in snr.items():
        if abs(value - requested) > SNR_TOLERANCE_DB:
            raise ValueError(f"{spec.record_id}/{key}: stored SNR {value:.3f} vs {requested} dB")
    return allowed, snr


def generate_signals(args, seeds: dict) -> None:
    out = args.out
    records, labels = out / "records", out / "labels"
    labels.mkdir(parents=True, exist_ok=True)
    metadata = read_csv(args.ptbxl_dir / "ptbxl_database.csv")
    excluded = excluded_patients(args, metadata)
    clean, confounders, natural = select_bench_sources(
        metadata, excluded_patients=excluded, seed=seeds["master_seed"]
    )
    rows_by_id = {r["filename_hr"]: r for group in (clean, natural) for r in group}
    rows_by_id |= {r["filename_hr"]: r for v in confounders.values() for r in v}
    specs = build_bench_specs(
        [_source(r) for r in clean],
        {k: [_source(r) for r in v] for k, v in confounders.items()},
        [_source(r) for r in natural],
        master_seed=seeds["master_seed"],
    )
    write_csv(
        out / "source_ids.csv",
        [
            {
                "record_id": s.record_id,
                "stratum": stratum_of(s.record_id),
                "source_record_id": s.source.record_id,
                "patient_id": rows_by_id[s.source.record_id]["patient_id"],
                "scp_codes": rows_by_id[s.source.record_id]["scp_codes"],
                "ptbxl_quality_flags": "|".join(s.source.ptbxl_quality_flags),
            }
            for s in specs
        ],
    )
    patients = check_patients(
        [rows_by_id[s.source.record_id]["patient_id"] for s in specs], excluded
    )
    recipe_path = out / "recipes.json"
    recipe_path.write_text(json.dumps([asdict(s) for s in specs], indent=2) + "\n")
    manifest = Manifest()
    provenance = Provenance(master_seed=seeds["master_seed"])
    provenance.sources = [s for s in provenance.sources if s.dataset in ("ptbxl", "nstdb")]
    for name, path in (
        ("ptbxl_metadata", args.ptbxl_dir / "ptbxl_database.csv"),
        ("v2_manifest", args.v2_corpus / "manifest.json"),
        ("set2_sources", args.set2_sources),
        ("recipes", recipe_path),
        ("benchmark_definition", REPO / "src/artefaux/benchmark.py"),
        ("recipe_interpreter", REPO / "src/artefaux/recipes.py"),
        ("generation_script", Path(__file__)),
    ):
        provenance.record_source_hash(name, path)
    for noise in ("em", "ma", "bw"):
        for suffix in (".hea", ".dat"):
            provenance.record_source_hash(
                f"nstdb/{noise}{suffix}", args.nstdb_dir / f"{noise}{suffix}"
            )
    provider = make_noise_provider(args.nstdb_dir)
    audit, max_err = [], 0.0
    for index, spec in enumerate(specs, start=1):
        source_path = args.ptbxl_dir / spec.source.record_id
        parent = load_wfdb_parent(source_path, "ptbxl").signal
        if parent.shape != (12, 5000):
            raise ValueError(f"{source_path}: expected a 10-second, 12-lead, 500 Hz parent")
        for suffix in (".hea", ".dat"):
            provenance.record_source_hash(
                f"ptbxl/{spec.source.record_id}{suffix}", source_path.with_suffix(suffix)
            )
        signal, label = build_record(
            parent, spec, seeds["master_seed"], TARGET_FS, noise_provider=provider
        )
        if not np.isfinite(signal).all() or np.max(np.abs(signal)) > 32.766:
            raise ValueError(f"{spec.record_id}: non-finite samples or int16 storage overload")
        parent_id = f"{spec.record_id}_clean"
        write_wfdb(parent_id, parent, TARGET_FS, records)
        write_wfdb(spec.record_id, signal, TARGET_FS, records)
        saved = wfdb.rdrecord(str(records / spec.record_id)).p_signal.T
        clean_saved = wfdb.rdrecord(str(records / parent_id)).p_signal.T
        allowed, snr = _mask_and_checks(spec, label, saved, clean_saved)
        if not np.array_equal(saved[~allowed], clean_saved[~allowed]):
            raise ValueError(f"{spec.record_id}: signal changed outside the truth-log mask")
        if snr:
            requested = next(s["snr_db"] for s in spec.steps if "snr_db" in s)
            max_err = max(max_err, *(abs(v - requested) for v in snr.values()))
            step = label.corruption_truth.steps[0]
            step = replace(
                step,
                params={
                    **step.params,
                    "snr_post_storage_db": snr,
                    "measurement_domain": "WFDB readback, contaminated interval only",
                },
            )
            label = replace(
                label,
                corruption_truth=replace(
                    label.corruption_truth, steps=(step, *label.corruption_truth.steps[1:])
                ),
            )
        label.write(labels / f"{spec.record_id}.json")
        manifest.add(ManifestEntry.from_label(label, parent_record_id=parent_id))
        first = spec.steps[0] if spec.steps else {}
        audit.append(
            {
                "record_id": spec.record_id,
                "stratum": stratum_of(spec.record_id),
                "ops": "+".join(s["op"] for s in spec.steps) or "none",
                "noise_type": first.get("noise_type", ""),
                "leads_requested": "|".join(first.get("leads", first.get("electrodes", []))),
                "leads_changed": "|".join(label.corruption_truth.leads_with_any_corruption),
                "interval_s": "|".join(map(str, first.get("interval_s", []))),
                "requested_snr_db": first.get("snr_db", ""),
                "post_storage_snr_db": json.dumps(snr, sort_keys=True),
                "untargeted_samples_identical": True,
            }
        )
        if index % 20 == 0 or index == N_RECORDS:
            print(f"Generated and verified {index}/{N_RECORDS} T1 records", flush=True)
    manifest.write_json(out / "manifest.json")
    manifest.write_csv(out / "manifest.csv")
    provenance.write(out / "provenance.json")
    write_csv(out / "generation_audit.csv", audit)
    (out / "verification.json").write_text(
        json.dumps(
            {
                "bench_id": BENCH_ID,
                "bench_version": BENCH_VERSION,
                "block": BLOCK,
                "n_records": N_RECORDS,
                **patients,
                "all_untargeted_samples_bit_identical": True,
                "max_post_storage_snr_error_db": max_err,
            },
            indent=2,
        )
        + "\n"
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_and_package(args, seeds: dict) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/artefaux-matplotlib")
    from ecg_io import read_ecg
    from signalpaper import from_record, render_pdf_multipage

    converter = load_converter()
    entries = json.loads((args.out / "manifest.json").read_text())["records"]
    audit = {r["record_id"]: r for r in read_csv(args.out / "generation_audit.csv")}
    sources = {r["record_id"]: r for r in read_csv(args.out / "source_ids.csv")}
    order = np.random.default_rng(seeds["blind_seed"]).permutation(len(entries))
    entries = [entries[i] for i in order]
    share = args.share_dir
    tool_dir = share / "tool_inputs"
    for folder in (share, tool_dir / "wfdb", tool_dir / "griasc"):
        folder.mkdir(parents=True, exist_ok=True)
    scenes, key, inputs = [], [], []
    for page, entry in enumerate(entries, start=1):
        rid, code = entry["record_id"], f"{BLOCK}-{page:03d}"
        label = json.loads((args.out / "labels" / f"{rid}.json").read_text())
        signal = wfdb.rdrecord(str(args.out / "records" / rid)).p_signal.T
        blind_path = write_wfdb(code, signal, TARGET_FS, tool_dir / "wfdb")
        saved = wfdb.rdrecord(str(blind_path))
        if (
            not np.array_equal(saved.p_signal.T, signal)
            or tuple(saved.sig_name) != CANONICAL_LEAD_ORDER
        ):
            raise ValueError(f"{code}: blinded WFDB export changed the signal or lead order")
        asc = converter.convert_record(
            blind_path, tool_dir / "griasc", header_lines=UNIG_HEADER_LINES
        )
        asc_path = tool_dir / "griasc" / asc["asc_file"]
        header = asc_path.read_text(encoding="utf-8").split("\n", 23)[:23]
        expected = {2: code, **UNIG_HEADER_LINES}
        if any(header[line - 1] != value for line, value in expected.items()) or any(
            header[line - 1] for line in (3, 4)
        ):
            raise ValueError(f"{code}: GRIASCII header differs from the adult Uni-G request")
        scene = from_record(
            read_ecg(blind_path, format_name="WFDB"),
            title=code,
            extra_footer="",
            filter_preset="none",
            gain_mm_per_mV=10.0,
            speed_mm_per_second=25.0,
            layout="strip8",
        )
        if scene.scale.gain_mm_per_mV != 10 or scene.scale.speed_mm_per_second != 25:
            raise ValueError("review PDF scale mismatch")
        scenes.append(scene)
        hea, dat = blind_path.with_suffix(".hea"), blind_path.with_suffix(".dat")
        inputs.append(
            {
                "schema_version": SCHEMA_VERSION,
                "bench_version": BENCH_VERSION,
                "blind_code": code,
                "wfdb_hea": f"wfdb/{hea.name}",
                "wfdb_dat": f"wfdb/{dat.name}",
                "asc": f"griasc/{asc_path.name}",
                "sha256_hea": _sha(hea),
                "sha256_dat": _sha(dat),
                "sha256_asc": _sha(asc_path),
                "fs": TARGET_FS,
                "n_samples": signal.shape[1],
            }
        )
        eb = label["expected_behaviour"]
        key.append(
            {
                "page": page,
                "blind_code": code,
                "record_id": rid,
                **{k: v for k, v in audit[rid].items() if k != "record_id"},
                "source_record_id": sources[rid]["source_record_id"],
                "patient_id": sources[rid]["patient_id"],
                "authored_record_quality": eb["record_quality"],
                "authored_data_integrity_failure": eb["data_integrity_failure"],
            }
        )
    print(f"Rendering {len(scenes)} blinded T1 pages (raw, strip8, overflow)", flush=True)
    pdf = share / f"artefaux_bench_{BLOCK}_blind_overflow.pdf"
    clips = render_pdf_multipage(scenes, pdf, show_clipping_banner=False, clip_waveform=False)
    for row, clipping in zip(key, clips, strict=True):
        row["exceeds_display_band"] = bool(clipping.any_clipped)
    write_csv(args.out / "PRIVATE_blind_key.csv", key)
    write_csv(tool_dir / "inputs.csv", inputs)
    compress_review(pdf, args.out)
    empty = [[r["blind_code"], "", "", "", "", "", ""] for r in key]
    for reviewer in ("PWM", "DTC"):
        base = share / f"artefaux_bench_{BLOCK}_{reviewer}"
        if not base.with_suffix(".xls").exists():
            write_bench_review_files(base, reviewer, empty, block=BLOCK)
    allowed = "\n".join(f"  {name}: {values}" for name, values in BENCH_ALLOWED.items())
    (share / "README.txt").write_text(
        f"Artefaux noise benchmark - block {BLOCK} ({N_RECORDS} recordings)\n\n"
        "DTC = Derek; PWM = Peter. Use the XLS sheet matching your initials and review\n"
        "independently: please do not discuss cases until both sheets are returned.\n"
        f"PDF: artefaux_bench_{BLOCK}_blind_overflow.pdf. {BLOCK}-001 is PDF page 1.\n"
        "Each page shows the eight independent leads (I, II, V1-V6), each for the full\n"
        "10 seconds, at 25 mm/s and 10 mm/mV, raw signal with no display filtering.\n"
        "Traces may extend beyond their allocated lead bands.\n\n"
        "For every recording, decide as you would before automatic interpretation:\n"
        "which leads you would exclude, which part of the recording is usable, and\n"
        "whether the ECG is analysable. Please use only these values:\n"
        f"{allowed}\n\n"
        "Example row: T1-000 | V4, V5 | full | partially analysable | | noisy V4-V5\n"
        "If the ECG should be repeated, write 'all' for leads and choose 'rhythm only'\n"
        "or 'not analysable'. Free text belongs in comments. Leave Agreed handling\n"
        "blank: it is completed together after both reviews are in.\n\n"
        "No source identifiers, corruption labels or answer key are included.\n",
        encoding="utf-8",
    )
    packages = {
        f"artefaux_bench_{BLOCK}_{r}_review.zip": [
            pdf,
            share / "README.txt",
            share / f"artefaux_bench_{BLOCK}_{r}.xls",
            share / f"artefaux_bench_{BLOCK}_{r}.csv",
        ]
        for r in ("PWM", "DTC")
    }
    packages[f"artefaux_bench_{BLOCK}_tool_inputs.zip"] = [
        tool_dir / "inputs.csv",
        *sorted((tool_dir / "wfdb").glob("*")),
        *sorted((tool_dir / "griasc").glob("*.asc")),
    ]
    for name, files in packages.items():
        target = share / name
        root = tool_dir if "tool_inputs" in name else share
        with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=path.relative_to(root))
        with ZipFile(target) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"archive verification failed: {target}")
            leaked = [n for n in archive.namelist() if "PRIVATE" in n or "label" in n.lower()]
            if leaked:
                raise ValueError(f"{target}: private files in a handoff: {leaked}")
        print(f"Prepared {target} ({target.stat().st_size / 1e6:.1f} MB)", flush=True)


def tool_freeze(args) -> dict | None:
    """Resolve the signalguard version under test to an exact commit, if one is given."""
    if not args.signalguard_ref:
        return None
    commit = subprocess.run(
        [
            "git",
            "-C",
            str(args.signalguard_repo),
            "rev-parse",
            f"{args.signalguard_ref}^{{commit}}",
        ],
        capture_output=True,
        text=True,
    )
    if commit.returncode != 0:
        raise SystemExit(f"cannot resolve signalguard ref {args.signalguard_ref!r}")
    return {"tool": "signalguard", "ref": args.signalguard_ref, "commit": commit.stdout.strip()}


def write_commitment(args, seeds_path: Path, frozen_tool: dict | None) -> None:
    public = args.public_dir
    public.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.share_dir / "tool_inputs" / "inputs.csv", public / "inputs.csv")
    commitment = {
        "schema_version": SCHEMA_VERSION,
        "bench_id": BENCH_ID,
        "bench_version": BENCH_VERSION,
        "block": BLOCK,
        "n_records": N_RECORDS,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artefaux_commit": _git_commit(),
        # The version under test must be fixed before any program runs on T1: here when it
        # is known at generation, otherwise in tools_freeze.json committed before the run.
        "tool_under_test": frozen_tool,
        "sha256": {
            "PRIVATE_seeds.json": sha256_file(seeds_path),
            "PRIVATE_blind_key.csv": sha256_file(args.out / "PRIVATE_blind_key.csv"),
            "inputs.csv": sha256_file(public / "inputs.csv"),
            "src/artefaux/benchmark.py": sha256_file(REPO / "src/artefaux/benchmark.py"),
            "src/artefaux/recipes.py": sha256_file(REPO / "src/artefaux/recipes.py"),
            "scripts/generate_benchmark.py": sha256_file(Path(__file__)),
        },
        "note": (
            "Commit-reveal: the private seeds and blind key stay with the coordinator until "
            "all reader sheets and program predictions are frozen; they are then published so "
            "anyone can verify these hashes and regenerate the block bit-exactly."
        ),
    }
    (public / "commitment.json").write_text(json.dumps(commitment, indent=2) + "\n")
    print(f"Wrote public commitment {public / 'commitment.json'}", flush=True)


def _is_within(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return resolved == root.resolve() or root.resolve() in resolved.parents


def _check_dry_run(args, parser: argparse.ArgumentParser) -> None:
    """Given seeds mean a dry run: its paths must be explicit and must not touch the real
    block, its handoffs or the committed ``bench/`` tree."""
    if args.master_seed is None and args.blind_seed is None:
        return
    for name, real in (("out", REAL_OUT), ("share_dir", REAL_SHARE), ("public_dir", REAL_PUBLIC)):
        flag = f"--{name.replace('_', '-')}"
        value = getattr(args, name)
        if value is None:
            parser.error(f"a dry run (--master-seed/--blind-seed) needs an explicit {flag}")
        if _is_within(value, real):
            parser.error(f"a dry run must not use {flag} {value}: it lies within {real}")
    if _is_within(args.public_dir, REPO / "bench"):
        parser.error(f"a dry run must not write into the committed bench/ tree: {args.public_dir}")


def _resume_seeds(args, parser: argparse.ArgumentParser) -> dict:
    """Seeds of a block whose signals already exist; command-line seeds must agree."""
    seeds_path = args.out / "PRIVATE_seeds.json"
    if not (args.out / "manifest.json").exists() or not seeds_path.exists():
        parser.error(f"--resume-packaging needs {args.out} to hold manifest.json and seeds")
    seeds = json.loads(seeds_path.read_text())
    for name in ("master_seed", "blind_seed"):
        given = getattr(args, name)
        if given is not None and given != seeds[name]:
            parser.error(f"--{name.replace('_', '-')} {given} disagrees with {seeds_path}")
    return seeds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help=f"default: {REAL_OUT.relative_to(REPO)}")
    parser.add_argument("--share-dir", type=Path, help=f"default: {REAL_SHARE.relative_to(REPO)}")
    parser.add_argument("--public-dir", type=Path, help=f"default: {REAL_PUBLIC.relative_to(REPO)}")
    parser.add_argument("--ptbxl-dir", type=Path, default=DEFAULT_PTBXL_DIR)
    parser.add_argument("--nstdb-dir", type=Path, default=DEFAULT_NSTDB_DIR)
    parser.add_argument("--v2-corpus", type=Path, default=REPO / "out/artefaux-v2")
    parser.add_argument(
        "--set2-sources", type=Path, default=REPO / "out/artefaux-review-set2/source_ids.csv"
    )
    parser.add_argument(
        "--signalguard-ref",
        help="tag of the signalguard version under test, recorded in the commitment",
    )
    parser.add_argument(
        "--signalguard-repo", type=Path, default=REPO.parents[1] / "ecg-suite/signalguard"
    )
    parser.add_argument("--master-seed", type=int, help="dry runs only; default is secret")
    parser.add_argument("--blind-seed", type=int, help="dry runs only; default is secret")
    parser.add_argument(
        "--resume-packaging",
        action="store_true",
        help="skip signal generation; reuse the seeds in --out/PRIVATE_seeds.json and only "
        "render, package and write the commitment",
    )
    args = parser.parse_args()
    _check_dry_run(args, parser)
    # Resolve the tool version before writing anything, so a bad ref fails early.
    frozen_tool = tool_freeze(args)
    args.out = REAL_OUT if args.out is None else args.out
    args.share_dir = REAL_SHARE if args.share_dir is None else args.share_dir
    args.public_dir = REAL_PUBLIC if args.public_dir is None else args.public_dir
    for name in ("xlrd", "xlwt", "ecg_io", "signalpaper"):
        if importlib.util.find_spec(name) is None:
            parser.error(f"missing local review dependency: {name}")
    seeds_path = args.out / "PRIVATE_seeds.json"
    if args.resume_packaging:
        seeds = _resume_seeds(args, parser)
    else:
        if (args.out / "manifest.json").exists():
            parser.error(f"{args.out} already holds a generated block; it is never regenerated")
        args.out.mkdir(parents=True, exist_ok=True)
        seeds = {
            "master_seed": (
                args.master_seed if args.master_seed is not None else secrets.randbits(63)
            ),
            "blind_seed": args.blind_seed if args.blind_seed is not None else secrets.randbits(63),
            "salt": secrets.token_hex(16),
        }
        seeds_path.write_text(json.dumps(seeds, indent=2) + "\n")
        generate_signals(args, seeds)
    render_and_package(args, seeds)
    write_commitment(args, seeds_path, frozen_tool)
    print("Complete. Keep out/ private until unblinding; commit bench/ at freeze.", flush=True)


if __name__ == "__main__":
    main()
