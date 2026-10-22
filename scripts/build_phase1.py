#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Phase 1 comparison set: review set 1 with the readers' confirmed answers as reference.

Local tooling: requires ecg-io, xlwt==1.3.0, xlrd==2.0.2, the v2 corpus in
``out/artefaux-v2`` and the set-1 synthesis in ``out/review-synthesis/set1`` (run
``scripts/reports/synthesise_review.py --set 1`` first). It writes:

``reports/review_packs/phase1/`` (handoffs, gitignored)
    ``tool_inputs/`` plus ``phase1_set1_tool_inputs.zip``: the 85 set-1 ECGs under their
    REV codes as WFDB and as GRIASCII with the adult Uni-G header, and ``inputs.csv``.
    ``artefaux85_set1_adjudication.{xls,csv}`` and a README: the disputed records only,
    for Peter and Derek to settle jointly.
``out/phase1/`` (private, gitignored)
    ``reference_units.csv`` (every unit, confirmed or disputed), ``summary.json``.
``bench/phase1/inputs.csv`` (public)
    codes and file hashes, so every program can prove it scored the same bytes.

Set-1 records with a digital-missing channel keep NaN in WFDB; ``ecg_io`` reads those
samples as zeros, so both programs receive the same dead (zero) channel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import wfdb

from artefaux.bench_scoring import confirmed_reference
from artefaux.benchmark import SCHEMA_VERSION, UNIG_HEADER_LINES
from artefaux.constants import CANONICAL_LEAD_ORDER, TARGET_FS
from artefaux.review import write_sheet_pair
from artefaux.review_coding import (
    ADJUDICATION_COLUMNS,
    DISPLAYED_LEADS,
    CodedResponse,
    code_adjudication,
    read_coding,
)
from artefaux.writer import write_wfdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_review_set import load_converter, read_csv, write_csv  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PHASE_VERSION = "phase1-set1-1.0"
ADJUDICATION_WIDTHS = (14, 22, 46, 46, 26, 20, 18, 40)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(c: CodedResponse) -> str:
    if c.repeat_ecg:
        return "repeat ECG"
    parts = [f"omit {', '.join(c.unusable_leads)}" if c.unusable_leads else "keep all leads"]
    if c.usable_section != "full":
        parts.append(f"use {c.usable_section.replace('_', ' ')}")
    return "; ".join(parts)


def _with_words(coded: str, words: str) -> str:
    return f"{coded}  [{words.strip()}]" if words.strip() else coded


def build_tool_inputs(args, key: list[dict]) -> None:
    converter = load_converter()
    tool_dir = args.share_dir / "tool_inputs"
    for folder in (tool_dir / "wfdb", tool_dir / "griasc"):
        folder.mkdir(parents=True, exist_ok=True)
    inputs = []
    for row in key:
        code = row["blind_code"]
        signal = wfdb.rdrecord(str(args.corpus / "records" / row["record_id"])).p_signal.T
        blind = write_wfdb(code, signal, TARGET_FS, tool_dir / "wfdb")
        saved = wfdb.rdrecord(str(blind))
        same = np.array_equal(saved.p_signal.T, signal, equal_nan=True)
        if not same or tuple(saved.sig_name) != CANONICAL_LEAD_ORDER:
            raise ValueError(f"{code}: blinded WFDB export changed the signal or lead order")
        asc = converter.convert_record(blind, tool_dir / "griasc", header_lines=UNIG_HEADER_LINES)
        asc_path = tool_dir / "griasc" / asc["asc_file"]
        header = asc_path.read_text(encoding="utf-8").split("\n", 23)[:23]
        if header[1] != code or any(header[k - 1] != v for k, v in UNIG_HEADER_LINES.items()):
            raise ValueError(f"{code}: GRIASCII header differs from the adult Uni-G request")
        hea, dat = blind.with_suffix(".hea"), blind.with_suffix(".dat")
        inputs.append(
            {
                "schema_version": SCHEMA_VERSION,
                "bench_version": PHASE_VERSION,
                "blind_code": code,
                "wfdb_hea": f"wfdb/{hea.name}",
                "wfdb_dat": f"wfdb/{dat.name}",
                "asc": f"griasc/{asc_path.name}",
                "sha256_hea": _sha(hea),
                "sha256_dat": _sha(dat),
                "sha256_asc": _sha(asc_path),
                "fs": TARGET_FS,
                "n_samples": signal.shape[1],
                "missing_channels": "|".join(
                    name
                    for name, lead in zip(CANONICAL_LEAD_ORDER, signal, strict=True)
                    if np.isnan(lead).all()
                ),
            }
        )
    write_csv(tool_dir / "inputs.csv", inputs)
    args.public_dir.mkdir(parents=True, exist_ok=True)
    (args.public_dir / "inputs.csv").write_bytes((tool_dir / "inputs.csv").read_bytes())
    target = args.share_dir / "phase1_set1_tool_inputs.zip"
    files = [tool_dir / "inputs.csv", *sorted((tool_dir / "wfdb").glob("*"))]
    files += sorted((tool_dir / "griasc").glob("*.asc"))
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.relative_to(tool_dir))
    with ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"archive verification failed: {target}")
    print(f"Prepared {target} ({len(inputs)} records)", flush=True)


