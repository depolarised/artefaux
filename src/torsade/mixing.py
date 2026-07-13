# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Real-noise mixing at a controlled signal-to-noise ratio.

Given a clean lead ``x`` and a real recorded noise segment ``n`` (NSTDB em/ma/bw),
scale the noise so the contaminated interval sits at a requested SNR ``s`` (dB):

    α = sqrt( Px / (Pn · 10^(s/10)) ),    y = x + α·n

Powers ``Px``/``Pn`` are the mean-square values *after removing the median* (DC),
computed over the **contaminated interval only** — not the whole 10 s window — so a
short noise burst is scaled against the signal it actually overlaps.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_EPS = 1e-12


def _dc_removed_power(x: np.ndarray) -> float:
    seg = x[np.isfinite(x)]
    if seg.size == 0:
        return 0.0
    return float(np.mean((seg - np.median(seg)) ** 2))


def snr_scale_factor(clean_seg: np.ndarray, noise_seg: np.ndarray, snr_db: float) -> float:
    """The α that places ``clean_seg + α·noise_seg`` at ``snr_db`` (DC-removed powers)."""
    px = _dc_removed_power(clean_seg)
    pn = _dc_removed_power(noise_seg)
    if pn <= _EPS or px <= _EPS:
        return 0.0
    return float(np.sqrt(px / (pn * 10.0 ** (snr_db / 10.0))))


@dataclass(frozen=True)
class MixResult:
    """Outcome of mixing real noise into one lead."""

    signal: np.ndarray  # (T,) noisy lead
    alpha: float
    snr_requested_db: float
    snr_measured_db: float
    interval: tuple[int, int]  # (start_sample, end_sample) contaminated


def measured_snr_db(clean_seg: np.ndarray, scaled_noise_seg: np.ndarray) -> float:
    """Post-hoc SNR of a contaminated segment (DC-removed powers), in dB."""
    px = _dc_removed_power(clean_seg)
    pn = _dc_removed_power(scaled_noise_seg)
    if pn <= _EPS:
        return float("inf")
    return float(10.0 * np.log10(max(px, _EPS) / pn))


def mix_lead(
    clean_lead: np.ndarray,
    noise: np.ndarray,
    snr_db: float,
    *,
    start: int = 0,
    duration: int | None = None,
) -> MixResult:
    """Mix ``noise`` into ``clean_lead`` over ``[start, start+duration)`` at ``snr_db``."""
    clean_lead = np.asarray(clean_lead, dtype=np.float64)
    t = clean_lead.shape[0]
    if duration is None:
        duration = t - start
    end = min(start + duration, t)
    length = end - start
    clean_seg = clean_lead[start:end]
    noise_seg = np.asarray(noise, dtype=np.float64)[:length]
    if noise_seg.shape[0] < length:
        raise ValueError(f"noise too short: need {length}, got {noise_seg.shape[0]}")

    alpha = snr_scale_factor(clean_seg, noise_seg, snr_db)
    scaled = alpha * noise_seg
    out = clean_lead.copy()
    out[start:end] = clean_seg + scaled
    return MixResult(
        signal=out,
        alpha=alpha,
        snr_requested_db=float(snr_db),
        snr_measured_db=measured_snr_db(clean_seg, scaled),
        interval=(start, end),
    )
