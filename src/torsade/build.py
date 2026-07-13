# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Corpus-build orchestration.

Ties loaders, recipes, writer, manifest, and provenance into a single
:func:`generate_corpus`. Two modes:

* ``synthetic=True`` — builds every record from synthetic parents and synthetic
  noise. Needs no data at all; used for CI and smoke tests.
* ``synthetic=False`` — resolves each spec's parent from PTB-XL and draws real noise
  from NSTDB (em/ma/bw) and MACECGDB (motion). This is the released-corpus path
  (``make regenerate``).

Default source roots point at a local PhysioNet mirror; override them on the CLI.
"""

from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import numpy as np

from .constants import TARGET_FS
from .corpus import build_corpus_specs
from .loaders import load_macecgdb_noise, load_nstdb_noise, load_wfdb_parent
from .manifest import Manifest, ManifestEntry
from .provenance import Provenance
from .recipes import RecordSpec, build_record, synthetic_noise_provider
from .synthetic import synthetic_parent_signal
from .writer import write_wfdb

# Local PhysioNet mirror layout (override via the CLI / generate_corpus args).
DEFAULT_PTBXL_DIR = Path("/data/physionet/ptb-xl-1.0.3")
DEFAULT_MACECGDB_DIR = Path("/data/physionet/motion-artifact-contaminated-ecg-database-1.0.0")
DEFAULT_NSTDB_DIR = Path("data/sources/nstdb")
DEFAULT_SOURCE_IDS_DIR = Path("recipes/source_ids")

# NSTDB carries the classic three noise types; MACECGDB carries motion by activity.
_NSTDB_TYPES = ("em", "ma", "bw")
_MACECGDB_SUFFIX = {"stand": "s", "walk": "w", "jump": "j"}


def make_noise_provider(nstdb_dir: str | Path, macecgdb_dir: str | Path | None = None):
    """A noise provider routing em/ma/bw to NSTDB and motion types to MACECGDB.

    The exact source record, channel, and start offset are drawn from the record's
    own RNG, so they are captured deterministically in the corruption-truth label.
    """
    nstdb_dir = Path(nstdb_dir)
    mac_dir = Path(macecgdb_dir) if macecgdb_dir else None
    mac_by_suffix: dict[str, list[str]] = {}
    if mac_dir and mac_dir.exists():
        for hea in sorted(mac_dir.glob("*.hea")):
            mac_by_suffix.setdefault(hea.stem[-1], []).append(hea.stem)

    def provider(step: dict, n: int, rng: np.random.Generator) -> np.ndarray:
        noise_type = step["noise_type"]
        if noise_type in _NSTDB_TYPES:
            src = step.get("noise_source", {})
            record = src.get("record", noise_type)
            channel = int(src.get("channel", 0))
            start = src.get("start_sample")
            if start is None:
                start = int(rng.integers(0, 100_000))
            return load_nstdb_noise(
                nstdb_dir / record, noise_type, n, channel=channel, start_sample=start
            ).signal
        # MACECGDB real motion
        if not mac_by_suffix:
            raise RuntimeError(f"MACECGDB not available for motion noise '{noise_type}'")
        suffix = _MACECGDB_SUFFIX.get(noise_type)
        pool = (
            mac_by_suffix.get(suffix) if suffix else [s for v in mac_by_suffix.values() for s in v]
        )
        if not pool:
            raise RuntimeError(f"no MACECGDB records for motion type '{noise_type}'")
        stem = pool[int(rng.integers(0, len(pool)))]
        channel = int(rng.integers(0, 4))
        start = int(rng.integers(0, 3500))
        return load_macecgdb_noise(
            mac_dir / stem, noise_type, n, channel=channel, start_sample=start
        ).signal

    return provider


def _read_ids(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found; run `make select` (scripts/select_sources.py) first "
            "to resolve PTB-XL parent ids from your local copy."
        )
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def resolve_source_ids(
    specs: list[RecordSpec], source_ids_dir: str | Path = DEFAULT_SOURCE_IDS_DIR
) -> list[RecordSpec]:
    """Bind concrete PTB-XL record ids (from ``select_sources``) into the specs.

    ``build_corpus_specs`` leaves ``source.record_id`` as ``None`` so the corpus
    definition stays data-independent. This step pairs, in deterministic group
    order, each naturally-poor spec with a quality-flagged PTB-XL record and each
    clean-parent spec (real-noise + engineering) with a clean PTB-XL record, using
    the CSVs written by ``scripts/select_sources.py``.
    """
    source_ids_dir = Path(source_ids_dir)
    clean = _read_ids(source_ids_dir / "ptbxl_clean.csv")
    noisy = _read_ids(source_ids_dir / "ptbxl_noisy.csv")

    n_clean_needed = sum(1 for s in specs if s.group != "naturally_poor")
    n_noisy_needed = sum(1 for s in specs if s.group == "naturally_poor")
    if len(clean) < n_clean_needed:
        raise ValueError(f"need {n_clean_needed} clean PTB-XL ids, selection has {len(clean)}")
    if len(noisy) < n_noisy_needed:
        raise ValueError(f"need {n_noisy_needed} noisy PTB-XL ids, selection has {len(noisy)}")

    resolved: list[RecordSpec] = []
    ci = ni = 0
    for spec in specs:
        if spec.source.record_id is not None:
            resolved.append(spec)
            continue
        if spec.group == "naturally_poor":
            row = noisy[ni]
            ni += 1
            flags = tuple(f for f in (row.get("quality_flags") or "").split("|") if f)
            source = replace(
                spec.source,
                record_id=row["filename_hr"],
                ptbxl_quality_flags=flags or spec.source.ptbxl_quality_flags,
            )
        else:
            row = clean[ci]
            ci += 1
            source = replace(spec.source, record_id=row["filename_hr"])
        resolved.append(replace(spec, source=source))
    return resolved


def _resolve_parent(spec: RecordSpec, ptbxl_dir: Path) -> np.ndarray:
    """Load a real PTB-XL parent (record_id is a ``records500/..`` relative path)."""
    if spec.source.dataset != "ptbxl":
        raise ValueError(
            f"{spec.record_id}: only ptbxl parents are supported (got {spec.source.dataset})"
        )
    if spec.source.record_id is None:
        raise ValueError(f"{spec.record_id}: source record_id unresolved; run select_sources first")
    return load_wfdb_parent(
        ptbxl_dir / spec.source.record_id, "ptbxl", source_id=spec.source.record_id
    ).signal


def generate_corpus(
    out_dir: str | Path,
    *,
    master_seed: int,
    ptbxl_dir: str | Path = DEFAULT_PTBXL_DIR,
    macecgdb_dir: str | Path = DEFAULT_MACECGDB_DIR,
    nstdb_dir: str | Path = DEFAULT_NSTDB_DIR,
    source_ids_dir: str | Path = DEFAULT_SOURCE_IDS_DIR,
    synthetic: bool = False,
) -> Manifest:
    """Generate the full corpus into ``out_dir`` and return the manifest."""
    out_dir = Path(out_dir)
    records_dir = out_dir / "records"
    labels_dir = out_dir / "labels"
    records_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    specs = build_corpus_specs()
    if not synthetic:
        specs = resolve_source_ids(specs, source_ids_dir)
    manifest = Manifest()
    provenance = Provenance(master_seed=master_seed, target_fs=TARGET_FS)

    provider = (
        synthetic_noise_provider if synthetic else make_noise_provider(nstdb_dir, macecgdb_dir)
    )
    ptbxl_dir = Path(ptbxl_dir)

    for spec in specs:
        parent = (
            synthetic_parent_signal(seed=spec.seed_index)
            if synthetic
            else _resolve_parent(spec, ptbxl_dir)
        )
        sig, label = build_record(parent, spec, master_seed, fs=TARGET_FS, noise_provider=provider)
        write_wfdb(spec.record_id, sig, TARGET_FS, records_dir)
        label.write(labels_dir / f"{spec.record_id}.json")

        parent_id = None
        if spec.has_clean_parent:
            parent_id = f"{spec.record_id}_clean"
            write_wfdb(parent_id, parent, TARGET_FS, records_dir)

        manifest.add(ManifestEntry.from_label(label, parent_record_id=parent_id))

    manifest.write_json(out_dir / "manifest.json")
    manifest.write_csv(out_dir / "manifest.csv")
    provenance.write(out_dir / "provenance.json")
    return manifest
