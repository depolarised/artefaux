# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Load source ECGs and noise into Torsade's canonical representation.

Every parent record becomes a ``(12, T)`` ``float64`` mV array in
:data:`~torsade.constants.CANONICAL_LEAD_ORDER` at :data:`~torsade.constants.TARGET_FS`.
NSTDB noise becomes a single-lead segment resampled to the same rate. All readers
go through :func:`wfdb.rdrecord`, so this module is the only place that touches the
on-disk source format.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import gcd
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal as sp_signal

from .constants import (
    CANONICAL_LEAD_ORDER,
    LEAD_INDEX,
    LEAD_NAME_ALIASES,
    N_LEADS,
    TARGET_FS,
)
from .electrode_domain import derive_limb_leads_from_I_II

try:  # wfdb is a hard dependency, but keep loaders importable for pure-array tests
    import wfdb
except ImportError:  # pragma: no cover
    wfdb = None


@dataclass(frozen=True)
class ParentECG:
    """A clean or naturally-poor parent record in canonical form."""

    signal: np.ndarray  # (12, T) float64 mV
    fs: int
    source_dataset: str  # "ptbxl" | "challenge2011"
    source_id: str
    lead_names: tuple[str, ...] = CANONICAL_LEAD_ORDER
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def n_samples(self) -> int:
        return self.signal.shape[1]

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.fs


@dataclass(frozen=True)
class NoiseSegment:
    """A single-lead real-noise segment (NSTDB) resampled to the target rate."""

    signal: np.ndarray  # (T,) float64
    fs: int
    noise_type: str  # "em" | "ma" | "bw"
    source_record: str
    source_channel: int
    start_sample: int


def resample_signal(signal: np.ndarray, fs_in: int, fs_out: int, *, axis: int = -1) -> np.ndarray:
    """Deterministic polyphase resampling. Returns ``signal`` unchanged if rates match."""
    if fs_in == fs_out:
        return np.asarray(signal, dtype=np.float64)
    g = gcd(int(fs_in), int(fs_out))
    up, down = int(fs_out) // g, int(fs_in) // g
    out = sp_signal.resample_poly(np.asarray(signal, dtype=np.float64), up, down, axis=axis)
    return np.ascontiguousarray(out, dtype=np.float64)


def _canonicalize_leads(sig: np.ndarray, names: list[str]) -> np.ndarray:
    """Reorder ``(n_sig, T)`` into canonical ``(12, T)``, deriving limb leads if absent."""
    if sig.ndim != 2:
        raise ValueError(f"expected 2-D (n_sig, T), got shape {sig.shape}")
    resolved = [LEAD_NAME_ALIASES.get(n.strip().lower(), n.strip()) for n in names]
    available: dict[str, np.ndarray] = {}
    for name, row in zip(resolved, sig, strict=False):
        if name in LEAD_INDEX and name not in available:
            available[name] = np.asarray(row, dtype=np.float64)

    if "I" not in available or "II" not in available:
        raise ValueError(f"leads I and II are required to canonicalize; got {sorted(available)}")
    if not all(ld in available for ld in ("III", "aVR", "aVL", "aVF")):
        iii, avr, avl, avf = derive_limb_leads_from_I_II(available["I"], available["II"])
        available.setdefault("III", iii)
        available.setdefault("aVR", avr)
        available.setdefault("aVL", avl)
        available.setdefault("aVF", avf)

    missing = [ld for ld in CANONICAL_LEAD_ORDER if ld not in available]
    if missing:
        raise ValueError(f"cannot assemble 12 leads; missing {missing}")

    out = np.empty((N_LEADS, sig.shape[1]), dtype=np.float64)
    for name, idx in LEAD_INDEX.items():
        out[idx] = available[name]
    return out


def load_wfdb_parent(
    record_path: str | Path,
    source_dataset: str,
    *,
    source_id: str | None = None,
    target_fs: int = TARGET_FS,
    metadata: Mapping[str, Any] | None = None,
) -> ParentECG:
    """Read a 12-lead WFDB record into a :class:`ParentECG`."""
    if wfdb is None:  # pragma: no cover
        raise RuntimeError("wfdb is required to read source records")
    record_path = Path(record_path)
    rec = wfdb.rdrecord(str(record_path.with_suffix("")))
    if rec.p_signal is None:
        raise ValueError(f"{record_path}: no physical signal")
    canonical = _canonicalize_leads(
        np.asarray(rec.p_signal, dtype=np.float64).T, list(rec.sig_name)
    )
    fs = int(round(rec.fs))
    canonical = resample_signal(canonical, fs, target_fs, axis=1)
    if not np.all(np.isfinite(canonical)):
        raise ValueError(f"{record_path}: non-finite samples after canonicalization")
    meta = dict(metadata or {})
    meta.setdefault("source_fs", fs)
    return ParentECG(
        signal=np.ascontiguousarray(canonical),
        fs=target_fs,
        source_dataset=source_dataset,
        source_id=source_id or record_path.stem,
        metadata=meta,
    )


def load_nstdb_noise(
    record_path: str | Path,
    noise_type: str,
    n_samples: int,
    *,
    channel: int = 0,
    start_sample: int = 0,
    target_fs: int = TARGET_FS,
) -> NoiseSegment:
    """Read a single channel of an NSTDB record, resample, and extract a segment.

    The segment wraps around the (resampled) record if ``start_sample + n_samples``
    exceeds its length, so any ``start_sample`` yields a full ``n_samples`` segment.
    """
    if wfdb is None:  # pragma: no cover
        raise RuntimeError("wfdb is required to read source records")
    record_path = Path(record_path)
    rec = wfdb.rdrecord(str(record_path.with_suffix("")))
    raw = np.asarray(rec.p_signal, dtype=np.float64)[:, channel]
    fs = int(round(rec.fs))
    resampled = resample_signal(raw, fs, target_fs)
    if resampled.shape[0] == 0:
        raise ValueError(f"{record_path}: empty noise record")
    idx = (np.arange(n_samples) + start_sample) % resampled.shape[0]
    segment = resampled[idx].copy()
    return NoiseSegment(
        signal=segment,
        fs=target_fs,
        noise_type=noise_type,
        source_record=record_path.stem,
        source_channel=channel,
        start_sample=start_sample,
    )
