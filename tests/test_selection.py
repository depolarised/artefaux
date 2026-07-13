# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Deterministic PTB-XL selection."""

from __future__ import annotations

from torsade.selection import is_clean, quality_flags, select_ptbxl


def _row(ecg_id, patient_id, **flags):
    base = {
        "ecg_id": ecg_id,
        "patient_id": patient_id,
        "baseline_drift": "",
        "static_noise": "",
        "burst_noise": "",
        "electrodes_problems": "",
    }
    base.update(flags)
    return base


def test_is_clean_and_flags():
    assert is_clean(_row(1, 10))
    dirty = _row(2, 11, static_noise="lead V1", baseline_drift="nan")
    assert not is_clean(dirty)
    assert quality_flags(dirty) == ("static_noise",)  # 'nan' counts as blank


def test_select_dedupes_by_patient_and_is_deterministic():
    rows = [_row(i, patient_id=i % 5) for i in range(10)]  # 5 patients, 2 ecgs each
    rows += [_row(100 + i, patient_id=100 + i, static_noise="x") for i in range(4)]  # 4 noisy
    clean_a, noisy_a = select_ptbxl(rows, n_clean=3, n_noisy=2, seed=7)
    clean_b, noisy_b = select_ptbxl(rows, n_clean=3, n_noisy=2, seed=7)
    assert [r["ecg_id"] for r in clean_a] == [r["ecg_id"] for r in clean_b]  # deterministic
    assert len({r["patient_id"] for r in clean_a}) == 3  # one ECG per patient
    assert len(noisy_a) == 2
    assert all(not is_clean(r) for r in noisy_a)


def test_request_more_than_available_returns_all():
    rows = [_row(i, patient_id=i) for i in range(3)]
    clean, _ = select_ptbxl(rows, n_clean=99, n_noisy=0, seed=1)
    assert len(clean) == 3
