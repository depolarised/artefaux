<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Calibration corpus `calib-v1`

Fresh data for fitting and selecting quality-gate thresholds, so that no threshold is fitted on
the reviewed ECGs (dev-log ADR-0018 amendment 2). Signals, labels and source lists stay private
under `out/calib-v1/`. This document holds design and aggregates only.

Definition: `src/artefaux/calib.py`. Generator and integrity check:
`scripts/generate_calib_corpus.py`. The definition needs no data, so the label file can be
recomputed anywhere.

## Freeze

`labels.csv` sha256: `45451cc66d41311c84208019369c150996413854cd8c323d193a9010fef2eeca`

Frozen 2026-11-04, before any quality gate ran on the corpus. `tests/test_calib.py` recomputes this
hash from the definition, so a changed label, cell, split or record fails the suite. The corpus's
identity is `checksums.csv` (sha256 of every stored record file), sha256
`db07d86d0e1f7e26162d8aee9769e6f1766c73c0e0d58d92e5a8ef9357a01405`; two independent generations
gave identical files, and `--verify` refuses any other manifest (the digest is pinned in the
generator). Labels depend only on recipes: artefaux does not import any gate
(`tests/test_calib.py`), and no gate output enters this repository's generator.

```sh
python scripts/generate_calib_corpus.py --set2-sources <set-2 source_ids.csv> \
    --nstdb-dir <nstdb> --out out/calib-v1           # refuses a non-empty directory
python scripts/generate_calib_corpus.py --set2-sources <set-2 source_ids.csv> \
    --out out/calib-v1 --verify                      # labels, parents, split, patients, checksums
python scripts/build_curator_table.py --set2-sources <set-2 source_ids.csv> --out out/calib-v1
```

`verification.json` and `provenance.json` record the generating commit `fb69c69` and its generator
hash. That commit was squashed, with the review fixes that followed it, into this branch's single
corpus commit before publication, so the hash no longer resolves. The squashed fixes changed only the
generator's `--verify` path, not `generate` or the definition.

Files in `out/calib-v1/`: `records/` (WFDB, 500 Hz, 10 s, 12 leads, 1 uV), `labels/` (truth log per
record), `labels.csv`, `records.csv` (split, cell, parent, patient, classes), `recipes.json`,
`manifest.{json,csv}`, `provenance.json`, `checksums.csv`, `verification.json`,
`ptbxl_curator_leads.csv`, `ptbxl_curator_summary.json`.

## Seeds

| Seed | Value | Drives |
|---|---:|---|
| `MASTER_SEED` | 20261104 | Per-record RNG (`SeedSequence(entropy, spawn_key=(5000 + index,))`) |
| `SELECTION_SEED` | 20261105 | Parent selection and dealing |
| `OFFSET_SEED` | 20261106 | NSTDB slots and jitter |

Set 1 used 20260713, set 2 uses 20261002, so none repeats. T1's seeds are secret and were not read.

## Patients

- Parents: PTB-XL 1.0.3, adults, one ECG per patient, one record per patient. Each patient therefore
  sits in exactly one split.
- Excluded: the 170 patients of review sets 1 and 2. Set 1 comes from the committed
  `recipes/source_ids/`; set 2 from `out/artefaux-review-set2/source_ids.csv`, of which only
  `patient_id` is used. `verification.json` records zero overlap.
- **T1 patients were not excluded.** T1's only source list also holds strata, diagnoses and quality
  flags, so it is not a file of identifiers alone and it was not read. T1 was withdrawn unseen. By
  chance about 3 of the 491 parents may be T1 patients (491 x 120 of about 18 900 patients). Any
  later replication on T1 must remove them first.
- Clean parents carry no curator flag and keep PTB-XL's natural mix of rhythms. Across all 491 parents:
  30 AFIB, 24 PVC, 6 PACE, 4 BIGU, 4 LVOLT, 1 AFLT, 0 TRIGU. A beat-template metric meets real beat
  variation during fitting; the clinical non-regression (curator table below) tests it per class.
- Naturally poor parents carry exactly one curator flag: 12 burst noise, 8 electrode problems, 10
  baseline drift, 10 static noise.

## Noise

