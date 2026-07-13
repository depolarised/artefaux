# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The three-layer label schema.

Every Torsade record carries three layers of ground truth:

1. **Clinical parent** — what the underlying ECG *is* (rhythm, Uni-G statements),
   inherited from the untouched parent.
2. **Corruption truth** — exactly what was done to it (leads/electrodes, artefact
   type, interval, SNR, seed, scaling, amplitude bookkeeping).
3. **Expected behaviour** — how a well-behaved quality gate *should* respond,
   expressed in the internal ``signalguard`` (per-lead / record) and ``noiseguard``
   (discard) vocabularies. These are authored deterministically from the recipe;
   Torsade does not run the detectors to produce them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# --- Label vocabularies (mirror signalguard) -------------------------------

QUALITY_LABELS = ("good", "borderline", "bad")
RECORD_QUALITIES = ("diagnostic", "limited", "rhythm_only", "reject")
CORPUS_GROUPS = ("naturally_poor", "real_noise", "engineering")


@dataclass(frozen=True)
class ClinicalParentLabel:
    source_dataset: str
    source_record_id: str | None
    age_years: float | None = None
    sex: str | None = None
    rhythm_class: str | None = None
    glasgow_statements: tuple[str, ...] = ()
    ptbxl_quality_flags: tuple[str, ...] = ()
    has_clean_parent: bool = False


@dataclass(frozen=True)
class CorruptionStep:
    op: str
    leads_affected: tuple[str, ...] = ()
    electrodes_affected: tuple[str, ...] = ()
    noise_type: str | None = None
    noise_source_record: str | None = None
    noise_source_start_sample: int | None = None
    interval_s: tuple[float, float] | None = None
    snr_requested_db: float | None = None
    snr_measured_db: float | None = None
    alpha: float | None = None
    amplitude: tuple[dict, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CorruptionTruthLabel:
    seed: int
    steps: tuple[CorruptionStep, ...] = ()
    leads_with_any_corruption: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedBehaviourLabel:
    record_quality: str
    lead_quality: Mapping[str, str]
    rejected_leads: tuple[str, ...] = ()
    derived_leads_invalidated: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    noiseguard_discard_record: bool = False
    noiseguard_bad_leads: tuple[str, ...] = ()
    data_integrity_failure: bool = False
    integrity_failure_type: str | None = None

    def __post_init__(self) -> None:
        if self.record_quality not in RECORD_QUALITIES:
            raise ValueError(f"invalid record_quality: {self.record_quality}")
        bad = {v for v in self.lead_quality.values() if v not in QUALITY_LABELS}
        if bad:
            raise ValueError(f"invalid lead_quality value(s): {sorted(bad)}")


@dataclass(frozen=True)
class RecordLabel:
    record_id: str
    group: str
    fs: int
    n_samples: int
    clinical_parent: ClinicalParentLabel
    corruption_truth: CorruptionTruthLabel
    expected_behaviour: ExpectedBehaviourLabel

    def __post_init__(self) -> None:
        if self.group not in CORPUS_GROUPS:
            raise ValueError(f"invalid group: {self.group}")

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RecordLabel:
        cp = ClinicalParentLabel(
            **{
                **d["clinical_parent"],
                "glasgow_statements": tuple(d["clinical_parent"].get("glasgow_statements", ())),
                "ptbxl_quality_flags": tuple(d["clinical_parent"].get("ptbxl_quality_flags", ())),
            }
        )
        ct_raw = d["corruption_truth"]
        steps = tuple(
            CorruptionStep(
                **{
                    **s,
                    "leads_affected": tuple(s.get("leads_affected", ())),
                    "electrodes_affected": tuple(s.get("electrodes_affected", ())),
                    "interval_s": tuple(s["interval_s"]) if s.get("interval_s") else None,
                    "amplitude": tuple(s.get("amplitude", ())),
                }
            )
            for s in ct_raw.get("steps", ())
        )
        ct = CorruptionTruthLabel(
            seed=ct_raw["seed"],
            steps=steps,
            leads_with_any_corruption=tuple(ct_raw.get("leads_with_any_corruption", ())),
        )
        eb_raw = d["expected_behaviour"]
        eb = ExpectedBehaviourLabel(
            record_quality=eb_raw["record_quality"],
            lead_quality=dict(eb_raw["lead_quality"]),
            rejected_leads=tuple(eb_raw.get("rejected_leads", ())),
            derived_leads_invalidated=tuple(eb_raw.get("derived_leads_invalidated", ())),
            reason_codes=tuple(eb_raw.get("reason_codes", ())),
            noiseguard_discard_record=eb_raw.get("noiseguard_discard_record", False),
            noiseguard_bad_leads=tuple(eb_raw.get("noiseguard_bad_leads", ())),
            data_integrity_failure=eb_raw.get("data_integrity_failure", False),
            integrity_failure_type=eb_raw.get("integrity_failure_type"),
        )
        return cls(
            record_id=d["record_id"],
            group=d["group"],
            fs=d["fs"],
            n_samples=d["n_samples"],
            clinical_parent=cp,
            corruption_truth=ct,
            expected_behaviour=eb,
        )
