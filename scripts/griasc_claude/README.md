<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
-->

# `griasc_claude` — Artefaux v2 → internal GRIASCII converter

A **local tool** that re-emits the built Artefaux v2 stress corpus in the internal
Glasgow/GRIANLYS ASCII (GRIASCII) v1.5 format, using the `ecg-io` reader/parser API.

It is deliberately *not* part of the shipped, self-contained Artefaux generator: it
depends on the internal `ecg-suite` package `ecg-io` (exactly as
`scripts/reports/render_ecg_review.py` does), and on an already-built corpus. The
generated `.asc` files and the index CSV are **not committed** (see `.gitignore`),
matching the project rule that derived signals are never redistributed — regenerate
locally from source.

## What it produces

For each of the **85 stress records** in `manifest.csv` (optionally the 70 paired
clean parents too), one GRIASCII v1.5 `.asc` file holding the canonical
`(12, T)` millivolt signal in canonical lead order
`[I, II, III, aVR, aVL, aVF, V1…V6]`, plus a `griasc_index.csv` audit sheet.

## Prerequisites

```bash
# From the Artefaux repo root, with the corpus already built under out/artefaux-v2:
uv pip install -e ../../ecg-suite/ecg-io    # ecg-io is not an Artefaux dependency
```

## Usage

```bash
# Convert the 85 stress records (default paths):
.venv/bin/python scripts/griasc_claude/convert_to_griasc.py

# Include the 70 paired clean parents as well:
.venv/bin/python scripts/griasc_claude/convert_to_griasc.py --include-clean

# Smoke-check the first 3 records:
.venv/bin/python scripts/griasc_claude/convert_to_griasc.py --limit 3

# Custom locations:
.venv/bin/python scripts/griasc_claude/convert_to_griasc.py \
    --corpus out/artefaux-v2 --manifest manifest.csv --out out/artefaux-v2-griasc
```

Output defaults to `out/artefaux-v2-griasc/records/*.asc` (under the repo-level
`/out/`, which is already git-ignored) with `out/artefaux-v2-griasc/griasc_index.csv`.

## Why the conversion is loss-free

Artefaux writes WFDB with an ADC gain of **1000 LSB/mV** and baseline **0**, so the
physical signal returned by `ecg_io.read_ecg` is exactly `adc / 1000`. Writing
GRIASCII with the matching calibration of **1000 LSB/mV** and integer ADC counts
`round(mV × 1000)` reproduces the original int16 ADC samples with zero loss. The
converter proves this per record by parsing every emitted file back with
`ecg_io`'s parser and asserting the decoded signal matches the source to within
half an LSB. Across the full v2 corpus the measured round-trip error is at the
float-epsilon floor (~`2e-16` mV) — i.e. loss-free at ADC resolution.

## Two decode paths (one caveat)

- **Low-level parser** `ecg_io._glasgow_ascii.parse_glasgow_ascii_file` returns raw
  millivolts and is what the converter verifies against — bit-exact.
- **High-level reader** `ecg_io.read_ecg("*.asc")` (the `GRIasc` reader) additionally
  subtracts each lead's **median** for DC removal, a documented reader behaviour. It
  therefore re-centres records carrying a deliberate baseline offset. The written
  signal is unaltered; only that reader's view is DC-removed.

A second GRIASCII quirk the converter guards against: the reader **re-derives**
`III/aVR/aVL/aVF` from `I` and `II` when a stored limb lead is all-zero. No v2 record
has an all-zero limb lead (flatline/lead-off corruptions land on non-zero constants
or precordial leads), so every record round-trips with lead identity intact; the
converter raises `ConversionError` if that ever stops being true.

## `digital_missing` samples

The `digital_missing` corruption is stored in WFDB as the int16 *missing-sample
sentinel* (−32768 / physical `NaN`). `ecg_io.read_ecg` decodes those to `0.0` mV
(`nan_to_num`), and GRIASCII — which has no `NaN` encoding — therefore stores `0`.
The `.asc` thus faithfully reproduces the millivolt signal the `ecg_io` API yields,
not the raw WFDB storage sentinel. (Concretely, in v2 this affects V6 of
`nlf_eng_040_catastrophic_integrity`, a fully-missing lead; it is a precordial lead,
so no limb-lead re-derivation is involved.)

## Scope

GRIASCII is a signal container. The three-layer Artefaux **labels** and the
**manifest** remain the authoritative metadata (rhythm class, corruption truth,
expected `signalguard`/`noiseguard` behaviour); this tool does not fold them into the
`.asc` header.
