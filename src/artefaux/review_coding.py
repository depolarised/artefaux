# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Code free-text reviewer responses into structured fields.

The review sets 1 and 2 sheets have six free-text columns. To compare readers with each
other, with the recipe truth and later with programs, each response is coded into the
same four fields that the benchmark form asks for directly:

* ``unusable_leads`` — displayed independent leads (I, II, V1–V6) the reader would omit;
* ``usable_section`` — ``full`` / ``first_half`` / ``second_half``;
* ``overall`` — ``analysable`` / ``partial`` / ``rhythm_only`` / ``not_analysable``;
* ``not_noise`` — non-noise findings the reader named (reversal, missing/flat, amplitude limit).

Automatic coding is a draft. Every response the parser cannot read unambiguously is fixed
by an explicit override row, and the coded table is verified by a person before analysis.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

DISPLAYED_LEADS: tuple[str, ...] = ("I", "II", "V1", "V2", "V3", "V4", "V5", "V6")
CHEST = DISPLAYED_LEADS[2:]
OVERALL = ("analysable", "partial", "rhythm_only", "not_analysable")
SECTIONS = ("full", "first_half", "second_half", "none")
NOT_NOISE = ("lead_reversal", "missing_or_flat", "amplitude_limit", "other")


@dataclass(frozen=True)
class CodedResponse:
    blind_code: str
    reader: str
    unusable_leads: tuple[str, ...]
    usable_section: str
    overall: str
    not_noise: tuple[str, ...]
    source: str = "auto"  # "auto", "override", or "form" (coded T1 sheet)

    @property
    def repeat_ecg(self) -> bool:
        return self.overall in ("rhythm_only", "not_analysable")

    def lead_unusable(self, lead: str) -> bool:
        """Per-lead judgement; a repeat-ECG decision makes every displayed lead unusable."""
        return self.repeat_ecg or lead in self.unusable_leads

    def as_row(self) -> dict[str, str]:
        return {
            "blind_code": self.blind_code,
            "reader": self.reader,
            "unusable_leads": ";".join(self.unusable_leads),
            "usable_section": self.usable_section,
            "overall": self.overall,
            "repeat_ecg": str(self.repeat_ecg),
            "not_noise": ";".join(self.not_noise),
            "source": self.source,
        }


def _ordered(leads: Iterable[str]) -> tuple[str, ...]:
    chosen = set(leads)
    return tuple(ld for ld in DISPLAYED_LEADS if ld in chosen)


_V_RANGE = re.compile(r"\bv\s?([1-6])\s*(?:-|–|to)\s*v?\s?([1-6])\b", re.I)
_V_SINGLE = re.compile(r"\bv\s?([1-6])\b", re.I)
_LIMB_WORD = {"i": "I", "1": "I", "ii": "II", "2": "II", '"': "II"}
# "lead 1", "leads I", "1 & 2", "I and II", "I, II" — limb leads only in an explicit context.
_LEAD_LIMB = re.compile(r"\bleads?\s+(ii|i|1|2)\b", re.I)
_LIMB_PAIR = re.compile(r"(?<![\w])(ii|i|1|2)\s*(?:&|and|,|\+)\s*(ii|i|1|2|\")(?![\w])", re.I)


def parse_leads(text: str) -> tuple[str, ...]:
    """Displayed leads named in an action phrase such as ``"take out V4, V5 & V6"``."""
    found: set[str] = set()
    t = text.replace("–", "-")
    for lo, hi in _V_RANGE.findall(t):
        a, b = sorted((int(lo), int(hi)))
        found.update(f"V{k}" for k in range(a, b + 1))
    t_no_ranges = _V_RANGE.sub(" ", t)
    found.update(f"V{k}" for k in _V_SINGLE.findall(t_no_ranges))
    for word in _LEAD_LIMB.findall(t):
        found.add(_LIMB_WORD[word.lower()])
    for first, second in _LIMB_PAIR.findall(t):
        found.add(_LIMB_WORD[first.lower()])
        found.add(_LIMB_WORD[second.lower()])
    lowered = t.lower()
    if re.search(r"\b(chest|precordial)\s+leads\b", lowered):
        found.update(CHEST)
    if re.search(r"\blimb\s+leads\b", lowered):
        found.update(("I", "II"))
    return _ordered(found)


