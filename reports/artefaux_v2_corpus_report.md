---
title: "ECG Noise and Lead-Failure Stress-Test Corpus (v2) — Generation Report and Full Record Roster"
date: "2026-07-16"
author: "Ioannis Valasakis"
affiliation: "Electrocardiography Group, University of Glasgow"
geometry: margin=2.5cm
fontsize: 11pt
colorlinks: true
header-includes:
  - \usepackage{booktabs}
  - \usepackage{longtable}
  - \usepackage{graphicx}
  - \usepackage{etoolbox}
  - \usepackage{fancyhdr}
  - \AtBeginEnvironment{longtable}{\small}
  - \pagestyle{fancy}
  - \fancyhf{}
  - \renewcommand{\headrulewidth}{0pt}
  - \fancyfoot[L]{\small Artefaux v2.0.0}
  - \fancyfoot[C]{\small\thepage}
  - \fancyfoot[R]{\small github.com/depolarised/artefaux}
---

# ECG Noise and Lead-Failure Stress-Test Corpus (v2)

**Ioannis Valasakis**

*Electrocardiography Group, University of Glasgow*

**Date:** 2026-07-16 · **Repository:** <https://github.com/depolarised/artefaux> (tag `v2.0.0`) ·
**Sources (every value below traces to these):** `recipes/corpus.yaml`, `recipes/source_ids/*.csv`,
`manifest.json` (all committed), regenerated in-memory from `artefaux.corpus` + `artefaux.recipes`
(`master_seed = 20260713`). Generator: `scripts/reports/generate_corpus_report.py`.

> **Scope.** This is a *stress-test set, not a clinically representative cohort.* It deliberately
> over-samples failure; do not use it to estimate real-world prevalence or deployment accuracy.

---

## 1. Objectives

This is a deterministic generator and reproducible corpus **definition** for stress-testing ECG
signal-quality gates (the internal `signalguard`) and noise detectors (`noiseguard`). It does **not**
redistribute derived signals: it ships code, recipes, labels, manifest, and provenance so a user
regenerates the corpus **bit-exactly** from their own open PhysioNet copies.

This report documents the generation algorithm and enumerates **all 85 stress records** with their
corruption truth and expected behaviour. Records resolve against a local PhysioNet mirror; the concrete
PTB-XL parent ids shown here are those in `recipes/source_ids/` (reproducible, seeded selection).

---

## 2. Corpus composition

| Group | n | Source | Corruption |
|:--|--:|:--|:--|
| Naturally poor | 15 | PTB-XL technical-validation quality flags | none (inherently noisy) |
| Real-noise pairs | 30 | clean PTB-XL + NSTDB `em`/`ma`/`bw` | SNR ladder {-6, -4, -2, +0, +2} dB |
| Engineering extremes | 40 | clean PTB-XL parents (+ MACECGDB motion) | single-lead (13) + multi-lead (27) |
| **Total** | **85** | | 22 labelled data-integrity failures |

Each record carries three label layers — **clinical parent** (authored rhythm class + PTB-XL quality flags; the Uni-G statement field is reserved and empty in v1),
**corruption truth** (electrodes/leads, requested + measured SNR, noise segment, seed, $\alpha$, amplitude
bookkeeping), and **expected behaviour** (per-lead and record-level, mapped to the `signalguard`
`QualityLabel` / `RecordQuality` and `noiseguard` discard vocabularies).

![Corpus composition — 85 stress records plus paired clean parents.](../figures/corpus_composition.png)

---

## 3. Sources and licensing

| Dataset | Role | Version | License |
|:--|:--|:--|:--|
| PTB-XL | clean + naturally-poor parents (500 Hz) | 1.0.3 | CC-BY-4.0 |
| PTB-XL+ | Uni-G/Glasgow layer — *cited and pinned, not consumed by v2* | 1.0.1 | CC-BY-4.0 |
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
$\alpha = \sqrt{P_x / (P_n \cdot 10^{s/10})}$, $y = x + \alpha\,n$, with $P_x$, $P_n$ the
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

All 85 records are listed below. **Expected quality** is the record-level `RecordQuality` a correctly-tuned
gate should assign; **Discard** is the expected `noiseguard` record-level decision; **Bad leads** is the
count of leads the label expects a detector to reject. PTB-XL parents are shown as record stems (the
`records500/NNNNN/` directory prefix is omitted).

### 5.1 Naturally poor (15)

Real PTB-XL records selected by technical-validation quality flags; no clean parent (inherently bad).

