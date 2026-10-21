<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Artefaux noise benchmark (`artefaux-bench` v1, block T1)

A blinded, held-out test set for comparing ECG quality gates — **signalguard** and the
**Glasgow program's (Uni-G) noise handling** — against an adjudicated expert reference.
The analysis is pre-registered in [`BENCHMARK_SAP.md`](BENCHMARK_SAP.md).

| Role | Data | Used for |
|---|---|---|
| Development | Review set 1 (the 85 v2 records) and review set 2 (85 records) | Tuning, calibration, synthesis |
| Test | Block **T1**, 120 records (this document) | Scoring only, once, after freeze |
| Replication | Block **T2** (future, same specification, new seed, disjoint patients) | Pooled T1+T2 analysis |

No tool may be tuned on T1. Development sets keep their own blind codes (`REV-###`);
T1 uses `T1-001` … `T1-120`, so codes are unique across sets.

## Why this design (set-1 findings)

The set-1 synthesis (`scripts/reports/synthesise_review.py --set 1`, private output under
`out/review-synthesis/set1/`) coded both readers' free text into structured fields.
The coding is a draft until verified by the coordinator; the figures below are from it.

- Readers agree well on **repeat the ECG** (κ 0.77, PABAK 0.88) and on **which leads
  are unusable** (per-lead κ 0.77 over 680 lead judgements), but only moderately on the
  three-way decision (κ 0.41), because Peter often chose a usable half where Derek kept
  the whole record (18 vs 5 half-record choices). The primary endpoints are therefore
  per-lead unusability and repeat-ECG; the usable half is secondary.
- **The authored "expected" labels are not a valid reference**: of ten records authored
  `reject`, both readers repeated two. The reference standard is expert review; recipe
  truth is secondary (where noise is, not whether the ECG is usable).
- In set 1 each noise type was applied to one lead scope only (electrode motion → all
  12 leads, muscle → limb leads, baseline wander → chest leads), so noise type and scope
  were **confounded**. T1 crosses them fully.
- Decisions changed between −6 and +2 dB; all-lead electrode motion was repeated at
  ≤ −2 dB by both readers in five of six records. T1's common ladder spans −9 … +6 dB.
- Integrity faults (flat, lead-off, constant ADC) were omitted lead-by-lead; Peter
  noted they are "not a noise problem". Lead reversal was named "not noise" and
  something the program should detect. Both are separate strata in T1.
- Synthetic-looking artefacts (intermittent lead-off "extra beats", simulated amplifier
  limits) drew realism comments, so T1 drops them and fades noise edges inside a record.
- Derek often noted mild noise in I and II. High-frequency content (>40 Hz) of
  recipe-untouched leads matches the clean parents (I 8.9 vs 8.6 µV), so this is not
  added by generation; chest leads V2–V5 carry more high-frequency content than I/II.

## Composition of T1 (120 records, 120 distinct patients)

| Stratum | n | Content |
|---|---:|---|
| `clean` | 12 | Quality-clean PTB-XL parents, no corruption |
| `confounder` | 12 | 3 limb-electrode swaps (LA/RA, LA/LL, RA/LL); 3 AF; 2 paced; 2 low voltage (`LVOLT`); 2 high voltage (`VCLVH`) |
| `full_noise` | 54 | NSTDB em/ma/bw × scope {I+II, V1–V6, all 8 independent leads} × SNR {−9, −6, −3, 0, +3, +6} dB, full 10 s |
| `half_noise` | 12 | em/ma/bw × {first, second} 5 s × {all, chest} at −6 dB; the other half is bit-exact |
| `electrode_noise` | 8 | NSTDB em on electrode {RA, LA, LL, RA+LL} at {−6, 0} dB, through limb leads and WCT |
| `integrity` | 12 | flatline (I, V3), lead-off (II, V5, V1+V2, V4 second half, I first half), constant ADC (V1, V4, I+II), rail saturation (V2, I+II) |
| `natural` | 10 | PTB-XL quality-flagged: 3 burst noise, 3 electrode problems, 2 baseline drift, 2 static noise |

Generation rules (all in `src/artefaux/benchmark.py` and the recipe interpreter):

- **Patients**: none of the 170 development-set patients; one ECG per patient across T1.
- **Noise segments**: development sets drew NSTDB offsets below 100 000 samples (the
  first 200 s of each record). T1 uses only later, non-overlapping 11 s slots.
- **Physical consistency**: a change to I or II is carried into III/aVR/aVL/aVF
  (`propagate_derived`), so no record has III ≠ II − I as a free cue.
- **Edges**: noise starting or ending inside the record is median-centred and faded over
  0.25 s (`taper_s`), avoiding an instantaneous baseline step at the boundary.
