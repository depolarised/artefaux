<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Changelog

## Unreleased

### Changed
- **T1 withdrawn before handoff (2026-10-22).** The `bench-v1.0.0` tag and `bench/v1/T1/`
  were removed; no reader or program saw T1. The comparison runs in phases on the reviewed
  sets with the readers' confirmed answers (`docs/PHASE1.md`): Phase 1 = review set 1,
  Phase 2 = review set 2. The T1 definition and generator remain for a later replication.
- Scoring uses a unit-level confirmed reference (`confirmed_reference`, `Reference`):
  agreed units plus jointly adjudicated ones; disputed units are reported, not scored.

- Phase 1 has no adjudication round (2026-10-22): its reference is the agreed units only.
- Uni-G repeat mapping names statement 13/3 ("Recording unsuitable for analysis", written
  with GriAnlys exit 100–104) alongside 2/68; recorded before the Phase 1 run.
- `docs/PHASE1.md` records the one design-informed signalguard v0.3.0 run on set 1 (2026-11-05,
  ADR 0018 amendments 2 to 4) and the pending Glasgow-side Uni-G run.

### Added
- **Phase 2 run (2026-11-12).** Short-set-2 sheets coded before any program ran (`--set 2s`,
  `fill_blank_codes`, `unspecified` section, never confirmed); `build_phase1.py` takes
  `--selection`/`--phase-version`; signalguard v0.2.0 and v0.3.0 scored; `weighted_endpoints`
  (inverse-probability rows in `phase_report.py --selection`); `scripts/package_glasgow_pack.py`
  builds Brian's Uni-G pack (ADR 0018 amendment 6).
- **Short set 2 (2026-11-11).** Peter and Derek review 30 of the 85 set-2 ECGs:
  `review.select_short_set` (recipe-only stratified draw, seed 20261111) and
  `scripts/generate_review_set_short.py` (pages copied from the set-2 PDF, set-2 codes kept).
  Phase 2 is scored on these 30, with an inverse-probability-weighted row to the full 85
  (ADR 0018 amendment 5). Set 1 is out with Brian for an independent Uni-G run, pending his response.
- `calib-v1`, a private calibration corpus on patients disjoint from review sets 1 and 2
  (`artefaux.calib`, `scripts/generate_calib_corpus.py`, `docs/CALIB_V1.md`): noise type crossed
  with lead scope, independent NSTDB segments per lead, labels from ADR-0018 amendment 2 and a
  mined repeat rule, hash-frozen before any tool runs on it. `--verify` checks the exact file
  list and a pinned manifest digest. Existing corpora are unchanged.
- `artefaux.ptbxl_curator`, `scripts/build_curator_table.py`: per-lead table of the PTB-XL
  curators' quality strings. Strings that cannot be read are unknown, never clean; an absent
  column or cell raises. The table leaves out the calibration corpus's patients as well as those
  of review sets 1 and 2.
- Sensitivity row "reject not propagated" in `phase_report.py`
  (`lead_level(reject_propagates=False)`); P1 is unchanged and the rule is now stated next to it.
- `scripts/reports/phase_report.py`: Phase 1 scoring (P1, P2, paired differences,
  pre-specified sensitivity analyses, reader-vs-reader benchmark, by corpus group).
  `bench_scoring.read_prediction_dir`, `prediction_from_coded` and `Reference.restrict`.
- `scripts/build_phase1.py`: Phase 1 tool inputs (WFDB + adult-header GRIASCII), confirmed
  reference units and the joint adjudication sheet. `review_coding.read_coding` and
  `code_adjudication`.
- Blinded noise benchmark `artefaux-bench` v1, block T1 (120 records): definition
  (`artefaux.benchmark`), generator (`scripts/generate_benchmark.py`), scoring
  (`artefaux.bench_scoring`), protocol (`docs/BENCHMARK.md`) and pre-registered analysis
  plan (`docs/BENCHMARK_SAP.md`).
- Review synthesis: free-text coding (`artefaux.review_coding`), agreement statistics
  (`artefaux.scoring`) and `scripts/reports/synthesise_review.py`.
- Recipe ops `electrode_nstdb` (recorded noise on limb electrodes) and `electrode_swap`
  (cable reversal); step options `propagate_derived` and `taper_s`. Existing recipes
  are unaffected (the synthetic smoke corpus is byte-identical).
- Label group `control` for clean and confounder records (benchmark only).
- GRIASCII converter `header_lines` option for a complete Uni-G analysis request.

### Fixed
- `artefaux.__version__` reported `1.0.0`; it is `2.0.0`, matching `pyproject.toml`.

### Known issue
- GRIASCII files exported before this change (v2 and review set 2) leave the electrode
  positioning line blank and set age 0 days; Uni-G reads their V1–V3 as paediatric
  V4R/V1/V2 and uses paediatric thresholds. Do not use them for Uni-G analysis.

## 2.0.0 — 2026-07-16
- Artefaux v2: 85-record discard-weighted stress corpus.
