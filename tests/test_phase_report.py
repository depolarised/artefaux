# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The phase report's pre-registered sensitivity rows, on fabricated runs."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path

from artefaux.bench_scoring import LEAD_COLUMNS, RECORD_COLUMNS
from artefaux.review_coding import DISPLAYED_LEADS

REPO = Path(__file__).resolve().parents[1]
PHASE = "phase-test"
CODES = ("REV-001", "REV-002", "REV-003")


def _load_report():
    spec = importlib.util.spec_from_file_location(
        "artefaux_phase_report", REPO / "scripts" / "reports" / "phase_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, columns, rows) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _run_dir(root: Path, source: str, repeats: dict[str, bool]) -> None:
    run = root / source
    run.mkdir(parents=True)
    records, leads = [], []
    for code in CODES:
        cells = ["1", PHASE, code, source, "0.1", "abc", str(repeats[code]).lower()]
        cells += ["partial", "full", "", "", "5"]
        records.append(dict(zip(RECORD_COLUMNS, cells, strict=True)))
        for lead in DISPLAYED_LEADS:
            label = "good"
            row = [code, source, lead, "false", label, "0.9"]
            leads.append(dict(zip(LEAD_COLUMNS, row, strict=True)))
    _write(run / "predictions_records.csv", RECORD_COLUMNS, records)
    _write(run / "predictions_leads.csv", LEAD_COLUMNS, leads)
    manifest = {"version": "0.1", "commit": "abcdef0", "inputs_sha256": "0" * 64}
    (run / "run_manifest.json").write_text(json.dumps(manifest))


def _args(tmp_path: Path) -> argparse.Namespace:
    coding = tmp_path / "coding.csv"
    columns = ("blind_code", "reader", "unusable_leads", "usable_section", "overall")
    columns += ("repeat_ecg", "not_noise", "source")
    rows = []
    for reader in ("PWM", "DTC"):
        rows.append(dict(zip(columns, ("REV-001", reader, "", "full", "analysable"), strict=False)))
        rows.append(dict(zip(columns, ("REV-002", reader, "", "full", "analysable"), strict=False)))
        rows.append(
            dict(zip(columns, ("REV-003", reader, "", "none", "not_analysable"), strict=False))
        )
    for row in rows:
        row.update(repeat_ecg=str(row["overall"] == "not_analysable"), not_noise="", source="auto")
    _write(coding, columns, rows)
    key = tmp_path / "key.csv"
    _write(key, ("blind_code", "group"), [{"blind_code": c, "group": "real_noise"} for c in CODES])
    predictions = tmp_path / "predictions"
    # signalguard rejects a kept record, and rejects the record the readers repeat.
    _run_dir(predictions, "signalguard", {"REV-001": True, "REV-002": False, "REV-003": True})
    _run_dir(predictions, "unig", {"REV-001": False, "REV-002": False, "REV-003": False})
    return argparse.Namespace(
        phase=PHASE,
        coding=coding,
        key=key,
        predictions=predictions,
        sources=["signalguard", "unig"],
        coding_verified=False,
    )


def test_reject_not_propagated_row_changes_only_the_program_side(tmp_path):
    report = _load_report()
    results = report.build(_args(tmp_path))

    primary = results["primary"]["signalguard"]["P1_all"]["counts"]
    assert (primary["tp"], primary["fp"], primary["fn"]) == (8, 8, 0)

    row = results["sensitivity"]["reject_not_propagated"]["signalguard"]
    counts = row["P1_all"]["counts"]
    # The lead rows mark nothing; the readers' repeat still makes REV-003 8 unusable units.
    assert (counts["tp"], counts["fp"], counts["fn"]) == (0, 0, 8)
    assert row["P2"] == results["primary"]["signalguard"]["P2"]


def test_primary_endpoint_is_unchanged_and_rows_are_in_the_table(tmp_path):
    report = _load_report()
    results = report.build(_args(tmp_path))
    text = report.markdown(results)
    assert "signalguard, reject not propagated" in text
    assert "Uni-G, reject not propagated" in text
    assert "signalguard, borderline = unusable" in text
    primary = results["primary"]["signalguard"]["P1_all"]["counts"]
    # P1 keeps the pre-registered rule: a rejected record counts all 8 leads unusable.
    assert primary["fp"] == 8
