# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Deterministic selection of PTB-XL parents from the user's metadata.

Given rows of ``ptbxl_database.csv`` (as dicts), pick clean parents (no quality
flags) and naturally-noisy records (any quality flag set), one ECG per patient,
sampled deterministically from a seed. Kept pure and dependency-light so it is
unit-tested without a PTB-XL download; the CLI wrapper is ``scripts/select_sources.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

#: PTB-XL technical-validation quality columns (free-text; empty ⇒ clean).
QUALITY_COLUMNS = ("baseline_drift", "static_noise", "burst_noise", "electrodes_problems")


def _is_blank(value: object) -> bool:
    s = str(value).strip().lower()
    return s in ("", "nan", "none")


def is_clean(row: Mapping[str, object]) -> bool:
    """True if a record carries no technical-validation quality flag."""
    return all(_is_blank(row.get(col, "")) for col in QUALITY_COLUMNS)


def quality_flags(row: Mapping[str, object]) -> tuple[str, ...]:
    """The quality-flag column names that are set for this record."""
    return tuple(col for col in QUALITY_COLUMNS if not _is_blank(row.get(col, "")))


def _dedupe_by_patient(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    seen: set = set()
    out: list[Mapping[str, object]] = []
    for row in sorted(rows, key=lambda r: str(r.get("ecg_id"))):
        pid = row.get("patient_id")
        if pid in seen:
            continue
        seen.add(pid)
        out.append(row)
    return out


def _sample(rows: list[Mapping[str, object]], n: int, seed: int) -> list[Mapping[str, object]]:
    if n >= len(rows):
        return rows
    rng = np.random.default_rng(seed)
    idx = sorted(rng.permutation(len(rows))[:n].tolist())
    return [rows[i] for i in idx]


def select_ptbxl(
    rows: Sequence[Mapping[str, object]],
    *,
    n_clean: int,
    n_noisy: int,
    seed: int,
) -> tuple[list[Mapping[str, object]], list[Mapping[str, object]]]:
    """Return ``(clean_rows, noisy_rows)`` selected deterministically, one per patient."""
    clean = _dedupe_by_patient([r for r in rows if is_clean(r)])
    noisy = _dedupe_by_patient([r for r in rows if not is_clean(r)])
    return _sample(clean, n_clean, seed), _sample(noisy, n_noisy, seed + 1)
