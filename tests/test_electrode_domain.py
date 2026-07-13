# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Electrode-domain algebra: exact round-trip and correct corruption propagation."""

from __future__ import annotations

import numpy as np

from torsade.constants import CHEST_LEADS, LEAD_INDEX, LIMB_LEADS
from torsade.electrode_domain import (
    corrupt_electrode_domain,
    electrodes_to_leads,
    leads_to_electrodes,
)


def test_roundtrip_is_exact(ecg12):
    reconstructed = electrodes_to_leads(leads_to_electrodes(ecg12))
    assert np.max(np.abs(reconstructed - ecg12)) < 1e-9


def test_limb_electrode_corrupts_limb_and_chest(ecg12):
    art = 0.5 * np.sin(np.linspace(0, 20, ecg12.shape[1]))
    res = corrupt_electrode_domain(ecg12, {"LA": art})
    changed = set(res.leads_changed)
    # LA feeds I, III, aVR, aVL (limb) and, via WCT, all chest leads.
    assert {"I", "III", "aVR", "aVL"} <= changed
    assert set(CHEST_LEADS) <= changed
    # Lead II depends only on LL and RA, so it must be untouched by an LA artefact.
    assert "II" not in changed
    # Derived limb leads that changed are flagged invalidated.
    assert set(res.derived_leads_invalidated) <= set(LIMB_LEADS)
    assert "III" in res.derived_leads_invalidated


def test_chest_electrode_corrupts_only_its_lead(ecg12):
    art = np.full(ecg12.shape[1], 2.0)
    res = corrupt_electrode_domain(ecg12, {"C2": art})
    assert res.leads_changed == ("V2",)
    assert res.derived_leads_invalidated == ()
    delta = res.signal[LEAD_INDEX["V2"]] - ecg12[LEAD_INDEX["V2"]]
    assert np.allclose(delta, 2.0)


def test_common_offset_on_all_electrodes_cancels(ecg12):
    # A common offset on *every* electrode (limb + chest) is a pure gauge shift
    # and cancels in every lead.
    off = np.full(ecg12.shape[1], 1.0)
    art = {name: off for name in ("RA", "LA", "LL", "C1", "C2", "C3", "C4", "C5", "C6")}
    res = corrupt_electrode_domain(ecg12, art)
    assert np.max(np.abs(res.signal - ecg12)) < 1e-9
    assert res.leads_changed == ()


def test_limb_common_offset_shifts_chest_via_wct(ecg12):
    # Offsetting only the limb electrodes moves WCT, so chest leads shift by -off
    # while every limb lead (all differences of limb electrodes) is unchanged.
    off = np.full(ecg12.shape[1], 1.0)
    res = corrupt_electrode_domain(ecg12, {"RA": off, "LA": off, "LL": off})
    assert set(res.leads_changed) == set(CHEST_LEADS)
    for limb in LIMB_LEADS:
        assert limb not in res.leads_changed
    for k in range(6):
        delta = res.signal[LEAD_INDEX[f"V{k + 1}"]] - ecg12[LEAD_INDEX[f"V{k + 1}"]]
        assert np.allclose(delta, -1.0)
