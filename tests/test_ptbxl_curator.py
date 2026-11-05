# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""PTB-XL curator lead strings: the parser, and the per-lead table built from them."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

from artefaux.constants import CANONICAL_LEAD_ORDER
from artefaux.ptbxl_curator import (
    CLASSES,
    TABLE_COLUMNS,
    curator_rows,
    parse_lead_scope,
    record_classes,
)
from artefaux.selection import QUALITY_COLUMNS

TABLE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_curator_table.py"
LIMB_TO_AVF = ("I", "II", "III", "aVR", "aVL", "aVF")


@pytest.mark.parametrize(
    ("raw", "leads"),
    [
        ("I-AVF", LIMB_TO_AVF),
        (" , I-AVF,  ", LIMB_TO_AVF),
        ("I - AVF", LIMB_TO_AVF),
        ("I -AVF", LIMB_TO_AVF),
        ("alles", CANONICAL_LEAD_ORDER),
        ("alle,  ,", CANONICAL_LEAD_ORDER),
        (", alles, noisy recording,", CANONICAL_LEAD_ORDER),
        ("V1", ("V1",)),
        ("v6,", ("V6",)),
        ("I,II", ("I", "II")),
        ("I,III,AVL", ("I", "III", "aVL")),
        ("I,III-AVR", ("I", "III", "aVR")),
        ("I-V1", (*LIMB_TO_AVF, "V1")),
        ("AVL-V2", ("aVL", "aVF", "V1", "V2")),
        ("v1-6", ("V1", "V2", "V3", "V4", "V5", "V6")),
        ("v4-v6", ("V4", "V5", "V6")),
        ("V5,6", ("V5", "V6")),
        ("v2, v6", ("V2", "V6")),
        ("V4,5,6", ("V4", "V5", "V6")),
        ("V3,V4-V6", ("V3", "V4", "V5", "V6")),
        ("I,II,AVL,V5;V6", ("I", "II", "aVL", "V5", "V6")),
        ("I,II,III.AVR,AVL,  ,", ("I", "II", "III", "aVR", "aVL")),
        ("I-Avr", ("I", "II", "III", "aVR")),
        ("avl-iii", ("III", "aVR", "aVL")),  # written backwards: the same span of leads
        ("v2 mittel", ("V2",)),
        ("I stark,  ,", ("I",)),
        ("mittel I", ("I",)),
    ],
)
def test_readable_strings_name_exactly_their_leads(raw, leads):
    scope = parse_lead_scope(raw)
    assert scope.state == "leads"
    assert set(scope.leads) == set(leads)


@pytest.mark.parametrize(
    "raw",
    [
        "V1???",
        "I???",
        "aVL???",
        "v6????",
        "Kontaktprobleme aVL ???",
        "Elektroden vertauscht???",
        "I-ALF",  # likely a typo for AVF; never guessed
        "I-V!",
        "V&",
        "V7",
        "V1V6",
        "3ES",
        "2",
        "pace",
        "ja",
        "stufen",
        "I-AVF,3ES",  # one unreadable token voids the whole string
        # A severity or remark without leads says the record is flagged, not where.
        "leicht",
        ", mittel,",
        "stark!",
        ", noisy recording,",
        ", drift",
        ", noise,",
    ],
)
def test_unreadable_or_unscoped_strings_are_unknown_never_clean(raw):
    scope = parse_lead_scope(raw)
    assert scope.state == "unknown"
    assert scope.leads == ()


@pytest.mark.parametrize("raw", ["", "   ", " ,  ,  ", "nan", None])
def test_blank_strings_mean_no_flag(raw):
    scope = parse_lead_scope(raw)
    assert scope.state == "none"
    assert scope.leads == ()


def _row(ecg_id=1, patient_id="10.0", **flags):
    base = {
        "ecg_id": str(ecg_id),
        "filename_hr": f"records500/00000/{ecg_id:05d}_hr",
        "patient_id": patient_id,
        "strat_fold": "3",
        "validated_by_human": "True",
        "scp_codes": "{'NORM': 100.0, 'SR': 0.0}",
        "static_noise": "",
        "burst_noise": "",
        "baseline_drift": "",
        "electrodes_problems": "",
    }
    base.update(flags)
    return base


def _by_lead(rows):
    return {r["lead"]: r for r in rows}


def test_table_has_one_row_per_lead_and_a_clean_record_is_clean_everywhere():
    rows = curator_rows([_row()], excluded_patients=set())
    assert [r["lead"] for r in rows] == list(CANONICAL_LEAD_ORDER)
    assert all(tuple(r) == TABLE_COLUMNS for r in rows)
    assert {r["lead_state"] for r in rows} == {"clean"}
    assert {r["record_clean"] for r in rows} == {"true"}


