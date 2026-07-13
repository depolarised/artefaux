# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Deterministic seeding and corpus provenance.

Reproducibility rests on two things: a per-record RNG derived deterministically
from a single master seed, and a ``provenance.json`` that pins the exact source
dataset versions and the SHA-256 of every source file a record was built from.
Given the same master seed and the same pinned sources, ``make regenerate``
reproduces the corpus bit-for-bit.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import __version__


def record_seed_sequence(master_seed: int, record_index: int) -> np.random.SeedSequence:
    """A collision-resistant per-record seed derived from the master seed."""
    return np.random.SeedSequence(entropy=int(master_seed), spawn_key=(int(record_index),))


def record_rng(master_seed: int, record_index: int) -> np.random.Generator:
    """A deterministic :class:`numpy.random.Generator` for one record."""
    return np.random.default_rng(record_seed_sequence(master_seed, record_index))


def seed_for_record(master_seed: int, record_index: int) -> int:
    """A loggable integer seed for one record (for the corruption-truth label)."""
    return int(record_seed_sequence(master_seed, record_index).generate_state(1)[0])


def sha256_file(path: str | Path, *, _chunk: int = 1 << 20) -> str:
    """SHA-256 of a file, streamed."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_chunk), b""):
            h.update(block)
    return h.hexdigest()


@dataclass(frozen=True)
class SourceRef:
    """A pinned source dataset."""

    dataset: str  # "ptbxl" | "ptbxl_plus" | "nstdb" | "challenge2011"
    version: str
    url: str
    license: str


DEFAULT_SOURCES: tuple[SourceRef, ...] = (
    SourceRef("ptbxl", "1.0.3", "https://physionet.org/content/ptb-xl/1.0.3/", "CC-BY-4.0"),
    SourceRef(
        "ptbxl_plus", "1.0.1", "https://physionet.org/content/ptb-xl-plus/1.0.1/", "CC-BY-4.0"
    ),
    SourceRef("nstdb", "1.0.0", "https://physionet.org/content/nstdb/1.0.0/", "ODC-BY-1.0"),
    SourceRef(
        "challenge2011",
        "1.0.0",
        "https://physionet.org/content/challenge-2011/1.0.0/",
        "PhysioNet Open Access",
    ),
)


@dataclass
class Provenance:
    """Everything needed to regenerate the corpus bit-exactly."""

    master_seed: int
    torsade_version: str = __version__
    target_fs: int = 500
    sources: list[SourceRef] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    source_file_hashes: dict[str, str] = field(default_factory=dict)
    generated_at_utc: str | None = None  # metadata only; never affects signals

    def record_source_hash(self, source_id: str, path: str | Path) -> None:
        self.source_file_hashes[source_id] = sha256_file(path)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sources"] = [asdict(s) for s in self.sources]
        return d

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
