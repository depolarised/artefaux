# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Supplementary review cohort and independent reviewer spreadsheets.

This definition is separate from the released v2 corpus: generating a second
review set must not change the first set or its blinded codes.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from pathlib import Path

from .constants import CANONICAL_LEAD_ORDER
from .recipes import RecordSpec, SourceSpec

EXTREME_SNR_DB = (-18, -14, -10)
LOWER_NOISE_SNR_DB = (-2, 0, 6, 12, 18)
MASTER_SEED = 20261002
BLIND_SEED = 20261003

_EXTREME_LEADS = (
    ("V5",),
    ("V1", "V2"),
    ("V4", "V5", "V6"),
    ("I", "II"),
    ("II", "V1"),
    ("V2", "V4"),
    ("I", "V3", "V6"),
    ("V1", "V2", "V3"),
    ("V6",),
    ("I", "V1"),
    ("II", "V5", "V6"),
    ("V3", "V4"),
    ("V2", "V3", "V4", "V5"),
    ("I", "II", "V2"),
    ("V1", "V4", "V6"),
)

# Twelve scopes at each SNR: eight full-length and four half-length cases.
_MIXED_SCOPES = (
    (("V1",), (0, 10)),
    (("V5",), (0, 10)),
    (("V1", "V2", "V3"), (0, 10)),
    (("V4", "V5", "V6"), (0, 10)),
    (("I", "II"), (0, 10)),
    (("I", "II", "V1", "V2"), (0, 10)),
    (CANONICAL_LEAD_ORDER, (0, 10)),
    (CANONICAL_LEAD_ORDER, (0, 10)),
    (("V2", "V3"), (0, 5)),
    (("V4", "V5", "V6"), (5, 10)),
    (("I", "II"), (0, 5)),
    (("I", "II", "V1", "V2"), (5, 10)),
)


def _expected(leads: Sequence[str], snr: int, interval: tuple[int, int]) -> dict:
    """Author review hypotheses; these are not adjudicated clinical outcomes."""
    full = interval == (0, 10)
    discard = full and len(leads) == 12 and snr <= 0
    quality = "bad" if snr <= 0 else "borderline" if snr < 12 else "good"
    return {
        "record_quality": "reject" if discard else "diagnostic" if snr >= 12 else "limited",
        "lead_quality": {"default": "good", "overrides": dict.fromkeys(leads, quality)},
        "rejected_leads": list(leads) if full and quality == "bad" else [],
        "noiseguard_bad_leads": list(leads) if quality == "bad" else [],
        "noiseguard_discard": discard,
    }


