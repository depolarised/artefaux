# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Precordial coupling: shared weight controls correlation; scoping; validation."""

from __future__ import annotations

import numpy as np
import pytest

from torsade.constants import LEAD_INDEX, LIMB_LEADS
from torsade.precordial import corrupt_precordial, coupled_noise_traces


def test_shared_weight_increases_correlation():
    hi = coupled_noise_traces(2000, 500, {"V4": 0.9, "V5": 0.9}, np.random.default_rng(0))
    lo = coupled_noise_traces(2000, 500, {"V4": 0.1, "V5": 0.1}, np.random.default_rng(0))
    corr_hi = np.corrcoef(hi["V4"], hi["V5"])[0, 1]
    corr_lo = np.corrcoef(lo["V4"], lo["V5"])[0, 1]
    assert corr_hi > corr_lo
    assert corr_hi > 0.5


def test_corrupt_precordial_scopes_to_targets(ecg12):
    res = corrupt_precordial(
        ecg12, {"V4": 0.8, "V5": 0.7}, snr_db=0.0, rng=np.random.default_rng(1), fs=500
    )
    assert res.leads_corrupted == ("V4", "V5")
    for limb in LIMB_LEADS:
        assert np.array_equal(res.signal[LEAD_INDEX[limb]], ecg12[LEAD_INDEX[limb]])
    assert np.array_equal(res.signal[LEAD_INDEX["V1"]], ecg12[LEAD_INDEX["V1"]])
    for snr in res.per_lead_snr_db.values():
        assert abs(snr - 0.0) < 0.5


def test_corrupt_precordial_rejects_limb_leads(ecg12):
    with pytest.raises(ValueError):
        corrupt_precordial(ecg12, {"I": 0.5}, 0.0, np.random.default_rng(2), fs=500)