def test_flagged_leads_are_noisy_and_the_rest_clean():
    rows = _by_lead(curator_rows([_row(static_noise=" , I-AVR,  ")], excluded_patients=set()))
    assert rows["I"]["lead_state"] == "noisy"
    assert rows["aVR"]["static_noise"] == "flagged"
    assert rows["aVL"]["lead_state"] == "clean"
    assert rows["V1"]["static_noise"] == "clean"
    assert rows["V1"]["record_clean"] == "false"


def test_unparseable_string_makes_every_lead_unknown_and_the_record_not_clean():
    rows = _by_lead(curator_rows([_row(electrodes_problems="V1???")], excluded_patients=set()))
    assert {r["lead_state"] for r in rows.values()} == {"unknown"}
    assert {r["electrodes_problems"] for r in rows.values()} == {"unknown"}
    assert {r["record_clean"] for r in rows.values()} == {"false"}


def test_a_flag_in_another_column_outranks_unknown():
    row = _row(electrodes_problems="V1???", burst_noise="V2")
    rows = _by_lead(curator_rows([row], excluded_patients=set()))
    assert rows["V2"]["lead_state"] == "noisy"
    assert rows["V1"]["lead_state"] == "unknown"


def test_excluded_patients_are_dropped():
    rows = [_row(1, "10.0"), _row(2, "11.0")]
    out = curator_rows(rows, excluded_patients={"10.0"})
    assert {r["ecg_id"] for r in out} == {"2"}


def test_classes_are_presence_of_the_scp_code_including_likelihood_zero():
    row = _row(scp_codes="{'AFIB': 0.0, 'PVC': 100.0, 'LVOLT': 0.0, 'SR': 0.0}")
    assert record_classes(row) == ("AFIB", "PVC", "LVOLT")
    assert CLASSES == ("NORM", "AFIB", "AFLT", "PVC", "BIGU", "TRIGU", "PACE", "LVOLT")
    rows = curator_rows([row], excluded_patients=set())
    assert rows[0]["scp_classes"] == "AFIB;PVC;LVOLT"


@pytest.mark.parametrize("column", QUALITY_COLUMNS)
def test_missing_quality_column_raises_and_never_reads_as_clean(column):
    row = _row()
    del row[column]
    with pytest.raises(ValueError, match=column):
        curator_rows([row], excluded_patients=set())


def test_truncated_row_raises_and_never_reads_as_clean():
    # csv.DictReader fills the fields of a short line with None.
    with pytest.raises(ValueError, match="electrodes_problems"):
        curator_rows([_row(electrodes_problems=None)], excluded_patients=set())


def _load_table_script():
    spec = importlib.util.spec_from_file_location("build_curator_table_under_test", TABLE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_rows(path, rows):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def table_inputs(tmp_path, monkeypatch):
    script = _load_table_script()
    monkeypatch.setattr(script, "development_patients", lambda *a, **k: {"10.0"})
    ptbxl, out = tmp_path / "ptbxl", tmp_path / "out"
    ptbxl.mkdir()
    out.mkdir()
    rows = [_row(1, "10.0"), _row(2, "11.0"), _row(3, "11.0"), _row(4, "12.0")]
    _write_rows(ptbxl / "ptbxl_database.csv", rows)
    argv = ["--ptbxl-dir", str(ptbxl), "--set2-sources", "unused", "--out", str(out)]
    return script, argv, out


def test_corpus_parents_leave_the_table_with_all_their_records(table_inputs):
    # A gate fitted on these patients must not be checked on them (ADR-0018 amendment 2).
    script, argv, out = table_inputs
    _write_rows(out / "records.csv", [{"record_id": "calib1_0001", "patient_id": "11.0"}])
    assert script.main(argv) == 0
    with (out / "ptbxl_curator_leads.csv").open(newline="") as fh:
        assert {r["patient_id"] for r in csv.DictReader(fh)} == {"12.0"}
    summary = json.loads((out / "ptbxl_curator_summary.json").read_text())
    assert summary["records_excluded_review_set_patients"] == 1
    assert summary["records_excluded_corpus_parent_patients"] == 2
    assert summary["records"]["total"] == 1


def test_table_refuses_to_run_without_the_corpus_index(table_inputs):
    script, argv, _ = table_inputs
    with pytest.raises(FileNotFoundError, match="records.csv"):
        script.main(argv)
