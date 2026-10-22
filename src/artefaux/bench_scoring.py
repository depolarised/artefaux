# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Score program predictions on the blinded benchmark against the expert reference.

Implements the pre-registered analysis in ``docs/BENCHMARK_SAP.md``. Inputs are plain
CSV rows (no tool imports): each program writes the common prediction schema, and the
reference is built from the two readers' confirmed (agreed or adjudicated) units.
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
#: Pre-registered bootstrap settings (docs/BENCHMARK_SAP.md); the defaults below use them.
SAP_BOOTSTRAP_SEED = 20261021
SAP_N_RESAMPLES = 2000
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


@dataclass(frozen=True)
class Reference:
    """The expert reference as confirmed units only.

    A unit is confirmed when both readers agree on it, or when a disputed unit has been
    settled by joint adjudication. Units still in dispute are absent from the scoring maps
    and listed in ``disputed``, so every metric runs over exactly the confirmed units.

    ``leads[(code, lead)]``: lead unusable (a repeat-ECG makes every displayed lead unusable).
    ``repeat[code]``: repeat the ECG. ``section[code]``: usable section, only for records
    neither reader would repeat. ``grade[code]``: overall grade where both grades agree.
    """

    leads: Mapping[tuple[str, str], bool]
    repeat: Mapping[str, bool]
    section: Mapping[str, str]
    grade: Mapping[str, str]
    disputed: Mapping[str, tuple[str, ...]]

    @property
    def codes(self) -> list[str]:
        return sorted({c for c, _ in self.leads} | set(self.repeat) | set(self.disputed))

    def lead_set(self, code: str) -> tuple[str, ...] | None:
        """Confirmed unusable-lead set of a kept record, or ``None`` if any part is open."""
        if self.repeat.get(code) is not False:
            return None
        if any((code, ld) not in self.leads for ld in DISPLAYED_LEADS):
            return None
        return tuple(ld for ld in DISPLAYED_LEADS if self.leads[(code, ld)])


def _adjudicated_value(settled: CodedResponse, item: str):
    if item == "repeat":
        return settled.repeat_ecg
    if item == "section":
        return settled.usable_section
    return settled.lead_unusable(item)


def _settle(code: str, item: str, va, vb, settled: CodedResponse | None):
    """Agreed value, adjudicated value for a dispute, or ``None`` while still open."""
    if va == vb:
        if settled is not None and _adjudicated_value(settled, item) != va:
            raise ValueError(
                f"{code}: readers agree on {item}; an adjudicated row may not override them"
            )
        return va
    if settled is not None:
        return _adjudicated_value(settled, item)
    return None


def confirmed_reference(
    first: Mapping[str, CodedResponse],
    second: Mapping[str, CodedResponse],
    adjudicated: Mapping[str, CodedResponse] | None = None,
) -> Reference:
    """Build the reference from two independent readers and optional adjudication.

    Agreement is decided unit by unit: each displayed lead, the repeat decision, the usable
    section (when neither reader repeats) and the grade. An adjudicated row settles only the
    units in dispute for its record; if it contradicts a unit both readers agreed on it is
    refused, so the reference cannot be changed after the fact.
    """
    adjudicated = dict(adjudicated or {})
    if set(first) != set(second):
        raise ValueError("the two readers' sheets cover different blind codes")
    unknown = set(adjudicated) - set(first)
    if unknown:
        raise ValueError(f"adjudicated rows for unknown codes: {sorted(unknown)[:5]}")
    leads: dict[tuple[str, str], bool] = {}
    repeat: dict[str, bool] = {}
    section: dict[str, str] = {}
    grade: dict[str, str] = {}
    disputed: dict[str, tuple[str, ...]] = {}
    for code in sorted(first):
        a, b, settled = first[code], second[code], adjudicated.get(code)
        open_items = []
        items = [
            (ld, a.lead_unusable(ld), b.lead_unusable(ld), leads, (code, ld))
            for ld in DISPLAYED_LEADS
        ]
        items.append(("repeat", a.repeat_ecg, b.repeat_ecg, repeat, code))
        if not a.repeat_ecg and not b.repeat_ecg:
            items.append(("section", a.usable_section, b.usable_section, section, code))
        for item, va, vb, store, key in items:
            decided = _settle(code, item, va, vb, settled)
            if decided is None:
                open_items.append(item)
            else:
                store[key] = decided
        if a.overall == b.overall:
            grade[code] = a.overall
        elif settled is not None:
            grade[code] = settled.overall
        if open_items:
            disputed[code] = tuple(open_items)
    return Reference(leads=leads, repeat=repeat, section=section, grade=grade, disputed=disputed)


def _lead_pred(p: Prediction, lead: str, reference: bool) -> bool:
    """Intention-to-diagnose: a failed record is discordant with the reference."""
    if p.failed:
        return not reference
    return p.repeat_ecg or lead in p.unusable_leads


