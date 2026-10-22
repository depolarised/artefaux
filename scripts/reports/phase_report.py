#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Score signalguard and Uni-G on a comparison phase against the readers' confirmed answers.

Implements ``docs/BENCHMARK_SAP.md`` on the confirmed units of one phase
(``docs/PHASE1.md``): P1 (lead unusable), P2 (repeat ECG), the paired differences
signalguard - Uni-G, the pre-specified sensitivity analyses (each reader alone, V1-V6
only, signalguard ``borderline`` as unusable, failures excluded), each reader scored
against the other as the human benchmark, and the primary endpoints by corpus group.

Inputs: the coded reader answers (``coding.csv``), the private blind key (for the corpus
group) and each program's run directory (``predictions_{records,leads}.csv`` plus
``run_manifest.json``). Writes ``results.json`` and ``results.md`` to ``--out``
(private by default). Every metric reports its denominator; disputed units are counted,
never scored.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

from artefaux.bench_scoring import (
    agreement_with_reference,
    confirmed_reference,
    lead_level,
    paired_comparison,
    prediction_from_coded,
    read_prediction_dir,
    record_level,
)
from artefaux.review_coding import read_coding

REPO = Path(__file__).resolve().parents[2]
LIMB, CHEST = ("I", "II"), ("V1", "V2", "V3", "V4", "V5", "V6")
LABELS = {"signalguard": "signalguard", "unig": "Uni-G"}


