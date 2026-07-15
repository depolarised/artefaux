#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Build the Artefaux v1 corpus report in the Glasgow ECG-AF report house style.

Pandoc-markdown with YAML front-matter (booktabs / longtable), numbered sections,
provenance line, right-aligned numeric tables. Every value is computed from the
*committed* corpus definition (``artefaux.corpus`` + ``recipes/source_ids/``) and the
recipe-authored labels, so no number in the report can drift from the source.

    python scripts/reports/generate_corpus_report.py            # -> reports/artefaux_v1_corpus_report.md
    python scripts/reports/generate_corpus_report.py --pdf      # also render PDF via pandoc, if available
"""

# ruff: noqa: E501  — this module embeds the report's prose/tables as long text lines.

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from artefaux.build import resolve_source_ids
from artefaux.constants import SNR_LADDER_DB
from artefaux.corpus import build_corpus_specs
from artefaux.recipes import build_record
from artefaux.synthetic import synthetic_parent_signal

MASTER_SEED = 20260713
REPO = Path(__file__).resolve().parents[2]


def _yn(flag: bool) -> str:
    return "yes" if flag else "—"


def _n_bad_leads(label) -> int:
    """Count of leads a detector is expected to reject — same formula as manifest.json."""
    return sum(1 for q in label.expected_behaviour.lead_quality.values() if q == "bad")


def _short_id(record_id: str | None) -> str:
    """PTB-XL id as its record stem (the ``records500/NNNNN/`` prefix is boilerplate)."""
    if not record_id:
        return "—"
    return record_id.rsplit("/", 1)[-1]


def _wrap(text: str) -> str:
    """Insert zero-width spaces after ``_``/``/`` so long ids can line-break.

    U+200B is a valid breakpoint in XeLaTeX and is invisible in the Markdown /
    GitHub view, so a long ``record_id`` wraps in the PDF without altering its text.
    """
    zwsp = "​"
    return text.replace("_", "_" + zwsp).replace("/", "/" + zwsp)


def _rid(record_id: str) -> str:
    return f"`{_wrap(record_id)}`"


def _leads_union(steps) -> list[str]:
    seen: list[str] = []
    for s in steps:
        for ld in (*s.leads_affected, *s.electrodes_affected):
            if ld not in seen:
                seen.append(ld)
    return seen


def _describe(step) -> str:
    """A compact, source-faithful description of one corruption step."""
    op = step.op
    p = step.params or {}
    leads = ", ".join(step.leads_affected)
    if op == "nstdb_mix":
        return f"NSTDB `{step.noise_type}` @ {step.snr_requested_db:+.0f} dB ({leads or 'all'})"
    if op == "motion_swing":
        s = f"MACECGDB `{step.noise_type}` swing {p.get('requested_p2p_mv'):g} mV p2p ({leads})"
        if p.get("rail_mv") is not None:
            s += f" → rail ±{p['rail_mv']:g} mV"
        return s
    if op == "precordial":
        w = p.get("shared_weights", {})
        return f"precordial coupling {', '.join(w)} @ {step.snr_requested_db:+.0f} dB"
    if op == "electrode_domain":
        el = ", ".join(step.electrodes_affected)
        return f"{el} electrode {p.get('kind', 'motion')} {p.get('amplitude_mv'):g} mV"
    if op in ("swing", "overload_swing"):
        label = "overload swing" if op == "overload_swing" else "swing"
        s = f"{label} {p.get('requested_p2p_mv'):g} mV p2p ({leads})"
        if p.get("rail_mv") is not None:
            s += f" → rail ±{p['rail_mv']:g} mV"
        iv = p.get("interval_s")
        if iv and tuple(iv) != (0.0, 10.0):
            s += f", t in [{iv[0]:g},{iv[1]:g}] s"
        return s
    if op == "step_recovery":
        return f"baseline step {p.get('step_mv'):g} mV, tau={p.get('tau_s'):g} s ({leads})"
    if op == "constant_adc":
        return f"stuck constant {p.get('value_mv'):g} mV ({leads})"
    if op == "flatline":
        return f"flatline / zero-fill ({leads})"
    if op == "lead_off":
        return f"lead-off ({leads})"
    if op == "intermittent_lead_off":
        return f"intermittent lead-off with reconnection ({leads})"
    if op == "digital_missing":
        return f"digital-missing / NaN ({leads})"
    if op == "opposite_polarity":
        return f"polarity inversion ({leads})"
    return f"{op} ({leads})"


def _describe_record(label) -> str:
    return " ; ".join(_describe(s) for s in label.corruption_truth.steps) or "—"


def _rows():
    specs = resolve_source_ids(build_corpus_specs(), REPO / "recipes" / "source_ids")
    rows = []
    for spec in specs:
        parent = synthetic_parent_signal(seed=spec.seed_index)
        _, label = build_record(parent, spec, MASTER_SEED, fs=500)
        rows.append((spec, label))
    return rows


def _table(header: str, aligns: list[str], lines: list[list[str]]) -> str:
    sep = "|" + "|".join(aligns) + "|"
    out = [header, sep, *["| " + " | ".join(c) + " |" for c in lines]]
    return "\n".join(out)


def _naturally_poor_table(rows) -> str:
    header = "| Record | PTB-XL source | Quality flag(s) | Expected quality | Discard |"
    aligns = [":--", ":--", ":--", ":--:", ":--:"]
    lines = []
    for spec, label in rows:
        if spec.group != "naturally_poor":
            continue
        cp, eb = label.clinical_parent, label.expected_behaviour
        lines.append(
            [
                _rid(spec.record_id),
                f"`{_short_id(cp.source_record_id)}`",
                ", ".join(cp.ptbxl_quality_flags) or "—",
                f"**{eb.record_quality}**",
                _yn(eb.noiseguard_discard_record),
            ]
        )
    return _table(header, aligns, lines)


def _real_noise_table(rows) -> str:
    header = (
        "| Record | Rhythm | PTB-XL parent | Noise @ SNR | Leads | Bad leads "
        "| Expected quality | Discard |"
    )
    aligns = [":--", ":--", ":--", ":--", ":--:", "--:", ":--:", ":--:"]
    lines = []
    for spec, label in rows:
        if spec.group != "real_noise":
            continue
        cp, eb = label.clinical_parent, label.expected_behaviour
        step = label.corruption_truth.steps[0]
        n_leads = len(step.leads_affected)
        scope = "12" if n_leads == 12 else str(n_leads)
        lines.append(
            [
                _rid(spec.record_id),
                (cp.rhythm_class or "—").replace("_", " "),
                f"`{_short_id(cp.source_record_id)}`",
                f"`{step.noise_type}` @ {step.snr_requested_db:+.0f} dB",
                scope,
                str(_n_bad_leads(label)),
                f"**{eb.record_quality}**",
                _yn(eb.noiseguard_discard_record),
            ]
        )
    return _table(header, aligns, lines)


def _engineering_table(rows, multi: bool) -> str:
    header = (
        "| Record | PTB-XL parent | Corruption | Integrity failure "
        "| Bad leads | Expected quality | Discard |"
    )
    aligns = [":--", ":--", ":--", ":--", "--:", ":--:", ":--:"]
    lines = []
    for spec, label in rows:
        if spec.group != "engineering":
            continue
        is_multi = len(_leads_union(label.corruption_truth.steps)) > 1
        if is_multi != multi:
            continue
        cp, eb = label.clinical_parent, label.expected_behaviour
        integ = eb.integrity_failure_type.replace("_", " ") if eb.data_integrity_failure else "—"
        lines.append(
            [
                _rid(spec.record_id),
                f"`{_short_id(cp.source_record_id)}`",
                _describe_record(label),
                integ,
                str(_n_bad_leads(label)),
                f"**{eb.record_quality}**",
                _yn(eb.noiseguard_discard_record),
            ]
        )
    return _table(header, aligns, lines)


def build_report() -> str:
    rows = _rows()
    n = len(rows)
    n_nat = sum(1 for s, _ in rows if s.group == "naturally_poor")
    n_noise = sum(1 for s, _ in rows if s.group == "real_noise")
    n_eng = sum(1 for s, _ in rows if s.group == "engineering")
    n_eng_single = sum(
        1
        for s, lbl in rows
        if s.group == "engineering" and len(_leads_union(lbl.corruption_truth.steps)) == 1
    )
    n_eng_multi = n_eng - n_eng_single
    n_integrity = sum(1 for _, lbl in rows if lbl.expected_behaviour.data_integrity_failure)
    ladder = ", ".join(f"{d:+d}" for d in sorted(SNR_LADDER_DB))

    fm = f"""---
