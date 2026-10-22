# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Free-text reviewer responses are coded into the benchmark's structured fields."""

from __future__ import annotations

import pytest

from artefaux.review_coding import (
    DISPLAYED_LEADS,
    apply_overrides,
    code_dtc,
    code_pwm,
    parse_leads,
    parse_section,
)


@pytest.mark.parametrize(
    ("text", "leads"),
    [
        ("take out V4, V5 & V6", ("V4", "V5", "V6")),
        ("Omit V1 - V3.", ("V1", "V2", "V3")),
        ("omit lead v5 only", ("V5",)),
        ("take out 1 & 2", ("I", "II")),
        ('noise in 1 & " leads', ("I", "II")),
        ("Remove I and II", ("I", "II")),
        ("omlt lead 1", ("I",)),
        ("Omit all limb leads", ("I", "II")),
        ("no action", ()),
        ("I am inclined to keep everything", ()),
        ("use first 5 secs", ()),
    ],
)
def test_parse_leads(text, leads):
    assert parse_leads(text) == leads


@pytest.mark.parametrize(
    ("text", "section"),
    [
        ("Analyse second 5 secs", "second_half"),
        ("Use 5-10 seconds here.", "second_half"),
        ("Use seond half", "second_half"),
        ("Exclude last 5 seconds", "first_half"),
        ("Use  0-5 secs.", "first_half"),
        ("use only first half of recording", "first_half"),
        ("Analyse last 5 seconds", "second_half"),
        ("Leave as is", "full"),
    ],
)
def test_parse_section(text, section):
    assert parse_section(text) == section


def _dtc(comment, decision, unsuitable=""):
    return {
        "Blind ECG code": "REV-900",
        "DTC Leads unsuitable": unsuitable,
        "DTC 50% OK?": "yes",
        "DTC comments": comment,
        "DTC decision": decision,
    }


def _pwm(decision, unsuitable="", half="No", comment=""):
    return {
        "Blind ECG code": "REV-900",
        "PWM Leads unsuitable": unsuitable,
        "PWM 50% OK?": half,
        "PWM comments": comment,
        "PWM decision": decision,
    }


def test_dtc_graded_vocabulary_and_repeat():
    rhythm = code_dtc(_dtc("repeat the ECG", "not analysable (apart from rhythm)"))
    assert rhythm.overall == "rhythm_only" and rhythm.repeat_ecg
    assert all(rhythm.lead_unusable(ld) for ld in ("I", "V6"))
    omit = code_dtc(_dtc("take out V2", "analysable", "V2 absent"))
    assert omit.overall == "partial" and omit.unusable_leads == ("V2",)
    assert omit.not_noise == ("missing_or_flat",)
    assert not omit.lead_unusable("V3")
    assert code_dtc(_dtc("no action", "analysable")).overall == "analysable"


def test_pwm_reject_keep_and_omit():
    assert code_pwm(_pwm("Reject all leads")).overall == "not_analysable"
    keep = code_pwm(_pwm("Process all leads", unsuitable="V2, V3 missing"))
    assert keep.overall == "analysable" and keep.unusable_leads == ()
    omit = code_pwm(_pwm("Omit V1-V3.  Omit last 5 secs if possible."))
    assert omit.unusable_leads == ("V1", "V2", "V3")
    assert omit.usable_section == "first_half"
    reversal = code_pwm(_pwm("Omit all limb leads", unsuitable="arm lead reversal"))
    assert reversal.not_noise == ("lead_reversal",)


def test_overrides_are_validated_and_marked():
    coded = [code_pwm(_pwm("Omit IV1-V6"))]
    fixed = apply_overrides(
        coded,
        [
            {
                "reader": "PWM",
                "blind_code": "REV-900",
                "field": "unusable_leads",
                "value": "V6;V1;V2;V3;V4;V5",
                "note": "typo",
            }
        ],
    )
    assert fixed[0].unusable_leads == ("V1", "V2", "V3", "V4", "V5", "V6")
    assert fixed[0].source == "override"
    bad = {"reader": "PWM", "blind_code": "REV-900", "field": "usable_section", "value": "middle"}
    with pytest.raises(ValueError, match="usable_section"):
        apply_overrides(coded, [bad])
    with pytest.raises(KeyError):
        apply_overrides(coded, [{**bad, "blind_code": "REV-901"}])


