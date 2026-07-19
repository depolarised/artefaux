# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Recipes: declarative corruption specs and the interpreter that applies them.

A :class:`RecordSpec` says *what* to do to a parent (a list of corruption ``steps``)
and *what a good gate should do* about it (``expected``). :func:`apply_recipe`
executes the steps; :func:`build_record` wraps that into a fully-labelled
:class:`~artefaux.labels.RecordLabel`. :func:`build_corpus_specs` returns the whole
Artefaux v2 corpus definition as data — source record IDs are resolved separately
against the user's PhysioNet copy (see ``scripts/`` and ``recipes/source_ids/``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .amplitude import amplitude_record
from .constants import CANONICAL_LEAD_ORDER, LEAD_INDEX, TARGET_FS
from .electrode_domain import corrupt_electrode_domain
from .engineering import (
    build_constant_adc,
    build_digital_missing,
    build_flatline,
    build_intermittent_lead_off,
    build_lead_off,
    build_opposite_polarity,
    build_step_recovery,
    build_swing,
)
from .labels import (
    ClinicalParentLabel,
    CorruptionStep,
    CorruptionTruthLabel,
    ExpectedBehaviourLabel,
    RecordLabel,
)
from .mixing import mix_lead
from .noise_shapes import baseline_trace, emg_trace, motion_trace, powerline_trace
from .precordial import corrupt_precordial
from .provenance import record_rng, seed_for_record

NoiseProvider = Callable[[dict, int, np.random.Generator], np.ndarray]


# --- Synthetic noise provider (used for CI and for source-free controls) ----


def synthetic_noise_provider(step: dict, n: int, rng: np.random.Generator) -> np.ndarray:
    """Return a synthetic single-lead noise trace matching ``step['noise_type']``."""
    noise_type = step.get("noise_type", "em")
    if noise_type == "em":
        return motion_trace(n, TARGET_FS, rng)
    if noise_type == "ma":
        return emg_trace(n, TARGET_FS, rng)
    if noise_type == "bw":
        return baseline_trace(n, TARGET_FS, rng)
    if noise_type == "powerline":
        return powerline_trace(n, TARGET_FS, rng)
    return motion_trace(n, TARGET_FS, rng)


def _resolve_leads(spec_leads: Any) -> list[str]:
    if spec_leads in ("all", None):
        return list(CANONICAL_LEAD_ORDER)
    return list(spec_leads)


def _interval_samples(interval_s: Sequence[float] | None, n: int, fs: int) -> tuple[int, int]:
    if interval_s is None:
        return 0, n
    start = max(0, int(round(interval_s[0] * fs)))
    end = min(n, int(round(interval_s[1] * fs)))
    return start, end


def _shape_trace(kind: str, n: int, rng: np.random.Generator, fs: int) -> np.ndarray:
    if kind == "motion":
        return motion_trace(n, fs, rng)
    if kind == "emg":
        return emg_trace(n, fs, rng)
    if kind == "baseline":
        return baseline_trace(n, fs, rng)
    if kind == "offset":
        return np.ones(n)
    raise ValueError(f"unknown artefact kind: {kind}")


