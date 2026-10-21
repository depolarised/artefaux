<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Statistical analysis plan — `artefaux-bench` v1, block T1

Pre-registered: this plan is committed and tagged (`bench-v1.0.0`) before any program
is run on T1 or any reader sheet is returned. Deviations are recorded with a date and
reason in `CHANGELOG.md`. Implementation: `src/artefaux/bench_scoring.py` and
`src/artefaux/scoring.py`. Reporting follows STARD 2015 (flow diagram and checklist).

## Question

How well do signalguard and Uni-G identify (a) leads that experts would exclude and
(b) ECGs that experts would repeat, on a blinded set of 10 s 12-lead ECGs with
controlled real noise, data-integrity faults, confounders and natural recordings?

## Reference standard

- Two readers (PWM, DTC), independent and blinded. Each record yields, per reader,
  `unusable_leads` (subset of I, II, V1–V6), `usable_section`, `overall`
  (analysable / partial / rhythm only / not analysable) and `not_noise` flags.
- `repeat_ecg` = overall is rhythm only or not analysable. A repeat makes every
  displayed lead unusable for the per-lead endpoint.
- Consensus: where readers agree on repeat-ECG and, if neither repeats, on both the exact
  unusable-lead set and the usable section, that is the reference (where only the grade
  differs, the more severe grade is kept). Any other disagreement needs the jointly
  adjudicated record. No default section (such as `full`) is substituted for a value
  the readers did not agree on.
- Secondary reference: recipe truth (which leads were changed, at what SNR).

## Units and endpoints

| | Endpoint | Unit | Estimate |
|---|---|---|---|
| **P1** | Lead unusable | record × lead, 960 = 120 × 8 | sensitivity, specificity (record-clustered bootstrap 95% CI, 2000 resamples, seed 20261021); PPV, NPV, F1 |
| **P2** | Repeat ECG | record, 120 | sensitivity, specificity, PPV, NPV (Wilson 95% CI) |
| P1Δ, P2Δ | signalguard − Uni-G | paired | P1: cluster-bootstrap CI of the sensitivity and specificity differences; P2: exact McNemar p and Newcombe paired CI |

Expected reference prevalence (from the design): about 25–30% unusable leads and 15–25
repeat-ECG records. T1 alone estimates P1 sensitivity to about ±0.07; P2 is
descriptive in T1 and powered only on pooled T1+T2. No hypothesis test is used to
claim superiority on T1 alone; differences are reported with CIs.

## Secondary analyses

1. Graded quality: 4×4 confusion matrix and linear-weighted κ against the reference
   (signalguard only; Uni-G does not emit a grade). Benchmark for "human-level":
   the PWM–DTC weighted κ and its bootstrap CI.
2. Lead-set agreement where neither source repeats: exact match and mean Jaccard.
3. Usable section in the `half_noise` stratum: proportion choosing the clean half
   (signalguard and readers; Uni-G does not output it).
4. Dose–response in `full_noise`: logistic regression of lead unusable on measured SNR
   by noise type and scope; SNR50 with bootstrap CI, for each program and each reader.
   If a cell is separated (every unit unusable at or below some SNR and usable at or
   above a higher one, ties at one level allowed), the maximum-likelihood SNR50 does not
   exist. Such a cell reports no point estimate and no bootstrap CI; it reports the
   interval-censored bounds instead: the highest SNR with all units unusable and the
   lowest with all units usable, which bracket the 50% crossing. An open side is shown
   as not bounded. A separated cell that does not fall with SNR is reported as not
   estimable.
5. Integrity faults: detection rate per fault type against recipe truth.
6. False alarms: any lead unusable or repeat-ECG in `clean` and `confounder` strata,
   by confounder type; lead-reversal recognition reported separately.
7. Agreement with recipe truth (changed lead vs flagged), by stratum.
8. Reader reliability: PWM–DTC κ and PABAK for every item; adjudication rate.
9. Operational: failures, runtime per record.

All tables are stratified by stratum, noise type, scope, SNR and lead.

## Pre-specified sensitivity analyses

- Each reader alone as the reference (Derek alone addresses Peter's Uni-G conflict of
  interest; Peter alone addresses the coordinator's signalguard conflict).
- P1 restricted to V1–V6 (Uni-G's I/II noise decisions are only partly in its output).
- signalguard `borderline` counted as unusable.
- Failures excluded instead of counted as discordant (`itd=False`). A record on which
  the program failed is removed from that program's lead-level and record-level
  denominators, so it is neither a positive nor a negative prediction. The record stays
  in the reference and in the other program's analysis. The paired comparisons (P1Δ,
  P2Δ) are intention-to-diagnose only in this version.

## Missing data and failures

Intention-to-diagnose (primary): a record on which a program fails (non-empty `error`)
is scored as discordant with the reference for every unit of that record. Unreadable
reader cells are returned to the reader; the analysis waits until every cell is valid.
No record is excluded after unblinding.

## Blinding and trust model

- **Reader blinding is sound.** Readers receive only the blinded PDF, the coding sheet
  and its README. They see no signals, recipe truth, program output or each other's
  sheet until both are frozen.
- **Tool blinding is procedural, not cryptographic.** Records and leads that the recipe
  does not change equal their public PTB-XL parents sample for sample (in the 500 Hz,
  mV representation of the tool inputs). Anyone holding a copy of PTB-XL can hash-match
  such a record or lead, which identifies the clean parents and, through PTB-XL
  metadata, the parent's diagnosis. A developer of either tool can therefore recognise
  some inputs, and tuning on the public parents cannot be excluded by design.
- **Mitigations:**
  1. The signalguard version is tagged before T1 is generated, and the tag is in the
     commitment.
  2. Both tools run by script, with no manual step; command lines and run manifests are
     fixed before the run.
  3. Prediction hashes (SHA-256 of each program's `predictions_records.csv` and
     `predictions_leads.csv`) are committed to `dev-log` before unblinding.
  4. Uni-G is preferably run by the Glasgow side, and signalguard by someone other than
     its developer, or by CI on the tagged version.
- **Declared in the report:** the residual risk above (a developer-run tool may have seen
  public parents) is stated in the T1 report and is not claimed to be excluded.

## Fixed mappings

## Fixed mappings

The native-to-common mappings in `BENCHMARK.md` are frozen with this plan. Program
settings: signalguard `GateMode.FULL_12_LEAD`, default thresholds of the tagged version;
Uni-G `GriAnlys -noisecheck` with the header in `UNIG_HEADER_LINES`, no other options.
