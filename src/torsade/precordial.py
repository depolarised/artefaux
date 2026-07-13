# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Precordial (chest-lead) corruption with shared + independent components.

A loose chest electrode disturbs mainly its own lead, but adjacent electrodes on
the same acquisition often share a common motion component. Copying an identical
noise trace into two leads looks artificial; Torsade instead builds each lead's
noise as a weighted mix of a shared component and an independent one, e.g.

    n_V4 = 0.8·n_shared + 0.2·n_1,   n_V5 = 0.7·n_shared + 0.3·n_2

so adjacent leads are correlated but distinct.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import CHEST_LEADS, LEAD_INDEX
from .mixing import mix_lead
from .noise_shapes import motion_trace, normalize_unit_power


def coupled_noise_traces(
    n_samples: int,
    fs: int,
    shared_weights: dict[str, float],
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Return per-lead unit-power noise traces sharing a common component.

    ``shared_weights`` maps each target lead to its shared-component weight in
    ``[0, 1]``; the remainder is an independent per-lead component.
    """
    shared = normalize_unit_power(motion_trace(n_samples, fs, rng))
    traces: dict[str, np.ndarray] = {}
    for lead, w in shared_weights.items():
        if not 0.0 <= w <= 1.0:
            raise ValueError(f"shared weight for {lead} must be in [0, 1], got {w}")
        indep = normalize_unit_power(motion_trace(n_samples, fs, rng))
        traces[lead] = normalize_unit_power(w * shared + (1.0 - w) * indep)
    return traces


@dataclass(frozen=True)
class PrecordialResult:
    signal: np.ndarray  # (12, T) corrupted
    leads_corrupted: tuple[str, ...]
    per_lead_snr_db: dict[str, float]  # measured SNR per lead


def corrupt_precordial(
    signal: np.ndarray,
    shared_weights: dict[str, float],
    snr_db: float,
    rng: np.random.Generator,
    *,
    fs: int,
    start: int = 0,
    duration: int | None = None,
) -> PrecordialResult:
    """Corrupt chest leads with coupled shared+independent noise at ``snr_db``."""
    bad = set(shared_weights) - set(CHEST_LEADS)
    if bad:
        raise ValueError(f"corrupt_precordial only accepts chest leads; got {sorted(bad)}")
    n = signal.shape[1]
    traces = coupled_noise_traces(n, fs, shared_weights, rng)
    out = signal.copy()
    measured: dict[str, float] = {}
    for lead, trace in traces.items():
        idx = LEAD_INDEX[lead]
        res = mix_lead(signal[idx], trace, snr_db, start=start, duration=duration)
        out[idx] = res.signal
        measured[lead] = res.snr_measured_db
    return PrecordialResult(
        signal=out,
        leads_corrupted=tuple(sorted(traces, key=lambda ld: LEAD_INDEX[ld])),
        per_lead_snr_db=measured,
    )
