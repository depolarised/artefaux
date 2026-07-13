# Architecture

Torsade is a small, pure-Python pipeline. Every signal is a `(12, T)` `float64`
array in **millivolts**, leads in canonical order
`[I, II, III, aVR, aVL, aVF, V1, V2, V3, V4, V5, V6]`, sampled at **500 Hz**. That
invariant is established at load time so every downstream module can assume it.

## Data flow

```
sources (PhysioNet)                     corpus definition (shipped)
   │                                        │
   ▼                                        ▼
loaders ──► ParentECG ─┐            corpus.build_corpus_specs() ─► RecordSpec[]
                       │                     │
NSTDB ──► NoiseSegment │                     ▼
                       └──► recipes.build_record(parent, spec) ──► (signal, RecordLabel)
                                    │  applies steps via:
                                    │    mixing / electrode_domain / precordial / engineering
                                    ▼
                        writer.write_wfdb  +  labels.RecordLabel.write  +  manifest / provenance
```

`build.generate_corpus` orchestrates the loop; `cli` and `scripts/` are thin
wrappers over it.

## Modules

| Module | Responsibility |
|---|---|
| `constants` | Lead order, limb/chest groups, SNR ladder, target rate, reference thresholds |
| `loaders` | Read WFDB parents and NSTDB noise into the canonical representation; resampling |
| `mixing` | Real-noise SNR mixing (`α` scaling, measured SNR) |
| `electrode_domain` | Einthoven/Goldberger algebra, WCT reconstruction, electrode corruption |
| `precordial` | Chest-lead corruption with shared + independent coupling |
| `engineering` | Extreme failure builders (clip, flatline, lead-off, NaN, swing, step, polarity, intermittent) |
| `noise_shapes` | Synthetic band-limited noise shapes (controls + CI) |
| `amplitude` | Peak-to-peak tracking and clipping detection |
| `provenance` | Deterministic per-record seeding; source hashing; `provenance.json` |
| `labels` | The three-layer label schema (see [LABEL_SCHEMA.md](LABEL_SCHEMA.md)) |
| `writer` | WFDB output via `wfdb.wrsamp` (incl. NaN handling) |
| `manifest` | Corpus index (JSON + CSV) |
| `recipes` | Declarative corruption specs and the interpreter (`apply_recipe`, `build_record`) |
| `corpus` | The Torsade v1 corpus definition and YAML serialization |
| `selection` | Deterministic PTB-XL parent selection from metadata |
| `synthetic` | Einthoven-consistent synthetic parents (smoke tests, figures) |
| `build` | End-to-end corpus generation |

## Design boundaries

- **No dependency on the internal `noiseguard` / `signalguard` packages.** Torsade
  *targets* their input contract and *authors* expected labels in their
  vocabularies, but never imports them. The corpus is tool-neutral ground truth.
- **`ecg-io` is readers-only**, so Torsade writes WFDB directly rather than
  round-tripping through it.
- **Real recorded noise (NSTDB) is primary.** The synthetic `noise_shapes` are used
  only for source-free controls and for CI, and are labelled as synthetic.

## Reproducibility

A single master seed drives everything; each record's RNG is
`SeedSequence(entropy=master_seed, spawn_key=(record_index,))`. Combined with the
pinned source versions and per-file SHA-256 in `provenance.json`,
`make download && make regenerate` reproduces the corpus bit-for-bit.

## Figures

Figures (`scripts/make_figures.py`) follow the ECG house style: IBM Plex type,
single accent `#6C5CE7`, colourblind-safe, no chartjunk, legible at embed size,
every number traceable to source. To avoid redistributing source signals, worked
examples use synthetic parents.