| | Channel | Start sample at 500 Hz (segment 5000 samples) | Source |
|---|---|---|---|
| Set 1 | 0 | `rng.integers(0, 100_000)` | `corpus.py`, `recipes.py` |
| Set 2 | 0 and 1 (`i % 2`) | `rng.integers(0, 100_000)` | `review.py`, `recipes.py` |
| T1 | 0 and 1 | Slots of 5500 from 120 000 to 897 278, one pool per NSTDB record | `benchmark.py` |
| `calib-v1` calib | 1 | 300 000 to 660 000 | `calib.py` |
| `calib-v1` holdout | 1 | 660 000 to 902 778 | `calib.py` |

- **No overlap with sets 1 and 2**, whose segments end before sample 105 000 on either channel. The
  two channels of a record are simultaneous, so the offset is what separates them, not the channel.
- **T1 can overlap.** From the code alone: T1 draws 32 `em`, 22 `ma` and 22 `bw` slots from 142 per
  record, across both channels, from a secret seed. About 77% of its slots lie at or above 300 000, so
  some T1 segments are expected to cover the same seconds of NSTDB as `calib-v1` on channel 1, or
  the simultaneous channel 0. No T1 offset was read, and only [105 000, 120 000) would be free of
  both, which is far too short. T1 was withdrawn; a replication would need fresh offsets.
- **Holdout noise is unseen:** the two split regions are disjoint.
- **Independent segments.** Each noised displayed lead has its own segment, at least 5000 samples from
  every other in the record. Nothing here relies on inter-lead noise being identical, which is a
  set-1 generation artefact. 1440 segments use 1431 distinct offsets, but they overlap in time across
  records: NSTDB gives the splits 65 and 44 slots of 10 s per noise type for 288 and 192 segments,
  so a stretch of noise recurs about 4.4 times per split, on other parents at other scales.
- **Chance correlation remains:** two independent 10 s segments of slow drift can correlate strongly
  (largest pairwise |r| of the added noise per record: median 0.66, maximum 0.99). `verify_record`
  refuses only a shared segment.

### Noise power by band, median per 10 s (basis of the SNR)

| Noise, channel, region | < 0.5 Hz | 0.5-15 Hz | 15-40 Hz | > 40 Hz |
|---|---:|---:|---:|---:|
| `em`, ch 0, below 100 000 (set 1) | 0.67 | 0.32 | 0.01 | 0.00 |
| `em`, ch 1, from 300 000 (`calib-v1`) | 0.77 | 0.21 | 0.01 | 0.00 |
| `ma`, ch 0, below 100 000 (set 1) | 0.67 | 0.15 | 0.13 | 0.03 |
| `ma`, ch 1, from 300 000 (`calib-v1`) | 0.65 | 0.10 | 0.18 | 0.06 |
| `bw`, ch 0, below 100 000 (set 1) | 0.97 | 0.03 | 0.00 | 0.00 |
| `bw`, ch 1, from 300 000 (`calib-v1`) | 0.97 | 0.03 | 0.00 | 0.00 |

**This shifts the `em` boundary.** At one nominal SNR, `calib-v1` `em` has about 1.9 dB less power at
0.5-15 Hz than set-1 `em`, so `em` at 0 dB here is close in band to set-1 `em` at +2 dB, which both
readers kept. The Amendment 2 table is binding and still labels 0 dB unusable. Results at
`noise/em/*/+0` must be reported separately, since this cell may overstate what readers would reject.

## Signal consistency

Checked on every stored record at generation (`verify_record`, WFDB readback):

- Every sample outside the truth log's lead and time mask equals the parent.
- NSTDB noise is mixed on acquisition channels. A change to I or II reaches III, aVR, aVL and aVF
  (Einthoven, Goldberger). Largest stored SNR error 0.02 dB (limit 0.5 dB).
- Limb-electrode faults go through the electrode model, so V1-V6 carry -1/3 of the electrode's
  artefact through the Wilson central terminal; checked sample by sample. Motion RMS is within 0.01%
  of the request.
- **Limitation:** lead-scope noise does not pass through the Wilson terminal. Noise on I and II leaves
  V1-V6 bit-identical, as set-1 `ma` did and as the readers saw it. Only the electrode families model
  how limb artefact reaches the chest leads, and they use synthetic motion (0.5-12 Hz), labelled so.

