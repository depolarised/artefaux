# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""v2 aggressive-low SNR ladder: the expected-label bands must be correct.

The v1 ``_real_noise_expected`` mapped everything above 0 dB via a single ``else``
branch to ``diagnostic``. Under the v2 ladder ``{-6,-4,-2,0,+2}`` that would silently
mislabel the −4/−2 dB records as clean, so these tests pin the new bands.
"""

from __future__ import annotations

import pytest

from artefaux.constants import SNR_LADDER_DB
from artefaux.corpus import _real_noise_expected, build_corpus_specs


def test_v2_snr_ladder_is_aggressive_low():
    assert SNR_LADDER_DB == (-6, -4, -2, 0, 2)


@pytest.mark.parametrize(
    "snr, record_quality, lead_quality, discard",
    [
        (-6, "reject", "bad", True),
        (-4, "limited", "bad", True),
        (-2, "limited", "bad", True),
        (0, "limited", "borderline", True),
        (2, "limited", "borderline", False),
    ],
)
def test_all_lead_scope_thresholds(snr, record_quality, lead_quality, discard):
    exp = _real_noise_expected(snr, "all")
    assert exp["record_quality"] == record_quality
    assert exp["lead_quality"]["default"] == lead_quality
    assert exp["noiseguard_discard"] is discard


def test_no_ladder_level_is_labelled_diagnostic():
    # Regression guard for the v1 else-branch that mislabelled -4/-2 dB as diagnostic.
    for snr in SNR_LADDER_DB:
        assert _real_noise_expected(snr, "all")["record_quality"] != "diagnostic"


@pytest.mark.parametrize("scope", ["limb", "chest"])
def test_subset_scope_stays_limited_and_discards_only_at_or_below_zero(scope):
    # Only the touched half degrades, so the record stays interpretable ("limited");
    # discard follows the band but only at or below 0 dB.
    severe = _real_noise_expected(-6, scope)
    assert severe["record_quality"] == "limited"
    assert severe["noiseguard_discard"] is True
    assert _real_noise_expected(2, scope)["noiseguard_discard"] is False


def test_real_noise_group_uses_only_the_ladder():
    snrs = {
        st["snr_db"]
        for s in build_corpus_specs()
        if s.group == "real_noise"
        for st in s.steps
        if st["op"] == "nstdb_mix"
    }
    assert snrs == set(SNR_LADDER_DB)