| Record | PTB-XL source | Quality flag(s) | Expected quality | Discard |
|:--|:--|:--|:--:|:--:|
| `nlf_​nat_​001` | `10646_hr` | electrodes_problems | **reject** | yes |
| `nlf_​nat_​002` | `10652_hr` | burst_noise | **limited** | — |
| `nlf_​nat_​003` | `11176_hr` | static_noise | **limited** | — |
| `nlf_​nat_​004` | `12587_hr` | static_noise | **limited** | — |
| `nlf_​nat_​005` | `13777_hr` | static_noise | **limited** | — |
| `nlf_​nat_​006` | `14197_hr` | static_noise | **limited** | — |
| `nlf_​nat_​007` | `16149_hr` | baseline_drift | **reject** | yes |
| `nlf_​nat_​008` | `16981_hr` | static_noise | **limited** | — |
| `nlf_​nat_​009` | `17281_hr` | static_noise | **limited** | — |
| `nlf_​nat_​010` | `17293_hr` | baseline_drift | **limited** | — |
| `nlf_​nat_​011` | `19487_hr` | static_noise | **limited** | — |
| `nlf_​nat_​012` | `20478_hr` | static_noise | **limited** | — |
| `nlf_​nat_​013` | `00359_hr` | static_noise | **reject** | yes |
| `nlf_​nat_​014` | `06320_hr` | baseline_drift | **limited** | — |
| `nlf_​nat_​015` | `06968_hr` | static_noise | **limited** | — |

### 5.2 Real-noise SNR-ladder pairs (30)

Clean PTB-XL parents mixed with NSTDB noise across the ladder {-6, -4, -2, +0, +2} dB. Each ships with its untouched
clean parent (`*_clean`).

