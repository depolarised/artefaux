# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Check the agreement and accuracy statistics against hand-computed values."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from artefaux.scoring import (
    BinaryCounts,
    cluster_bootstrap_ci,
    cohen_kappa,
    fit_snr50,
    jaccard,
    mcnemar_exact,
    pabak,
    paired_difference_ci,
    wilson_ci,
)


def test_wilson_interval_matches_reference_value():
    # 8/10: Wilson 95% interval is 0.4902–0.9433 (Newcombe 1998, table I).
    lo, hi = wilson_ci(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-4)
    assert hi == pytest.approx(0.9433, abs=1e-4)
    assert all(math.isnan(v) for v in wilson_ci(0, 0))


def test_binary_metrics_from_pairs():
    predicted = [True, True, False, False, True, False]
    reference = [True, False, True, False, True, False]
    counts = BinaryCounts.from_pairs(predicted, reference)
    assert (counts.tp, counts.fp, counts.fn, counts.tn) == (2, 1, 1, 2)
    m = counts.metrics()
    assert m["sensitivity"]["value"] == pytest.approx(2 / 3)
    assert m["specificity"]["value"] == pytest.approx(2 / 3)
    assert m["f1"]["value"] == pytest.approx(4 / 6)


def test_cohen_kappa_hand_computed():
    # 2x2 table [[20, 5], [10, 15]]: p_o = 0.7, p_e = 0.5 -> kappa = 0.4.
    a = ["y"] * 25 + ["n"] * 25
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert cohen_kappa(a, b, ["y", "n"]) == pytest.approx(0.4)
    assert pabak(a, b, 2) == pytest.approx(0.4)
    assert cohen_kappa(a, a, ["y", "n"]) == pytest.approx(1.0)


def test_linear_weighted_kappa_penalises_distance():
    cats = ["analysable", "partial", "rhythm_only", "not_analysable"]
    a = ["analysable", "partial", "rhythm_only", "not_analysable"] * 5
    near = ["partial", "partial", "rhythm_only", "not_analysable"] * 5
    far = ["not_analysable", "partial", "rhythm_only", "not_analysable"] * 5
    assert cohen_kappa(a, near, cats, weights="linear") > cohen_kappa(
        a, far, cats, weights="linear"
    )
    with pytest.raises(ValueError, match="outside"):
        cohen_kappa(["x"], ["y"], ["y"])


def test_mcnemar_and_paired_difference():
    assert mcnemar_exact(0, 0) == 1.0
    # b=1, c=9: two-sided exact p = 2 * P(X<=1 | n=10) = 22/1024.
    assert mcnemar_exact(1, 9) == pytest.approx(22 / 1024)
    first = [True] * 30 + [False] * 10
    second = [True] * 20 + [False] * 20
    delta, lo, hi = paired_difference_ci(first, second)
    assert delta == pytest.approx(0.25)
    assert lo < delta < hi
    assert lo > 0  # ten discordant pairs, all in one direction


def test_cluster_bootstrap_is_seeded_and_brackets_the_estimate():
    values = np.array([1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 1, 1], dtype=float)
    clusters = np.repeat(np.arange(6), 2)

    def stat(idx):
        return float(values[idx].mean())

    first = cluster_bootstrap_ci(stat, clusters, n_resamples=500, seed=7)
    assert first == cluster_bootstrap_ci(stat, clusters, n_resamples=500, seed=7)
    assert first[0] <= values.mean() <= first[1]


def test_jaccard_and_snr50():
    assert jaccard(set(), set()) == 1.0
    assert jaccard({"V1", "V2"}, {"V2", "V3"}) == pytest.approx(1 / 3)
    snr = np.repeat([-9, -6, -3, 0, 3, 6], 20)
    rng = np.random.default_rng(0)
    p = 1 / (1 + np.exp(-(-1.5 - 0.8 * snr)))  # true snr50 = -1.875 dB
    fit = fit_snr50(snr, rng.random(snr.size) < p)
    assert fit["snr50"] == pytest.approx(-1.875, abs=1.0)
    assert fit["converged"] and not fit["separated"]
    assert math.isnan(fit["snr50_lo"]) and math.isnan(fit["snr50_hi"])
    assert math.isnan(fit_snr50([0, 1, 2], [True, True, True])["snr50"])


