# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Benchmark scoring on fabricated predictions with hand-computed answers."""

from __future__ import annotations

import math

import pytest

from artefaux.bench_scoring import (
    LEAD_COLUMNS,
    RECORD_COLUMNS,
    consensus_reference,
    lead_level,
    load_predictions,
    paired_comparison,
    record_level,
)
from artefaux.review_coding import DISPLAYED_LEADS, CodedResponse

CODES = ["T1-001", "T1-002", "T1-003", "T1-004"]


def ref(code, leads=(), overall=None):
    overall = overall or ("partial" if leads else "analysable")
    return CodedResponse(code, "consensus", tuple(leads), "full", overall, ())


def rows(source, decisions, errors=()):
    """``decisions``: code -> (repeat, unusable leads)."""
    rec, lead = [], []
    for code in CODES:
        repeat, unusable = decisions[code]
        rec.append(
            dict(
                zip(
                    RECORD_COLUMNS,
                    [
                        "1",
                        "1.0.0",
                        code,
                        source,
                        "0.1",
                        "abc",
                        str(repeat).lower(),
                        "not_emitted",
                        "not_emitted",
                        "",
                        "crash" if code in errors else "",
                        "5",
                    ],
                    strict=True,
                )
            )
        )
        for ld in DISPLAYED_LEADS:
            lead.append(
                dict(
                    zip(LEAD_COLUMNS, [code, source, ld, str(ld in unusable), "", ""], strict=True)
                )
            )
    return rec, lead


REFERENCE = {
    "T1-001": ref("T1-001"),
    "T1-002": ref("T1-002", ["V1", "V2"]),
    "T1-003": ref("T1-003", overall="not_analysable"),
    "T1-004": ref("T1-004", ["I"]),
}


def test_lead_and_record_metrics_hand_computed():
    pred = load_predictions(
        *rows(
            "toolA",
            {
                "T1-001": (False, ["V6"]),  # 1 FP
                "T1-002": (False, ["V1"]),  # 1 TP, 1 FN
                "T1-003": (True, []),  # 8 TP (repeat => every lead)
                "T1-004": (False, []),  # 1 FN
            },
        ),
        CODES,
    )
    lead = lead_level(pred, REFERENCE, CODES, seed=1, n_resamples=200)
    # Reference positives: 2 + 8 + 1 = 11; predicted TP = 1 + 8 = 9.
    assert lead["counts"] == {"tp": 9, "fp": 1, "fn": 2, "tn": 20}
    assert lead["sensitivity"]["value"] == pytest.approx(9 / 11)
    assert lead["sensitivity"]["lo"] <= 9 / 11 <= lead["sensitivity"]["hi"]
    rec = record_level(pred, REFERENCE, CODES)
    assert rec["sensitivity"]["value"] == 1.0 and rec["specificity"]["value"] == 1.0


def test_failures_count_against_the_tool_under_intention_to_diagnose():
    perfect = {
        "T1-001": (False, []),
        "T1-002": (False, ["V1", "V2"]),
        "T1-003": (True, []),
        "T1-004": (False, ["I"]),
    }
    pred = load_predictions(*rows("toolA", perfect, errors={"T1-003"}), CODES)
    itd = record_level(pred, REFERENCE, CODES)
    assert itd["sensitivity"]["value"] == 0.0
    lead = lead_level(pred, REFERENCE, CODES, seed=1, n_resamples=50)
    assert lead["counts"]["fn"] == 8


def test_schema_violations_are_rejected():
    rec, lead = rows("toolA", {c: (False, []) for c in CODES})
    with pytest.raises(ValueError, match="codes differ"):
        load_predictions(rec[:-1], lead, CODES)
    with pytest.raises(ValueError, match="duplicate"):
        load_predictions(rec, lead + lead[:1], CODES)
    bad = [dict(r, usable_section="middle") for r in rec]
    with pytest.raises(ValueError, match="usable_section"):
        load_predictions(bad, lead, CODES)


def test_consensus_requires_adjudication_for_disagreements():
    a = {"T1-001": ref("T1-001", ["V1"])}
    b = {"T1-001": ref("T1-001", ["V2"])}
    with pytest.raises(ValueError, match="adjudicated"):
        consensus_reference(a, b, {})
    settled = consensus_reference(a, b, {"T1-001": ref("T1-001", ["V1", "V2"])})
    assert settled["T1-001"].unusable_leads == ("V1", "V2")
    assert consensus_reference(a, a, {})["T1-001"].unusable_leads == ("V1",)


def test_paired_comparison_direction():
    good = {
        "T1-001": (False, []),
        "T1-002": (False, ["V1", "V2"]),
        "T1-003": (True, []),
        "T1-004": (False, ["I"]),
    }
    blind = {c: (False, []) for c in CODES}
    a = load_predictions(*rows("good", good), CODES)
    b = load_predictions(*rows("blind", blind), CODES)
    cmp = paired_comparison(a, b, REFERENCE, CODES, seed=3, n_resamples=200)
    assert cmp["record_sensitivity"]["difference"] == 1.0
    assert cmp["lead_sensitivity"]["difference"] == pytest.approx(1.0)


