<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Phased comparison on the reviewed sets (Phase 1 = review set 1)

signalguard and the Glasgow program (Uni-G) are compared on ECGs that Peter (PWM) and
Derek (DTC) have **already reviewed**, with their **confirmed** answers as the reference.

| Phase | ECGs | Reference | Status |
|---|---|---|---|
| 1 | Review set 1: the 85 v2 records, `REV-001`…`REV-085` (set-1 codes) | Set-1 answers, agreed units only (no adjudication round) | Both programs run and scored (draft until the coding is verified) |
| 2 | Review set 2: 85 records (set-2 codes) | Set-2 answers, same rules | Waiting for the returned sheets |

The input files, output schema, native-to-common mappings and trust model are those of
[`BENCHMARK.md`](BENCHMARK.md); the endpoints and statistics are those of
[`BENCHMARK_SAP.md`](BENCHMARK_SAP.md), applied to the confirmed units of each phase.

## Reference: confirmed units

Each reader's answer is coded into unusable leads (I, II, V1–V6), repeat-ECG, usable
section and grade (`artefaux.review_coding`; set-1 free text is coded with documented
overrides, `out/review-synthesis/set1/overrides.csv`, and checked by the coordinator).
The reference is built **unit by unit** (`artefaux.bench_scoring.confirmed_reference`):

- a lead judgement, a repeat decision or a usable section is **confirmed** when both readers
  give the same answer (a repeat makes every displayed lead unusable);
- a unit they disagree on is **disputed** and is left out of scoring. A joint adjudication
  sheet could settle disputed units (never agreed ones), but Phase 1 has **no adjudication
  round** (owner decision, 2026-10-22, ADR 0018 amendment 1): its reference is the agreed
  units only;
- every metric reports how many units it used and how many remained disputed.

Set 1, before adjudication (coding not yet verified):

| Endpoint | Confirmed | Of which |
|---|---|---|
| Lead unusable | 622 / 680 lead judgements | 139 unusable, 483 usable |
| Repeat ECG | 80 / 85 records | 10 repeat, 70 keep |
| Records with any dispute | 35 | 19 on leads, 11 on section, 5 on repeat |

## Inputs

`reports/review_packs/phase1/phase1_set1_tool_inputs.zip`, built by
`scripts/build_phase1.py`: the 85 set-1 ECGs as WFDB (12 leads, 500 Hz, mV) and GRIASCII
v1.5 with the adult Uni-G header, plus `inputs.csv` (codes, file hashes,
`bench_version = phase1-set1-1.0`). The same index is committed as `bench/phase1/inputs.csv`.
Five set-1 records carry a digital-missing channel (`missing_channels` column): WFDB stores
NaN, which `ecg_io` reads as zeros, and GRIASCII carries zeros, so both programs receive
the same dead channel. Programs return the common prediction schema with
`bench_version = phase1-set1-1.0`.

## Caveats, declared in the report

- Set 1 was used to design this comparison (the set-1 synthesis), and its answers and
  key are known to the coordinator, who develops signalguard. From now on signalguard is
  **not tuned on set 1**; its version is frozen and recorded in `dev-log` before it runs on
  Phase 1. Results are reported per reader and against the confirmed reference.
- Set-1 PDFs were shown with diagnostic filtering; the programs receive the raw signals.
- Peter co-developed Uni-G; per-reader results are reported alongside the confirmed reference.

## Commands

```sh
MPLCONFIGDIR=/tmp/artefaux-matplotlib .venv/bin/python scripts/reports/synthesise_review.py --set 1
MPLCONFIGDIR=/tmp/artefaux-matplotlib .venv/bin/python scripts/build_phase1.py [--coding-verified]
# run both programs on tool_inputs/inputs.csv (each refuses uncommitted package changes):
#   signalguard repo:  scripts/run_artefaux_phase.py --inputs <inputs.csv> --out out/phase1/predictions/signalguard
#   unigue repo:       tools/scripts/run_artefaux_phase.py --inputs <inputs.csv> --out out/phase1/predictions/unig
.venv/bin/python scripts/reports/phase_report.py [--coding-verified]   # -> out/phase1/report/
```

## Runs

Both programs ran by script on the 85 records with versions frozen beforehand in dev-log
(ADR 0018 amendment 1): signalguard v0.2.0 (package tree identical to the tag),
`GateMode.FULL_12_LEAD`; Uni-G 30.4.3-wizofe, `-noisecheck`. Neither failed on any record.
Five records Uni-G judged unanalysable (exit 100/103 with statement 13/3) are repeat-ECG
decisions under the mapping in `BENCHMARK.md`. The scored tables are private
(`out/phase1/report/results.md`); every row reports its denominator.