title: "ECG Noise and Lead-Failure Stress-Test Corpus (v1) — Generation Report and Full Record Roster"
date: "2026-07-13"
author: "Ioannis Valasakis"
affiliation: "Electrocardiography Group, University of Glasgow"
geometry: margin=2.5cm
fontsize: 11pt
colorlinks: true
header-includes:
  - \\usepackage{{booktabs}}
  - \\usepackage{{longtable}}
  - \\usepackage{{graphicx}}
  - \\usepackage{{etoolbox}}
  - \\usepackage{{fancyhdr}}
  - \\AtBeginEnvironment{{longtable}}{{\\small}}
  - \\pagestyle{{fancy}}
  - \\fancyhf{{}}
  - \\renewcommand{{\\headrulewidth}}{{0pt}}
  - \\fancyfoot[L]{{\\small Artefaux v1.0.0}}
  - \\fancyfoot[C]{{\\small\\thepage}}
  - \\fancyfoot[R]{{\\small github.com/depolarised/artefaux}}
---

# ECG Noise and Lead-Failure Stress-Test Corpus (v1)

**Ioannis Valasakis**

*Electrocardiography Group, University of Glasgow*

**Date:** 2026-07-13 · **Repository:** <https://github.com/depolarised/artefaux> (tag `v1.0.0`) ·
**Sources (every value below traces to these):** `recipes/corpus.yaml`, `recipes/source_ids/*.csv`,
`manifest.json` (all committed), regenerated in-memory from `artefaux.corpus` + `artefaux.recipes`
(`master_seed = {MASTER_SEED}`). Generator: `scripts/reports/generate_corpus_report.py`.

