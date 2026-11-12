# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Benchmark scoring on fabricated predictions with hand-computed answers."""

from __future__ import annotations

import inspect
import math

import pytest

from artefaux.bench_scoring import (
    LEAD_COLUMNS,
    RECORD_COLUMNS,
    SAP_BOOTSTRAP_SEED,
    SAP_N_RESAMPLES,
    agreement_with_reference,
    confirmed_reference,
    lead_level,
    load_predictions,
    paired_comparison,
    prediction_from_coded,
    read_prediction_dir,
    record_level,
    weighted_endpoints,
)
from artefaux.review_coding import DISPLAYED_LEADS, CodedResponse

CODES = ["T1-001", "T1-002", "T1-003", "T1-004"]


def coded(code, leads=(), overall=None, section="full", reader="R"):
    overall = overall or ("partial" if leads or section != "full" else "analysable")
    return CodedResponse(code, reader, tuple(leads), section, overall, ())


READER = {
    "T1-001": coded("T1-001"),
    "T1-002": coded("T1-002", ["V1", "V2"]),
    "T1-003": coded("T1-003", overall="not_analysable"),
    "T1-004": coded("T1-004", ["I"]),
}
# Two identical readers: every unit is confirmed.
REFERENCE = confirmed_reference(READER, READER)


def rows(source, decisions, errors=(), version="1.0.0"):
    """``decisions``: code -> (repeat, unusable leads)."""
    rec, lead = [], []
    for code in CODES:
        repeat, unusable = decisions[code]
        values = [
            "1",
            version,
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
        ]
        rec.append(dict(zip(RECORD_COLUMNS, values, strict=True)))
        for ld in DISPLAYED_LEADS:
            cells = [code, source, ld, str(ld in unusable), "", ""]
            lead.append(dict(zip(LEAD_COLUMNS, cells, strict=True)))
    return rec, lead