def apply_recipe(
    signal: np.ndarray,
    steps: Sequence[dict],
    rng: np.random.Generator,
    fs: int,
    noise_provider: NoiseProvider,
) -> tuple[np.ndarray, list[CorruptionStep]]:
    """Apply a list of corruption steps in order, returning the signal and truth log."""
    sig = signal.copy()
    n = sig.shape[1]
    log: list[CorruptionStep] = []

    for step in steps:
        op = step["op"]

        if op == "nstdb_mix":
            leads = _resolve_leads(step.get("leads", "all"))
            snr = float(step["snr_db"])
            start, end = _interval_samples(step.get("interval_s"), n, fs)
            duration = end - start
            # Resolve the noise segment offset here (not inside the provider) so the
            # exact source segment is captured in the audit trail. Drawing it from the
            # same rng at this point keeps the output byte-identical to a provider draw.
            src = dict(step.get("noise_source", {}))
            if src.get("start_sample") is None:
                src["start_sample"] = int(rng.integers(0, 100_000))
            noise = noise_provider({**step, "noise_source": src}, duration, rng)
            alphas, measured = [], []
            for lead in leads:
                idx = LEAD_INDEX[lead]
                res = mix_lead(sig[idx], noise, snr, start=start, duration=duration)
                sig[idx] = res.signal
                alphas.append(res.alpha)
                measured.append(res.snr_measured_db)
            log.append(
                CorruptionStep(
                    op=op,
                    leads_affected=tuple(leads),
                    noise_type=step.get("noise_type"),
                    noise_source_record=src.get("record", step.get("noise_type")),
                    noise_source_start_sample=src.get("start_sample"),
                    interval_s=(start / fs, end / fs),
                    snr_requested_db=snr,
                    snr_measured_db=float(np.mean(measured)),
                    alpha=float(np.mean(alphas)),
                    params={"leads": leads},
                )
            )

        elif op == "motion_swing":
            leads = list(step["leads"])
            p2p = float(step["p2p_mv"])
            rail = step.get("rail_mv")
            start, end = _interval_samples(step.get("interval_s"), n, fs)
            amp_records = []
            for lead in leads:
                idx = LEAD_INDEX[lead]
                trace = noise_provider(step, end - start, rng)
                ptp = float(np.ptp(trace)) or 1.0
                seg = sig[idx, start:end] + trace * (p2p / ptp)
                if rail is not None:
                    seg = np.clip(seg, -rail, rail)
                before = sig[idx].copy()
                sig[idx, start:end] = seg
                amp_records.append(
                    amplitude_record(lead, before, sig[idx], fs, rail_mv=rail).as_dict()
                )
            log.append(
                CorruptionStep(
                    op="motion_swing",
                    leads_affected=tuple(leads),
                    noise_type=step.get("noise_type"),
                    interval_s=(start / fs, end / fs),
                    params={
                        "requested_p2p_mv": p2p,
                        "rail_mv": rail,
                        "data_integrity_failure": rail is not None,
                        "integrity_failure_type": "rail_saturation" if rail is not None else None,
                    },
                    amplitude=tuple(amp_records),
                )
            )

        elif op == "precordial":
            res = corrupt_precordial(
                sig,
                dict(step["shared_weights"]),
                float(step["snr_db"]),
                rng,
                fs=fs,
                start=_interval_samples(step.get("interval_s"), n, fs)[0],
                duration=None,
            )
            sig = res.signal
            log.append(
                CorruptionStep(
                    op=op,
                    leads_affected=res.leads_corrupted,
                    snr_requested_db=float(step["snr_db"]),
                    snr_measured_db=float(np.mean(list(res.per_lead_snr_db.values()))),
                    params={"shared_weights": dict(step["shared_weights"])},
                )
            )

        elif op == "electrode":
            electrode = step["electrode"]
            kind = step.get("kind", "motion")
            amp = float(step.get("amplitude_mv", 1.0))
            start, end = _interval_samples(step.get("interval_s"), n, fs)
            trace = np.zeros(n)
            trace[start:end] = amp * _shape_trace(kind, end - start, rng, fs)
            res = corrupt_electrode_domain(sig, {electrode: trace})
            sig = res.signal
            log.append(
                CorruptionStep(
                    op="electrode_domain",
                    leads_affected=res.leads_changed,
                    electrodes_affected=res.electrodes_corrupted,
                    interval_s=(start / fs, end / fs),
                    params={
                        "kind": kind,
                        "amplitude_mv": amp,
                        "derived_leads_invalidated": list(res.derived_leads_invalidated),
                    },
                )
            )

        else:  # engineering builders
            res = _apply_engineering(op, sig, step, rng, fs)
            sig = res.signal
            log.append(
                CorruptionStep(
                    op=res.case_type,
                    leads_affected=res.leads_affected,
                    interval_s=(
                        tuple(res.details["interval_s"]) if "interval_s" in res.details else None
                    ),
                    params={
                        **{k: v for k, v in res.details.items() if k != "amplitude"},
                        "data_integrity_failure": res.data_integrity_failure,
                        "integrity_failure_type": res.integrity_failure_type,
                    },
                    amplitude=tuple(res.details.get("amplitude", ())),
                )
            )

    return sig, log