> **Scope.** This is a *stress-test set, not a clinically representative cohort.* It deliberately
> over-samples failure; do not use it to estimate real-world prevalence or deployment accuracy.

---

## 1. Objectives

This is a deterministic generator and reproducible corpus **definition** for stress-testing ECG
signal-quality gates (the internal `signalguard`) and noise detectors (`noiseguard`). It does **not**
redistribute derived signals: it ships code, recipes, labels, manifest, and provenance so a user
regenerates the corpus **bit-exactly** from their own open PhysioNet copies.

This report documents the generation algorithm and enumerates **all {n} stress records** with their
corruption truth and expected behaviour. Records resolve against a local PhysioNet mirror; the concrete
PTB-XL parent ids shown here are those in `recipes/source_ids/` (reproducible, seeded selection).

---

## 2. Corpus composition

| Group | n | Source | Corruption |
|:--|--:|:--|:--|
| Naturally poor | {n_nat} | PTB-XL technical-validation quality flags | none (inherently noisy) |
| Real-noise pairs | {n_noise} | clean PTB-XL + NSTDB `em`/`ma`/`bw` | SNR ladder {{{ladder}}} dB |
| Engineering extremes | {n_eng} | clean PTB-XL parents (+ MACECGDB motion) | single-lead ({n_eng_single}) + multi-lead ({n_eng_multi}) |
| **Total** | **{n}** | | {n_integrity} labelled data-integrity failures |

Each record carries three label layers — **clinical parent** (authored rhythm class + PTB-XL quality flags; the Uni-G statement field is reserved and empty in v1),
**corruption truth** (electrodes/leads, requested + measured SNR, noise segment, seed, $\\alpha$, amplitude
bookkeeping), and **expected behaviour** (per-lead and record-level, mapped to the `signalguard`
`QualityLabel` / `RecordQuality` and `noiseguard` discard vocabularies).

![Corpus composition — {n} stress records plus paired clean parents.](../figures/corpus_composition.png)

---

## 3. Sources and licensing

| Dataset | Role | Version | License |
|:--|:--|:--|:--|
| PTB-XL | clean + naturally-poor parents (500 Hz) | 1.0.3 | CC-BY-4.0 |
| PTB-XL+ | Uni-G/Glasgow layer — *cited and pinned, not consumed by v1* | 1.0.1 | CC-BY-4.0 |
| MIT-BIH NSTDB | `em`/`ma`/`bw` noise for the SNR ladder | 1.0.0 | ODC-BY-1.0 |
| MACECGDB | real standing/walking/jumping motion | 1.0.0 | ODC-BY-1.0 |

PTB-XL, PTB-XL+, and MACECGDB are read from a local PhysioNet mirror; **only NSTDB** is fetched by
`make download`. **Code** is GPL-3.0-or-later; **manifest, labels, and docs** are CC-BY-4.0. No source
signals are redistributed — see `ATTRIBUTION.md`.

---

## 4. Generation algorithm

**4.1 Canonical form.** Every parent becomes a `(12, T)` float64 mV array in canonical lead order
`[I, II, III, aVR, aVL, aVF, V1–V6]` at 500 Hz (NSTDB resampled from 360 Hz by deterministic polyphase
resampling). Absent limb leads are derived from I and II.

**4.2 Real-noise SNR mixing.** For a clean lead $x$, real noise $n$, and requested SNR $s$ (dB):
$\\alpha = \\sqrt{{P_x / (P_n \\cdot 10^{{s/10}})}}$, $y = x + \\alpha\\,n$, with $P_x$, $P_n$ the
DC-removed mean-square powers over the contaminated interval only. Both the requested and the *measured*
SNR, and the exact NSTDB segment offset, are recorded in the label.

