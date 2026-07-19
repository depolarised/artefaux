# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Artefaux is a **deterministic generator and reproducible corpus *definition*** for ECG noise &
lead-failure stress testing. v2 ships the generation engine plus the corpus metadata (recipes +
manifest + labels + provenance) that regenerates an **85-record** 12-lead stress corpus (15
naturally-poor / 30 real-noise / 40 engineering, + 70 paired clean parents) **bit-exactly**
from open PhysioNet sources. v2 is weighted toward clinically-unusable ("discard") records: the
real-noise ladder is an aggressive-low `{-6,-4,-2,0,+2}` dB sweep and the engineering group grows to 40.
It deliberately **does not redistribute derived signals** — users fetch
sources and regenerate locally. It is a *stress-test set*, not a clinically representative cohort.

> This project sits at `~/dev/ecg/noise-suite/artefaux`, a tree the parent `~/dev/ecg/CLAUDE.md`
> layout predates. The global DeepMind + Clinical-AI personas and engineering/figure-review standards
> from `~/.claude/CLAUDE.md` and `~/dev/ecg/CLAUDE.md` still apply; this file is the project-local
> authority. Unlike the rest of the workspace, Artefaux is managed with **uv** (`.venv` + `uv.lock`).

## Commands

Everything is driven through the `Makefile` (interpreter is `.venv/bin/python`):

```bash
make setup       # uv venv .venv + uv pip install -e ".[dev,figures]"
make test        # .venv/bin/python -m pytest   (74 tests, 16 files; needs no data)
make lint        # ruff check + black --check   over src tests scripts
make format      # ruff --fix + black
make smoke       # synthetic end-to-end build (no download) — the fast sanity check
```

Single test / focused run:
```bash
.venv/bin/python -m pytest tests/test_mixing.py::test_mixing_is_deterministic
.venv/bin/python -m pytest -k electrode -q
```

Regenerating shipped artifacts:
```bash
make corpus      # export_corpus.py: recipes/corpus.yaml + manifest.{json,csv} from artefaux.corpus
make figures     # scripts/make_figures.py (uses synthetic parents — never ships source signals)
make report      # scripts/reports/generate_corpus_report.py  (PDF=1 to also render via pandoc)
```

Full corpus build (needs the real sources):
```bash
make download    # NSTDB only (the one source not in the local PhysioNet mirror)
make select      # resolve PTB-XL parent ids from your local copy → recipes/source_ids/*.csv
make regenerate  # scripts/generate.py → out/artefaux-v1/{records,labels,manifest,provenance}
```
Sources: PTB-XL / PTB-XL+ / MACECGDB are read from a local mirror (`/data/physionet/...`, override
via the `PTBXL` / `MACECGDB` / `NSTDB` Make vars). Master seed is `20260713` (`SEED` var).

## Architecture

Full detail lives in `docs/ARCHITECTURE.md`, `docs/GENERATION.md`, `docs/LABEL_SCHEMA.md`, and
`DATASHEET.md` — read those before touching signal or label logic. The load-bearing ideas:

**Signal invariant (established at load time, assumed everywhere downstream):** every signal is a
`(12, T)` `float64` array in **millivolts**, canonical lead order
`[I, II, III, aVR, aVL, aVF, V1..V6]`, resampled to **500 Hz** (`scipy.signal.resample_poly`).

**Data flow:** `loaders` → `RecordSpec` (from `corpus.build_corpus_specs`) → `recipes.build_record`
applies ordered corruption steps via `mixing` / `electrode_domain` / `precordial` / `engineering`,
emitting `(signal, RecordLabel)` → `writer.write_wfdb` + `labels` + `manifest` + `provenance`.
`build.generate_corpus` is the orchestrating loop; `cli.py` and `scripts/` are thin wrappers.

**The corpus definition is code, and the committed metadata is generated from it.**
`src/artefaux/corpus.py::build_corpus_specs()` is the single source of truth. `recipes/corpus.yaml`,
`manifest.json`, and `manifest.csv` are *derived artifacts* — regenerate with `make corpus` and commit
them in the same change, or CI fails (it runs `export_corpus.py` then `git diff --exit-code`). Manifest
columns are authored from the spec, never measured from a signal, so a synthetic parent suffices to
regenerate them.

