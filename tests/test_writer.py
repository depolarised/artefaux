# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""WFDB writer: physical round-trip within quantization, and NaN handling."""

from __future__ import annotations

import numpy as np
import wfdb

from torsade.constants import CANONICAL_LEAD_ORDER, LEAD_INDEX
from torsade.engineering import build_digital_missing
from torsade.writer import ADC_GAIN_PER_MV, write_wfdb


def test_wfdb_physical_roundtrip(ecg12, tmp_path):
    path = write_wfdb("rec", ecg12, 500, tmp_path)
    back = wfdb.rdrecord(str(path))
    assert list(back.sig_name) == list(CANONICAL_LEAD_ORDER)
    assert int(back.fs) == 500
    reloaded = np.asarray(back.p_signal, dtype=np.float64).T
    assert reloaded.shape == ecg12.shape
    # Within one ADC step (1/gain mV).
    assert np.nanmax(np.abs(reloaded - ecg12)) <= 1.0 / ADC_GAIN_PER_MV + 1e-9


def test_wfdb_nan_roundtrips(ecg12, tmp_path):
    res = build_digital_missing(ecg12, "V6", fs=500)
    path = write_wfdb("rec_nan", res.signal, 500, tmp_path)
    back = wfdb.rdrecord(str(path))
    reloaded = np.asarray(back.p_signal, dtype=np.float64).T
    assert np.isnan(reloaded[LEAD_INDEX["V6"]]).all()
    assert np.all(np.isfinite(reloaded[LEAD_INDEX["I"]]))