def _clean(value):
    """JSON-safe copy: NaN becomes null."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def endpoints(pred, ref, *, itd=True) -> dict:
    return {
        "P1_all": lead_level(pred, ref, itd=itd),
        "P1_V1_V6": lead_level(pred, ref, leads=CHEST, itd=itd),
        "P1_I_II": lead_level(pred, ref, leads=LIMB, itd=itd),
        "P2": record_level(pred, ref, itd=itd),
    }


def run_info(directory: Path) -> dict:
    manifest = json.loads((directory / "run_manifest.json").read_text())
    with (directory / "predictions_records.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    runtimes = [float(r["runtime_ms"]) for r in rows if not r["error"]]
    return {
        "version": manifest["version"],
        "commit": manifest["commit"],
        "inputs_sha256": manifest["inputs_sha256"],
        "n_errors": sum(bool(r["error"]) for r in rows),
        "errors": {r["blind_code"]: r["error"] for r in rows if r["error"]},
        "runtime_ms_median": statistics.median(runtimes) if runtimes else None,
    }


def build(args) -> dict:
    with args.key.open(newline="") as fh:
        key = list(csv.DictReader(fh))
    codes = [r["blind_code"] for r in key]
    groups: dict[str, list[str]] = {}
    for row in key:
        groups.setdefault(row["group"], []).append(row["blind_code"])
    readers = read_coding(args.coding)
    pwm, dtc = readers["PWM"], readers["DTC"]
    ref = confirmed_reference(pwm, dtc)
    preds = {
        src: read_prediction_dir(args.predictions / src, codes, bench_version=args.phase)
        for src in args.sources
    }
    sg_borderline = read_prediction_dir(
        args.predictions / "signalguard",
        codes,
        bench_version=args.phase,
        unusable_labels=("borderline",),
    )
    ref_pwm, ref_dtc = confirmed_reference(pwm, pwm), confirmed_reference(dtc, dtc)
    first, second = args.sources
    out = {
        "phase": args.phase,
        "coding_verified": args.coding_verified,
        "reference": {
            "lead_units_confirmed": len(ref.leads),
            "lead_units_confirmed_unusable": sum(ref.leads.values()),
            "lead_units_total": 8 * len(codes),
            "repeat_confirmed": len(ref.repeat),
            "repeat_confirmed_yes": sum(ref.repeat.values()),
            "records_with_disputes": len(ref.disputed),
            "adjudicated": 0,
        },
        "runs": {src: run_info(args.predictions / src) for src in args.sources},
        "primary": {src: endpoints(p, ref) for src, p in preds.items()},
        "agreement": {src: agreement_with_reference(p, ref) for src, p in preds.items()},
        "paired": {f"{first}-{second}": paired_comparison(preds[first], preds[second], ref)},
        "sensitivity": {
            "reference_PWM_alone": {src: endpoints(p, ref_pwm) for src, p in preds.items()},
            "reference_DTC_alone": {src: endpoints(p, ref_dtc) for src, p in preds.items()},
            "signalguard_borderline_unusable": endpoints(sg_borderline, ref),
            "failures_excluded": {src: endpoints(p, ref, itd=False) for src, p in preds.items()},
        },
        "readers": {
            "PWM_vs_DTC": endpoints(
                {c: prediction_from_coded(r, "PWM") for c, r in pwm.items()}, ref_dtc
            ),
            "DTC_vs_PWM": endpoints(
                {c: prediction_from_coded(r, "DTC") for c, r in dtc.items()}, ref_pwm
            ),
        },
        "by_group": {
            group: {
                "n_records": len(members),
                **{src: endpoints(p, ref.restrict(members)) for src, p in preds.items()},
            }
            for group, members in sorted(groups.items())
        },
    }
    return _clean(out)


def _ci(m: dict | None) -> str:
    if not m or m.get("value") is None:
        return "–"
    if m.get("lo") is None:
        return f"{m['value']:.2f}"
    return f"{m['value']:.2f} ({m['lo']:.2f}–{m['hi']:.2f})"


def _diff(m: dict | None) -> str:
    if not m or m.get("difference") is None:
        return "–"
    p = f", McNemar p = {m['mcnemar_p']:.3f}" if "mcnemar_p" in m else ""
    return f"{m['difference']:+.2f} ({m['lo']:+.2f} to {m['hi']:+.2f}){p}"


def _endpoint_rows(name: str, e: dict) -> list[str]:
    p1, p2 = e["P1_all"], e["P2"]
    c = p1["counts"]
    return [
        f"| {name} | {_ci(p1['sensitivity'])} | {_ci(p1['specificity'])} "
        f"| {c['tp']}/{c['fp']}/{c['fn']}/{c['tn']} | {_ci(p2['sensitivity'])} "
        f"| {_ci(p2['specificity'])} |"
    ]


HEAD = (
    "| | Lead sensitivity | Lead specificity | TP/FP/FN/TN | Repeat sensitivity "
    "| Repeat specificity |\n|---|---|---|---|---|---|"
)


def markdown(r: dict) -> str:
    ref = r["reference"]
    lines = [
        f"# Phase results: {r['phase']}",
        "",
        "Private. Reference = units on which Peter and Derek agree; no adjudication. "
        + ("Coding verified." if r["coding_verified"] else "**Coding not yet verified (draft).**"),
        "",
        f"Reference: {ref['lead_units_confirmed']}/{ref['lead_units_total']} lead units "
        f"({ref['lead_units_confirmed_unusable']} unusable); {ref['repeat_confirmed']} repeat "
        f"decisions ({ref['repeat_confirmed_yes']} repeat); {ref['records_with_disputes']} records "
        "with a disputed unit, left out of the units they dispute.",
        "",
        "## Runs",
        "",
        "| Program | Version | Commit | Failures | Median ms |",
        "|---|---|---|---|---|",
    ]
    for src, info in r["runs"].items():
        lines.append(
            f"| {LABELS.get(src, src)} | {info['version']} | `{info['commit'][:7]}` "
            f"| {info['n_errors']} | {info['runtime_ms_median']:.0f} |"
        )
    lines += ["", "## Primary endpoints (95% CI)", "", HEAD]
    for src, e in r["primary"].items():
        lines += _endpoint_rows(LABELS.get(src, src), e)
    lines += ["", "Lead-level by lead group (sensitivity / specificity):", ""]
    lines += ["| | I, II | V1–V6 |", "|---|---|---|"]
    for src, e in r["primary"].items():
        lines.append(
            f"| {LABELS.get(src, src)} | {_ci(e['P1_I_II']['sensitivity'])} / "
            f"{_ci(e['P1_I_II']['specificity'])} | {_ci(e['P1_V1_V6']['sensitivity'])} / "
            f"{_ci(e['P1_V1_V6']['specificity'])} |"
        )
    ((pair, d),) = r["paired"].items()
    lines += [
        "",
        f"## Paired difference ({pair.replace('unig', 'Uni-G')})",
        "",
        "| Endpoint | Difference (95% CI) |",
        "|---|---|",
        f"| Lead sensitivity | {_diff(d['lead_sensitivity'])} |",
        f"| Lead specificity | {_diff(d['lead_specificity'])} |",
        f"| Repeat sensitivity (n = {d['record_sensitivity']['n']}) "
        f"| {_diff(d['record_sensitivity'])} |",
        f"| Repeat specificity (n = {d['record_specificity']['n']}) "
        f"| {_diff(d['record_specificity'])} |",
        "",
        "## Agreement",
        "",
        "| | Graded κ (linear) | Lead set exact | Mean Jaccard | n sets |",
        "|---|---|---|---|---|",
    ]
    for src, a in r["agreement"].items():
        kappa = "–" if a["graded_weighted_kappa"] is None else f"{a['graded_weighted_kappa']:.2f}"
        exact = "–" if a["lead_set_exact_match"] is None else f"{a['lead_set_exact_match']:.2f}"
        jac = "–" if a["lead_set_mean_jaccard"] is None else f"{a['lead_set_mean_jaccard']:.2f}"
        lines.append(f"| {LABELS.get(src, src)} | {kappa} | {exact} | {jac} | {a['n_lead_sets']} |")
    lines += ["", "## Readers scored against each other (human benchmark)", "", HEAD]
    lines += _endpoint_rows("Peter vs Derek", r["readers"]["PWM_vs_DTC"])
    lines += _endpoint_rows("Derek vs Peter", r["readers"]["DTC_vs_PWM"])
    s = r["sensitivity"]
    lines += ["", "## Sensitivity analyses", "", HEAD]
    for name, block in (
        ("Peter alone", "reference_PWM_alone"),
        ("Derek alone", "reference_DTC_alone"),
    ):
        for src, e in s[block].items():
            lines += _endpoint_rows(f"{LABELS.get(src, src)}, {name}", e)
    lines += _endpoint_rows(
        "signalguard, borderline = unusable", s["signalguard_borderline_unusable"]
    )
    for src, e in s["failures_excluded"].items():
        lines += _endpoint_rows(f"{LABELS.get(src, src)}, failures excluded", e)
    lines += ["", "## By corpus group", "", HEAD]
    for group, block in r["by_group"].items():
        for src in r["primary"]:
            lines += _endpoint_rows(
                f"{group} (n = {block['n_records']}), {LABELS.get(src, src)}", block[src]
            )
    lines += [
        "",
        "## Caveats",
        "",
        "- Set 1 informed the design and its key is known to the coordinator, who develops",
        "  signalguard and ran both programs (by script, versions frozen in dev-log ADR 0018).",
        "- Readers saw filtered set-1 PDFs; the programs received the raw signals.",
        "- Uni-G's I/II noise decisions are only partly visible in its output (internal flags).",
        "- Peter co-developed Uni-G: see the Derek-alone analysis.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", default="phase1-set1-1.0")
    parser.add_argument(
        "--coding", type=Path, default=REPO / "out/review-synthesis/set1/coding.csv"
    )
    parser.add_argument(
        "--key", type=Path, default=REPO / "reports/artefaux_v2_ecg_review_blind.key.csv"
    )
    parser.add_argument("--predictions", type=Path, default=REPO / "out/phase1/predictions")
    parser.add_argument("--sources", nargs=2, default=["signalguard", "unig"])
    parser.add_argument("--out", type=Path, default=REPO / "out/phase1/report")
    parser.add_argument("--coding-verified", action="store_true")
    args = parser.parse_args()
    results = build(args)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (args.out / "results.md").write_text(markdown(results))
    print(f"Wrote {args.out}/results.{{json,md}}")


if __name__ == "__main__":
    main()