**Final check on any definition change — the corpus report and figures are also derived, but CI does
NOT guard them.** CI only diff-checks `recipes/corpus.yaml` + `manifest.{json,csv}`. The committed
report (`reports/artefaux_v2_corpus_report.{md,pdf}`, from `make report PDF=1`) and figures
(`figures/*.png`, from `make figures`) are computed from the same definition but are unenforced — change
the definition, forget to regenerate them, and they drift silently while CI stays green. So after any
change to `corpus.py` / `recipes.py` / `labels.py`, the final check is: `make corpus && make report
PDF=1 && make figures`, then `git diff` to confirm each derived artifact is consistent. **One caveat:**
the report's §7 "Verification" numbers (test count, SNR error, byte-identical claim) are *hand-authored
prose in `generate_corpus_report.py`, not computed* — regeneration does not refresh them, so update them
by hand when the underlying facts change (e.g. the test count when tests are added). `render_ecg_review.py`'s
outputs are untracked local-tool products, not part of this check.

**Recipes are a declarative op interpreter.** A `RecordSpec.steps` is a tuple of op dicts dispatched in
`recipes.apply_recipe`: `nstdb_mix`, `motion_swing`, `precordial`, `electrode`, and the `engineering`
builders (`swing`/`flatline`/`constant_adc`/`lead_off`/`digital_missing`/`step_recovery`/
`opposite_polarity`/`intermittent_lead_off`). Adding a corruption means: a builder (usually in
`engineering.py`), a branch in `apply_recipe`, and the corresponding `CorruptionStep` truth-logging.

**Three-layer labels, authored from the recipe — never by running a detector** (`labels.py`,
`docs/LABEL_SCHEMA.md`): (1) clinical parent, (2) corruption truth (exact steps, seed, measured SNR,
amplitude bookkeeping), (3) expected behaviour. Expected behaviour targets **two distinct vocabularies
on purpose**: `signalguard` (graded: diagnostic/limited/rhythm_only/reject) and `noiseguard` (binary
per-lead + record discard). A record can be `limited` for one and `discard=false` for the other.
Data-integrity failures (NaN / flatline / stuck-constant / rail-saturation) are labelled
`data_integrity_failure` with an `integrity_failure_type`, **not** as noise.

**Determinism is contractual.** One master seed drives everything; each record's RNG is
`SeedSequence(entropy=master_seed, spawn_key=(record_index,))` (`provenance.py`). Noise-segment offsets
are resolved inside `apply_recipe` (not the provider) specifically so output stays byte-identical and
the exact source segment is captured in the audit trail. Preserve this when editing the mixing path.

## Boundaries and conventions

- **Never import `noiseguard` / `signalguard`.** Artefaux *targets* their input contract and *authors*
  expected labels in their vocabularies but stays tool-neutral ground truth. It also doesn't depend on
  `ecg-io` (writes WFDB directly via `wfdb.wrsamp`).
- **Real recorded noise (NSTDB) is primary.** The synthetic `noise_shapes` are only for source-free
  controls and CI, and are always labelled synthetic.
- **Public generator vs. local tooling:** the core generator is self-contained. `scripts/reports/
  render_ecg_review.py` is a *local* tool that depends on the internal `ecg-suite` packages
  (`ecg_io` + `signalpaper`, installed via `uv pip install -e ../../ecg-suite/...`) and on a generated
  corpus — it is not part of the shipped, self-contained pipeline.
- **Source IDs are resolved separately from the definition.** `build_corpus_specs` leaves
  `source.record_id = None` so the definition is data-independent; `build.resolve_source_ids` binds
  concrete PTB-XL ids from `recipes/source_ids/*.csv` at generation time.
- **Licensing / headers:** code is GPL-3.0-or-later; manifest, labels, and docs are CC-BY-4.0. Every
  Python source file starts with the SPDX header (`# SPDX-License-Identifier: GPL-3.0-or-later` +
  copyright line) — match it on new files. Line length is 100 (ruff `E,F,I,W,UP,B` + black).
