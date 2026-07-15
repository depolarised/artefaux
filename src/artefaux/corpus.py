# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The Artefaux v1 corpus definition, as data.

``build_corpus_specs()`` returns all ~67 record specs: 15 naturally-poor,
30 real-noise pairs across the SNR ladder, and 22 engineering extremes split into
single-lead and multi-lead-mixed failures. Source record IDs are left ``None`` here;
they are resolved against the user's PhysioNet copy by the selection step (see
``scripts/select_sources.py``) and pinned in ``provenance.json``.

This module is the single source of truth for the corpus; ``recipes/corpus.yaml``
is generated from it so the two never drift.
"""

from __future__ import annotations

from dataclasses import asdict

import yaml

from .constants import CHEST_LEADS, CORPUS_PREFIX, LIMB_LEADS, SNR_LADDER_DB
from .recipes import RecordSpec, SourceSpec

# Rhythm/morphology spread for the real-noise parents (draft table, condensed).
_RHYTHMS = ("sinus", "afib", "pac_pvc", "bbb_conduction", "st_t", "flutter_svt")
_NOISE_TYPES = ("em", "ma", "bw")


def _rid(prefix: str, i: int) -> str:
    return f"{CORPUS_PREFIX}_{prefix}_{i:03d}"


# --- 15 naturally poor ------------------------------------------------------


_POOR_FLAG_CYCLE = (
    ("electrodes_problems",),
    ("static_noise", "burst_noise"),
    ("baseline_drift",),
    ("static_noise",),
    ("burst_noise", "baseline_drift"),
    ("electrodes_problems", "static_noise"),
)


def _naturally_poor() -> list[RecordSpec]:
    """15 naturally-noisy PTB-XL records, selected by technical-validation quality flags.

    All 15 come from PTB-XL's technical-validation quality flags
    (``static_noise`` / ``burst_noise`` / ``baseline_drift`` / ``electrodes_problems``),
    which mark ~5k genuinely noisy real 12-lead ECGs under an open licence.
    """
    specs: list[RecordSpec] = []
    for i in range(15):
        flags = _POOR_FLAG_CYCLE[i % len(_POOR_FLAG_CYCLE)]
        severe = "electrodes_problems" in flags and i % 3 == 0
        specs.append(
            RecordSpec(
                record_id=_rid("nat", i + 1),
                group="naturally_poor",
                source=SourceSpec(
                    dataset="ptbxl", ptbxl_quality_flags=flags, rhythm_class="unknown"
                ),
                seed_index=100 + i,
                steps=(),
                expected={
                    "record_quality": "reject" if severe else "limited",
                    "lead_quality": {"default": "bad" if severe else "borderline"},
                    "noiseguard_discard": severe,
                    "reason_codes": ["GATE_REJECT"] if severe else [],
                },
            )
        )
    return specs


# --- 30 real-noise pairs ----------------------------------------------------


def _real_noise_expected(snr: int, leads: str) -> dict:
    if snr <= -6:
        rq, dq, discard = "reject", "bad", True
    elif snr == 0:
        rq, dq, discard = "limited", "borderline", True
    elif snr == 6:
        rq, dq, discard = "limited", "borderline", False
    else:  # 12, 18 dB
        rq, dq, discard = "diagnostic", "good", False

    if leads == "all":
        return {
            "record_quality": rq,
            "lead_quality": {"default": dq},
            "noiseguard_discard": discard,
        }
    # Subset contamination: only the touched leads degrade.
    touched = CHEST_LEADS if leads == "chest" else LIMB_LEADS
    rq_sub = "diagnostic" if snr >= 12 else "limited"
    return {
        "record_quality": rq_sub,
        "lead_quality": {"default": "good", "overrides": {ld: dq for ld in touched}},
        "noiseguard_discard": discard and snr <= 0,
    }


def _real_noise() -> list[RecordSpec]:
    specs: list[RecordSpec] = []
    lead_scopes = ("all", "limb", "chest")
    for i in range(30):
        snr = SNR_LADDER_DB[i % len(SNR_LADDER_DB)]
        rhythm = _RHYTHMS[i % len(_RHYTHMS)]
        noise = _NOISE_TYPES[i % len(_NOISE_TYPES)]
        scope = lead_scopes[i % 3]
        if scope == "all":
            leads: str | list[str] = "all"
        elif scope == "limb":
            leads = list(LIMB_LEADS)
        else:
            leads = list(CHEST_LEADS)
        specs.append(
            RecordSpec(
                record_id=_rid("noise", i + 1),
                group="real_noise",
                source=SourceSpec(dataset="ptbxl", rhythm_class=rhythm),
                seed_index=200 + i,
                has_clean_parent=True,
                steps=(
                    {
                        "op": "nstdb_mix",
                        "leads": leads,
                        "noise_type": noise,
                        "snr_db": snr,
                        "noise_source": {"record": noise, "channel": 0},
                    },
                ),
                expected=_real_noise_expected(snr, scope),
            )
        )
    return specs


# --- 22 engineering extremes (11 single-lead + 11 multi-lead) ---------------


def _limited(overrides: dict, **extra) -> dict:
    base = {
        "record_quality": "limited",
        "lead_quality": {"default": "good", "overrides": overrides},
    }
    base.update(extra)
    return base


def _engineering() -> list[RecordSpec]:
    # (id_suffix, steps, expected)
    single: list[tuple[str, tuple[dict, ...], dict]] = [
        ("emg_v1", ({"op": "swing", "leads": ["V1"], "p2p_mv": 6.0},), _limited({"V1": "bad"})),
        (
            "macecg_walk_v2",
            ({"op": "motion_swing", "leads": ["V2"], "p2p_mv": 8.0, "noise_type": "walk"},),
            _limited({"V2": "bad"}),
        ),
        (
            "intermittent_v6",
            ({"op": "intermittent_lead_off", "leads": ["V6"]},),
            _limited(
                {"V6": "bad"},
                data_integrity_failure=True,
                integrity_failure_type="intermittent_lead_off",
            ),
        ),
        (
            "step_ii",
            ({"op": "step_recovery", "leads": ["II"], "step_mv": 4.0, "tau_s": 1.0},),
            _limited({"II": "borderline"}),
        ),
        (
            "macecg_jump_overload_v3",
            (
                {
                    "op": "motion_swing",
                    "leads": ["V3"],
                    "p2p_mv": 30.0,
                    "rail_mv": 5.0,
                    "noise_type": "jump",
                },
            ),
            _limited(
                {"V3": "bad"}, data_integrity_failure=True, integrity_failure_type="rail_saturation"
            ),
        ),
        (
            "flatline_v4",
            ({"op": "flatline", "leads": ["V4"]},),
            _limited(
                {"V4": "bad"}, data_integrity_failure=True, integrity_failure_type="flatline_zero"
            ),
        ),
        (
            "constant_v5",
            ({"op": "constant_adc", "leads": ["V5"], "value_mv": 1.2},),
            _limited(
                {"V5": "bad"}, data_integrity_failure=True, integrity_failure_type="constant_adc"
            ),
        ),
        (
            "missing_v6",
            ({"op": "digital_missing", "leads": ["V6"]},),
            _limited(
                {"V6": "bad"},
                data_integrity_failure=True,
                integrity_failure_type="digital_missing_channel",
            ),
        ),
        (
            "flatline_i",
            ({"op": "flatline", "leads": ["I"]},),
            _limited(
                {"I": "bad", "III": "bad", "aVR": "bad", "aVL": "bad", "aVF": "bad"},
                data_integrity_failure=True,
                integrity_failure_type="flatline_zero",
                derived_leads_invalidated=["III", "aVR", "aVL", "aVF"],
                reason_codes=[
                    "LEAD_I_BAD",
                    "DERIVED_LIMB_LEADS_CONTAMINATED",
                    "FULL_12_LEAD_INTERPRETATION_NOT_ALLOWED",
                ],
            ),
        ),
        (
            "leadoff_v2",
            ({"op": "lead_off", "leads": ["V2"]},),
            _limited({"V2": "bad"}, data_integrity_failure=True, integrity_failure_type="lead_off"),
        ),
        (
            "emg_burst_v5",
            ({"op": "swing", "leads": ["V5"], "p2p_mv": 5.0, "interval_s": [3.0, 6.0]},),
            _limited({"V5": "borderline"}),
        ),
    ]
    multi: list[tuple[str, tuple[dict, ...], dict]] = [
        (
            "couple_v1v2",
            ({"op": "precordial", "shared_weights": {"V1": 0.8, "V2": 0.7}, "snr_db": 0.0},),
            _limited({"V1": "bad", "V2": "bad"}),
        ),
        (
            "couple_v4v5",
            ({"op": "precordial", "shared_weights": {"V4": 0.8, "V5": 0.7}, "snr_db": 6.0},),
            _limited({"V4": "borderline", "V5": "borderline"}),
        ),
        (
            "triple_v1v2v3",
            (
                {
                    "op": "precordial",
                    "shared_weights": {"V1": 0.7, "V2": 0.7, "V3": 0.7},
                    "snr_db": -6.0,
                },
            ),
            _limited({"V1": "bad", "V2": "bad", "V3": "bad"}, noiseguard_discard=True),
        ),
        (
            "electrode_la",
            ({"op": "electrode", "electrode": "LA", "kind": "motion", "amplitude_mv": 1.0},),
            _limited(
                {
                    "I": "bad",
                    "III": "bad",
                    "aVR": "bad",
                    "aVL": "bad",
                    "V1": "borderline",
                    "V2": "borderline",
                    "V3": "borderline",
                    "V4": "borderline",
                    "V5": "borderline",
                    "V6": "borderline",
                },
                noiseguard_discard=True,
                derived_leads_invalidated=["III", "aVR", "aVL"],
                reason_codes=["LEAD_I_BAD", "DERIVED_LIMB_LEADS_CONTAMINATED"],
            ),
        ),
        (
            "electrode_ra",
            ({"op": "electrode", "electrode": "RA", "kind": "offset", "amplitude_mv": 3.0},),
            {
                "record_quality": "reject",
                "lead_quality": {
                    "default": "borderline",
                    "overrides": {
                        "I": "bad",
                        "II": "bad",
                        "III": "bad",
                        "aVR": "bad",
                        "aVL": "bad",
                        "aVF": "bad",
                    },
                },
                "noiseguard_discard": True,
                "derived_leads_invalidated": ["III", "aVR", "aVL", "aVF"],
                "reason_codes": ["BOTH_LIMB_LEADS_BAD", "GATE_REJECT"],
            },
        ),
        (
            "saturate_v2v3",
            ({"op": "swing", "leads": ["V2", "V3"], "p2p_mv": 30.0, "rail_mv": 5.0},),
            _limited(
                {"V2": "bad", "V3": "bad"},
                data_integrity_failure=True,
                integrity_failure_type="rail_saturation",
            ),
        ),
        (
            "saturate_v4v5v6",
            ({"op": "swing", "leads": ["V4", "V5", "V6"], "p2p_mv": 30.0, "rail_mv": 5.0},),
            _limited(
                {"V4": "bad", "V5": "bad", "V6": "bad"},
                noiseguard_discard=True,
                data_integrity_failure=True,
                integrity_failure_type="rail_saturation",
            ),
        ),
        (
            "electrode_ll",
            ({"op": "electrode", "electrode": "LL", "kind": "motion", "amplitude_mv": 1.2},),
            _limited(
                {
                    "II": "bad",
                    "III": "bad",
                    "aVF": "bad",
                    "V1": "borderline",
                    "V4": "borderline",
                    "V6": "borderline",
                },
                noiseguard_discard=True,
                derived_leads_invalidated=["III", "aVR", "aVL", "aVF"],
                reason_codes=["LEAD_II_BAD", "DERIVED_LIMB_LEADS_CONTAMINATED"],
            ),
        ),
        (
            "compound_wild",
            (
                {"op": "electrode", "electrode": "LA", "kind": "motion", "amplitude_mv": 0.8},
                {"op": "motion_swing", "leads": ["V2"], "p2p_mv": 8.0, "noise_type": "walk"},
                {"op": "lead_off", "leads": ["V5"], "interval_s": [4.0, 7.0]},
            ),
            _limited(
                {
                    "I": "bad",
                    "III": "bad",
                    "aVL": "bad",
                    "V2": "bad",
                    "V5": "bad",
                    "V1": "borderline",
                    "V3": "borderline",
                },
                noiseguard_discard=True,
                data_integrity_failure=True,
                integrity_failure_type="lead_off",
            ),
        ),
        (
            "reversal_i",
            ({"op": "opposite_polarity", "leads": ["I"]},),
            _limited({"I": "borderline"}, reason_codes=["LEAD_REVERSAL_SUSPECTED"]),
        ),
        (
            "mixed_integrity",
            (
                {"op": "digital_missing", "leads": ["V1"]},
                {"op": "swing", "leads": ["V6"], "p2p_mv": 25.0, "rail_mv": 5.0},
                {"op": "step_recovery", "leads": ["II"], "step_mv": 3.0, "tau_s": 1.5},
            ),
            _limited(
                {"V1": "bad", "V6": "bad", "II": "borderline"},
                data_integrity_failure=True,
                integrity_failure_type="digital_missing_channel",
            ),
        ),
    ]

    specs: list[RecordSpec] = []
    idx = 0
    for suffix, steps, expected in single + multi:
        idx += 1
        specs.append(
            RecordSpec(
                record_id=f"{CORPUS_PREFIX}_eng_{idx:03d}_{suffix}",
                group="engineering",
                source=SourceSpec(dataset="ptbxl", rhythm_class="sinus"),
                seed_index=300 + idx,
                has_clean_parent=True,
                steps=tuple(steps),
                expected=expected,
            )
        )
    return specs


def build_corpus_specs() -> list[RecordSpec]:
    """Return the full Artefaux v1 corpus definition (~67 records)."""
    return _naturally_poor() + _real_noise() + _engineering()


def specs_to_yaml(specs: list[RecordSpec], master_seed: int) -> str:
    """Serialize specs to the ``recipes/corpus.yaml`` format."""
    payload = {
        "version": 1,
        "master_seed": master_seed,
        "target_fs": 500,
        "records": [
            {**asdict(s), "source": asdict(s.source), "steps": [dict(st) for st in s.steps]}
            for s in specs
        ],
    }
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
