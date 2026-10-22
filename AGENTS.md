<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# Artefaux agent guidance

Read `CLAUDE.md` for the generator architecture and regeneration rules. Read
`docs/REVIEW_SET_2.md` before changing local review artifacts or handoff tooling.

## Project conventions

- Use the project `.venv` and uv. Run `.venv/bin/python -m pytest` for tests, and
  Ruff/Black for changed Python files. Real-source generation and PDF review checks
  require the local data and internal `ecg_io`/`signalpaper` packages.
- Signals are `(12, T)` float64 arrays in millivolts, canonical lead order
  `[I, II, III, aVR, aVL, aVF, V1..V6]`, at 500 Hz. Review records last ten seconds.
- Preserve deterministic per-record seeding and the exact noise-source audit.
  Expected quality labels are authored hypotheses, not reviewer decisions.
- The released v2 definition is `src/artefaux/corpus.py`. The additional review set
  is `src/artefaux/review.py`; keep its definition and outputs separate from v2.
- Follow the existing SPDX/copyright headers. Code is GPL-3.0-or-later;
  documentation and corpus metadata are CC-BY-4.0.

## Confirmed review requirements

- **Both review sets use overflow plots.** Use `layout="strip8"`, 25 mm/s,
  10 mm/mV, `clip_waveform=False`, and `show_clipping_banner=False`. Allow the traces
  to extend beyond their lead bands; do not clamp them or automatically reduce gain.
- Preserve the first set's diagnostic filtering and original page/code mapping
  from `reports/artefaux_v2_ecg_review_blind.key.csv`. The second set uses raw
  (`filter_preset="none"`) traces to preserve the clean five-second half.
- **XLS files must be plain:** one heading row and the data rows, default cell
  formatting, no colours, shading, theme, decorative borders, or added title rows.
  Keep genuine Excel 97–2003 BIFF8 `.xls` files and their CSV companions.
- Reviewer initials are **PWM = Peter** and **DTC = Derek**. The six columns are
  `Blind ECG code`, `<initials> Leads unsuitable`, `<initials> 50% OK?`,
  `<initials> comments`, `<initials> decision`, and `Agreed handling`.
- Preserve original CSVs and existing review cell values. Presentation changes may
  rewrite an XLS while retaining its cells. Keep Peter's supplied first-set comments
  in his sheet only; independent Derek sheets must not contain those responses.
- The supplementary set has **85 new strips total**: 15 selective extreme cases in
  one five-second half and selected leads, plus 70 lower-noise examples including
  10 untouched controls. Here, "lower noise floor" means **less added noise**.
- Keep both sets' established `REV-001`–`REV-085` mappings. Use the set number to
  distinguish them. Source IDs, labels, clean parents, and keys stay outside reviewer
  PDFs, spreadsheets, signal headers, and ZIPs.

## Signalguard vs Uni-G comparison

- Read `docs/PHASE1.md` first. Phase 1 = review set 1 with the readers' confirmed answers;
  Phase 2 = review set 2. Disputed units go to the joint adjudication sheet
  (`reports/review_packs/phase1/`) and are never scored until settled.
- The withdrawn T1 block's coded seven-column reader form (`bench_review_columns`) and
  generator remain for a possible replication; they are not in use.

## Handoff locations and checks

- Shareable files: `reports/review_packs/set1/`, `set2/`, and reviewer ZIPs in
  `reports/review_packs/`. PDFs use the explicit `*_blind_overflow.pdf` names;
  the older `*_blind.pdf` handoff filenames contain the same overflow PDFs.
- Coordinator artifacts: `out/artefaux-review-set2/`, especially
  `PRIVATE_blind_key.csv`. These and derived signals remain gitignored.
- Refresh plots and packages with
  `MPLCONFIGDIR=/tmp/artefaux-matplotlib .venv/bin/python scripts/generate_review_set.py --reuse-corpus`.
  This reuses the existing signals and retains review responses.
- After presentation changes, verify 85 pages per set, unchanged codes and cell
  values, no clipping banners, plain XLS formatting, and refreshed ZIP contents.
  Keep private truth out of reviewer archives. Signal-definition changes also
  require the interval/lead-mask and post-storage SNR checks in the generator.
