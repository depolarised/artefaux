# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Corpus-build orchestration.

Ties loaders, recipes, writer, manifest, and provenance into a single
:func:`generate_corpus`. Two modes:

* ``synthetic=True`` — builds every record from synthetic parents and synthetic
  noise. Needs no PhysioNet download; used for CI and smoke tests.
* ``synthetic=False`` — resolves each spec's parent from the user's PhysioNet copy
  and mixes real NSTDB noise. This is the released-corpus path (``make regenerate``).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .constants import TARGET_FS
from .corpus import build_corpus_specs
from .loaders import load_nstdb_noise, load_wfdb_parent
from .manifest import Manifest, ManifestEntry
from .provenance import Provenance
from .recipes import RecordSpec, build_record, synthetic_noise_provider
from .synthetic import synthetic_parent_signal
from .writer import write_wfdb


def make_nstdb_provider(nstdb_dir: str | Path):
    """A noise provider that draws real NSTDB segments from ``nstdb_dir``.

    Start offset defaults to a deterministic draw from the record's own RNG, so the
    exact segment used is captured in the corruption-truth label.
    """
    nstdb_dir = Path(nstdb_dir)

    def provider(step: dict, n: int, rng: np.random.Generator) -> np.ndarray:
        src = step.get("noise_source", {})
        record = src.get("record", step.get("noise_type", "em"))
        channel = int(src.get("channel", 0))
        start = src.get("start_sample")
        if start is None:
            start = int(rng.integers(0, 100_000))
        seg = load_nstdb_noise(
            nstdb_dir / record, step["noise_type"], n, channel=channel, start_sample=start
        )
        return seg.signal

    return provider


def _resolve_parent(spec: RecordSpec, sources_dir: Path) -> np.ndarray:
    """Load a real parent for ``spec`` from ``sources_dir/<dataset>/<record_id>``."""
    if spec.source.record_id is None:
        raise ValueError(
            f"{spec.record_id}: source record_id is unresolved; run select_sources first"
        )
    record_path = sources_dir / spec.source.dataset / spec.source.record_id
    parent = load_wfdb_parent(record_path, spec.source.dataset, source_id=spec.source.record_id)
    return parent.signal


def generate_corpus(
    out_dir: str | Path,
    *,
    master_seed: int,
    sources_dir: str | Path | None = None,
    synthetic: bool = False,
) -> Manifest:
    """Generate the full corpus into ``out_dir`` and return the manifest."""
    out_dir = Path(out_dir)
    records_dir = out_dir / "records"
    labels_dir = out_dir / "labels"
    records_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    specs = build_corpus_specs()
    manifest = Manifest()
    provenance = Provenance(master_seed=master_seed, target_fs=TARGET_FS)

    if synthetic:
        provider = synthetic_noise_provider
    else:
        if sources_dir is None:
            raise ValueError("sources_dir is required unless synthetic=True")
        sources_dir = Path(sources_dir)
        provider = make_nstdb_provider(sources_dir / "nstdb")

    for spec in specs:
        if synthetic:
            parent = synthetic_parent_signal(seed=spec.seed_index)
        else:
            parent = _resolve_parent(spec, sources_dir)

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
