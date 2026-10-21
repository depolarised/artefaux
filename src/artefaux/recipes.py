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
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

from .amplitude import amplitude_record
from .constants import CANONICAL_LEAD_ORDER, DERIVED_LIMB_LEADS, LEAD_INDEX, TARGET_FS
from .electrode_domain import corrupt_electrode_domain, derive_limb_leads_from_I_II
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
from .mixing import _dc_removed_power, measured_snr_db, mix_lead
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


def _taper_interior_edges(noise: np.ndarray, start: int, end: int, n: int, ramp: int) -> np.ndarray:
    """Remove the noise median and fade it in/out over edges inside the record.

    Without this, a noise segment switched on mid-record adds an instantaneous baseline
    step at the boundary, a synthetic tell absent from recorded artefact. Edges at the
    record start or end are left as they are. The SNR is then set on the tapered trace.
    """
    out = np.asarray(noise, dtype=np.float64) - np.median(noise)
    ramp = min(ramp, out.size // 2)
    if ramp > 0:
        rise = 0.5 - 0.5 * np.cos(np.pi * (np.arange(ramp) + 0.5) / ramp)
        if start > 0:
            out[:ramp] *= rise
        if end < n:
            out[-ramp:] *= rise[::-1]
    return out


def _propagate_derived(before: np.ndarray, after: np.ndarray) -> tuple[str, ...]:
    """Carry changes in I and II into III/aVR/aVL/aVF, in place; return the leads changed.

    A cart stores I and II and derives the other limb leads, so an acquisition-channel
    change to I or II must reach them too. Adding the derived *change* (the relations are
    linear) leaves every untouched sample bit-identical.
    """
    d_i = after[LEAD_INDEX["I"]] - before[LEAD_INDEX["I"]]
    d_ii = after[LEAD_INDEX["II"]] - before[LEAD_INDEX["II"]]
    if not (np.any(d_i) or np.any(d_ii)):
        return ()
    changed = []
    for name, delta in zip(DERIVED_LIMB_LEADS, derive_limb_leads_from_I_II(d_i, d_ii), strict=True):
        if np.any(delta):
            after[LEAD_INDEX[name]] = before[LEAD_INDEX[name]] + delta
            changed.append(name)
    return tuple(changed)


def _reject_direct_derived_change(before: np.ndarray, after: np.ndarray, step: dict) -> None:
    """Refuse a propagating step that also edits III/aVR/aVL/aVF itself.

    :func:`_propagate_derived` overwrites the derived limb leads with the change implied
    by I and II, so a direct edit to one of them would be silently discarded.
    """
    direct = [
        name
        for name in DERIVED_LIMB_LEADS
        if not np.array_equal(before[LEAD_INDEX[name]], after[LEAD_INDEX[name]], equal_nan=True)
    ]
    if direct:
        raise ValueError(
            f"propagate_derived step {step['op']!r} changed derived limb lead(s) {direct} "
            "itself, and propagation would overwrite them; restrict its leads to I and II"
        )


def _electrode_nstdb(
    sig: np.ndarray, step: dict, rng: np.random.Generator, fs: int, noise_provider: NoiseProvider
) -> tuple[np.ndarray, CorruptionStep]:
    """Recorded NSTDB noise on limb electrodes, propagated through the lead algebra.

    The SNR is a power ratio on the bipolar limb leads among I and II that the electrodes
    change: mean clean power over mean added-noise power across those leads. One scale
    factor is shared by every electrode. It is solved from a unit-scale propagation, so
    the requested SNR holds exactly even when two noised electrodes share a lead.
    """
    electrodes = list(step["electrodes"])
    n = sig.shape[1]
    start, end = _interval_samples(step.get("interval_s"), n, fs)
    sources = step["noise_sources"]
    if len(sources) != len(electrodes) or set(electrodes) - {"RA", "LA", "LL"}:
        raise ValueError("electrode_nstdb needs limb electrodes and one noise source each")
    unit = {}
    for e, src in zip(electrodes, sources, strict=True):
        trace = noise_provider({**step, "noise_source": dict(src)}, end - start, rng)
        unit[e] = np.zeros(n)
        unit[e][start:end] = trace - np.median(trace)
    ref_leads = sorted(
        {ld for e in electrodes for ld in {"RA": ("I", "II"), "LA": ("I",), "LL": ("II",)}[e]},
        key=lambda x: LEAD_INDEX[x],
    )
    unit_noise = corrupt_electrode_domain(sig, unit).signal - sig
    ref = [LEAD_INDEX[ld] for ld in ref_leads]
    px = float(np.mean([_dc_removed_power(sig[i, start:end]) for i in ref]))
    pn = float(np.mean([_dc_removed_power(unit_noise[i, start:end]) for i in ref]))
    snr = float(step["snr_db"])
    alpha = float(np.sqrt(px / (pn * 10.0 ** (snr / 10.0)))) if pn > 0 else 0.0
    res = corrupt_electrode_domain(sig, {e: alpha * art for e, art in unit.items()})
    added = res.signal - sig
    snr_measured = 10.0 * np.log10(
        px / float(np.mean([_dc_removed_power(added[i, start:end]) for i in ref]))
    )
    per_lead = {
        ld: measured_snr_db(
            sig[LEAD_INDEX[ld], start:end],
            res.signal[LEAD_INDEX[ld], start:end] - sig[LEAD_INDEX[ld], start:end],
        )
        for ld in res.leads_changed
    }
    entry = CorruptionStep(
        op="electrode_nstdb",
        leads_affected=res.leads_changed,
        electrodes_affected=res.electrodes_corrupted,
        noise_type=step.get("noise_type"),
        noise_source_record=sources[0].get("record"),
        noise_source_start_sample=sources[0].get("start_sample"),
        interval_s=(start / fs, end / fs),
        snr_requested_db=snr,
        snr_measured_db=float(snr_measured),
        alpha=alpha,
        params={
            "snr_reference_leads": ref_leads,
            "noise_sources": [dict(s) for s in sources],
            "snr_measured_db_per_lead": per_lead,
            "derived_leads_invalidated": list(res.derived_leads_invalidated),
            "corruption_domain": "electrode",
        },
    )
    return res.signal, entry


# A limb-electrode swap as an exact signed permutation of the *stored* leads. Derived from
# the electrode potentials (I=LA-RA, II=LL-RA, III=LL-LA, aVR=RA-(LA+LL)/2,
# aVL=LA-(RA+LL)/2, aVF=LL-(RA+LA)/2): each target lead maps to ``(source lead, sign)``.
# Nothing is recomputed, so records that are not Einthoven-exact (independently stored
# leads) keep their own samples, and the lead blind to the swap keeps its stored trace.
_SWAP_PERMUTATIONS: dict[frozenset[str], dict[str, tuple[str, int]]] = {
    frozenset({"LA", "RA"}): {
        "I": ("I", -1),
        "II": ("III", 1),
        "III": ("II", 1),
        "aVR": ("aVL", 1),
        "aVL": ("aVR", 1),
        "aVF": ("aVF", 1),
    },
    frozenset({"LA", "LL"}): {
        "I": ("II", 1),
        "II": ("I", 1),
        "III": ("III", -1),
        "aVR": ("aVR", 1),
        "aVL": ("aVF", 1),
        "aVF": ("aVL", 1),
    },
    frozenset({"RA", "LL"}): {
        "I": ("III", -1),
        "II": ("II", -1),
        "III": ("I", -1),
        "aVR": ("aVF", 1),
        "aVL": ("aVL", 1),
        "aVF": ("aVR", 1),
    },
}


def _electrode_swap(sig: np.ndarray, step: dict) -> tuple[np.ndarray, CorruptionStep]:
    """Swap two limb electrodes (a cable reversal): a non-noise confounder.

    ``leads_affected`` lists the leads whose stored samples actually change. The chest
    leads and the lead blind to the swap are copied bit-for-bit from the input.
    """
    a, b = step["electrodes"]
    if a == b or {a, b} - {"RA", "LA", "LL"}:
        raise ValueError(f"electrode_swap needs two distinct limb electrodes, got {a}, {b}")
    out = sig.copy()
    for target, (source, sign) in _SWAP_PERMUTATIONS[frozenset({a, b})].items():
        out[LEAD_INDEX[target]] = sign * sig[LEAD_INDEX[source]]
    changed = tuple(
        ld
        for ld in CANONICAL_LEAD_ORDER
        if not np.array_equal(out[LEAD_INDEX[ld]], sig[LEAD_INDEX[ld]])
    )
    entry = CorruptionStep(
        op="electrode_swap",
        leads_affected=changed,
        electrodes_affected=(a, b),
        params={
            "lead_reversal": f"{a}/{b}",
            "data_integrity_failure": False,
            "integrity_failure_type": None,
        },
    )
    return out, entry


def apply_recipe(
    signal: np.ndarray,
    steps: Sequence[dict],
    rng: np.random.Generator,
    fs: int,
    noise_provider: NoiseProvider,
) -> tuple[np.ndarray, list[CorruptionStep]]:
    """Apply a list of corruption steps in order, returning the signal and truth log.

    A step with ``"propagate_derived": True`` also carries its changes to leads I and II
    into the derived limb leads (see :func:`_propagate_derived`).
    """
    sig = signal.copy()
    n = sig.shape[1]
    log: list[CorruptionStep] = []

    for step in steps:
        before = sig.copy() if step.get("propagate_derived") else None
        sig = _apply_step(sig, step, rng, fs, noise_provider, log, n)
        if before is not None:
            _reject_direct_derived_change(before, sig, step)
            derived = _propagate_derived(before, sig)
            last = log[-1]
            log[-1] = replace(
                last,
                leads_affected=tuple(
                    sorted(set(last.leads_affected) | set(derived), key=lambda x: LEAD_INDEX[x])
                ),
                params={**last.params, "derived_leads_propagated": list(derived)},
            )

    return sig, log


def _apply_step(
    sig: np.ndarray,
    step: dict,
    rng: np.random.Generator,
    fs: int,
    noise_provider: NoiseProvider,
    log: list[CorruptionStep],
    n: int,
) -> np.ndarray:
    """Apply one step, append its truth entry to ``log`` and return the new signal."""
    op = step["op"]
    if op == "electrode_nstdb":
        sig, entry = _electrode_nstdb(sig, step, rng, fs, noise_provider)
        log.append(entry)
        return sig
    if op == "electrode_swap":
        sig, entry = _electrode_swap(sig, step)
        log.append(entry)
        return sig

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
        taper = step.get("taper_s")
        if taper:
            noise = _taper_interior_edges(noise, start, end, n, int(round(taper * fs)))
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
                params={"leads": leads, **({"taper_s": taper} if taper else {})},
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
            amp_records.append(amplitude_record(lead, before, sig[idx], fs, rail_mv=rail).as_dict())
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

    return sig


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