- **No NaN**: GRIASCII cannot encode a missing sample, and signalling it out of band
  would hand Uni-G the answer, so digital-missing channels stay in v2 only.
- **Verification** at generation: every sample outside the truth-log lead/time mask is
  bit-identical to its parent; stored SNR within 0.5 dB of the request (WFDB readback);
  blinded WFDB and GRIASCII round trips; the GRIASCII header carries only the code and
  the adult analysis request below.

## Inputs (what each program receives)

`artefaux_bench_T1_tool_inputs.zip`, identical bytes for every program:

| File | Contents |
|---|---|
| `wfdb/T1-NNN.{hea,dat}` | 12 leads, 500 Hz, 5000 samples, mV, 16-bit, 1000 ADC/mV, canonical order |
| `griasc/T1-NNN.asc` | GRIASCII v1.5, 1000 LSB/mV, same samples |
| `inputs.csv` | `schema_version, bench_version, blind_code, wfdb_hea, wfdb_dat, asc, sha256_hea, sha256_dat, sha256_asc, fs, n_samples` |

**GRIASCII header for Uni-G** (`UNIG_HEADER_LINES`): age 18 262 days (adult thresholds),
`Adult` electrode positioning, 50 Hz mains filter, `QTcHodge`, `0 0` pacemaker line
(library detection on), `12Lead`. Line 10 is essential: left blank, Uni-G reads input
V1–V3 as paediatric V4R/V1/V2 (verified on dry-run files: a flat V3 was reported as V2).
**Review-set-2 and v2 GRIASCII exports have line 10 blank and age 0; any Uni-G output
on them is invalid.**

## Outputs (what each program and reader returns)

Every source — signalguard, Uni-G, each reader, the adjudicated reference — is mapped
to the same three items, so all comparisons are like for like.

`predictions_records.csv`

| Column | Values |
|---|---|
| `schema_version` | `1` |
| `bench_version` | `1.0.0` |
| `blind_code` | `T1-001` … |
| `source`, `source_version`, `source_commit` | e.g. `signalguard`, `0.4.0`, git SHA |
| `repeat_ecg` | `true` / `false` — record unusable for interpretation |
| `graded_quality` | `analysable` / `partial` / `rhythm_only` / `not_analysable` / `not_emitted` |
| `usable_section` | `full` / `first_half` / `second_half` / `none` / `not_emitted` |
| `native_codes` | the tool's own codes, `;`-separated (e.g. `reject;LEAD_I_BAD`, `2/68`) |
| `error` | empty, or the failure message (scored as a failure; see the SAP) |
| `runtime_ms` | wall time for the record |

`predictions_leads.csv`: `blind_code, source, lead, unusable, native_label, score` — one
row per displayed independent lead (I, II, V1–V6); `score` is optional (e.g. signalguard
`signal_quality_score`).

`run_manifest.json`: tool name, version, commit, exact command line, environment, and
the SHA-256 of `inputs.csv`. Validation: `artefaux.bench_scoring.load_predictions`.

### Native-to-common mappings (frozen before any run)

| Item | signalguard (`GateMode.FULL_12_LEAD`) | Uni-G (`GriAnlys -noisecheck`) |
|---|---|---|
| Lead unusable | label `bad` or in `rejected_leads` (`borderline` = usable; sensitivity analysis treats it as unusable) | `0` in the `-rhythm` availability line (input mask all `1`) |
| `repeat_ecg` | `record_quality == reject` | all eight leads unavailable, or statement 2/68 "Technically unsatisfactory tracing" |
| `graded_quality` | diagnostic→`analysable`, limited→`partial`, rhythm_only→`rhythm_only`, reject→`not_analysable` | `not_emitted` |
| `usable_section` | half chosen when every `bad_segment_intervals_s` interval lies in one half; else `full` | `not_emitted` (half flags are not written to any output) |

Uni-G limitation, to be reported: noise in I or II sets internal flags rather than
dropping the lead, so Uni-G's I/II decisions are only partly observable in its output.

## Reader protocol

- Readers: Peter (PWM) and Derek (DTC), independently, blinded to recipe truth, program
  outputs and each other. Peter co-developed Uni-G and the coordinator develops
  signalguard: results are reported per reader and with Derek alone as a sensitivity
  analysis.
- Material: `artefaux_bench_T1_blind_overflow.pdf` (strip8: I, II, V1–V6, full 10 s,
  25 mm/s, 10 mm/mV, raw signal, overflow on) and a plain XLS (one heading row):
  `Blind ECG code | <IN> Unusable leads | <IN> Usable section | <IN> Overall |
  <IN> Not noise | <IN> comments | Agreed handling`. Allowed values are in the README;
  `artefaux.review_coding.code_bench` parses them strictly and lists any invalid cell.
