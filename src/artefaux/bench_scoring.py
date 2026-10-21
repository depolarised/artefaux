# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Score program predictions on the blinded benchmark against the expert reference.

Implements the pre-registered analysis in ``docs/BENCHMARK_SAP.md``. Inputs are plain
CSV rows (no tool imports): each program writes the common prediction schema, the
readers' coded sheets give the reference, and adjudication rows settle disagreements.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from .benchmark import BENCH_VERSION
from .review_coding import DISPLAYED_LEADS, OVERALL, SECTIONS, CodedResponse
from .scoring import (
    BinaryCounts,
    cluster_bootstrap_ci,
    cohen_kappa,
    jaccard,
    mcnemar_exact,
    paired_difference_ci,
)

PREDICTION_SCHEMA_VERSION = 1
RECORD_COLUMNS = (
    "schema_version",
    "bench_version",
    "blind_code",
    "source",
    "source_version",
    "source_commit",
    "repeat_ecg",
    "graded_quality",
    "usable_section",
    "native_codes",
    "error",
    "runtime_ms",
)
LEAD_COLUMNS = ("blind_code", "source", "lead", "unusable", "native_label", "score")
SECTION_VALUES = (*SECTIONS, "not_emitted")
GRADED_VALUES = (*OVERALL, "not_emitted")
_BOOL = {"true": True, "false": False, "1": True, "0": False}


@dataclass(frozen=True)
class Prediction:
    blind_code: str
    source: str
    repeat_ecg: bool
    graded_quality: str
    usable_section: str
    unusable_leads: tuple[str, ...]
    failed: bool


def _bool(value: str, where: str) -> bool:
    try:
        return _BOOL[value.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"{where}: expected true/false, got {value!r}") from exc


def load_predictions(
    record_rows: Iterable[Mapping[str, str]],
    lead_rows: Iterable[Mapping[str, str]],
    codes: Sequence[str],
    *,
    bench_version: str = BENCH_VERSION,
) -> dict[str, Prediction]:
    """Validate one program's prediction files against the schema and the code list.

    Every code must appear exactly once in the record file and with all eight displayed
    leads in the lead file. A run that failed on a record carries a non-empty ``error``;
    its other fields are ignored and the record is scored as a failure (see the SAP).
    """
    record_rows, lead_rows = list(record_rows), list(lead_rows)
    if not record_rows:
        raise ValueError("no prediction rows")
    if tuple(record_rows[0]) != RECORD_COLUMNS:
        raise ValueError(f"record columns must be {RECORD_COLUMNS}")
    if lead_rows and tuple(lead_rows[0]) != LEAD_COLUMNS:
        raise ValueError(f"lead columns must be {LEAD_COLUMNS}")
    sources = {r["source"] for r in record_rows}
    if len(sources) != 1:
        raise ValueError(f"one source per prediction file, got {sorted(sources)}")
    by_code: dict[str, Mapping[str, str]] = {}
    for row in record_rows:
        if int(row["schema_version"]) != PREDICTION_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {row['schema_version']}")
        if row["bench_version"] != bench_version:
            raise ValueError(f"{row['blind_code']}: bench_version {row['bench_version']!r}")
        if row["blind_code"] in by_code:
            raise ValueError(f"duplicate prediction for {row['blind_code']}")
        by_code[row["blind_code"]] = row
    if set(by_code) != set(codes):
        missing, extra = set(codes) - set(by_code), set(by_code) - set(codes)
        raise ValueError(f"codes differ: missing {sorted(missing)[:5]}, extra {sorted(extra)[:5]}")
    leads: dict[str, dict[str, bool]] = {c: {} for c in codes}
    for row in lead_rows:
        code, lead = row["blind_code"], row["lead"]
        if code not in leads or lead not in DISPLAYED_LEADS or lead in leads[code]:
            raise ValueError(f"bad or duplicate lead row {code}/{lead}")
        leads[code][lead] = _bool(row["unusable"], f"{code}/{lead}")
    out = {}
    for code, row in by_code.items():
        failed = bool(row["error"].strip())
        if not failed:
            if set(leads[code]) != set(DISPLAYED_LEADS):
                raise ValueError(f"{code}: lead rows must cover {DISPLAYED_LEADS}")
            if row["graded_quality"] not in GRADED_VALUES:
                raise ValueError(f"{code}: graded_quality {row['graded_quality']!r}")
            if row["usable_section"] not in SECTION_VALUES:
                raise ValueError(f"{code}: usable_section {row['usable_section']!r}")
        out[code] = Prediction(
            blind_code=code,
            source=row["source"],
            repeat_ecg=False if failed else _bool(row["repeat_ecg"], f"{code}/repeat_ecg"),
            graded_quality="not_emitted" if failed else row["graded_quality"],
            usable_section="not_emitted" if failed else row["usable_section"],
            unusable_leads=tuple(ld for ld in DISPLAYED_LEADS if leads[code].get(ld, False)),
            failed=failed,
        )
    return out