def build_reference(args, readers, codes) -> dict:
    settled = {}
    if args.adjudication and args.adjudication.exists():
        problems = []
        for row in read_csv(args.adjudication):
            response, issues = code_adjudication(row)
            problems += issues
            if response is not None:
                settled[response.blind_code] = response
        if problems:
            raise ValueError("adjudication sheet needs correction:\n" + "\n".join(problems))
    ref = confirmed_reference(readers["PWM"], readers["DTC"], settled)
    units = []
    for code in codes:
        for item in (*DISPLAYED_LEADS, "repeat", "section"):
            if item in DISPLAYED_LEADS:
                value = ref.leads.get((code, item))
            else:
                value = (ref.repeat if item == "repeat" else ref.section).get(code)
            units.append(
                {
                    "blind_code": code,
                    "item": item,
                    "value": "" if value is None else value,
                    "status": (
                        "disputed"
                        if item in ref.disputed.get(code, ())
                        else (
                            "adjudicated"
                            if code in settled and value is not None
                            else "confirmed" if value is not None else "not_applicable"
                        )
                    ),
                }
            )
    args.private_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.private_dir / "reference_units.csv", units)
    lead_units = [u for u in units if u["item"] in DISPLAYED_LEADS]
    summary = {
        "phase": PHASE_VERSION,
        "n_records": len(codes),
        "coding_verified": args.coding_verified,
        "lead_units_confirmed": sum(u["value"] != "" for u in lead_units),
        "lead_units_confirmed_unusable": sum(u["value"] is True for u in lead_units),
        "lead_units_total": len(lead_units),
        "repeat_confirmed": len(ref.repeat),
        "repeat_confirmed_yes": sum(ref.repeat.values()),
        "records_with_disputes": len(ref.disputed),
        "records_adjudicated": len(settled),
    }
    (args.private_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return {"ref": ref, "summary": summary}


def build_adjudication_sheet(args, readers, ref, sheets) -> None:
    rows = []
    for code in sorted(ref.disputed):
        p, d = readers["PWM"][code], readers["DTC"][code]
        rows.append(
            [
                code,
                ", ".join(ref.disputed[code]),
                _with_words(describe(p), sheets["PWM"][code]),
                _with_words(describe(d), sheets["DTC"][code]),
                "",
                "",
                "",
                "",
            ]
        )
    base = args.share_dir / "artefaux85_set1_adjudication"
    if base.with_suffix(".xls").exists():
        print(f"Keeping existing {base}.xls (it may hold agreed answers)", flush=True)
    else:
        write_sheet_pair(
            base,
            ADJUDICATION_COLUMNS,
            rows,
            sheet_name="Set 1 adjudication",
            widths=ADJUDICATION_WIDTHS,
        )
    (args.share_dir / "README_adjudication.txt").write_text(
        "Artefaux review set 1 - joint adjudication (Peter and Derek together)\n\n"
        f"{len(rows)} of the 85 set-1 ECGs have a point where your two independent answers\n"
        "differ. Everything you already agree on is fixed and is not in this sheet.\n"
        "Each row shows the disputed items, each answer as coded from your sheets\n"
        "(your own words in brackets), and three columns for the agreed answer.\n"
        "Please give the complete agreed answer for that ECG:\n"
        "  Agreed unusable leads: none | all | any of I, II, V1, V2, V3, V4, V5, V6\n"
        "  Agreed usable section: full | first 5 s | second 5 s | neither\n"
        "  Agreed repeat ECG: yes | no\n"
        "Leave a row blank if you cannot agree; it stays out of the comparison.\n"
        "The ECGs are the pages of artefaux85_set1_blind_overflow.pdf (set1 folder);\n"
        "REV-001 is page 1.\n",
        encoding="utf-8",
    )
    print(f"Prepared {base}.xls with {len(rows)} disputed records", flush=True)


def reader_words(args, key) -> dict[str, dict[str, str]]:
    """Each reader's own decision wording, for the adjudication sheet."""
    sys.path.insert(0, str(REPO / "scripts/reports"))
    from synthesise_review import read_sheet  # noqa: E402

    words = {}
    for reader, path, column in (
        ("PWM", args.pwm, "PWM decision"),
        ("DTC", args.dtc, "DTC comments"),
    ):
        rows = {r["Blind ECG code"]: r for r in read_sheet(path)}
        words[reader] = {k["blind_code"]: rows[k["blind_code"]][column] for k in key}
    return words


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--key", type=Path, default=REPO / "reports/artefaux_v2_ecg_review_blind.key.csv"
    )
    parser.add_argument("--corpus", type=Path, default=REPO / "out/artefaux-v2")
    parser.add_argument(
        "--coding", type=Path, default=REPO / "out/review-synthesis/set1/coding.csv"
    )
    parser.add_argument(
        "--pwm", type=Path, default=REPO / "reports/review_packs/set1/artefaux85_PWM.xlsx"
    )
    parser.add_argument(
        "--dtc", type=Path, default=REPO / "reports/review_packs/set1/artefaux85_DTC .xls"
    )
    parser.add_argument("--adjudication", type=Path, help="returned adjudication CSV, if any")
    parser.add_argument("--share-dir", type=Path, default=REPO / "reports/review_packs/phase1")
    parser.add_argument("--private-dir", type=Path, default=REPO / "out/phase1")
    parser.add_argument("--public-dir", type=Path, default=REPO / "bench/phase1")
    parser.add_argument(
        "--coding-verified",
        action="store_true",
        help="the coordinator has checked coding.csv against the readers' sheets",
    )
    args = parser.parse_args()
    key = read_csv(args.key)
    codes = [r["blind_code"] for r in key]
    if len(codes) != 85 or len(set(codes)) != 85:
        raise ValueError("expected the 85 set-1 blind codes")
    readers = read_coding(args.coding)
    for reader in ("PWM", "DTC"):
        if set(readers.get(reader, {})) != set(codes):
            raise ValueError(f"{args.coding}: {reader} coding does not cover the 85 codes")
    args.share_dir.mkdir(parents=True, exist_ok=True)
    built = build_reference(args, readers, codes)
    build_adjudication_sheet(args, readers, built["ref"], reader_words(args, key))
    build_tool_inputs(args, key)
    print(json.dumps(built["summary"], indent=2), flush=True)
    if not args.coding_verified:
        print("NOTE: coding not yet verified; the reference is a draft until it is.", flush=True)


if __name__ == "__main__":
    main()
