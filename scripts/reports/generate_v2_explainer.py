#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Build the Artefaux v2 *explainer* — the short companion to the waveform review pack.

Where ``generate_corpus_report.py`` enumerates every record, this document explains the
corpus at a glance: it makes the three groups visually distinct (via the colour-coded
figures), states the purpose of each group in a sentence or two, and lays out the criteria
used to assign the expected-behaviour labels. Every count and the SNR→label table are
computed from the committed corpus definition (``artefaux.corpus``) and the recipe-authored
labels, so no number in the explainer can drift from the source.

    python scripts/reports/generate_v2_explainer.py            # -> reports/artefaux_v2_explainer.md
    python scripts/reports/generate_v2_explainer.py --pdf      # also render a PDF via pandoc, if available
"""

# ruff: noqa: E501  — this module embeds the explainer's prose/tables as long text lines.

from __future__ import annotations

import argparse
import subprocess
from collections import defaultdict
from pathlib import Path

from artefaux.constants import SNR_LADDER_DB
from artefaux.corpus import _real_noise_expected, build_corpus_specs
from artefaux.recipes import build_record
from artefaux.synthetic import synthetic_parent_signal

MASTER_SEED = 20260713
REPO = Path(__file__).resolve().parents[2]

GROUP_ORDER = ("naturally_poor", "real_noise", "engineering")
GROUP_TITLE = {
    "naturally_poor": "Naturally poor",
    "real_noise": "Real-noise (low-SNR)",
    "engineering": "Engineering extremes",
}


def _labels():
    """Build every record's label from a synthetic parent (labels are seed-independent)."""
    for spec in build_corpus_specs():
        parent = synthetic_parent_signal(seed=spec.seed_index)
        _, label = build_record(parent, spec, MASTER_SEED, fs=500)
        yield spec, label


def _tallies():
    t = {g: defaultdict(int) for g in GROUP_ORDER}
    for spec, label in _labels():
        eb = label.expected_behaviour
        g = spec.group
        t[g]["n"] += 1
        t[g]["discard"] += int(eb.noiseguard_discard_record)
        t[g]["reject"] += int(eb.record_quality == "reject")
        t[g]["integrity"] += int(eb.data_integrity_failure)
    return t


def _summary_table(t) -> str:
    header = "| Group | n | Discard | Reject | Integrity failures | Source | Corruption |"
    sep = "|:--|--:|--:|--:|--:|:--|:--|"
    src = {
        "naturally_poor": "PTB-XL (quality flags)",
        "real_noise": "clean PTB-XL + NSTDB",
        "engineering": "clean PTB-XL (+ MACECGDB)",
    }
    corr = {
        "naturally_poor": "none (inherently noisy)",
        "real_noise": f"NSTDB `em`/`ma`/`bw` @ {{{_ladder_str()}}} dB",
        "engineering": "deterministic acquisition failures",
    }
    rows = [header, sep]
    for g in GROUP_ORDER:
        c = t[g]
        rows.append(
            f"| {GROUP_TITLE[g]} | {c['n']} | {c['discard']} | {c['reject']} | {c['integrity']} | {src[g]} | {corr[g]} |"
        )
    total = {k: sum(t[g][k] for g in GROUP_ORDER) for k in ("n", "discard", "reject", "integrity")}
    rows.append(
        f"| **Total** | **{total['n']}** | **{total['discard']}** | **{total['reject']}** | **{total['integrity']}** | | |"
    )
    return "\n".join(rows)


def _ladder_str() -> str:
    return ", ".join(f"{d:+d}" for d in sorted(SNR_LADDER_DB))


def _snr_band_table() -> str:
    """The real-noise SNR→label mapping, generated from the authoritative function."""
    header = "| SNR (dB) | Record quality | Lead quality | Discard |"
    sep = "|:--:|:--|:--|:--:|"
    rows = [header, sep]
    for snr in sorted(SNR_LADDER_DB):
        exp = _real_noise_expected(snr, "all")
        discard = "yes" if exp["noiseguard_discard"] else "—"
        rows.append(
            f"| {snr:+d} | {exp['record_quality']} | {exp['lead_quality']['default']} | {discard} |"
        )
    return "\n".join(rows)


