# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Extreme "engineering" failure builders.

These deliberately break acquisition rather than merely adding noise: rail
clipping, flat/constant channels, disconnected leads, digital-missing (NaN)
channels, enormous swings, step displacement with recovery, polarity reversal,
and intermittent lead-off. Each returns the corrupted ``(12, T)`` array plus a
truthful description, and flags whether the case is a *data-integrity failure*
(missing/flat/rail) rather than physiological noise.

Builders accept one lead or a list of leads, so both single-lead and multi-lead
mixed cases are expressed with the same primitives.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from .amplitude import amplitude_record
from .constants import LEAD_INDEX
from .noise_shapes import motion_trace


def _coerce_leads(leads: str | Sequence[str]) -> list[str]:
    if isinstance(leads, str):
        return [leads]
    return list(leads)


def _interval_samples(interval_s: tuple[float, float] | None, n: int, fs: int) -> tuple[int, int]:
    if interval_s is None:
        return 0, n
    start = max(0, int(round(interval_s[0] * fs)))
    end = min(n, int(round(interval_s[1] * fs)))
    if end <= start:
        raise ValueError(f"empty interval {interval_s}")
    return start, end


@dataclass(frozen=True)
class EngineeringResult:
    signal: np.ndarray  # (12, T), may contain NaN for digital-missing cases
    leads_affected: tuple[str, ...]
    case_type: str
    data_integrity_failure: bool
    integrity_failure_type: str | None
    details: dict = field(default_factory=dict)


def _amp_details(
    leads: list[str], before: np.ndarray, after: np.ndarray, fs: int, rail_mv: float | None
) -> list[dict]:
    return [
        amplitude_record(
            ld, before[LEAD_INDEX[ld]], after[LEAD_INDEX[ld]], fs, rail_mv=rail_mv
        ).as_dict()
        for ld in leads
    ]


def build_swing(
    signal: np.ndarray,
    leads: str | Sequence[str],
    p2p_mv: float,
    rng: np.random.Generator,
    *,
    fs: int,
    interval_s: tuple[float, float] | None = None,
    rail_mv: float | None = None,
) -> EngineeringResult:
    """Add a large electrode-motion swing of ~``p2p_mv`` peak-to-peak; optionally clip.

    With ``rail_mv`` set and ``p2p_mv`` beyond the rail, this is an *overload* case:
    the requested amplitude and the actual post-clip amplitude are both recorded.
    """
    leads = _coerce_leads(leads)
    out = signal.copy()
    s, e = _interval_samples(interval_s, signal.shape[1], fs)
    for ld in leads:
        idx = LEAD_INDEX[ld]
        swing = motion_trace(e - s, fs, rng)
        ptp = float(np.ptp(swing)) or 1.0
        seg = out[idx, s:e] + swing * (p2p_mv / ptp)
        if rail_mv is not None:
            seg = np.clip(seg, -rail_mv, rail_mv)
        out[idx, s:e] = seg
    clipped = rail_mv is not None
    return EngineeringResult(
        signal=out,
        leads_affected=tuple(leads),
        case_type="overload_swing" if clipped else "swing",
        data_integrity_failure=clipped,
        integrity_failure_type="rail_saturation" if clipped else None,
        details={
            "requested_p2p_mv": p2p_mv,
            "rail_mv": rail_mv,
            "interval_s": [s / fs, e / fs],
            "amplitude": _amp_details(leads, signal, out, fs, rail_mv),
        },
    )


def build_flatline(
    signal: np.ndarray,
    leads: str | Sequence[str],
    *,
    fs: int,
    interval_s: tuple[float, float] | None = None,
) -> EngineeringResult:
    """Zero-fill a lead (dead channel)."""
    leads = _coerce_leads(leads)
    out = signal.copy()
    s, e = _interval_samples(interval_s, signal.shape[1], fs)
    for ld in leads:
        out[LEAD_INDEX[ld], s:e] = 0.0
    return EngineeringResult(
        signal=out,
        leads_affected=tuple(leads),
        case_type="flatline",
        data_integrity_failure=True,
        integrity_failure_type="flatline_zero",
        details={"interval_s": [s / fs, e / fs]},
    )


def build_constant_adc(
    signal: np.ndarray,
    leads: str | Sequence[str],
    value_mv: float,
    *,
    fs: int,
    interval_s: tuple[float, float] | None = None,
) -> EngineeringResult:
    """Pin a lead to a constant non-zero value (stuck ADC)."""
    leads = _coerce_leads(leads)
    out = signal.copy()
    s, e = _interval_samples(interval_s, signal.shape[1], fs)
    for ld in leads:
        out[LEAD_INDEX[ld], s:e] = value_mv
    return EngineeringResult(
        signal=out,
        leads_affected=tuple(leads),
        case_type="constant_adc",
        data_integrity_failure=True,
        integrity_failure_type="constant_adc",
        details={"value_mv": value_mv, "interval_s": [s / fs, e / fs]},
    )


