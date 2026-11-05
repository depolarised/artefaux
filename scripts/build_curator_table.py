#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Write the per-lead PTB-XL curator table (``docs/CALIB_V1.md``) for the clinical non-regression.

Excludes the patients of review sets 1 and 2 and the patients behind the calibration corpus, which
is read from ``records.csv`` in ``--out``: a gate fitted on those patients must not be checked on
them. Outputs ``ptbxl_curator_leads.csv`` and ``ptbxl_curator_summary.json`` (aggregates only).
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from artefaux.build import DEFAULT_PTBXL_DIR
from artefaux.calib import development_patients
from artefaux.provenance import sha256_file
from artefaux.ptbxl_curator import TABLE_COLUMNS, curator_rows, parse_lead_scope, summarise
from artefaux.selection import QUALITY_COLUMNS

REPO = Path(__file__).resolve().parents[1]
SET1_ID_FILES = (
    REPO / "recipes" / "source_ids" / "ptbxl_clean.csv",
    REPO / "recipes" / "source_ids" / "ptbxl_noisy.csv",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ptbxl-dir", type=Path, default=DEFAULT_PTBXL_DIR)
    parser.add_argument("--set2-sources", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    with (args.ptbxl_dir / "ptbxl_database.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    corpus_index = args.out / "records.csv"
    if not corpus_index.exists():
        raise FileNotFoundError(f"{corpus_index}: generate the corpus before this table")
    with corpus_index.open(newline="") as fh:
        parents = {r["patient_id"] for r in csv.DictReader(fh)}
    development = development_patients(rows, SET1_ID_FILES, args.set2_sources)
    table = curator_rows(rows, excluded_patients=development | parents)

    path = args.out / "ptbxl_curator_leads.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TABLE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(table)
    kept = [r for r in rows if r["patient_id"] not in development | parents]
    after_development = [r for r in rows if r["patient_id"] not in development]
    summary = {
        **summarise(table),
        "records_in_database": len(rows),
        "records_excluded_review_set_patients": len(rows) - len(after_development),
        "records_excluded_corpus_parent_patients": len(after_development) - len(kept),
        "flag_strings": {
            col: {
                "flagged_records": sum(parse_lead_scope(r[col]).state != "none" for r in kept),
                "unknown_records": sum(parse_lead_scope(r[col]).state == "unknown" for r in kept),
            }
            for col in QUALITY_COLUMNS
        },
        "table_sha256": sha256_file(path),
    }
    (args.out / "ptbxl_curator_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
