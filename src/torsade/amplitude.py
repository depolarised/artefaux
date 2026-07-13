# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Amplitude bookkeeping — peak-to-peak tracking and clipping detection.

Every corruption records what it did to each lead's amplitude, and whether it
drove the signal into the acquisition rail. This is what makes an SNR label
honest: once a device range is exceeded, the *requested* amplitude and the
*actual* post-clip amplitude diverge, and both must be stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def peak_to_peak_mv(x: np.ndarray) -> float:
    """NaN-safe peak-to-peak amplitude in mV (0.0 if all-NaN)."""
    finite = x[np.isfinite(x)]
    if finite.size == 0:
        return 0.0
    return float(np.max(finite) - np.min(finite))


def detect_clipping(
    x: np.ndarray,
    rail_mv: float,
    fs: int,
    *,
    tol_mv: float = 1e-6,
    min_run: int = 3,
) -> tuple[float, tuple[tuple[float, float], ...]]:
    """Return ``(clipped_fraction, intervals_s)`` for samples pinned at ``±rail_mv``.

    Only runs of at least ``min_run`` consecutive pinned samples count, so a single
    sample that merely touches the rail is not mistaken for clipping.
    """
    if rail_mv <= 0:
        return 0.0, ()
    at_rail = np.isfinite(x) & (np.abs(x) >= rail_mv - tol_mv)
    intervals: list[tuple[float, float]] = []
    clipped = 0
    run_start: int | None = None
    for i, flag in enumerate(at_rail):
        if flag and run_start is None:
            run_start = i
        elif not flag and run_start is not None:
            if i - run_start >= min_run:
                intervals.append((run_start / fs, i / fs))
                clipped += i - run_start
            run_start = None
    if run_start is not None and len(at_rail) - run_start >= min_run:
        intervals.append((run_start / fs, len(at_rail) / fs))
        clipped += len(at_rail) - run_start
    return clipped / x.size, tuple(intervals)


@dataclass(frozen=True)
class AmplitudeRecord:
    """Per-lead amplitude accounting for one corruption step."""

    lead: str
    p2p_before_mv: float
    p2p_after_mv: float
    clipped: bool = False
    clip_fraction: float = 0.0
    clip_intervals_s: tuple[tuple[float, float], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "lead": self.lead,
            "p2p_before_mv": round(self.p2p_before_mv, 6),
            "p2p_after_mv": round(self.p2p_after_mv, 6),
            "clipped": self.clipped,
            "clip_fraction": round(self.clip_fraction, 6),
            "clip_intervals_s": [list(iv) for iv in self.clip_intervals_s],
        }


def amplitude_record(
    lead: str,
    before: np.ndarray,
    after: np.ndarray,
    fs: int,
    *,
    rail_mv: float | None = None,
) -> AmplitudeRecord:
    """Build an :class:`AmplitudeRecord` comparing a lead before and after corruption."""
    clip_fraction, intervals = (0.0, ())
    if rail_mv is not None:
        clip_fraction, intervals = detect_clipping(after, rail_mv, fs)
    return AmplitudeRecord(
        lead=lead,
        p2p_before_mv=peak_to_peak_mv(before),
        p2p_after_mv=peak_to_peak_mv(after),
        clipped=clip_fraction > 0.0,
        clip_fraction=clip_fraction,
        clip_intervals_s=intervals,
    )
