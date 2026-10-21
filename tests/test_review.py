# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Protect half-strip recovery, lower-noise mixing, and independent review files."""

from __future__ import annotations

import csv

import numpy as np
import pytest

from artefaux.constants import CANONICAL_LEAD_ORDER, LEAD_INDEX
from artefaux.corpus import build_corpus_specs
from artefaux.recipes import SourceSpec, build_record
from artefaux.review import (
    LOWER_NOISE_SNR_DB,
    MASTER_SEED,
    build_review_specs,
    write_review_files,
)


def review_specs():
    return build_review_specs([SourceSpec("ptbxl", f"source_{i}") for i in range(85)])


def test_new_cohort_is_separate_and_has_clean_and_discard_controls():
    specs = review_specs()
    assert len(specs) == 85
    assert len({s.record_id for s in specs}) == 85
    assert not {s.record_id for s in specs} & {s.record_id for s in build_corpus_specs()}
    assert sum(not s.steps for s in specs) == 10
    assert sum(s.expected.get("noiseguard_discard", False) for s in specs) == 4
    mixed = specs[25:]
    assert {s.steps[0]["snr_db"] for s in mixed} == set(LOWER_NOISE_SNR_DB)
    assert sum(len(s.steps[0]["leads"]) == 12 for s in mixed) == 10
    assert sum(s.steps[0]["interval_s"] != [0, 10] for s in mixed) == 20


def test_extreme_changes_only_selected_leads_and_one_half(ecg12):
    halves = []
    for spec in review_specs()[:15]:
        signal, label = build_record(ecg12, spec, MASTER_SEED, 500)
        step = label.corruption_truth.steps[0]
        start, stop = (int(t * 500) for t in step.interval_s)
        halves.append(step.interval_s)
        assert 0 < len(step.leads_affected) < 12
        assert stop - start == 2500
        assert np.array_equal(signal[:, :start], ecg12[:, :start])
        assert np.array_equal(signal[:, stop:], ecg12[:, stop:])
        for lead in CANONICAL_LEAD_ORDER:
            index = LEAD_INDEX[lead]
            if lead in step.leads_affected:
                assert not np.array_equal(signal[index, start:stop], ecg12[index, start:stop])
            else:
                assert np.array_equal(signal[index], ecg12[index])
        assert not label.expected_behaviour.noiseguard_discard_record
    assert halves.count((0.0, 5.0)) == 8
    assert halves.count((5.0, 10.0)) == 7


def test_mixed_noise_power_falls_as_snr_increases(ecg12):
    # Same parent and real-noise-like trace; the requested dB change must actually
    # lower noise power, rather than merely relabel the records.
    def provider(step, n, rng):
        return np.sin(np.arange(n) * 0.2)

    specs = review_specs()[25:]
    noise_powers = []
    for spec in specs[::12]:
        signal, _ = build_record(ecg12, spec, MASTER_SEED, 500, noise_provider=provider)
        noise_powers.append(float(np.mean((signal[LEAD_INDEX["V1"]] - ecg12[6]) ** 2)))
    assert all(a > b for a, b in zip(noise_powers, noise_powers[1:], strict=False))
    assert np.isclose(noise_powers[0] / noise_powers[-1], 100)
    for spec in review_specs()[15:25]:
        signal, _ = build_record(ecg12, spec, MASTER_SEED, 500)
        assert np.array_equal(signal, ecg12)


def test_duplicate_parent_sources_are_rejected():
    with pytest.raises(ValueError, match="distinct"):
        build_review_specs([SourceSpec("ptbxl", "same") for _ in range(85)])


def test_xls_quotes_text_and_review_responses_roundtrip(tmp_path):
    xlrd = pytest.importorskip("xlrd")
    pytest.importorskip("xlwt")
    rows = [["REV-001", 'Some baseline "wobble"', "", "=literal text", "Leave as is", ""]]
    csv_path, xls_path = write_review_files(
        tmp_path / "artefaux85PWM", "PWM", rows, dataset="Set 1"
    )
    assert xls_path.read_bytes()[:8] == bytes.fromhex("d0cf11e0a1b11ae1")
    with xlrd.open_workbook(xls_path) as book:
        assert book.nsheets == 1
        sheet = book.sheet_by_index(0)
        assert sheet.row_values(1) == rows[0]
        assert sheet.cell_type(1, 3) == xlrd.XL_CELL_TEXT
        assert sheet.cell_value(0, 1) == "PWM Leads unsuitable"
    with csv_path.open(newline="") as handle:
        csv_rows = list(csv.reader(handle))
    assert csv_rows[1] == rows[0]
    before = xls_path.read_bytes()
    with pytest.raises(FileExistsError, match="overwrite"):
        write_review_files(tmp_path / "artefaux85PWM", "PWM", rows, dataset="Set 1")
    assert xls_path.read_bytes() == before


def test_bench_form_has_coded_columns_and_stays_plain(tmp_path):
    xlrd = pytest.importorskip("xlrd")
    pytest.importorskip("xlwt")
    from artefaux.review import bench_review_columns, write_bench_review_files

    columns = bench_review_columns("DTC")
    assert columns == [
        "Blind ECG code",
        "DTC Unusable leads",
        "DTC Usable section",
        "DTC Overall",
        "DTC Not noise",
        "DTC comments",
        "Agreed handling",
    ]
    rows = [["T1-001", "", "", "", "", "", ""], ["T1-002", "", "", "", "", "", ""]]
    _, xls_path = write_bench_review_files(tmp_path / "bench_DTC", "DTC", rows, block="T1")
    with xlrd.open_workbook(xls_path, formatting_info=True) as book:
        sheet = book.sheet_by_index(0)
        assert (sheet.nrows, sheet.ncols) == (3, 7)
        assert sheet.row_values(0) == columns
        # One default cell format for every cell: no fills, borders or bold headings.
        assert len({sheet.cell_xf_index(r, c) for r in range(3) for c in range(7)}) == 1