def _apply_engineering(op: str, sig: np.ndarray, step: dict, rng: np.random.Generator, fs: int):
    leads = step["leads"]
    interval_s = step.get("interval_s")
    if op == "swing":
        return build_swing(
            sig,
            leads,
            float(step["p2p_mv"]),
            rng,
            fs=fs,
            interval_s=interval_s,
            rail_mv=step.get("rail_mv"),
        )
    if op == "flatline":
        return build_flatline(sig, leads, fs=fs, interval_s=interval_s)
    if op == "constant_adc":
        return build_constant_adc(sig, leads, float(step["value_mv"]), fs=fs, interval_s=interval_s)
    if op == "lead_off":
        return build_lead_off(sig, leads, rng, fs=fs, interval_s=interval_s)
    if op == "digital_missing":
        return build_digital_missing(sig, leads, fs=fs, interval_s=interval_s)
    if op == "step_recovery":
        return build_step_recovery(
            sig,
            leads,
            float(step["step_mv"]),
            float(step["tau_s"]),
            fs=fs,
            start_s=float(step.get("start_s", 2.0)),
        )
    if op == "opposite_polarity":
        return build_opposite_polarity(sig, leads, fs=fs)
    if op == "intermittent_lead_off":
        return build_intermittent_lead_off(
            sig,
            leads,
            rng,
            fs=fs,
            n_dropouts=int(step.get("n_dropouts", 3)),
        )
    raise ValueError(f"unknown op: {op}")


# --- Spec containers --------------------------------------------------------


@dataclass(frozen=True)
class SourceSpec:
    dataset: str
    record_id: str | None = None
    rhythm_class: str | None = None
    glasgow_statements: tuple[str, ...] = ()
    ptbxl_quality_flags: tuple[str, ...] = ()
    age_years: float | None = None
    sex: str | None = None


@dataclass(frozen=True)
class RecordSpec:
    record_id: str
    group: str
    source: SourceSpec
    seed_index: int
    steps: tuple[dict, ...] = ()
    expected: dict = field(default_factory=dict)
    has_clean_parent: bool = False


def expand_expected(expected: dict) -> ExpectedBehaviourLabel:
    """Expand a compact ``expected`` block into a full :class:`ExpectedBehaviourLabel`."""
    lq_spec = expected.get("lead_quality", {"default": "good"})
    default = lq_spec.get("default", "good")
    lead_quality = {ld: default for ld in CANONICAL_LEAD_ORDER}
    for ld, val in lq_spec.get("overrides", {}).items():
        lead_quality[ld] = val
    return ExpectedBehaviourLabel(
        record_quality=expected["record_quality"],
        lead_quality=lead_quality,
        rejected_leads=tuple(expected.get("rejected_leads", ())),
        derived_leads_invalidated=tuple(expected.get("derived_leads_invalidated", ())),
        reason_codes=tuple(expected.get("reason_codes", ())),
        noiseguard_discard_record=expected.get("noiseguard_discard", False),
        noiseguard_bad_leads=tuple(expected.get("noiseguard_bad_leads", ())),
        data_integrity_failure=expected.get("data_integrity_failure", False),
        integrity_failure_type=expected.get("integrity_failure_type"),
    )


def build_record(
    parent_signal: np.ndarray,
    spec: RecordSpec,
    master_seed: int,
    fs: int,
    noise_provider: NoiseProvider = synthetic_noise_provider,
) -> tuple[np.ndarray, RecordLabel]:
    """Apply a spec to a parent signal and return ``(signal, RecordLabel)``."""
    rng = record_rng(master_seed, spec.seed_index)
    seed = seed_for_record(master_seed, spec.seed_index)
    sig, steps = apply_recipe(parent_signal, spec.steps, rng, fs, noise_provider)
    corrupted_leads = sorted(
        {ld for st in steps for ld in st.leads_affected}, key=lambda x: LEAD_INDEX[x]
    )
    ct = CorruptionTruthLabel(
        seed=seed, steps=tuple(steps), leads_with_any_corruption=tuple(corrupted_leads)
    )
    cp = ClinicalParentLabel(
        source_dataset=spec.source.dataset,
        source_record_id=spec.source.record_id,
        age_years=spec.source.age_years,
        sex=spec.source.sex,
        rhythm_class=spec.source.rhythm_class,
        glasgow_statements=spec.source.glasgow_statements,
        ptbxl_quality_flags=spec.source.ptbxl_quality_flags,
        has_clean_parent=spec.has_clean_parent,
    )
    label = RecordLabel(
        record_id=spec.record_id,
        group=spec.group,
        fs=fs,
        n_samples=sig.shape[1],
        clinical_parent=cp,
        corruption_truth=ct,
        expected_behaviour=expand_expected(spec.expected),
    )
    return sig, label