_FIRST = re.compile(
    r"first\s+(5|five)\s*sec|first\s+(half|50\s*%)|0\s*-\s*5\s*sec|"
    r"(omit|exclude|excluded?)\s+(the\s+)?(last|final)\s+(5|five)|use\s+only\s+first",
    re.I,
)
_SECOND = re.compile(
    r"second\s+(5|five)\s*sec|se(c|co)?o?n+d\s+(half|50\s*%)|5\s*-\s*10\s*sec|"
    r"(analy[sz]e|use)\s+(the\s+)?last\s+(5|five)|seonc?d\s+half",
    re.I,
)


def parse_section(text: str) -> str:
    """Which five-second half the reader would analyse; ``full`` when none is named."""
    first, second = bool(_FIRST.search(text)), bool(_SECOND.search(text))
    if first and not second:
        return "first_half"
    if second and not first:
        return "second_half"
    return "full"


def parse_not_noise(text: str) -> tuple[str, ...]:
    t = text.lower()
    flags = []
    if re.search(r"revers|inverted", t):
        flags.append("lead_reversal")
    if re.search(r"missing|absent|\bflat|no signal|not a noise problem", t):
        flags.append("missing_or_flat")
    if re.search(r"amplifier|trimmed|truncated|chopped|out of range|cut off", t):
        flags.append("amplitude_limit")
    return tuple(flags)


def _dtc_overall(decision: str) -> str:
    d = decision.lower()
    if "not analysable" in d and "rhythm" in d:
        return "rhythm_only"
    if "not analysable" in d:
        return "not_analysable"
    if "partial" in d or "maybe" in d:
        return "partial"
    return "analysable"


def code_dtc(row: Mapping[str, str]) -> CodedResponse:
    """Derek's sheet: the action is in *comments*, the graded call in *decision*."""
    action = row["DTC comments"]
    overall = _dtc_overall(row["DTC decision"])
    if "repeat" in action.lower() and overall not in ("rhythm_only", "not_analysable"):
        overall = "not_analysable"
    leads = () if overall in ("rhythm_only", "not_analysable") else parse_leads(action)
    section = parse_section(action)
    if overall == "analysable" and (leads or section != "full"):
        overall = "partial"
    return CodedResponse(
        blind_code=row["Blind ECG code"],
        reader="DTC",
        unusable_leads=leads,
        usable_section=section,
        overall=overall,
        not_noise=parse_not_noise(f"{row['DTC Leads unsuitable']} {action}"),
    )


_PWM_REJECT = re.compile(r"reject all|omit complete|will not proceed", re.I)
_PWM_KEEP = re.compile(
    r"leave as is|process all|accept as is|use all leads|all leads have to remain|"
    r"use whole ecg|basically acceptable|process all leads",
    re.I,
)


def code_pwm(row: Mapping[str, str]) -> CodedResponse:
    """Peter's sheet: the action is in *decision*; he gives no graded call."""
    decision = row["PWM decision"]
    if _PWM_REJECT.search(decision):
        leads, section, overall = (), "full", "not_analysable"
    else:
        keep = bool(_PWM_KEEP.search(decision))
        leads = () if keep else parse_leads(decision)
        section = parse_section(decision)
        overall = "partial" if (leads or section != "full") else "analysable"
    return CodedResponse(
        blind_code=row["Blind ECG code"],
        reader="PWM",
        unusable_leads=leads,
        usable_section=section,
        overall=overall,
        not_noise=parse_not_noise(
            f"{row['PWM Leads unsuitable']} {row['PWM 50% OK?']} {row['PWM comments']}"
        ),
    )


CODERS = {"DTC": code_dtc, "PWM": code_pwm}
OVERRIDE_COLUMNS = ("reader", "blind_code", "field", "value", "note")


def apply_overrides(
    coded: Iterable[CodedResponse], overrides: Iterable[Mapping[str, str]]
) -> list[CodedResponse]:
    """Replace coded fields with explicit, documented overrides (one row per field)."""
    by_key = {(c.reader, c.blind_code): c for c in coded}
    for row in overrides:
        key = (row["reader"], row["blind_code"])
        if key not in by_key:
            raise KeyError(f"override for unknown response {key}")
        field, value = row["field"], row["value"].strip()
        if field in ("unusable_leads", "not_noise"):
            parts = tuple(p for p in value.split(";") if p)
            vocab = DISPLAYED_LEADS if field == "unusable_leads" else NOT_NOISE
            if set(parts) - set(vocab):
                raise ValueError(f"{key}: invalid {field} {value!r}")
            parsed = _ordered(parts) if field == "unusable_leads" else parts
        elif field == "usable_section":
            if value not in SECTIONS:
                raise ValueError(f"{key}: invalid usable_section {value!r}")
            parsed = value
        elif field == "overall":
            if value not in OVERALL:
                raise ValueError(f"{key}: invalid overall {value!r}")
            parsed = value
        else:
            raise ValueError(f"{key}: unknown override field {field!r}")
        by_key[key] = replace(by_key[key], **{field: parsed}, source="override")
    return list(by_key.values())


