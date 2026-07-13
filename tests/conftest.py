# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Shared synthetic fixtures — no PhysioNet download required.

The synthetic 12-lead is *Einthoven-consistent* (III/aVR/aVL/aVF are derived from
I and II) so that electrode-domain round-trips are exact. Records are written as
real WFDB via ``wfdb.wrsamp`` so the loaders exercise the true on-disk path.
"""

from __future__ import annotations

import numpy as np
import pytest
import wfdb

from torsade.constants import CANONICAL_LEAD_ORDER
from torsade.electrode_domain import derive_limb_leads_from_I_II


def make_einthoven_ecg(fs: int = 500, seconds: float = 10.0, seed: int = 0) -> np.ndarray:
    """Return a synthetic, Einthoven-consistent ``(12, T)`` mV array."""
    rng = np.random.default_rng(seed)
    n = int(round(fs * seconds))
    t = np.arange(n) / fs

    def beats(amp: float, width: float = 0.02) -> np.ndarray:
        sig = np.zeros_like(t)
        for k in range(int(seconds)):
            sig += amp * np.exp(-((t - (k + 0.3)) ** 2) / (2 * width**2))
        return sig

    lead_i = beats(1.0) + 0.05 * np.sin(2 * np.pi * 0.20 * t)
    lead_ii = beats(1.5) + 0.05 * np.sin(2 * np.pi * 0.15 * t)
    iii, avr, avl, avf = derive_limb_leads_from_I_II(lead_i, lead_ii)
    chest = {f"V{k + 1}": beats(0.8 + 0.15 * k) + 0.02 * rng.standard_normal(n) for k in range(6)}
    leads = {"I": lead_i, "II": lead_ii, "III": iii, "aVR": avr, "aVL": avl, "aVF": avf, **chest}
    return np.stack([leads[name] for name in CANONICAL_LEAD_ORDER], axis=0)


@pytest.fixture
def ecg12() -> np.ndarray:
    return make_einthoven_ecg(seed=1)


@pytest.fixture
def wfdb_parent(tmp_path):
    """A 12-lead WFDB parent at 500 Hz. Returns the extensionless record path."""
    sig = make_einthoven_ecg(fs=500, seconds=10.0, seed=2)
    wfdb.wrsamp(
        record_name="parent",
        fs=500,
        units=["mV"] * 12,
        sig_name=list(CANONICAL_LEAD_ORDER),
        p_signal=sig.T,
        fmt=["16"] * 12,
        write_dir=str(tmp_path),
    )
    return tmp_path / "parent"


@pytest.fixture
def nstdb_record(tmp_path):
    """A two-channel 360 Hz noise record (NSTDB-like). Returns the record path."""
    fs = 360
    n = fs * 10
    t = np.arange(n) / fs
    rng = np.random.default_rng(3)
    noise = 0.3 * np.sin(2 * np.pi * 7.0 * t) + 0.1 * rng.standard_normal(n)
    sig = np.stack([noise, 0.5 * noise], axis=1)
    wfdb.wrsamp(
        record_name="em",
        fs=fs,
        units=["mV", "mV"],
        sig_name=["noise0", "noise1"],
        p_signal=sig,
        fmt=["16", "16"],
        write_dir=str(tmp_path),
    )
    return tmp_path / "em"