def build_lead_off(
    signal: np.ndarray,
    leads: str | Sequence[str],
    rng: np.random.Generator,
    *,
    fs: int,
    interval_s: tuple[float, float] | None = None,
    residual_drift_mv: float = 0.05,
) -> EngineeringResult:
    """Disconnected electrode: near-zero cardiac content with weak drift/noise."""
    leads = _coerce_leads(leads)
    out = signal.copy()
    s, e = _interval_samples(interval_s, signal.shape[1], fs)
    for ld in leads:
        drift = residual_drift_mv * motion_trace(e - s, fs, rng)
        out[LEAD_INDEX[ld], s:e] = drift
    return EngineeringResult(
        signal=out,
        leads_affected=tuple(leads),
        case_type="lead_off",
        data_integrity_failure=True,
        integrity_failure_type="lead_off",
        details={"residual_drift_mv": residual_drift_mv, "interval_s": [s / fs, e / fs]},
    )


def build_digital_missing(
    signal: np.ndarray,
    leads: str | Sequence[str],
    *,
    fs: int,
    interval_s: tuple[float, float] | None = None,
) -> EngineeringResult:
    """Set a channel to NaN (digital missing). A software-robustness test, not noise."""
    leads = _coerce_leads(leads)
    out = signal.copy()
    s, e = _interval_samples(interval_s, signal.shape[1], fs)
    for ld in leads:
        out[LEAD_INDEX[ld], s:e] = np.nan
    return EngineeringResult(
        signal=out,
        leads_affected=tuple(leads),
        case_type="digital_missing",
        data_integrity_failure=True,
        integrity_failure_type="digital_missing_channel",
        details={"interval_s": [s / fs, e / fs]},
    )


def build_step_recovery(
    signal: np.ndarray,
    leads: str | Sequence[str],
    step_mv: float,
    tau_s: float,
    *,
    fs: int,
    start_s: float = 2.0,
) -> EngineeringResult:
    """A step baseline displacement that decays exponentially back (loose-then-settling contact)."""
    leads = _coerce_leads(leads)
    out = signal.copy()
    n = signal.shape[1]
    start = int(round(start_s * fs))
    t = np.arange(n - start) / fs
    envelope = step_mv * np.exp(-t / tau_s)
    for ld in leads:
        out[LEAD_INDEX[ld], start:] += envelope
    return EngineeringResult(
        signal=out,
        leads_affected=tuple(leads),
        case_type="step_recovery",
        data_integrity_failure=False,
        integrity_failure_type=None,
        details={
            "step_mv": step_mv,
            "tau_s": tau_s,
            "start_s": start_s,
            "amplitude": _amp_details(leads, signal, out, fs, None),
        },
    )


def build_opposite_polarity(
    signal: np.ndarray,
    leads: str | Sequence[str],
    *,
    fs: int,
) -> EngineeringResult:
    """Invert a lead's polarity (reversed electrode connection)."""
    leads = _coerce_leads(leads)
    out = signal.copy()
    for ld in leads:
        out[LEAD_INDEX[ld]] = -signal[LEAD_INDEX[ld]]
    return EngineeringResult(
        signal=out,
        leads_affected=tuple(leads),
        case_type="opposite_polarity",
        data_integrity_failure=False,
        integrity_failure_type=None,
        details={"lead_reversal_suspected": True},
    )


def build_intermittent_lead_off(
    signal: np.ndarray,
    leads: str | Sequence[str],
    rng: np.random.Generator,
    *,
    fs: int,
    n_dropouts: int = 3,
    dropout_s: float = 1.0,
    reconnect_transient_mv: float = 0.5,
) -> EngineeringResult:
    """Alternating valid signal and dropout, with a transient spike on reconnection."""
    leads = _coerce_leads(leads)
    out = signal.copy()
    n = signal.shape[1]
    duration = n / fs
    dur = int(round(dropout_s * fs))
    # Evenly spaced dropout onsets that fit inside the record.
    slots = np.linspace(dur, n - 2 * dur, n_dropouts).astype(int)
    intervals: list[list[float]] = []
    for ld in leads:
        idx = LEAD_INDEX[ld]
        for onset in slots:
            end = min(onset + dur, n)
            out[idx, onset:end] = 0.0
            intervals.append([onset / fs, end / fs])
            if end < n:  # reconnection transient
                trans_len = min(int(0.05 * fs), n - end)
                out[idx, end : end + trans_len] += reconnect_transient_mv * np.exp(
                    -np.arange(trans_len) / (0.01 * fs)
                )
    return EngineeringResult(
        signal=out,
        leads_affected=tuple(leads),
        case_type="intermittent_lead_off",
        data_integrity_failure=True,
        integrity_failure_type="intermittent_lead_off",
        details={
            "n_dropouts": n_dropouts,
            "dropout_s": dropout_s,
            "reconnect_transient_mv": reconnect_transient_mv,
            "dropout_intervals_s": intervals,
            "record_duration_s": duration,
        },
    )
