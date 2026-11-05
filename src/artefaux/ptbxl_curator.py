# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Per-lead noise table from the PTB-XL curators' free-text quality columns.

``static_noise``, ``burst_noise``, ``baseline_drift`` and ``electrodes_problems`` hold
hand-written strings such as ``I-AVF``, ``alles``, ``v5,6`` or ``V1???``. They are the only
real 12-lead noise labels available here, so a misread string changes a specificity check.

The parser is strict: a string reads as leads only if every token is understood. A token it
cannot read, a question mark, or a severity with no lead (``leicht``) makes the column
``unknown`` for all twelve leads. Unknown is never clean. A blank cell means the curators flagged
nothing, so a column or cell that is absent altogether is an error, not a blank. Pure and
dependency-light; the CLI wrapper is ``scripts/build_curator_table.py``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .constants import CANONICAL_LEAD_ORDER
from .selection import QUALITY_COLUMNS

#: PTB-XL's own lead order, which range strings such as ``AVL-V2`` run along.
_BY_LOWER = {lead.lower(): i for i, lead in enumerate(CANONICAL_LEAD_ORDER)}
_ALL = {"alles", "alle"}
#: Severity words and record-level remarks: they qualify a flag but name no lead.
_REMARKS = {"leicht", "mittel", "stark", "stark!", "noise", "noisy", "recording", "drift"}
_CHEST_START = _BY_LOWER["v1"]

#: SCP codes of the clinical non-regression classes (dev-log ADR-0018 amendment 2).
CLASSES = ("NORM", "AFIB", "AFLT", "PVC", "BIGU", "TRIGU", "PACE", "LVOLT")

TABLE_COLUMNS = (
    "ecg_id",
    "filename_hr",
    "patient_id",
    "strat_fold",
    "validated_by_human",
    "lead",
    *QUALITY_COLUMNS,
    "lead_state",
    "record_clean",
    "scp_classes",
)


@dataclass(frozen=True)
class LeadScope:
    """What one curator column says: ``none``, ``leads`` (named in ``leads``) or ``unknown``."""

    state: str
    leads: tuple[str, ...] = ()


_UNKNOWN = LeadScope("unknown")
_NONE = LeadScope("none")


def _lead_index(token: str, *, after_chest: bool = False) -> int | None:
    if token in _BY_LOWER:
        return _BY_LOWER[token]
    if after_chest and re.fullmatch(r"[1-6]", token):
        return _BY_LOWER[f"v{token}"]
    return None


def _token_leads(token: str, previous: int | None) -> set[int] | None:
    """Lead indices of one token, or ``None`` if it cannot be read."""
    after_chest = previous is not None and previous >= _CHEST_START
    if "-" not in token:
        index = _lead_index(token, after_chest=after_chest)
        return None if index is None else {index}
    first, _, last = token.partition("-")
    start = _lead_index(first, after_chest=after_chest)
    if start is None:
        return None
    end = _lead_index(last, after_chest=start >= _CHEST_START)
    if end is None:
        return None
    return set(range(min(start, end), max(start, end) + 1))


def parse_lead_scope(raw: object) -> LeadScope:
    """Parse one curator cell. Blank is ``none``; anything not fully understood is ``unknown``."""
    text = "" if raw is None else str(raw).strip().lower()
    if text in ("", "nan", "none") or not text.strip(" ,"):
        return _NONE
    if "?" in text:
        return _UNKNOWN
    text = re.sub(r"\s*-+\s*", "-", text)
    leads: set[int] = set()
    previous: int | None = None
    named_leads = False
    for token in re.split(r"[,;.\s]+", text):
        if not token or token in _REMARKS:
            continue
        if token in _ALL:
            leads.update(range(len(CANONICAL_LEAD_ORDER)))
            named_leads = True
            previous = None
            continue
        indices = _token_leads(token, previous)
        if indices is None:
            return _UNKNOWN
        leads |= indices
        named_leads = True
        previous = max(indices)
    if not named_leads:
        return _UNKNOWN
    return LeadScope("leads", tuple(CANONICAL_LEAD_ORDER[i] for i in sorted(leads)))


def record_classes(row: Mapping[str, str]) -> tuple[str, ...]:
    """Clinical classes present on a record, in :data:`CLASSES` order.

    Presence is the criterion: PTB-XL forms statements such as LVOLT carry likelihood 0.
    """
    codes = ast.literal_eval(row["scp_codes"])
    return tuple(c for c in CLASSES if c in codes)


def _column_state(scope: LeadScope, lead: str) -> str:
    if scope.state == "unknown":
        return "unknown"
    return "flagged" if lead in scope.leads else "clean"


def curator_rows(
    rows: Iterable[Mapping[str, str]], *, excluded_patients: set[str]
) -> list[dict[str, str]]:
    """One row per record and lead for every record of a patient not excluded.

    Raises ``ValueError`` if a quality column or cell is absent: read as blank, it would put a
    record nobody annotated into the clean denominator.
    """
    out: list[dict[str, str]] = []
    for row in rows:
        if row["patient_id"] in excluded_patients:
            continue
        absent = [col for col in QUALITY_COLUMNS if row.get(col) is None]
        if absent:
            raise ValueError(f"record {row.get('ecg_id')}: no value for {', '.join(absent)}")
        scopes = {col: parse_lead_scope(row[col]) for col in QUALITY_COLUMNS}
        per_lead = []
        for lead in CANONICAL_LEAD_ORDER:
            states = {col: _column_state(scopes[col], lead) for col in QUALITY_COLUMNS}
            values = set(states.values())
            state = "noisy" if "flagged" in values else "unknown" if "unknown" in values else None
            per_lead.append((lead, states, state or "clean"))
        clean = all(state == "clean" for _, _, state in per_lead)
        classes = ";".join(record_classes(row))
        for lead, states, state in per_lead:
            out.append(
                {
                    "ecg_id": row["ecg_id"],
                    "filename_hr": row["filename_hr"],
                    "patient_id": row["patient_id"],
                    "strat_fold": row["strat_fold"],
                    "validated_by_human": row["validated_by_human"],
                    "lead": lead,
                    **states,
                    "lead_state": state,
                    "record_clean": str(clean).lower(),
                    "scp_classes": classes,
                }
            )
    return out


def summarise(rows: Sequence[Mapping[str, str]]) -> dict[str, dict[str, int]]:
    """Aggregate counts for the documentation: never a per-record value."""
    leads: dict[str, int] = {"noisy": 0, "clean": 0, "unknown": 0}
    records: set[str] = set()
    clean_records: set[str] = set()
    by_class: dict[str, set[str]] = {c: set() for c in CLASSES}
    clean_by_class: dict[str, set[str]] = {c: set() for c in CLASSES}
    for row in rows:
        leads[row["lead_state"]] += 1
        records.add(row["ecg_id"])
        if row["record_clean"] == "true":
            clean_records.add(row["ecg_id"])
        for name in filter(None, row["scp_classes"].split(";")):
            by_class[name].add(row["ecg_id"])
            if row["record_clean"] == "true":
                clean_by_class[name].add(row["ecg_id"])
    return {
        "lead_units": leads,
        "records": {"total": len(records), "curator_clean": len(clean_records)},
        "records_by_class": {c: len(v) for c, v in by_class.items()},
        "curator_clean_records_by_class": {c: len(v) for c, v in clean_by_class.items()},
    }
