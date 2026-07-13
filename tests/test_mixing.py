# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""SNR mixing: measured SNR matches request; interval scoping; determinism."""

from __future__ import annotations

import numpy as np
import pytest

from torsade.mixing import measured_snr_db, mix_lead


@pytest.fixture
def clean_and_noise(ecg12):
    clean = ecg12[6]  # V1
    rng = np.random.default_rng(10)
    noise = 0.3 * np.sin(np.linspace(0, 80, clean.size)) + 0.05 * rng.standard_normal(clean.size)
    return clean, noise


@pytest.mark.parametrize("snr_db", [-6, 0, 6, 12, 18])
def test_measured_snr_matches_request(clean_and_noise, snr_db):
    clean, noise = clean_and_noise
    res = mix_lead(clean, noise, snr_db)
    assert abs(res.snr_measured_db - snr_db) < 0.5


def test_mixing_only_touches_the_interval(clean_and_noise):
    clean, noise = clean_and_noise
    start, dur = 1000, 1500
    res = mix_lead(clean, noise, 0.0, start=start, duration=dur)
    assert np.array_equal(res.signal[:start], clean[:start])
    assert np.array_equal(res.signal[start + dur :], clean[start + dur :])
    assert not np.array_equal(res.signal[start : start + dur], clean[start : start + dur])
    # Requested SNR is defined over the contaminated interval.
    seg_clean = clean[start : start + dur]
    seg_noise = res.signal[start : start + dur] - seg_clean
    assert abs(measured_snr_db(seg_clean, seg_noise) - 0.0) < 0.5


def test_mixing_is_deterministic(clean_and_noise):
    clean, noise = clean_and_noise
    a = mix_lead(clean, noise, 6.0)
    b = mix_lead(clean, noise, 6.0)
    assert np.array_equal(a.signal, b.signal)
    assert a.alpha == b.alpha


def test_zero_noise_power_is_safe(ecg12):
    res = mix_lead(ecg12[0], np.zeros(ecg12.shape[1]), 0.0)
    assert res.alpha == 0.0
    assert np.array_equal(res.signal, ecg12[0])
