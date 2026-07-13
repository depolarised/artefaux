# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Amplitude bookkeeping and clipping detection."""

from __future__ import annotations

import numpy as np

from torsade.amplitude import amplitude_record, detect_clipping, peak_to_peak_mv


def test_peak_to_peak_is_nan_safe():
    assert peak_to_peak_mv(np.array([np.nan, 1.0, -1.0, np.nan])) == 2.0
    assert peak_to_peak_mv(np.full(4, np.nan)) == 0.0


def test_detect_clipping_finds_a_run():
    fs = 500
    x = np.sin(np.linspace(0, 10, fs)) * 0.5
    x[100:200] = 5.0  # a 0.2 s pinned run at the rail
    frac, intervals = detect_clipping(x, rail_mv=5.0, fs=fs)
    assert frac > 0.0
    assert len(intervals) == 1
    start_s, end_s = intervals[0]
    assert abs(start_s - 100 / fs) < 1e-9
    assert abs(end_s - 200 / fs) < 1e-9


def test_single_sample_touch_is_not_clipping():
    x = np.zeros(500)
    x[250] = 5.0
    frac, intervals = detect_clipping(x, rail_mv=5.0, fs=500)
    assert frac == 0.0
    assert intervals == ()


def test_amplitude_record_reports_clip():
    fs = 500
    before = np.sin(np.linspace(0, 10, fs))
    after = np.clip(before * 20, -5.0, 5.0)
    rec = amplitude_record("V2", before, after, fs, rail_mv=5.0)
    assert rec.lead == "V2"
    assert rec.p2p_after_mv > rec.p2p_before_mv
    assert rec.clipped
    assert rec.clip_fraction > 0.0
    assert "clip_intervals_s" in rec.as_dict()