- Adjudication: the consensus rule in [Blinding, freeze and unblinding](#blinding-freeze-and-unblinding)
  (repeat-ECG; unusable-lead set and usable section where neither repeats). Disagreements
  are settled jointly and recorded per record; pre-adjudication answers are kept.

## Blinding, freeze and unblinding

1. Tag the signalguard version to be tested; generate T1 with
   `scripts/generate_benchmark.py` (seeds come from `secrets`; they and the blind key
   stay in `out/artefaux-bench-v1/T1/`).
2. Commit `bench/v1/T1/{inputs.csv,commitment.json}` with this document and the SAP;
   tag `bench-v1.0.0`. The commitment holds SHA-256 of the private seeds and key.
3. Send reader ZIPs (PDF + sheet + README, no signals) and the tool-input ZIP.
4. Run each program by script on the tool-input ZIP, no manual step. Uni-G is run by the
   Glasgow side; signalguard is run by someone other than its developer, or by CI on the
   tagged version (see [Trust model](#trust-model)). Record the SHA-256 of every
   `predictions_*.csv` and `run_manifest.json` in `dev-log` before unblinding.
5. Consensus, per record: the readers agree on repeat-ECG and, where neither repeats, on
   the unusable-lead set and the usable section. Any other case goes to adjudication, and
   pre-adjudication answers are kept. After both reader sheets and all predictions are
   frozen: adjudicate, open the key, score (`artefaux.bench_scoring`), and publish the
   seeds and key so anyone can verify the commitment and regenerate T1 bit-exactly.

## Trust model

What is enforced by code, what rests on procedure, and what is declared in the report.

- **Reader blinding (enforced by design).** Readers receive only the PDF, their sheet and
  the README. The packager checks every handoff archive and fails the run if a member
  mentions `PRIVATE` or `label`. Codes come from a permutation drawn from the blind seed; the
  mapping stays in `PRIVATE_blind_key.csv`. Readers are asked not to discuss cases until
  both sheets are returned; that request is procedural.
- **Tool blinding (procedural, not cryptographic).** Programs receive the tool-input ZIP,
  which carries codes but no key. The coordinator generates the signals, so tool blinding
  rests on these steps:
  1. The signalguard version is tagged before T1 is generated, and the tag is recorded in
     the commitment.
  2. Both programs run by script, with no manual step, on the identical ZIP.
  3. Prediction hashes are committed to `dev-log` before unblinding, so outputs cannot be
     changed after the key is opened.
  4. Uni-G is run by the Glasgow side. signalguard is run by someone other than its
     developer, or by CI on the tagged version. A coordinator-run signalguard is the
     weakest link and is declared as such if it occurs.
- **Commitment (commit-reveal).** `bench/v1/T1/commitment.json` holds SHA-256 hashes of the
  private seeds, blind key and definition files, so the mapping cannot change after
  freeze. The seeds protect against casual recovery of the mapping, not against a party
  with the full PTB-XL mirror who hash-matches untouched leads (see
  `scripts/generate_benchmark.py`).
- **Declared in the report.** Who ran each program, tool versions and commits, prediction
  hashes, and any step that deviated from this section.

## Versioning

- `BENCH_ID = "artefaux-bench"`, `BENCH_VERSION` follows semantic versioning; every CSV
  and JSON carries `schema_version`.
- A tagged block is **immutable**. Any fix is a new version, never an in-place edit.
- T2 (same specification, new seed, patients disjoint from development sets and T1) is
  `bench-v1.1.0`; a change of specification is `2.0.0`.
- Record changes in `CHANGELOG.md`.

## Commands

```sh
# set-1 synthesis (private output under out/review-synthesis/set1/)
MPLCONFIGDIR=/tmp/artefaux-matplotlib .venv/bin/python scripts/reports/synthesise_review.py --set 1
# set 2, when returned
.venv/bin/python scripts/reports/synthesise_review.py --set 2 --pwm <file> --dtc <file>
# generate T1 (once; refuses to overwrite)
MPLCONFIGDIR=/tmp/artefaux-matplotlib .venv/bin/python scripts/generate_benchmark.py \
    --ptbxl-dir /data/physionet/ptb-xl-1.0.3
# re-render and re-package an existing block with its own seeds (no signal regeneration)
MPLCONFIGDIR=/tmp/artefaux-matplotlib .venv/bin/python scripts/generate_benchmark.py \
    --ptbxl-dir /data/physionet/ptb-xl-1.0.3 --resume-packaging
```

A dry run passes `--master-seed` and/or `--blind-seed` together with explicit `--out`,
`--share-dir` and `--public-dir` paths outside the real block, its handoffs and `bench/`.