PERFECT = {
    "T1-001": (False, []),
    "T1-002": (False, ["V1", "V2"]),
    "T1-003": (True, []),
    "T1-004": (False, ["I"]),
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
    lead = lead_level(pred, REFERENCE, seed=1, n_resamples=200)
    # Reference positives: 2 + 8 + 1 = 11; predicted TP = 1 + 8 = 9.
    assert lead["counts"] == {"tp": 9, "fp": 1, "fn": 2, "tn": 20}
    assert lead["sensitivity"]["value"] == pytest.approx(9 / 11)
    assert lead["sensitivity"]["lo"] <= 9 / 11 <= lead["sensitivity"]["hi"]
    rec = record_level(pred, REFERENCE)
    assert rec["sensitivity"]["value"] == 1.0 and rec["specificity"]["value"] == 1.0


def test_only_confirmed_units_are_scored():
    # Readers disagree on V2 of T1-002 and on repeating T1-003: those units are left out.
    other = dict(READER)
    other["T1-002"] = coded("T1-002", ["V1"])
    other["T1-003"] = coded("T1-003", ["V1"])
    ref = confirmed_reference(READER, other)
    assert ref.disputed["T1-002"] == ("V2",)
    assert "repeat" in ref.disputed["T1-003"] and "T1-003" not in ref.repeat
    assert ("T1-002", "V2") not in ref.leads and ref.leads[("T1-002", "V1")]
    # T1-003: V1 is unusable for both (repeat makes every lead unusable); V2-V6, I, II open.
    assert ref.leads[("T1-003", "V1")] is True
    pred = load_predictions(*rows("toolA", PERFECT), CODES)
    lead = lead_level(pred, ref, seed=1, n_resamples=50)
    assert lead["n_units"] == 32 - 1 - 7
    assert record_level(pred, ref)["specificity"]["n"] == 3


def test_adjudication_settles_only_disputed_units():
    other = dict(READER)
    other["T1-002"] = coded("T1-002", ["V1"])
    settled = {"T1-002": coded("T1-002", ["V1", "V2"], reader="joint")}
    ref = confirmed_reference(READER, other, settled)
    assert ref.leads[("T1-002", "V2")] is True and "T1-002" not in ref.disputed
    clash = {"T1-002": coded("T1-002", ["V2"], reader="joint")}  # drops the agreed V1
    with pytest.raises(ValueError, match="may not override"):
        confirmed_reference(READER, other, clash)
    with pytest.raises(ValueError, match="unknown codes"):
        confirmed_reference(READER, READER, {"T1-999": coded("T1-999")})
    with pytest.raises(ValueError, match="different blind codes"):
        confirmed_reference(READER, {"T1-001": READER["T1-001"]})


def test_section_is_confirmed_only_when_both_keep_and_agree():
    a = {"T1-001": coded("T1-001", section="first_half", reader="PWM")}
    b = {"T1-001": coded("T1-001", section="second_half", reader="DTC")}
    ref = confirmed_reference(a, b)
    assert ref.disputed["T1-001"] == ("section",) and "T1-001" not in ref.section
    both_repeat = {"T1-001": coded("T1-001", overall="rhythm_only", section="none")}
    ref = confirmed_reference(both_repeat, {"T1-001": coded("T1-001", overall="not_analysable")})
    assert ref.repeat["T1-001"] is True and "T1-001" not in ref.section
    assert "T1-001" not in ref.grade  # grades differ and nothing settled them


def test_failures_count_against_the_tool_under_intention_to_diagnose():
    pred = load_predictions(*rows("toolA", PERFECT, errors={"T1-003"}), CODES)
    assert record_level(pred, REFERENCE)["sensitivity"]["value"] == 0.0
    assert lead_level(pred, REFERENCE, seed=1, n_resamples=50)["counts"]["fn"] == 8


def test_itd_false_excludes_failed_records():
    pred = load_predictions(*rows("toolA", PERFECT, errors={"T1-003"}), CODES)
    excluded = record_level(pred, REFERENCE, itd=False)
    assert excluded["sensitivity"]["n"] == 0
    assert math.isnan(excluded["sensitivity"]["value"])
    assert excluded["specificity"]["n"] == 3 and excluded["specificity"]["value"] == 1.0
    lead = lead_level(pred, REFERENCE, seed=1, n_resamples=50, itd=False)
    assert (lead["n_records"], lead["n_units"]) == (3, 24)
    assert lead["counts"] == {"tp": 3, "fp": 0, "fn": 0, "tn": 21}
    assert lead_level(pred, REFERENCE, seed=1, n_resamples=50)["n_records"] == 4


def test_schema_violations_are_rejected():
    rec, lead = rows("toolA", {c: (False, []) for c in CODES})
    with pytest.raises(ValueError, match="codes differ"):
        load_predictions(rec[:-1], lead, CODES)
    with pytest.raises(ValueError, match="duplicate"):
        load_predictions(rec, lead + lead[:1], CODES)
    with pytest.raises(ValueError, match="usable_section"):
        load_predictions([dict(r, usable_section="middle") for r in rec], lead, CODES)
    stale_rec, stale_lead = rows("toolA", {c: (False, []) for c in CODES}, version="0.9.0")
    with pytest.raises(ValueError, match="bench_version"):
        load_predictions(stale_rec, stale_lead, CODES)
    assert load_predictions(stale_rec, stale_lead, CODES, bench_version="0.9.0")


def test_paired_comparison_direction_and_failures():
    blind = {c: (False, []) for c in CODES}
    good = load_predictions(*rows("good", PERFECT), CODES)
    cmp = paired_comparison(
        good, load_predictions(*rows("blind", blind), CODES), REFERENCE, n_resamples=200
    )
    assert cmp["record_sensitivity"]["difference"] == 1.0
    assert cmp["lead_sensitivity"]["difference"] == pytest.approx(1.0)
    failing = load_predictions(*rows("broken", PERFECT, errors=set(CODES)), CODES)
    cmp = paired_comparison(failing, good, REFERENCE, n_resamples=50)
    assert cmp["record_sensitivity"]["difference"] == -1.0
    assert cmp["record_specificity"]["difference"] == -1.0
    assert cmp["record_specificity"]["n"] == 3
    assert cmp["lead_specificity"]["difference"] == -1.0


def test_paired_comparison_reports_lead_specificity_with_cluster_ci():
    over_call = {c: (False, list(DISPLAYED_LEADS)) for c in CODES}
    a = load_predictions(*rows("overcall", over_call), CODES)
    b = load_predictions(*rows("perfect", PERFECT), CODES)
    cmp = paired_comparison(a, b, REFERENCE, n_resamples=200)
    assert cmp["lead_sensitivity"]["difference"] == pytest.approx(0.0)
    assert cmp["lead_specificity"]["difference"] == pytest.approx(-1.0)
    assert cmp["lead_specificity"]["lo"] <= -1.0 <= cmp["lead_specificity"]["hi"]


def test_lead_set_agreement_uses_fully_confirmed_kept_records():
    pred = load_predictions(*rows("toolA", PERFECT), CODES)
    out = agreement_with_reference(pred, REFERENCE)
    assert out["n_lead_sets"] == 3 and out["lead_set_exact_match"] == 1.0


def test_bootstrap_defaults_are_the_preregistered_ones():
    assert (SAP_BOOTSTRAP_SEED, SAP_N_RESAMPLES) == (20261021, 2000)
    for fn in (lead_level, paired_comparison):
        params = inspect.signature(fn).parameters
        assert params["seed"].default == SAP_BOOTSTRAP_SEED
        assert params["n_resamples"].default == SAP_N_RESAMPLES


def _write_run(directory, decisions, labels=None):
    import csv

    rec, lead = rows("toolA", decisions)
    for row in lead:
        row["native_label"] = (labels or {}).get((row["blind_code"], row["lead"]), "good")
    for name, cols, data in (
        ("predictions_records.csv", RECORD_COLUMNS, rec),
        ("predictions_leads.csv", LEAD_COLUMNS, lead),
    ):
        with (directory / name).open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
            writer.writerows(data)


def test_read_prediction_dir_counts_extra_native_labels_as_unusable(tmp_path):
    _write_run(tmp_path, PERFECT, labels={("T1-001", "V3"): "borderline"})
    plain = read_prediction_dir(tmp_path, CODES, bench_version="1.0.0")
    assert plain["T1-001"].unusable_leads == ()
    strict = read_prediction_dir(
        tmp_path, CODES, bench_version="1.0.0", unusable_labels=("borderline",)
    )
    assert strict["T1-001"].unusable_leads == ("V3",)
    assert strict["T1-002"].unusable_leads == ("V1", "V2")


def test_prediction_from_coded_scores_a_reader_like_a_program():
    pred = {c: prediction_from_coded(r, "PWM") for c, r in READER.items()}
    assert pred["T1-003"].repeat_ecg and not pred["T1-003"].failed
    lead = lead_level(pred, REFERENCE, seed=1, n_resamples=50)
    assert lead["counts"]["fp"] == lead["counts"]["fn"] == 0


def test_restrict_keeps_only_the_named_records():
    other = dict(READER)
    other["T1-002"] = coded("T1-002", ["V1"])
    sub = confirmed_reference(READER, other).restrict(["T1-002", "T1-003"])
    assert sub.codes == ["T1-002", "T1-003"]
    assert set(sub.repeat) == {"T1-002", "T1-003"} and set(sub.disputed) == {"T1-002"}
    pred = load_predictions(*rows("toolA", PERFECT), CODES)
    assert lead_level(pred, sub, seed=1, n_resamples=50)["n_records"] == 2


def test_lead_level_without_reject_propagation_uses_the_lead_rows_only():
    """Sensitivity row: a rejected record keeps only the leads its own rows mark unusable."""
    decisions = {
        "T1-001": (True, []),  # tool repeats a record the readers keep: 8 false positives
        "T1-002": (False, ["V1", "V2"]),
        "T1-003": (True, ["I"]),  # tool repeats a repeated record: only I counts directly
        "T1-004": (False, ["I"]),
    }
    pred = load_predictions(*rows("tool", decisions), CODES)

    propagated = lead_level(pred, REFERENCE, n_resamples=20)["counts"]
    assert (propagated["tp"], propagated["fp"], propagated["fn"]) == (11, 8, 0)

    direct = lead_level(pred, REFERENCE, n_resamples=20, reject_propagates=False)["counts"]
    # The reference is unchanged: a reader's repeat still makes all 8 of T1-003 unusable.
    assert (direct["tp"], direct["fp"], direct["fn"]) == (4, 0, 7)


def test_unspecified_section_is_never_confirmed():
    a = {"T1-001": coded("T1-001", section="unspecified", reader="PWM")}
    ref = confirmed_reference(a, {"T1-001": coded("T1-001", section="unspecified")})
    assert ref.disputed["T1-001"] == ("section",) and "T1-001" not in ref.section
    settled = {"T1-001": coded("T1-001", section="first_half", reader="joint")}
    assert confirmed_reference(a, a, settled).section["T1-001"] == "first_half"


def test_weighted_endpoints_reweight_records_hand_computed():
    pred = load_predictions(
        *rows(
            "toolA",
            {
                "T1-001": (False, ["V6"]),  # 1 FP of 8 negatives
                "T1-002": (False, ["V1"]),  # 1 TP, 1 FN; 6 TN
                "T1-003": (True, []),  # 8 TP; repeat caught
                "T1-004": (False, []),  # 1 FN; 7 TN
            },
        ),
        CODES,
    )
    flat = weighted_endpoints(pred, REFERENCE, dict.fromkeys(CODES, 1.0))
    assert flat["lead_sensitivity"] == pytest.approx(9 / 11)
    assert flat["lead_specificity"] == pytest.approx(20 / 21)
    heavy = weighted_endpoints(pred, REFERENCE, {**dict.fromkeys(CODES, 1.0), "T1-001": 3.0})
    assert heavy["lead_specificity"] == pytest.approx((21 + 13) / (24 + 13))
    assert heavy["repeat_sensitivity"] == 1.0 and heavy["repeat_specificity"] == 1.0
    none_repeat = confirmed_reference({"T1-001": READER["T1-001"]}, {"T1-001": READER["T1-001"]})
    only = {"T1-001": pred["T1-001"]}
    assert weighted_endpoints(only, none_repeat, {"T1-001": 1.0})["repeat_sensitivity"] is None
