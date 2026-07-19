# Artefaux

**A deterministic generator and reproducible corpus definition for ECG noise & lead-failure stress testing.**

*Artefaux* — a portmanteau of *artefact* and *faux* (French for "false"). The suite injects controlled,
synthetic (*faux*) artefact — real recorded noise braided into clean 12-lead ECGs and engineered
electrode/lead failures — producing a richly-labelled corpus for stress-testing ECG signal-quality
gates and noise detectors.

> **This is a stress-test set, not a clinically representative cohort.** It deliberately over-samples
> failure. Do not use it to estimate real-world prevalence or detector accuracy in deployment.

## What this is

Artefaux v2 ships the **generation engine** and the **corpus definition** (recipes + manifest + labels +
provenance) needed to regenerate an 85-record stress corpus **bit-exactly** from open PhysioNet sources.
It does **not** redistribute derived signals — you fetch the sources and regenerate locally:

```bash
make download      # fetch NSTDB (the only source not in a local PhysioNet mirror)
make select        # resolve PTB-XL parent record ids from your local PTB-XL copy
make regenerate    # build the corpus (WFDB records + labels + manifest) into ./out
```

PTB-XL (500 Hz), PTB-XL+, and MACECGDB are read from a local PhysioNet mirror
(`/data/physionet/...` by default; override the `PTBXL`/`MACECGDB` Make variables).

## Corpus composition (v2)

v2 is an **85-record** corpus reweighted toward clinically-unusable ("discard") ECGs: the real-noise
ladder drops the clean end for an aggressive low-SNR sweep, and the engineering group grows to 40.

| Group | n | Source | Corruption |
|---|---:|---|---|
| Naturally poor | 15 | PTB-XL quality-flagged records | none (inherently noisy) |
| Real-noise pairs | 30 | clean PTB-XL + NSTDB `em`/`ma`/`bw` | SNR ladder {−6, −4, −2, 0, +2} dB |
| Engineering extremes | 40 | clean PTB-XL parents (+ MACECGDB motion) | single + multi-lead + extreme failures |

Each record carries three label layers: **clinical parent** (authored rhythm class + PTB-XL quality flags; the Uni-G statement field is reserved and empty in v2), **corruption truth**
(electrodes/leads, SNR, seed, amplitude bookkeeping), and **expected behaviour** (per-lead and record-level,
mapped to the internal `signalguard`/`noiseguard` vocabularies).

## Licensing

- **Code:** GPL-3.0-or-later (see `LICENSE`).
- **Manifest, labels, and documentation:** CC-BY-4.0 (see `LICENSES/CC-BY-4.0.txt`).
- **Source data** is not redistributed; see `ATTRIBUTION.md` for the datasets you must obtain and cite.

Full generation algorithm, label schema, and provenance are documented under `docs/` and `DATASHEET.md`.
