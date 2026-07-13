# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Engineering-case builders: each failure mode behaves and labels correctly."""

from __future__ import annotations

import numpy as np

from torsade.constants import LEAD_INDEX
from torsade.engineering import (
    build_constant_adc,
    build_digital_missing,
    build_flatline,
    build_intermittent_lead_off,
    build_lead_off,
    build_opposite_polarity,
    build_step_recovery,
    build_swing,
)

FS = 500


def test_swing_increases_amplitude_without_rail(ecg12):
    res = build_swing(ecg12, "V2", p2p_mv=8.0, rng=np.random.default_rng(0), fs=FS)
    idx = LEAD_INDEX["V2"]
    assert np.ptp(res.signal[idx]) > np.ptp(ecg12[idx])
    assert not res.data_integrity_failure
    assert res.case_type == "swing"


def test_overload_swing_clips_to_rail(ecg12):
    rail = 5.0
    res = build_swing(ecg12, "V2", p2p_mv=30.0, rng=np.random.default_rng(0), fs=FS, rail_mv=rail)
    idx = LEAD_INDEX["V2"]
    assert res.signal[idx].max() <= rail + 1e-9
    assert res.signal[idx].min() >= -rail - 1e-9
    assert np.ptp(res.signal[idx]) > rail
    assert res.data_integrity_failure and res.integrity_failure_type == "rail_saturation"


def test_flatline_zeroes_lead(ecg12):
    res = build_flatline(ecg12, "V3", fs=FS)
    assert np.all(res.signal[LEAD_INDEX["V3"]] == 0.0)
    assert res.integrity_failure_type == "flatline_zero"


def test_constant_adc_is_flat_nonzero(ecg12):
    res = build_constant_adc(ecg12, "V4", value_mv=1.3, fs=FS)
    lead = res.signal[LEAD_INDEX["V4"]]
    assert np.all(lead == 1.3)
    assert np.ptp(lead) == 0.0


def test_lead_off_has_near_zero_content(ecg12):
    res = build_lead_off(ecg12, "V5", rng=np.random.default_rng(1), fs=FS)
    assert np.ptp(res.signal[LEAD_INDEX["V5"]]) < 0.5
    assert res.data_integrity_failure


def test_digital_missing_sets_nan(ecg12):
    res = build_digital_missing(ecg12, "V6", fs=FS)
    assert np.isnan(res.signal[LEAD_INDEX["V6"]]).all()
    assert res.integrity_failure_type == "digital_missing_channel"
    # Other leads stay finite.
    assert np.all(np.isfinite(res.signal[LEAD_INDEX["I"]]))


def test_step_recovery_decays(ecg12):
    res = build_step_recovery(ecg12, "II", step_mv=3.0, tau_s=1.0, fs=FS, start_s=2.0)
    idx = LEAD_INDEX["II"]
    delta = res.signal[idx] - ecg12[idx]
    at_step = delta[int(2.0 * FS) + 1]
    near_end = delta[-1]
    assert at_step > 2.0  # ~step height
    assert near_end < at_step  # decayed
    assert not res.data_integrity_failure


def test_opposite_polarity_negates(ecg12):
    res = build_opposite_polarity(ecg12, "III", fs=FS)
    assert np.array_equal(res.signal[LEAD_INDEX["III"]], -ecg12[LEAD_INDEX["III"]])
    assert res.details["lead_reversal_suspected"]


def test_intermittent_lead_off_has_multiple_dropouts(ecg12):
    res = build_intermittent_lead_off(
        ecg12, "V1", rng=np.random.default_rng(2), fs=FS, n_dropouts=3
    )
    assert len(res.details["dropout_intervals_s"]) == 3
    assert res.data_integrity_failure


def test_multi_lead_case_affects_all_listed(ecg12):
    res = build_flatline(ecg12, ["V1", "V2"], fs=FS)
    assert set(res.leads_affected) == {"V1", "V2"}
    assert np.all(res.signal[LEAD_INDEX["V1"]] == 0.0)
    assert np.all(res.signal[LEAD_INDEX["V2"]] == 0.0)