## Labels

Binding table (ADR-0018 amendment 2), by lead:

| Fault on that lead | Unusable | Grey, not scored | Usable |
|---|---|---|---|
| NSTDB `em` | ≤ 0 dB | – | ≥ +3 dB |
| NSTDB `ma` | – | ≤ −6 dB | ≥ −3 dB |
| NSTDB `bw` | ≤ −9 dB | −6 dB | ≥ −3 dB |
| Limb-electrode motion (leads carrying it) | ≥ 1.0 mV RMS | 0.5 mV RMS | – |
| Coupled precordial noise | 0 dB | +6 dB | – |
| Lead off, compound faults | all | – | – |
| Untouched lead, DC electrode offset, clean, naturally poor | – | – | all |

`labels.csv` has 13 rows per record: `record_id, split, family, cell, reader_evidence, item, label,
rule`. `item` is a lead or `repeat`. Lead labels are `unusable`, `usable`, `grey` or `not_displayed`.
Readers saw I, II and V1-V6 only, so III, aVR, aVL and aVF are `not_displayed` and not scored. Scoring
uses `unusable` and `usable` only.

These labels are extrapolated from reader behaviour on set 1. They are neither recipe truth nor a
reference standard. Only Phase 2 tests a gate against readers on unseen ECGs.

## Repeat rule

**Repeat if at least 7 of the 8 displayed leads (I, II, V1-V6) are unusable.** This is the proposed
rule for the gate's record policy (WP3), and it gives the record-level label here.

`repeat_label` adds the grey region: `repeat` needs at least 7 unusable leads whatever the grey leads
turn out to be; `keep` needs unusable + grey ≤ 5; anything else is `grey`, not scored.

What the 10 confirmed repeats of set 1 share:

| Group | Records | Displayed leads carrying a fault |
|---|---:|---|
| `em` on all leads, ≤ 0 dB | 6 | 8 |
| One limb electrode in motion, ≥ 1.0 mV | 2 | 7 (the untouched limb lead stays clean) |
| Limb-electrode motion plus other faults | 2 | 8 and 7 |

Compound faults alone do not predict a repeat (two compound records with 3 and 4 faulted leads were
kept by both readers), nor does a noisy limb pair (one such record is disputed, every `ma` record was
kept). Per-record detail stays in the private failure atlas, section 9
(`out/phase1/report/failure_atlas.md`; the scripts that built it are in `out/phase1/report/src/`). This
repository is public and the set-1 key is private.

In-sample on the 80 confirmed repeat decisions of set 1, with lead counts from the label table applied
to the set-1 recipes. CIs are Wilson 95%. **This is design-informed and optimistic: the table was
extrapolated from the same readers.**

**Assumption in these counts.** Set 1 also holds single faults the Amendment 2 table does not name
(flatline, swing, overload, constant ADC, digital missing, intermittent lead-off, opposite polarity,
step recovery, and precordial noise at −6 dB). They are counted as unusable on the leads carrying them.
The rows ≥ 5 to ≥ 8 give the same counts on confirmed records without this assumption. The ≥ 3 row does
not: counting only faults the table names gives FP 5, TN 65, specificity 0.93. Three of the five
disputed records reach their lead counts (6, 3 and 2) only through the assumption.

| Rule | TP | FN | FP | TN | Sensitivity (95% CI) | Specificity (95% CI) |
|---|---:|---:|---:|---:|---|---|
| ≥ 8 of 8 | 7 | 3 | 1 | 69 | 0.70 (0.40-0.89) | 0.99 (0.92-1.00) |
| **≥ 7 of 8** | **10** | **0** | **1** | **69** | **1.00 (0.72-1.00)** | **0.99 (0.92-1.00)** |
| ≥ 6 of 8 | 10 | 0 | 1 | 69 | 1.00 (0.72-1.00) | 0.99 (0.92-1.00) |
| ≥ 5 of 8 | 10 | 0 | 1 | 69 | 1.00 (0.72-1.00) | 0.99 (0.92-1.00) |
| ≥ 3 of 8 | 10 | 0 | 8 | 62 | 1.00 (0.72-1.00) | 0.89 (0.79-0.94) |
| I and II both unusable | 7 | 3 | 1 | 69 | 0.70 (0.40-0.89) | 0.99 (0.92-1.00) |
| Any compound fault | 2 | 8 | 5 | 65 | 0.20 (0.06-0.51) | 0.93 (0.84-0.97) |