![Real-noise SNR ladder (illustrative synthetic parent; NSTDB-style electrode motion).](../figures/snr_ladder.png)

**4.3 Electrode-domain corruption.** Limb-electrode potentials are recovered in the RA-as-reference gauge
(`RA = 0`, `LA = I`, `LL = II`); chest-electrode potentials as `Ck = Vk + WCT`, `WCT = (RA+LA+LL)/3`. An
artefact is added to a chosen electrode; the WCT and all twelve leads are recomputed, and the invalidated
derived leads are recorded. (The classical WCT is an idealised electrode model, **not** a torso forward
model.)

**4.4 Engineering extremes.** Deterministic builders for clipping/rail-saturation, flatline (zero),
constant-ADC, lead-off, digital-missing (NaN), electrode-motion swings, step-and-exponential-recovery,
polarity inversion, and intermittent lead-off. NaN / flat / constant / rail cases are labelled
`data_integrity_failure` with a type — **not** as noise.

![Engineering extreme: an overload swing clipped at the acquisition rail.](../figures/overload_example.png)

---

## 5. Full record roster

All {n} records are listed below. **Expected quality** is the record-level `RecordQuality` a correctly-tuned
gate should assign; **Discard** is the expected `noiseguard` record-level decision; **Bad leads** is the
count of leads the label expects a detector to reject. PTB-XL parents are shown as record stems (the
`records500/NNNNN/` directory prefix is omitted).

### 5.1 Naturally poor ({n_nat})

Real PTB-XL records selected by technical-validation quality flags; no clean parent (inherently bad).

{{naturally_poor}}

### 5.2 Real-noise SNR-ladder pairs ({n_noise})

Clean PTB-XL parents mixed with NSTDB noise across the ladder {{{ladder}}} dB. Each ships with its untouched
clean parent (`*_clean`).

{{real_noise}}

### 5.3 Engineering extremes — single-lead ({n_eng_single})

{{eng_single}}

### 5.4 Engineering extremes — multi-lead / mixed ({n_eng_multi})

Electrode-domain propagation, precordial coupling, multi-lead saturation, and compound "wild" cases.

{{eng_multi}}

---

## 6. Reproducibility and provenance

A single master seed (`{MASTER_SEED}`) plus `provenance.json` (pinned source versions, per-record seed,
source-file SHA-256) make the corpus bit-exactly regenerable:

```bash
make download        # NSTDB only (PTB-XL / PTB-XL+ / MACECGDB from the local mirror)
make select          # resolve PTB-XL parent ids -> recipes/source_ids/  (seeded)
make regenerate      # WFDB records + labels + manifest + provenance -> ./out
```

Determinism is per-record: `SeedSequence(entropy=master_seed, spawn_key=(record_index,))`. The corpus
definition leaves source ids unresolved; `resolve_source_ids()` binds the seeded PTB-XL selection into the
specs at generation time.

---

## 7. Verification

Confirmed end-to-end on the local PhysioNet mirror (PTB-XL 1.0.3, MACECGDB 1.0.0, NSTDB 1.0.0):

- **Counts:** {n} records ({n_nat} / {n_noise} / {n_eng}) + 52 paired clean parents.
- **SNR ladder:** max \\|requested - measured\\| SNR error **0.0 dB** across all {n_noise} mixes (tol 0.5 dB).
- **Data integrity:** digital-missing (NaN) round-trips through WFDB — the affected channel reads back
  all-NaN while intact leads stay finite.
- **Determinism:** two independent full regenerations are **byte-identical**.
- **Quality gates:** 57 unit/integration tests pass; `ruff` + `black` clean.

---

*Generated by Artefaux v1.0.0 (<https://github.com/depolarised/artefaux>) via
`scripts/reports/generate_corpus_report.py`; every figure and table value is computed from the
committed corpus definition.*
"""
    body = fm
    body = body.replace("{naturally_poor}", _naturally_poor_table(rows))
    body = body.replace("{real_noise}", _real_noise_table(rows))
    body = body.replace("{eng_single}", _engineering_table(rows, multi=False))
    body = body.replace("{eng_multi}", _engineering_table(rows, multi=True))
    return body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="generate_corpus_report", description=__doc__)
    p.add_argument("--output", default=str(REPO / "reports" / "artefaux_v1_corpus_report.md"))
    p.add_argument("--pdf", action="store_true", help="Also render a PDF via pandoc, if available.")
    args = p.parse_args(argv)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report())
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
                    "--pdf-engine=xelatex",  # xelatex handles the Unicode (α, τ, ∈, →) natively
                    "--resource-path",
                    str(out.parent),
                ],
                check=True,
                cwd=out.parent,
            )
            print("wrote", pdf)
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            print(f"PDF render skipped ({exc}); the Markdown report is complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