SNR_LEVELS = [-9, -6, -3, 0, 3, 6]


def test_separated_ladder_gives_interval_censored_bounds():
    # Unusable at -9, -6, -3 dB; usable at 0, 3, 6 dB: the MLE diverges, so the crossing
    # is only bracketed by the adjacent observed levels -3 and 0.
    snr = np.repeat(SNR_LEVELS, 5)
    fit = fit_snr50(snr, snr <= -3)
    assert fit["separated"] is True
    assert fit["converged"] is False
    assert math.isnan(fit["snr50"]) and math.isnan(fit["slope"])
    assert fit["snr50_lo"] == -3 and fit["snr50_hi"] == 0


def test_quasi_complete_separation_brackets_the_tie_level():
    # -3 dB is mixed (2 of 4 unusable): quasi-complete separation, no finite MLE.
    snr = np.repeat(SNR_LEVELS, 4)
    unusable = np.array([1] * 8 + [1, 1, 0, 0] + [0] * 12, dtype=bool)
    fit = fit_snr50(snr, unusable)
    assert fit["separated"] is True
    assert math.isnan(fit["snr50"])
    assert fit["snr50_lo"] == -6 and fit["snr50_hi"] == 0


def test_separated_outcome_without_dose_response_is_all_nan():
    snr = np.repeat([-6, 0, 6], 5)
    fit = fit_snr50(snr, snr >= 0)
    assert fit["separated"] is True
    for key in ("intercept", "slope", "snr50", "snr50_lo", "snr50_hi"):
        assert math.isnan(fit[key]), key


@pytest.mark.parametrize("value", [False, True])
def test_constant_outcome_is_not_fitted(value):
    fit = fit_snr50(np.repeat([-6, 0, 6], 5), np.full(15, value))
    assert math.isnan(fit["snr50"])
    assert fit["separated"] is False and fit["converged"] is False


def test_non_converged_fit_reports_no_snr50(monkeypatch):
    snr = np.repeat(SNR_LEVELS, 20)
    rng = np.random.default_rng(0)
    p = 1 / (1 + np.exp(-(-1.5 - 0.8 * snr)))  # would give a finite slope if trusted
    unusable = rng.random(snr.size) < p
    fake = SimpleNamespace(x=np.array([-1.5, -0.8]), success=False)
    monkeypatch.setattr("artefaux.scoring.optimize.minimize", lambda *a, **k: fake)
    fit = fit_snr50(snr, unusable)
    assert fit["converged"] is False
    assert math.isnan(fit["snr50"])


def test_paired_difference_ci_has_nominal_coverage():
    # Newcombe's method 10 (with the continuity-corrected phi) should cover the true paired
    # difference about 95% of the time; checked by simulation rather than a quoted table.
    rng = np.random.default_rng(11)
    probs = [0.30, 0.15, 0.05, 0.50]  # both, first only, second only, neither
    truth = probs[1] - probs[2]
    hits, n_sims, n = 0, 2000, 50
    for _ in range(n_sims):
        cell = rng.choice(4, size=n, p=probs)
        first, second = np.isin(cell, (0, 1)), np.isin(cell, (0, 2))
        _, lo, hi = paired_difference_ci(first, second)
        hits += lo <= truth <= hi
    assert 0.93 <= hits / n_sims <= 0.985


def test_continuity_corrected_phi_never_narrows_the_interval():
    # Positive association (ad > bc) shrinks the interval; the correction tempers that.
    first = [True] * 20 + [True] * 6 + [False] * 2 + [False] * 22
    second = [True] * 20 + [False] * 6 + [True] * 2 + [False] * 22
    delta, lo, hi = paired_difference_ci(first, second)
    assert delta == pytest.approx(4 / 50)
    assert -1 <= lo < delta < hi <= 1