_BENCH_SECTION = {
    "full": "full",
    "first 5 s": "first_half",
    "second 5 s": "second_half",
    "neither": "none",
}
_BENCH_OVERALL = {
    "analysable": "analysable",
    "partially analysable": "partial",
    "rhythm only": "rhythm_only",
    "not analysable": "not_analysable",
}
_BENCH_NOT_NOISE = {
    "lead reversal": "lead_reversal",
    "missing or flat lead": "missing_or_flat",
    "amplifier limit": "amplitude_limit",
    "other": "other",
}


def _norm(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip().lower())
    return re.sub(r"\b5\s*(?:seconds?|secs?|s)\b", "5 s", text)


def code_bench(row: Mapping[str, str], reader: str) -> tuple[CodedResponse | None, list[str]]:
    """Strictly code one row of the T1 coded form; return ``(response, problems)``.

    Nothing is guessed: any cell outside the allowed values is reported so it can go
    back to the reader, and the response is ``None`` until every cell is valid.
    """
    code = row["Blind ECG code"]
    problems = []
    leads_text = _norm(row[f"{reader} Unusable leads"])
    if leads_text in ("none", ""):
        leads: tuple[str, ...] = ()
        if not leads_text:
            problems.append(f"{code}: Unusable leads is blank (write 'none')")
    elif leads_text == "all":
        leads = DISPLAYED_LEADS
    else:
        parts = [p.strip().upper() for p in re.split(r"[,;/&]|\band\b", leads_text) if p.strip()]
        bad = [p for p in parts if p not in DISPLAYED_LEADS]
        if bad:
            problems.append(f"{code}: unknown lead(s) {bad}")
        leads = _ordered(p for p in parts if p in DISPLAYED_LEADS)
    section = _BENCH_SECTION.get(_norm(row[f"{reader} Usable section"]))
    if section is None:
        problems.append(f"{code}: Usable section {row[f'{reader} Usable section']!r}")
    overall = _BENCH_OVERALL.get(_norm(row[f"{reader} Overall"]))
    if overall is None:
        problems.append(f"{code}: Overall {row[f'{reader} Overall']!r}")
    flags = []
    for part in (p for p in re.split(r"[,;]", _norm(row[f"{reader} Not noise"])) if p.strip()):
        flag = _BENCH_NOT_NOISE.get(part.strip())
        if flag is None:
            problems.append(f"{code}: Not noise {part.strip()!r}")
        else:
            flags.append(flag)
    if section is not None and overall is not None:
        problems.extend(_contradictions(code, leads, leads_text == "all", section, overall))
    if problems:
        return None, problems
    return (
        CodedResponse(
            blind_code=code,
            reader=reader,
            unusable_leads=leads,
            usable_section=section,
            overall=overall,
            not_noise=tuple(flags),
            source="form",
        ),
        [],
    )


_REPEAT_OVERALL = ("rhythm_only", "not_analysable")


def _contradictions(
    code: str, leads: tuple[str, ...], named_all: bool, section: str, overall: str
) -> list[str]:
    """Self-contradictory combinations of the three cells; a reader may repeat while
    naming the worst leads, so repeat grades with listed leads are not flagged."""
    problems = []
    if named_all and overall not in _REPEAT_OVERALL:
        problems.append(f"{code}: all leads unusable but Overall is not rhythm only/not analysable")
    elif leads and overall == "analysable":
        problems.append(f"{code}: unusable leads listed but Overall is analysable")
    if section == "none" and overall in ("analysable", "partial"):
        problems.append(f"{code}: Usable section is neither but Overall is {overall}")
    return problems


def read_overrides(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if rows and tuple(rows[0]) != OVERRIDE_COLUMNS:
        raise ValueError(f"{path}: expected columns {OVERRIDE_COLUMNS}")
    return rows