def build_review_specs(sources: Sequence[SourceSpec]) -> list[RecordSpec]:
    """85 new parents: 15 selective extreme + 10 clean + 60 lower-noise strips.

    NSTDB corruption is explicitly in the acquisition-channel domain. A chosen
    lead is changed directly; no electrode/WCT propagation is applied.
    """
    if len(sources) != 85:
        raise ValueError(f"need exactly 85 distinct parents, got {len(sources)}")
    if len({s.record_id for s in sources}) != 85 or any(s.record_id is None for s in sources):
        raise ValueError("review parents must have 85 distinct resolved source IDs")
    specs = []
    noise_types = ("em", "ma", "bw")
    for i, leads in enumerate(_EXTREME_LEADS):
        interval = (0, 5) if i % 2 == 0 else (5, 10)
        snr = EXTREME_SNR_DB[i % 3]
        noise_type = noise_types[(i + i // 3) % 3]
        specs.append(
            RecordSpec(
                record_id=f"nlf_review2_ext_{i + 1:03d}",
                group="engineering",
                source=sources[i],
                seed_index=2000 + i,
                steps=(
                    {
                        "op": "nstdb_mix",
                        "noise_type": noise_type,
                        "noise_source": {"record": noise_type, "channel": i % 2},
                        "leads": list(leads),
                        "interval_s": list(interval),
                        "snr_db": snr,
                    },
                ),
                expected=_expected(leads, snr, interval),
                has_clean_parent=True,
            )
        )
    for i in range(10):
        specs.append(
            RecordSpec(
                record_id=f"nlf_review2_clean_{i + 1:03d}",
                group="real_noise",
                source=sources[len(specs)],
                seed_index=2000 + len(specs),
                expected={"record_quality": "diagnostic", "lead_quality": {"default": "good"}},
                has_clean_parent=True,
            )
        )
    for level, snr in enumerate(LOWER_NOISE_SNR_DB):
        for scope, (leads, interval) in enumerate(_MIXED_SCOPES):
            i = level * len(_MIXED_SCOPES) + scope
            noise_type = noise_types[(scope + level) % 3]
            specs.append(
                RecordSpec(
                    record_id=f"nlf_review2_mix_{i + 1:03d}",
                    group="real_noise",
                    source=sources[len(specs)],
                    seed_index=2000 + len(specs),
                    steps=(
                        {
                            "op": "nstdb_mix",
                            "noise_type": noise_type,
                            "noise_source": {"record": noise_type, "channel": i % 2},
                            "leads": list(leads),
                            "interval_s": list(interval),
                            "snr_db": snr,
                        },
                    ),
                    expected=_expected(leads, snr, interval),
                    has_clean_parent=True,
                )
            )
    return specs


def review_columns(reviewer: str) -> list[str]:
    if reviewer not in ("PWM", "DTC"):
        raise ValueError("reviewer must be PWM or DTC")
    return [
        "Blind ECG code",
        f"{reviewer} Leads unsuitable",
        f"{reviewer} 50% OK?",
        f"{reviewer} comments",
        f"{reviewer} decision",
        "Agreed handling",
    ]


def write_review_files(
    base: Path, reviewer: str, rows: Sequence[Sequence[str]], *, dataset: str
) -> tuple[Path, Path]:
    """Write matching CSV and genuine Excel 97-2003 BIFF8 XLS files.

    The single visible worksheet contains only blind codes and reviewer entries.
    All entries are literal text, including strings starting with '='.
    """
    return write_sheet_pair(
        base, review_columns(reviewer), rows, sheet_name=f"{dataset} {reviewer}", widths=_WIDTHS
    )


_WIDTHS = (18, 30, 26, 60, 42, 42)


def write_sheet_pair(
    base: Path,
    columns: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    sheet_name: str,
    widths: Sequence[int],
) -> tuple[Path, Path]:
    """Plain XLS plus CSV with one heading row; refuses to overwrite responses."""
    rows = [list(row) for row in rows]
    if any(len(row) != len(columns) for row in rows):
        raise ValueError(f"each review row must have exactly {len(columns)} columns")
    codes = [row[0] for row in rows]
    if len(set(codes)) != len(codes):
        raise ValueError("blind ECG codes must be unique")
    csv_path, xls_path = base.with_suffix(".csv"), base.with_suffix(".xls")
    if csv_path.exists() or xls_path.exists():
        raise FileExistsError(f"refusing to overwrite review responses: {base}")
    base.parent.mkdir(parents=True, exist_ok=True)
    _write_plain_xls(xls_path, [list(columns), *rows], sheet_name=sheet_name, widths=widths)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        writer.writerows(rows)
    return csv_path, xls_path


def _write_plain_xls(
    path: Path,
    rows: Sequence[Sequence[str]],
    *,
    sheet_name: str,
    widths: Sequence[int] = _WIDTHS,
) -> None:
    """Use Excel's default cell format: just headings and data, with no theme."""
    import xlrd
    import xlwt

    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet(sheet_name)
    for col, width in enumerate(widths):
        sheet.col(col).width = width * 256
    for rownum, values in enumerate(rows):
        for col, value in enumerate(values):
            sheet.write(rownum, col, value)
    content = io.BytesIO()
    book.save(content)
    data = content.getvalue()
    # Verify the complete file before replacing an existing workbook.
    with xlrd.open_workbook(file_contents=data) as checked:
        tab = checked.sheet_by_index(0)
        if tab.nrows != len(rows) or tab.ncols != len(rows[0]):
            raise RuntimeError("XLS dimensions do not match the review sheet")
        for rownum, values in enumerate(rows):
            if tab.row_values(rownum) != list(values):
                raise RuntimeError(f"XLS round-trip failed at row {rownum + 1}")
    path.write_bytes(data)


def simplify_review_workbook(path: Path) -> None:
    """Remove presentation styling without changing any existing cell value."""
    import xlrd

    with xlrd.open_workbook(path) as original:
        if original.nsheets != 1:
            raise ValueError("expected a single review worksheet")
        sheet = original.sheet_by_index(0)
        rows = [sheet.row_values(i) for i in range(sheet.nrows)]
        sheet_name = sheet.name
    widths = _WIDTHS if len(rows[0]) == len(_WIDTHS) else BENCH_WIDTHS
    _write_plain_xls(path, rows, sheet_name=sheet_name, widths=widths)


# --- Benchmark (T1) coded review form ------------------------------------------------

BENCH_WIDTHS = (14, 26, 18, 22, 24, 60, 30)
#: Allowed cell values, printed in the reviewer README. Lead lists use commas.
BENCH_ALLOWED = {
    "Unusable leads": "none | all | any of I, II, V1, V2, V3, V4, V5, V6 (comma-separated)",
    "Usable section": "full | first 5 s | second 5 s | neither",
    "Overall": "analysable | partially analysable | rhythm only | not analysable",
    "Not noise": "blank, or any of: lead reversal, missing or flat lead, amplifier limit, other",
}


def bench_review_columns(reviewer: str) -> list[str]:
    if reviewer not in ("PWM", "DTC"):
        raise ValueError("reviewer must be PWM or DTC")
    return [
        "Blind ECG code",
        *(f"{reviewer} {name}" for name in BENCH_ALLOWED),
        f"{reviewer} comments",
        "Agreed handling",
    ]


def write_bench_review_files(
    base: Path, reviewer: str, rows: Sequence[Sequence[str]], *, block: str
) -> tuple[Path, Path]:
    """The coded T1 form: plain XLS + CSV, one heading row, no validation styling."""
    return write_sheet_pair(
        base,
        bench_review_columns(reviewer),
        rows,
        sheet_name=f"{block} {reviewer}",
        widths=BENCH_WIDTHS,
    )