| Record | Rhythm | PTB-XL parent | Noise @ SNR | Leads | Bad leads | Expected quality | Discard |
|:--|:--|:--|:--|:--:|--:|:--:|:--:|
| `nlf_​noise_​001` | sinus | `10236_hr` | `em` @ -6 dB | 12 | 12 | **reject** | yes |
| `nlf_​noise_​002` | afib | `10330_hr` | `ma` @ -4 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​003` | pac pvc | `11089_hr` | `bw` @ -2 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​004` | bbb conduction | `11662_hr` | `em` @ +0 dB | 12 | 0 | **limited** | yes |
| `nlf_​noise_​005` | st t | `12040_hr` | `ma` @ +2 dB | 6 | 0 | **limited** | — |
| `nlf_​noise_​006` | flutter svt | `12086_hr` | `bw` @ -6 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​007` | sinus | `12407_hr` | `em` @ -4 dB | 12 | 12 | **limited** | yes |
| `nlf_​noise_​008` | afib | `01306_hr` | `ma` @ -2 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​009` | pac pvc | `13114_hr` | `bw` @ +0 dB | 6 | 0 | **limited** | yes |
| `nlf_​noise_​010` | bbb conduction | `13332_hr` | `em` @ +2 dB | 12 | 0 | **limited** | — |
| `nlf_​noise_​011` | st t | `13611_hr` | `ma` @ -6 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​012` | flutter svt | `01364_hr` | `bw` @ -4 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​013` | sinus | `01382_hr` | `em` @ -2 dB | 12 | 12 | **limited** | yes |
| `nlf_​noise_​014` | afib | `14071_hr` | `ma` @ +0 dB | 6 | 0 | **limited** | yes |
| `nlf_​noise_​015` | pac pvc | `14211_hr` | `bw` @ +2 dB | 6 | 0 | **limited** | — |
| `nlf_​noise_​016` | bbb conduction | `14337_hr` | `em` @ -6 dB | 12 | 12 | **reject** | yes |
| `nlf_​noise_​017` | st t | `15473_hr` | `ma` @ -4 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​018` | flutter svt | `15535_hr` | `bw` @ -2 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​019` | sinus | `15873_hr` | `em` @ +0 dB | 12 | 0 | **limited** | yes |
| `nlf_​noise_​020` | afib | `15877_hr` | `ma` @ +2 dB | 6 | 0 | **limited** | — |
| `nlf_​noise_​021` | pac pvc | `16615_hr` | `bw` @ -6 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​022` | bbb conduction | `16930_hr` | `em` @ -4 dB | 12 | 12 | **limited** | yes |
| `nlf_​noise_​023` | st t | `01709_hr` | `ma` @ -2 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​024` | flutter svt | `17553_hr` | `bw` @ +0 dB | 6 | 0 | **limited** | yes |
| `nlf_​noise_​025` | sinus | `17727_hr` | `em` @ +2 dB | 12 | 0 | **limited** | — |
| `nlf_​noise_​026` | afib | `17770_hr` | `ma` @ -6 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​027` | pac pvc | `17867_hr` | `bw` @ -4 dB | 6 | 6 | **limited** | yes |
| `nlf_​noise_​028` | bbb conduction | `18284_hr` | `em` @ -2 dB | 12 | 12 | **limited** | yes |
| `nlf_​noise_​029` | st t | `18508_hr` | `ma` @ +0 dB | 6 | 0 | **limited** | yes |
| `nlf_​noise_​030` | flutter svt | `19002_hr` | `bw` @ +2 dB | 6 | 0 | **limited** | — |

### 5.3 Engineering extremes — single-lead (13)

| Record | PTB-XL parent | Corruption | Integrity failure | Bad leads | Expected quality | Discard |
|:--|:--|:--|:--|--:|:--:|:--:|
| `nlf_​eng_​001_​emg_​v1` | `19238_hr` | swing 6 mV p2p (V1) | — | 1 | **limited** | — |
| `nlf_​eng_​002_​macecg_​walk_​v2` | `19268_hr` | MACECGDB `walk` swing 8 mV p2p (V2) | — | 1 | **limited** | — |
| `nlf_​eng_​003_​intermittent_​v6` | `19661_hr` | intermittent lead-off with reconnection (V6) | intermittent lead off | 1 | **limited** | — |
| `nlf_​eng_​004_​step_​ii` | `01979_hr` | baseline step 4 mV, tau=1 s (II) | — | 0 | **limited** | — |
| `nlf_​eng_​005_​macecg_​jump_​overload_​v3` | `01995_hr` | MACECGDB `jump` swing 30 mV p2p (V3) → rail ±5 mV | rail saturation | 1 | **limited** | — |
| `nlf_​eng_​006_​flatline_​v4` | `20943_hr` | flatline / zero-fill (V4) | flatline zero | 1 | **limited** | — |
| `nlf_​eng_​007_​constant_​v5` | `20977_hr` | stuck constant 1.2 mV (V5) | constant adc | 1 | **limited** | — |
| `nlf_​eng_​008_​missing_​v6` | `21495_hr` | digital-missing / NaN (V6) | digital missing channel | 1 | **limited** | — |
| `nlf_​eng_​009_​flatline_​i` | `21820_hr` | flatline / zero-fill (I) | flatline zero | 5 | **limited** | — |
| `nlf_​eng_​010_​leadoff_​v2` | `21834_hr` | lead-off (V2) | lead off | 1 | **limited** | — |
| `nlf_​eng_​011_​emg_​burst_​v5` | `02779_hr` | swing 5 mV p2p (V5), t in [3,6] s | — | 0 | **limited** | — |
| `nlf_​eng_​021_​reversal_​i` | `03941_hr` | polarity inversion (I) | — | 0 | **limited** | — |
| `nlf_​eng_​031_​flatline_​ii` | `06175_hr` | flatline / zero-fill (II) | flatline zero | 5 | **limited** | yes |

### 5.4 Engineering extremes — multi-lead / mixed (27)

Electrode-domain propagation, precordial coupling, multi-lead saturation, and compound "wild" cases.

| Record | PTB-XL parent | Corruption | Integrity failure | Bad leads | Expected quality | Discard |
|:--|:--|:--|:--|--:|:--:|:--:|
| `nlf_​eng_​012_​couple_​v1v2` | `02965_hr` | precordial coupling V1, V2 @ +0 dB | — | 2 | **limited** | — |
| `nlf_​eng_​013_​couple_​v4v5` | `03016_hr` | precordial coupling V4, V5 @ +6 dB | — | 0 | **limited** | — |
| `nlf_​eng_​014_​triple_​v1v2v3` | `03047_hr` | precordial coupling V1, V2, V3 @ -6 dB | — | 3 | **limited** | yes |
| `nlf_​eng_​015_​electrode_​la` | `03365_hr` | LA electrode motion 1 mV | — | 4 | **limited** | yes |
| `nlf_​eng_​016_​electrode_​ra` | `03427_hr` | RA electrode offset 3 mV | — | 6 | **reject** | yes |
| `nlf_​eng_​017_​saturate_​v2v3` | `03543_hr` | overload swing 30 mV p2p (V2, V3) → rail ±5 mV | rail saturation | 2 | **limited** | — |
| `nlf_​eng_​018_​saturate_​v4v5v6` | `03687_hr` | overload swing 30 mV p2p (V4, V5, V6) → rail ±5 mV | rail saturation | 3 | **limited** | yes |
| `nlf_​eng_​019_​electrode_​ll` | `03730_hr` | LL electrode motion 1.2 mV | — | 3 | **limited** | yes |
| `nlf_​eng_​020_​compound_​wild` | `03885_hr` | LA electrode motion 0.8 mV ; MACECGDB `walk` swing 8 mV p2p (V2) ; lead-off (V5) | lead off | 5 | **limited** | yes |
| `nlf_​eng_​022_​mixed_​integrity` | `03987_hr` | digital-missing / NaN (V1) ; overload swing 25 mV p2p (V6) → rail ±5 mV ; baseline step 3 mV, tau=1.5 s (II) | digital missing channel | 2 | **limited** | — |
| `nlf_​eng_​023_​saturate_​v1v2v3` | `04593_hr` | overload swing 30 mV p2p (V1, V2, V3) → rail ±5 mV | rail saturation | 3 | **limited** | yes |
| `nlf_​eng_​024_​saturate_​precordial_​all` | `00476_hr` | overload swing 32 mV p2p (V1, V2, V3, V4, V5, V6) → rail ±5 mV | rail saturation | 6 | **reject** | yes |
| `nlf_​eng_​025_​emg_​v2v3_​severe` | `05141_hr` | swing 12 mV p2p (V2, V3) | — | 2 | **limited** | yes |
| `nlf_​eng_​026_​flatline_​v5v6` | `05267_hr` | flatline / zero-fill (V5, V6) | flatline zero | 2 | **limited** | yes |
| `nlf_​eng_​027_​constant_​v2v3` | `05298_hr` | stuck constant 2 mV (V2, V3) | constant adc | 2 | **limited** | yes |
| `nlf_​eng_​028_​missing_​v1v2v3` | `05883_hr` | digital-missing / NaN (V1, V2, V3) | digital missing channel | 3 | **limited** | yes |
| `nlf_​eng_​029_​leadoff_​v4v5v6` | `05887_hr` | lead-off (V4, V5, V6) | lead off | 3 | **limited** | yes |
| `nlf_​eng_​030_​intermittent_​v2v5` | `05940_hr` | intermittent lead-off with reconnection (V2, V5) | intermittent lead off | 2 | **limited** | yes |
| `nlf_​eng_​032_​electrode_​ra_​severe` | `06526_hr` | RA electrode offset 5 mV | — | 6 | **reject** | yes |
| `nlf_​eng_​033_​electrode_​la_​offset` | `06789_hr` | LA electrode offset 4 mV | — | 4 | **limited** | yes |
| `nlf_​eng_​034_​electrode_​ll_​offset` | `07086_hr` | LL electrode offset 4 mV | — | 3 | **limited** | yes |
| `nlf_​eng_​035_​double_​electrode_​ra_​ll` | `08699_hr` | RA electrode offset 3 mV ; LL electrode offset 3 mV | — | 6 | **reject** | yes |
| `nlf_​eng_​036_​baseline_​swing_​limb` | `08931_hr` | MACECGDB `walk` swing 10 mV p2p (I, II) | — | 2 | **limited** | yes |
| `nlf_​eng_​037_​compound_​wild2` | `09188_hr` | LA electrode motion 1 mV ; overload swing 30 mV p2p (V3) → rail ±5 mV ; intermittent lead-off with reconnection (V6) ; baseline step 4 mV, tau=1.5 s (II) | rail saturation | 5 | **limited** | yes |
| `nlf_​eng_​038_​mixed_​integrity2` | `09509_hr` | digital-missing / NaN (V3) ; flatline / zero-fill (V5) ; stuck constant 1.5 mV (V1) | digital missing channel | 3 | **limited** | yes |
| `nlf_​eng_​039_​reversal_​ii_​v1` | `09836_hr` | polarity inversion (II) ; polarity inversion (V1) | — | 0 | **limited** | — |
| `nlf_​eng_​040_​catastrophic_​integrity` | `09915_hr` | flatline / zero-fill (I) ; digital-missing / NaN (V6) ; overload swing 30 mV p2p (V3) → rail ±5 mV ; intermittent lead-off with reconnection (V4) | digital missing channel | 8 | **reject** | yes |

---

## 6. Reproducibility and provenance

A single master seed (`20260713`) plus `provenance.json` (pinned source versions, per-record seed,
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

- **Counts:** 85 records (15 / 30 / 40) + 70 paired clean parents.
- **SNR ladder:** max \|requested - measured\| SNR error **0.0 dB** across all 30 mixes (tol 0.5 dB).
- **Data integrity:** digital-missing (NaN) round-trips through WFDB — the affected channel reads back
  all-NaN while intact leads stay finite.
- **Determinism:** two independent full regenerations are **byte-identical**.
- **Quality gates:** 74 unit/integration tests pass; `ruff` + `black` clean.

---

*Generated by Artefaux v2.0.0 (<https://github.com/depolarised/artefaux>) via
`scripts/reports/generate_corpus_report.py`; every figure and table value is computed from the
committed corpus definition.*