def _lead_units(
    pred: Mapping[str, Prediction], ref: Reference, leads: Sequence[str], itd: bool
) -> list[tuple[str, str]]:
    """Confirmed lead units; without intention-to-diagnose, failed records are excluded."""
    return [(c, ld) for (c, ld) in sorted(ref.leads) if ld in leads and (itd or not pred[c].failed)]


def lead_level(
    pred: Mapping[str, Prediction],
    ref: Reference,
    *,
    leads: Sequence[str] = DISPLAYED_LEADS,
    seed: int = SAP_BOOTSTRAP_SEED,
    itd: bool = True,
    n_resamples: int = SAP_N_RESAMPLES,
) -> dict:
    """P1: per-lead unusable detection over confirmed units, record-clustered bootstrap CIs."""
    units = _lead_units(pred, ref, leads, itd)
    r = np.array([ref.leads[u] for u in units], dtype=bool)
    p = np.array([_lead_pred(pred[c], ld, ref.leads[(c, ld)]) for c, ld in units], dtype=bool)
    clusters = [c for c, _ in units]
    counts = BinaryCounts.from_pairs(p, r)
    out = {
        "counts": counts.__dict__,
        "n_units": len(units),
        "n_records": len(set(clusters)),
    }
    for name, fn in (
        ("sensitivity", lambda i: p[i][r[i]].mean() if r[i].any() else np.nan),
        ("specificity", lambda i: (~p[i][~r[i]]).mean() if (~r[i]).any() else np.nan),
    ):
        lo, hi = cluster_bootstrap_ci(fn, clusters, n_resamples=n_resamples, seed=seed)
        out[name] = {"value": counts.metrics()[name]["value"], "lo": lo, "hi": hi}
    for name in ("ppv", "npv", "f1"):
        out[name] = {"value": counts.metrics()[name]["value"]}
    return out


def record_level(pred: Mapping[str, Prediction], ref: Reference, *, itd: bool = True) -> dict:
    """P2: repeat-ECG over confirmed records, with Wilson CIs."""
    codes = [c for c in sorted(ref.repeat) if itd or not pred[c].failed]
    r = [ref.repeat[c] for c in codes]
    p = [(not ref.repeat[c]) if pred[c].failed else pred[c].repeat_ecg for c in codes]
    m = BinaryCounts.from_pairs(p, r).metrics()
    return {k: m[k] for k in ("sensitivity", "specificity", "ppv", "npv", "f1")}


def paired_comparison(
    first: Mapping[str, Prediction],
    second: Mapping[str, Prediction],
    ref: Reference,
    *,
    seed: int = SAP_BOOTSTRAP_SEED,
    n_resamples: int = SAP_N_RESAMPLES,
) -> dict:
    """Paired differences (first − second): record-level McNemar/Newcombe, lead-level bootstrap."""
    out = {}
    for name, subset in (
        ("sensitivity", [c for c in sorted(ref.repeat) if ref.repeat[c]]),
        ("specificity", [c for c in sorted(ref.repeat) if not ref.repeat[c]]),
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
    units = sorted(ref.leads)
    r = np.array([ref.leads[u] for u in units], dtype=bool)
    # Per-unit correctness, so one formula serves sensitivity (r) and specificity (~r).
    ca = np.array([_lead_pred(first[c], ld, ref.leads[(c, ld)]) for c, ld in units]) == r
    cb = np.array([_lead_pred(second[c], ld, ref.leads[(c, ld)]) for c, ld in units]) == r
    clusters = [c for c, _ in units]
    for name, mask in (("lead_sensitivity", r), ("lead_specificity", ~r)):

        def diff(i, mask=mask):
            m = mask[i]
            return ca[i][m].mean() - cb[i][m].mean() if m.any() else np.nan

        lo, hi = cluster_bootstrap_ci(diff, clusters, n_resamples=n_resamples, seed=seed)
        value = float(ca[mask].mean() - cb[mask].mean()) if mask.any() else float("nan")
        out[name] = {"difference": value, "lo": lo, "hi": hi}
    return out


def agreement_with_reference(pred: Mapping[str, Prediction], ref: Reference) -> dict:
    """Secondary: graded agreement (weighted κ) and lead-set agreement on confirmed records."""
    graded = [c for c in sorted(ref.grade) if pred[c].graded_quality in OVERALL]
    kappa = (
        cohen_kappa(
            [pred[c].graded_quality for c in graded],
            [ref.grade[c] for c in graded],
            OVERALL,
            weights="linear",
        )
        if graded
        else float("nan")
    )
    sets = []
    for code in ref.codes:
        confirmed = ref.lead_set(code)
        p = pred[code]
        if confirmed is not None and not p.failed and not p.repeat_ecg:
            sets.append((set(p.unusable_leads), set(confirmed)))
    return {
        "graded_weighted_kappa": kappa,
        "n_graded": len(graded),
        "lead_set_exact_match": float(np.mean([a == b for a, b in sets])) if sets else float("nan"),
        "lead_set_mean_jaccard": (
            float(np.mean([jaccard(a, b) for a, b in sets])) if sets else float("nan")
        ),
        "n_lead_sets": len(sets),
    }