The false repeat is one record of `em` at −2 dB on all leads, which both readers kept. Thresholds 5, 6
and 7 tie on confirmed decisions, so those do not identify the threshold. Seven rests on individual
reader answers: no reader kept a record with 7 or 8 leads unusable, whereas the four answers keeping a
record at exactly 6 all come from one reader marking V1-V6 (on three of those records the other reader
repeated, on the fourth he kept all leads). Hence 6 is grey here. On frozen v0.2.0 lead labels the same
rule catches 0 of 10, so it depends on better per-lead evidence.

## Split

By patient. Replicates 0-2 of every five go to `calib` (fit), replicates 3-4 to `holdout` (select), so
every cell reaches both splits. Selection rule (ADR-0018 amendment 2): maximise lead sensitivity subject to
lead specificity ≥ 0.93 on `calib`, confirm on `holdout`; secondary, repeat sensitivity ≥ 0.6 at repeat
specificity ≥ 0.95.

## Counts per cell

"Faulted leads" is the label of the leads each cell faults; all other displayed leads are `usable`.
Reader evidence: `direct` means set 1 showed this fault at this level to the readers; `extrapolated`
means the same kind of fault at another level or shape; `none` means set 1 never showed it.

| Family | Records | calib | holdout |
|---|---|---|---|
| noise | 270 | 162 | 108 |
| electrode_motion | 45 | 27 | 18 |
| electrode_dc | 12 | 9 | 3 |
| lead_off | 24 | 18 | 6 |
| coupled | 20 | 12 | 8 |
| compound | 20 | 15 | 5 |
| natural | 40 | 26 | 14 |
| clean | 60 | 36 | 24 |
| total | 491 | 305 | 186 |

