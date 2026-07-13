# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Loaders: canonical shape/order, resampling, and finiteness."""

from __future__ import annotations

import numpy as np

from torsade.constants import TARGET_FS
from torsade.loaders import load_nstdb_noise, load_wfdb_parent, resample_signal


def test_resample_identity_when_rates_match():
    x = np.arange(100, dtype=np.float64)
    assert np.array_equal(resample_signal(x, 500, 500), x)


def test_resample_changes_length_360_to_500():
    x = np.zeros(360)
    out = resample_signal(x, 360, 500)
    assert out.shape[0] == 500  # 360 * 500/360


def test_load_parent_is_canonical(wfdb_parent):
    parent = load_wfdb_parent(wfdb_parent, "synthetic")
    assert parent.signal.shape == (12, 5000)
    assert parent.fs == TARGET_FS
    assert parent.signal.dtype == np.float64
    assert np.all(np.isfinite(parent.signal))
    assert parent.source_id == "parent"


def test_load_nstdb_resamples_and_windows(nstdb_record):
    seg = load_nstdb_noise(nstdb_record, "em", n_samples=5000, start_sample=0)
    assert seg.signal.shape == (5000,)
    assert seg.fs == TARGET_FS
    assert seg.noise_type == "em"
    # Wrap-around: any start yields a full-length segment.
    seg2 = load_nstdb_noise(nstdb_record, "em", n_samples=5000, start_sample=4800)
    assert seg2.signal.shape == (5000,)
