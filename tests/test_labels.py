# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Label schema: JSON round-trip and validation."""

from __future__ import annotations

import json

import pytest

from torsade.constants import CANONICAL_LEAD_ORDER
from torsade.labels import (
    ClinicalParentLabel,
    CorruptionStep,
    CorruptionTruthLabel,
    ExpectedBehaviourLabel,
    RecordLabel,
)


def _example_label() -> RecordLabel:
    lead_quality = {ld: "good" for ld in CANONICAL_LEAD_ORDER}
    lead_quality["V2"] = "bad"
    return RecordLabel(
        record_id="torsade_eng_001",
        group="engineering",
        fs=500,
        n_samples=5000,
        clinical_parent=ClinicalParentLabel(
            source_dataset="ptbxl",
            source_record_id="00123_hr",
            rhythm_class="sinus",
            glasgow_statements=("SINUS RHYTHM",),
            has_clean_parent=True,
        ),
        corruption_truth=CorruptionTruthLabel(
            seed=12345,
            steps=(
                CorruptionStep(
                    op="overload_swing",
                    leads_affected=("V2",),
                    interval_s=(0.0, 10.0),
                    params={"rail_mv": 5.0},
                ),
            ),
            leads_with_any_corruption=("V2",),
        ),
        expected_behaviour=ExpectedBehaviourLabel(
            record_quality="limited",
            lead_quality=lead_quality,
            data_integrity_failure=True,
            integrity_failure_type="rail_saturation",
        ),
    )


def test_label_json_roundtrip():
    label = _example_label()
    restored = RecordLabel.from_dict(json.loads(label.to_json()))
    assert restored.record_id == label.record_id
    assert restored.expected_behaviour.lead_quality["V2"] == "bad"
    assert restored.corruption_truth.steps[0].op == "overload_swing"
    assert restored.corruption_truth.steps[0].interval_s == (0.0, 10.0)
    assert restored.expected_behaviour.integrity_failure_type == "rail_saturation"


def test_invalid_record_quality_rejected():
    with pytest.raises(ValueError):
        ExpectedBehaviourLabel(record_quality="great", lead_quality={"I": "good"})


def test_invalid_lead_quality_rejected():
    with pytest.raises(ValueError):
        ExpectedBehaviourLabel(record_quality="diagnostic", lead_quality={"I": "meh"})


def test_invalid_group_rejected():
    with pytest.raises(ValueError):
        RecordLabel(
            record_id="x",
            group="not_a_group",
            fs=500,
            n_samples=1,
            clinical_parent=ClinicalParentLabel("ptbxl", None),
            corruption_truth=CorruptionTruthLabel(seed=0),
            expected_behaviour=ExpectedBehaviourLabel("diagnostic", {"I": "good"}),
        )