def consensus_reference(
    first: Mapping[str, CodedResponse],
    second: Mapping[str, CodedResponse],
    adjudicated: Mapping[str, CodedResponse],
) -> dict[str, CodedResponse]:
    """Agreement where both readers agree on the primary items, adjudication elsewhere.

    Items that must agree: repeat-ECG and, when neither repeats, the unusable-lead set and
    the usable section. Every disagreement needs an adjudicated row, which then also
    supplies the grade. Where only the grade differs, the more severe grade is kept.
    """
    out = {}
    for code in first:
        a, b = first[code], second[code]
        agree = a.repeat_ecg == b.repeat_ecg and (
            a.repeat_ecg
            or (
                set(a.unusable_leads) == set(b.unusable_leads)
                and a.usable_section == b.usable_section
            )
        )
        if agree and code not in adjudicated:
            out[code] = a if a.overall == b.overall else _merge_agreed(a, b)
        elif code in adjudicated:
            out[code] = adjudicated[code]
        else:
            raise ValueError(f"{code}: readers disagree and no adjudicated row exists")
    return out


def _merge_agreed(a: CodedResponse, b: CodedResponse) -> CodedResponse:
    """Agreed items carry over; keep the more severe of two differing grades."""
    grade = max(a.overall, b.overall, key=OVERALL.index)
    return CodedResponse(
        blind_code=a.blind_code,
        reader="consensus",
        unusable_leads=a.unusable_leads,
        usable_section=a.usable_section,
        overall=grade,
        not_noise=tuple(sorted(set(a.not_noise) | set(b.not_noise))),
        source="agreement",
    )


def _lead_units(codes: Sequence[str], leads: Sequence[str]):
    return [(c, ld) for c in codes for ld in leads]


def _lead_pred(p: Prediction, lead: str, reference: bool) -> bool:
    """Intention-to-diagnose: a failed record is discordant with the reference."""
    if p.failed:
        return not reference
    return p.repeat_ecg or lead in p.unusable_leads


def _scored_codes(pred: Mapping[str, Prediction], codes: Sequence[str], itd: bool) -> list[str]:
    """All codes under intention-to-diagnose; otherwise failed records are excluded."""
    return list(codes) if itd else [c for c in codes if not pred[c].failed]


def lead_level(
    pred: Mapping[str, Prediction],
    ref: Mapping[str, CodedResponse],
    codes: Sequence[str],
    *,
    leads: Sequence[str] = DISPLAYED_LEADS,
    seed: int,
    itd: bool = True,
    n_resamples: int = 2000,
) -> dict:
    """P1: per-lead unusable detection with record-clustered bootstrap CIs."""
    codes = _scored_codes(pred, codes, itd)
    units = _lead_units(codes, leads)
    r = np.array([ref[c].lead_unusable(ld) for c, ld in units])
    p = np.array([_lead_pred(pred[c], ld, ref[c].lead_unusable(ld)) for c, ld in units])
    clusters = [c for c, _ in units]
    counts = BinaryCounts.from_pairs(p, r)
    out = {"counts": counts.__dict__, "n_units": len(units), "n_records": len(codes)}
    for name, fn in (
        ("sensitivity", lambda i: p[i][r[i]].mean() if r[i].any() else np.nan),
        ("specificity", lambda i: (~p[i][~r[i]]).mean() if (~r[i]).any() else np.nan),
    ):
        lo, hi = cluster_bootstrap_ci(fn, clusters, n_resamples=n_resamples, seed=seed)
        out[name] = {"value": counts.metrics()[name]["value"], "lo": lo, "hi": hi}
    for name in ("ppv", "npv", "f1"):
        out[name] = {"value": counts.metrics()[name]["value"]}
    return out