def _bench(leads, section, overall, not_noise=""):
    return {
        "Blind ECG code": "T1-001",
        "DTC Unusable leads": leads,
        "DTC Usable section": section,
        "DTC Overall": overall,
        "DTC Not noise": not_noise,
    }


def test_coded_form_is_parsed_strictly():
    from artefaux.review_coding import code_bench

    ok, problems = code_bench(_bench("V2, v3", "Second 5 s", "Partially analysable"), "DTC")
    assert problems == [] and ok.unusable_leads == ("V2", "V3")
    assert ok.usable_section == "second_half" and ok.overall == "partial"
    every, _ = code_bench(_bench("all", "neither", "not analysable", "lead reversal"), "DTC")
    assert every.repeat_ecg and every.usable_section == "none"
    assert every.not_noise == ("lead_reversal",)
    bad, problems = code_bench(_bench("V7", "middle", "fine"), "DTC")
    assert bad is None and len(problems) == 3
    blank, problems = code_bench(_bench("", "full", "analysable"), "DTC")
    assert blank is None and "blank" in problems[0]


@pytest.mark.parametrize(
    ("leads", "section", "overall"),
    [
        ("all", "full", "analysable"),
        ("all", "full", "partially analysable"),
        ("all", "first 5 s", "partially analysable"),
        ("V2", "full", "analysable"),
        ("I, II", "neither", "analysable"),
        ("V5", "neither", "partially analysable"),
    ],
)
def test_contradictory_bench_rows_are_reported(leads, section, overall):
    from artefaux.review_coding import code_bench

    response, problems = code_bench(_bench(leads, section, overall), "DTC")
    assert response is None
    assert problems and all(p.startswith("T1-001:") for p in problems)


def test_repeat_grade_with_named_leads_is_not_flagged():
    from artefaux.review_coding import code_bench

    worst, problems = code_bench(_bench("V1, V2", "full", "rhythm only"), "DTC")
    assert problems == [] and worst.repeat_ecg
    named, problems = code_bench(_bench("V1, V2", "neither", "not analysable"), "DTC")
    assert problems == [] and named.usable_section == "none"
    consistent, problems = code_bench(_bench("none", "neither", "rhythm only"), "DTC")
    assert problems == [] and consistent.overall == "rhythm_only"


def test_coding_table_round_trips(tmp_path):
    import csv

    from artefaux.review_coding import read_coding

    rows = [
        code_dtc(_dtc("take out V2", "analysable", "V2 absent")),
        code_pwm(_pwm("Reject all leads")),
    ]
    path = tmp_path / "coding.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].as_row()))
        writer.writeheader()
        writer.writerows(r.as_row() for r in rows)
    loaded = read_coding(path)
    assert loaded["DTC"]["REV-900"] == rows[0]
    assert loaded["PWM"]["REV-900"].repeat_ecg


def _adj(leads, section, repeat):
    return {
        "Blind ECG code": "REV-010",
        "Agreed unusable leads": leads,
        "Agreed usable section": section,
        "Agreed repeat ECG": repeat,
    }


def test_adjudication_rows_are_parsed_completely_or_left_open():
    from artefaux.review_coding import code_adjudication

    assert code_adjudication(_adj("", "", "")) == (None, [])
    kept, problems = code_adjudication(_adj("V2, V3", "full", "no"))
    assert problems == [] and kept.unusable_leads == ("V2", "V3") and not kept.repeat_ecg
    assert kept.reader == "joint"
    clean, _ = code_adjudication(_adj("none", "full", "No"))
    assert clean.overall == "analysable"
    repeat, problems = code_adjudication(_adj("", "", "yes"))
    assert problems == [] and repeat.repeat_ecg and repeat.unusable_leads == DISPLAYED_LEADS
    bad, problems = code_adjudication(_adj("V9", "full", "maybe"))
    assert bad is None and problems