def test_failed_run_is_wrong_in_both_paired_subsets():
    # A tool that fails everywhere is wrong on every record; the perfect tool is right on
    # every record. Specificity (non-repeat records) must show the same -1 as sensitivity.
    perfect = {
        "T1-001": (False, []),
        "T1-002": (False, ["V1", "V2"]),
        "T1-003": (True, []),
        "T1-004": (False, ["I"]),
    }
    failing = load_predictions(*rows("broken", perfect, errors=set(CODES)), CODES)
    good = load_predictions(*rows("perfect", perfect), CODES)
    cmp = paired_comparison(failing, good, REFERENCE, CODES, seed=3, n_resamples=50)
    assert cmp["record_sensitivity"]["difference"] == -1.0
    assert cmp["record_specificity"]["difference"] == -1.0
    assert cmp["record_specificity"]["n"] == 3
    assert cmp["lead_specificity"]["difference"] == -1.0


def test_paired_comparison_reports_lead_specificity_with_cluster_ci():
    # Over-caller: every lead flagged on every record. Sensitivity is unaffected; lead
    # specificity is lost on all 21 non-unusable units (7 + 6 + 8 for T1-001, T1-002, T1-004).
    over_call = {c: (False, list(DISPLAYED_LEADS)) for c in CODES}
    perfect = {
        "T1-001": (False, []),
        "T1-002": (False, ["V1", "V2"]),
        "T1-003": (True, []),
        "T1-004": (False, ["I"]),
    }
    a = load_predictions(*rows("overcall", over_call), CODES)
    b = load_predictions(*rows("perfect", perfect), CODES)
    cmp = paired_comparison(a, b, REFERENCE, CODES, seed=3, n_resamples=200)
    assert cmp["lead_sensitivity"]["difference"] == pytest.approx(0.0)
    assert cmp["lead_specificity"]["difference"] == pytest.approx(-1.0)
    assert cmp["lead_specificity"]["lo"] <= -1.0 <= cmp["lead_specificity"]["hi"]
    assert {"difference", "lo", "hi"} <= cmp["lead_specificity"].keys()


def test_itd_false_excludes_failed_records_from_lead_and_record_level():
    perfect = {
        "T1-001": (False, []),
        "T1-002": (False, ["V1", "V2"]),
        "T1-003": (True, []),
        "T1-004": (False, ["I"]),
    }
    pred = load_predictions(*rows("toolA", perfect, errors={"T1-003"}), CODES)

    # Excluded: the failed T1-003 (a repeat-ECG in the reference) leaves no positives.
    excluded = record_level(pred, REFERENCE, CODES, itd=False)
    assert excluded["sensitivity"]["n"] == 0
    assert math.isnan(excluded["sensitivity"]["value"])
    assert excluded["specificity"]["n"] == 3
    assert excluded["specificity"]["value"] == 1.0

    # Intention-to-diagnose keeps it as a discordant (missed) repeat.
    itd = record_level(pred, REFERENCE, CODES, itd=True)
    assert itd["sensitivity"]["n"] == 1
    assert itd["sensitivity"]["value"] == 0.0

    lead = lead_level(pred, REFERENCE, CODES, seed=1, n_resamples=50, itd=False)
    assert lead["n_records"] == 3
    assert lead["n_units"] == 24
    assert lead["counts"] == {"tp": 3, "fp": 0, "fn": 0, "tn": 21}
    assert lead_level(pred, REFERENCE, CODES, seed=1, n_resamples=50)["n_records"] == 4


def test_consensus_requires_agreement_on_usable_section():
    a = {"T1-001": CodedResponse("T1-001", "PWM", (), "first_half", "partial", ())}
    b = {"T1-001": CodedResponse("T1-001", "DTC", (), "second_half", "partial", ())}
    with pytest.raises(ValueError, match="adjudicated"):
        consensus_reference(a, b, {})
    settled = {"T1-001": CodedResponse("T1-001", "adjudicated", (), "none", "partial", ())}
    assert consensus_reference(a, b, settled)["T1-001"].usable_section == "none"


def test_consensus_keeps_agreed_section_without_full_fallback():
    a = {"T1-001": CodedResponse("T1-001", "PWM", ("V1",), "first_half", "partial", ())}
    b = {"T1-001": CodedResponse("T1-001", "DTC", ("V1",), "first_half", "analysable", ())}
    out = consensus_reference(a, b, {})["T1-001"]
    assert out.usable_section == "first_half"
    assert out.unusable_leads == ("V1",)
    assert out.overall == "partial"


def test_consensus_ignores_section_when_both_repeat():
    a = {"T1-001": CodedResponse("T1-001", "PWM", (), "full", "not_analysable", ())}
    b = {"T1-001": CodedResponse("T1-001", "DTC", (), "none", "rhythm_only", ())}
    out = consensus_reference(a, b, {})["T1-001"]
    assert out.repeat_ecg


def test_load_predictions_rejects_other_bench_version():
    rec, lead = rows("toolA", {c: (False, []) for c in CODES})
    stale = [dict(r, bench_version="0.9.0") for r in rec]
    with pytest.raises(ValueError, match="bench_version"):
        load_predictions(stale, lead, CODES)
    assert load_predictions(rec, lead, CODES)  # the fixture's 1.0.0 is accepted
