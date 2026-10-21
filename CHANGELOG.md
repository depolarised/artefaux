<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Changelog

## Unreleased

### Added
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