| Cell | Faulted leads | Repeat | calib | holdout | Reader evidence |
|---|---|---|---|---|---|
| noise/em/limb/-9 | unusable | keep | 3 | 2 | none |
| noise/em/limb/-6 | unusable | keep | 3 | 2 | none |
| noise/em/limb/-3 | unusable | keep | 3 | 2 | none |
| noise/em/limb/+0 | unusable | keep | 3 | 2 | none |
| noise/em/limb/+3 | usable | keep | 3 | 2 | none |
| noise/em/limb/+6 | usable | keep | 3 | 2 | none |
| noise/em/chest/-9 | unusable | grey | 3 | 2 | none |
| noise/em/chest/-6 | unusable | grey | 3 | 2 | none |
| noise/em/chest/-3 | unusable | grey | 3 | 2 | none |
| noise/em/chest/+0 | unusable | grey | 3 | 2 | none |
| noise/em/chest/+3 | usable | keep | 3 | 2 | none |
| noise/em/chest/+6 | usable | keep | 3 | 2 | none |
| noise/em/all/-9 | unusable | repeat | 3 | 2 | extrapolated |
| noise/em/all/-6 | unusable | repeat | 3 | 2 | direct |
| noise/em/all/-3 | unusable | repeat | 3 | 2 | direct |
| noise/em/all/+0 | unusable | repeat | 3 | 2 | direct |
| noise/em/all/+3 | usable | keep | 3 | 2 | extrapolated |
| noise/em/all/+6 | usable | keep | 3 | 2 | extrapolated |
| noise/ma/limb/-9 | grey | keep | 3 | 2 | extrapolated |
| noise/ma/limb/-6 | grey | keep | 3 | 2 | direct |
| noise/ma/limb/-3 | usable | keep | 3 | 2 | direct |
| noise/ma/limb/+0 | usable | keep | 3 | 2 | direct |
| noise/ma/limb/+3 | usable | keep | 3 | 2 | extrapolated |
| noise/ma/limb/+6 | usable | keep | 3 | 2 | extrapolated |
| noise/ma/chest/-9 | grey | grey | 3 | 2 | none |
| noise/ma/chest/-6 | grey | grey | 3 | 2 | none |
| noise/ma/chest/-3 | usable | keep | 3 | 2 | none |
| noise/ma/chest/+0 | usable | keep | 3 | 2 | none |
| noise/ma/chest/+3 | usable | keep | 3 | 2 | none |
| noise/ma/chest/+6 | usable | keep | 3 | 2 | none |
| noise/ma/all/-9 | grey | grey | 3 | 2 | none |
| noise/ma/all/-6 | grey | grey | 3 | 2 | none |
| noise/ma/all/-3 | usable | keep | 3 | 2 | none |
| noise/ma/all/+0 | usable | keep | 3 | 2 | none |
| noise/ma/all/+3 | usable | keep | 3 | 2 | none |
| noise/ma/all/+6 | usable | keep | 3 | 2 | none |
| noise/bw/limb/-9 | unusable | keep | 3 | 2 | none |
| noise/bw/limb/-6 | grey | keep | 3 | 2 | none |
| noise/bw/limb/-3 | usable | keep | 3 | 2 | none |
| noise/bw/limb/+0 | usable | keep | 3 | 2 | none |
| noise/bw/limb/+3 | usable | keep | 3 | 2 | none |
| noise/bw/limb/+6 | usable | keep | 3 | 2 | none |
| noise/bw/chest/-9 | unusable | grey | 3 | 2 | extrapolated |
| noise/bw/chest/-6 | grey | grey | 3 | 2 | direct |
| noise/bw/chest/-3 | usable | keep | 3 | 2 | direct |
| noise/bw/chest/+0 | usable | keep | 3 | 2 | direct |
| noise/bw/chest/+3 | usable | keep | 3 | 2 | extrapolated |
| noise/bw/chest/+6 | usable | keep | 3 | 2 | extrapolated |
| noise/bw/all/-9 | unusable | repeat | 3 | 2 | none |
| noise/bw/all/-6 | grey | grey | 3 | 2 | none |
| noise/bw/all/-3 | usable | keep | 3 | 2 | none |
| noise/bw/all/+0 | usable | keep | 3 | 2 | none |
| noise/bw/all/+3 | usable | keep | 3 | 2 | none |
| noise/bw/all/+6 | usable | keep | 3 | 2 | none |
| electrode_motion/RA/0.5 | grey | grey | 3 | 2 | none |
| electrode_motion/RA/1.0 | unusable | repeat | 3 | 2 | none |
| electrode_motion/RA/2.0 | unusable | repeat | 3 | 2 | none |
| electrode_motion/LA/0.5 | grey | grey | 3 | 2 | none |
| electrode_motion/LA/1.0 | unusable | repeat | 3 | 2 | direct |
| electrode_motion/LA/2.0 | unusable | repeat | 3 | 2 | extrapolated |
| electrode_motion/LL/0.5 | grey | grey | 3 | 2 | none |
| electrode_motion/LL/1.0 | unusable | repeat | 3 | 2 | direct |
| electrode_motion/LL/2.0 | unusable | repeat | 3 | 2 | extrapolated |
| electrode_dc/RA/4.0 | usable | keep | 3 | 1 | direct |
| electrode_dc/LA/4.0 | usable | keep | 3 | 1 | direct |
| electrode_dc/LL/4.0 | usable | keep | 3 | 1 | direct |
| lead_off/I | unusable | keep | 3 | 1 | extrapolated |
| lead_off/II | unusable | keep | 3 | 1 | extrapolated |
| lead_off/V2 | unusable | keep | 3 | 1 | direct |
| lead_off/V5 | unusable | keep | 3 | 1 | direct |
| lead_off/V1+V2 | unusable | keep | 3 | 1 | direct |
| lead_off/V4+V5+V6 | unusable | keep | 3 | 1 | direct |
| coupled/V1+V2/+0 | unusable | keep | 3 | 2 | direct |
| coupled/V1+V2/+6 | grey | keep | 3 | 2 | extrapolated |
| coupled/V4+V5/+0 | unusable | keep | 3 | 2 | extrapolated |
| coupled/V4+V5/+6 | grey | keep | 3 | 2 | direct |
| compound/A | unusable | repeat | 3 | 1 | extrapolated |
| compound/B | unusable | repeat | 3 | 1 | extrapolated |
| compound/C | unusable | keep | 3 | 1 | extrapolated |
| compound/D | unusable | keep | 3 | 1 | extrapolated |
| compound/E | unusable | repeat | 3 | 1 | none |
| natural/electrodes_problems | usable | keep | 6 | 2 | direct |
| natural/burst_noise | usable | keep | 8 | 4 | direct |
| natural/baseline_drift | usable | keep | 6 | 4 | direct |
| natural/static_noise | usable | keep | 6 | 4 | direct |
| clean | usable | keep | 36 | 24 | extrapolated |