def build_explainer() -> str:
    t = _tallies()
    n = sum(t[g]["n"] for g in GROUP_ORDER)
    n_discard = sum(t[g]["discard"] for g in GROUP_ORDER)
    ladder = _ladder_str()

    return f"""---
title: "Artefaux v2 — Discard / Extreme Stress Pack: Explainer"
date: "2026-07-16"
author: "Ioannis Valasakis"
affiliation: "Electrocardiography Group, University of Glasgow"
geometry: margin=2.5cm
fontsize: 11pt
colorlinks: true
header-includes:
  - \\usepackage{{booktabs}}
  - \\usepackage{{longtable}}
  - \\usepackage{{graphicx}}
  - \\usepackage{{fancyhdr}}
  - \\pagestyle{{fancy}}
  - \\fancyhf{{}}
  - \\renewcommand{{\\headrulewidth}}{{0pt}}
  - \\fancyfoot[L]{{\\small Artefaux v2.0.0}}
  - \\fancyfoot[C]{{\\small\\thepage}}
  - \\fancyfoot[R]{{\\small github.com/depolarised/artefaux}}
---

# Artefaux v2 — Discard / Extreme Stress Pack

**Ioannis Valasakis** · *Electrocardiography Group, University of Glasgow* · 2026-07-16

This is the plain-language companion to the v2 waveform review pack
(`reports/artefaux_v2_ecg_review.pdf`, rendered with every lead as a full 10-second strip).
v2 is deliberately **weighted toward clinically-unusable recordings**: **{n_discard} of {n}**
records are expected to be discarded. It exists to stress a signal-quality gate where it
matters — near and beyond the point where an ECG stops being interpretable.

> **Scope.** A *stress-test set, not a clinically representative cohort.* It over-samples
> failure on purpose; do not read prevalence or deployment accuracy from it.

---

## 1. The three groups at a glance

The corpus is 85 stress records in three groups, each with its own colour throughout this
document and the figures.

![Composition of the v2 corpus by group.](../figures/corpus_composition.png)

![How many records each group expects a gate to discard versus keep.](../figures/group_severity.png)

{_summary_table(t)}

---

## 2. What each group is for

**Naturally poor ({t['naturally_poor']['n']}) — real-world noisy reference.** Genuine PTB-XL
12-lead ECGs flagged by PTB-XL's own technical-validation quality columns (`static_noise`,
`burst_noise`, `baseline_drift`, `electrodes_problems`). No synthetic corruption and no clean
parent — this is what real acquisition noise looks like, and it anchors the engineered cases
against reality. The severe electrode-problem records are labelled reject/discard; the rest are
`limited` but genuinely noisy.

**Real-noise ({t['real_noise']['n']}) — a controlled low-SNR dose–response.** Clean PTB-XL
parents mixed with real MIT-BIH NSTDB noise (`em` electrode motion, `ma` muscle artefact, `bw`
baseline wander) at a fixed, *aggressive-low* SNR ladder {{{ladder}}} dB. Unlike v1's clean-to-noisy
ladder, v2 drops the easy end and concentrates on the accept/reject decision region, so a
detector's behaviour can be traced as a function of severity rather than measured at a single
point. Each ships with its untouched clean parent (`*_clean`) for paired comparison.

**Engineering extremes ({t['engineering']['n']}) — deterministic acquisition failures.**
Recipe-built breakage rather than added noise: rail-clipping saturation, flat / stuck-constant /
disconnected / digital-missing (NaN) channels, huge electrode-motion swings, step-and-recovery
baseline shifts, polarity reversal, intermittent lead-off, and compound "wild" multi-mode records.
Single-lead, multi-lead, and whole-precordium variants exercise both per-lead and record-level gate
logic.

---

## 3. How labels are assigned

Every record carries three label layers: the **clinical parent** (authored rhythm class + PTB-XL
quality flags), the **corruption truth** (exact leads/electrodes, artefact, requested + measured SNR,
seed, amplitude bookkeeping), and the **expected behaviour** (what a correctly-tuned gate should do).
Labels are authored from the recipe — never by running a detector.

Expected behaviour is written in **two deliberately different vocabularies**: `signalguard` (a graded
record verdict — `diagnostic` / `limited` / `rhythm_only` / `reject`, plus a per-lead
`good`/`borderline`/`bad`) and `noiseguard` (a binary record-level *discard*). A record can be
`limited` for one and `discard=false` for the other; the label captures both.

**Real-noise: SNR → label.** For whole-record contamination the bands are (generated from the
definition, so they match the corpus exactly):

{_snr_band_table()}

Subset (limb- or chest-only) contamination degrades only the touched half, so the record stays
`limited` and discards only at or below 0 dB.

**Naturally poor.** Severe electrode-problem records are `reject` / discard; the remaining
quality-flagged records are `limited` and kept.

**Engineering.** Labels are authored per failure mode from what the recipe actually does to each lead.
Crucially, **NaN / flat / stuck-constant / rail-saturated cases are labelled
`data_integrity_failure` with a specific `integrity_failure_type` — not as noise** — because they are
acquisition/software faults a gate must catch by a different route than a low SNR.

---

## 4. The waveform pack

The companion `reports/artefaux_v2_ecg_review.pdf` renders each record with **every independent lead
(I, II, V1–V6) as its own full 10-second strip** (25 mm/s, 10 mm/mV, diagnostic filter), so a reviewer
sees each lead's complete recording at once and rail-clipping shows honestly as a `clipped` marker.
Regenerate the whole set with:

```bash
make regenerate                                              # build out/artefaux-v2 from local sources
python scripts/reports/render_ecg_review.py --layout strip8  # -> reports/artefaux_v2_ecg_review.pdf
python scripts/reports/generate_v2_explainer.py --pdf        # this document
```

---

*Generated by Artefaux v2.0.0 (<https://github.com/depolarised/artefaux>) via
`scripts/reports/generate_v2_explainer.py`; every count and the SNR→label table are computed from the
committed corpus definition.*
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="generate_v2_explainer", description=__doc__)
    p.add_argument("--output", default=str(REPO / "reports" / "artefaux_v2_explainer.md"))
    p.add_argument("--pdf", action="store_true", help="Also render a PDF via pandoc, if available.")
    args = p.parse_args(argv)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_explainer())
    print("wrote", out)

    if args.pdf:
        pdf = out.with_suffix(".pdf")
        try:
            subprocess.run(
                [
                    "pandoc",
                    str(out),
                    "-o",
                    str(pdf),
                    "--pdf-engine=xelatex",
                    "--resource-path",
                    str(out.parent),
                ],
                check=True,
                cwd=out.parent,
            )
            print("wrote", pdf)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            print(f"PDF render skipped ({exc}); the Markdown explainer is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