def record_level(
    pred: Mapping[str, Prediction],
    ref: Mapping[str, CodedResponse],
    codes: Sequence[str],
    *,
    itd: bool = True,
) -> dict:
    """P2: record-level repeat-ECG with Wilson CIs."""
    codes = _scored_codes(pred, codes, itd)
    r = [ref[c].repeat_ecg for c in codes]
    p = [(not ref[c].repeat_ecg) if pred[c].failed else pred[c].repeat_ecg for c in codes]
    m = BinaryCounts.from_pairs(p, r).metrics()
    return {k: m[k] for k in ("sensitivity", "specificity", "ppv", "npv", "f1")}


def paired_comparison(
    first: Mapping[str, Prediction],
    second: Mapping[str, Prediction],
    ref: Mapping[str, CodedResponse],
    codes: Sequence[str],
    *,
    seed: int,
    n_resamples: int = 2000,
) -> dict:
    """Paired differences (first − second): record-level McNemar/Newcombe, lead-level bootstrap."""
    out = {}
    for name, subset in (
        ("sensitivity", [c for c in codes if ref[c].repeat_ecg]),
        ("specificity", [c for c in codes if not ref[c].repeat_ecg]),
    ):
        want = name == "sensitivity"
        # Correct means a non-failed prediction matching the reference (a failure is wrong).
        a = [not first[c].failed and first[c].repeat_ecg == want for c in subset]
        b = [not second[c].failed and second[c].repeat_ecg == want for c in subset]
        if not subset:
            out[f"record_{name}"] = None
            continue
        diff, lo, hi = paired_difference_ci(a, b)
        n_b = sum(x and not y for x, y in zip(a, b, strict=True))
        n_c = sum(y and not x for x, y in zip(a, b, strict=True))
        out[f"record_{name}"] = {
            "difference": diff,
            "lo": lo,
            "hi": hi,
            "mcnemar_p": mcnemar_exact(n_b, n_c),
            "n": len(subset),
        }
    units = _lead_units(codes, DISPLAYED_LEADS)
    r = np.array([ref[c].lead_unusable(ld) for c, ld in units])
    # Per-unit correctness, so one formula serves sensitivity (r) and specificity (~r).
    ca = np.array([_lead_pred(first[c], ld, ref[c].lead_unusable(ld)) for c, ld in units]) == r
    cb = np.array([_lead_pred(second[c], ld, ref[c].lead_unusable(ld)) for c, ld in units]) == r
    clusters = [c for c, _ in units]
    for name, mask in (("lead_sensitivity", r), ("lead_specificity", ~r)):

        def diff(i, mask=mask):
            m = mask[i]
            return ca[i][m].mean() - cb[i][m].mean() if m.any() else np.nan

        lo, hi = cluster_bootstrap_ci(diff, clusters, n_resamples=n_resamples, seed=seed)
        value = float(ca[mask].mean() - cb[mask].mean()) if mask.any() else float("nan")
        out[name] = {"difference": value, "lo": lo, "hi": hi}
    return out


def agreement_with_reference(
    pred: Mapping[str, Prediction], ref: Mapping[str, CodedResponse], codes: Sequence[str]
) -> dict:
    """Secondary: graded agreement (weighted κ) and lead-set agreement where both keep."""
    graded = [c for c in codes if pred[c].graded_quality in OVERALL]
    kappa = (
        cohen_kappa(
            [pred[c].graded_quality for c in graded],
            [ref[c].overall for c in graded],
            OVERALL,
            weights="linear",
        )
        if graded
        else float("nan")
    )
    keep = [
        c for c in codes if not ref[c].repeat_ecg and not pred[c].repeat_ecg and not pred[c].failed
    ]
    sets = [(set(pred[c].unusable_leads), set(ref[c].unusable_leads)) for c in keep]
    return {
        "graded_weighted_kappa": kappa,
        "n_graded": len(graded),
        "lead_set_exact_match": float(np.mean([a == b for a, b in sets])) if sets else float("nan"),
        "lead_set_mean_jaccard": (
            float(np.mean([jaccard(a, b) for a, b in sets])) if sets else float("nan")
        ),
        "n_lead_sets": len(sets),
    }