Lead units on the displayed leads: `calib` 1717 usable, 501 unusable, 222 grey; `holdout` 1045 usable,
295 unusable, 148 grey. Repeat labels: `calib` 42 repeat, 221 keep, 42 grey; `holdout` 25 repeat, 133
keep, 28 grey.

## Cells with no reader evidence

Set 1 locked noise type to lead scope, so 209 of 491 records have no reader evidence and must be
reported separately from the rest (ADR-0018 amendment 2):

- NSTDB noise off the set-1 pairing: `em` on limb or chest, `ma` on chest or all, `bw` on limb or all
  (36 cells, 180 records).
- Limb-electrode motion at 0.5 mV on any electrode, and on RA at any amplitude (5 cells, 25 records).
- Compound case E: RA motion with other faults (4 records).

`extrapolated` cells (149 records) lie outside the set-1 SNR range of −6 to +2 dB, or change a set-1
fault's level or shape. All `clean` records are in this group, since set 1 showed readers untouched leads
but no untouched record.

## PTB-XL curator table

`out/calib-v1/ptbxl_curator_leads.csv`: one row per record and lead, sha256
`cd67dd638dea416a2963046828ca469bc10130254bfec58516e8547a5f1833e7`. It parses `static_noise`,
`burst_noise`, `baseline_drift` and `electrodes_problems` (`artefaux.ptbxl_curator`). Of 21 799 records,
the table leaves out 206 of patients in sets 1 and 2 and a further 584 of the 491 corpus parents'
patients, since a gate fitted on those patients must not be checked on them. T1 patients are not
excluded.

- Each column per lead is `flagged`, `clean` or `unknown`. `lead_state`: `noisy` if any column flags the
  lead, else `unknown` if any column is unknown, else `clean`. `record_clean` needs all twelve clean.
- Readable: `I-AVF`, `alles`, `v5,6`, `V3,V4-V6`, `I - AVR`, `avl-iii`.
- **Unknown for all 12 leads, never clean:** any token not understood (`V1???`, `I-ALF`, `V&`, `3ES`,
  `pace`), and a flag with no lead (`leicht`, `noisy recording`). Typos are not guessed.
- `scp_classes`: NORM, AFIB, AFLT, PVC, BIGU, TRIGU, PACE, LVOLT by presence of the code, since PTB-XL
  form statements such as LVOLT carry likelihood 0.

| Column | Flagged records | Of which unknown |
|---|---:|---:|
| `static_noise` | 3218 | 202 |
| `burst_noise` | 593 | 5 |
| `baseline_drift` | 1572 | 21 |
| `electrodes_problems` | 21 | 4 |

Lead units: 223 745 clean, 25 658 noisy, 2705 unknown. Records: 21 009, of which 16 091 curator-clean.

| Class | Records | Curator-clean records |
|---|---:|---:|
| NORM | 9156 | 7150 |
| AFIB | 1453 | 1033 |
| AFLT | 71 | 51 |
| PVC | 1106 | 849 |
| BIGU | 75 | 68 |
| TRIGU | 18 | 14 |
| PACE | 284 | 226 |
| LVOLT | 174 | 155 |

TRIGU, AFLT and BIGU are small: any per-class rate needs its confidence interval. A patient can have
several records here, so intervals must cluster by patient. Curators flagged by lead and by eye, so
"clean" means not flagged. MACECGDB stays available locally
as a real-motion sanity set; it has no labels here.

## Other limitations

- Five replicates per noise cell: a per-cell rate is coarse, so CIs must accompany it.
- Coupled precordial noise and electrode motion are synthetic; set 1 also used synthetic shapes there.
- Naturally poor records are labelled usable by the table, although a curator flagged each one. Set 1
  supports this on average, not record by record (both readers cut half of one such record).
- The label table itself is untested: it extrapolates two readers on 85 records.
