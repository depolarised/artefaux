# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The T1 benchmark definition: composition, held-out noise, and physically consistent leads."""

from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from artefaux.benchmark import (
    CONFOUNDER_CODES,
    FULL_SNR_DB,
    HALF_SNR_DB,
    INDEPENDENT_LEADS,
    LIMB_LEADS,
    N_CLEAN_PARENTS,
    N_RECORDS,
    NATURAL_FLAGS,
    NOISE_TYPES,
    NSTDB_RESAMPLED_LEN,
    NSTDB_SLOT,
    NSTDB_TEST_START,
    SCOPES,
    STRATA,
    build_bench_specs,
    select_bench_sources,
    stratum_of,
)
from artefaux.constants import CANONICAL_LEAD_ORDER, CHEST_LEADS, DERIVED_LIMB_LEADS, LEAD_INDEX
from artefaux.corpus import build_corpus_specs
from artefaux.electrode_domain import derive_limb_leads_from_I_II
from artefaux.recipes import SourceSpec, build_record
from artefaux.review import build_review_specs

SEED = 12345


def bench_specs():
    clean = [SourceSpec("ptbxl", f"clean_{i}") for i in range(N_CLEAN_PARENTS)]
    confounders = {
        name: [SourceSpec("ptbxl", f"{name}_{i}") for i in range(n)]
        for name, (_, n) in CONFOUNDER_CODES.items()
    }
    natural = [SourceSpec("ptbxl", f"natural_{i}") for i in range(10)]
    return build_bench_specs(clean, confounders, natural, master_seed=SEED)


def _derived_consistent(sig: np.ndarray) -> bool:
    expected = derive_limb_leads_from_I_II(sig[LEAD_INDEX["I"]], sig[LEAD_INDEX["II"]])
    return all(
        np.allclose(sig[LEAD_INDEX[name]], value, atol=1e-9)
        for name, value in zip(("III", "aVR", "aVL", "aVF"), expected, strict=True)
    )


def test_composition_and_separation_from_development_sets():
    specs = bench_specs()
    assert len(specs) == N_RECORDS == sum(STRATA.values())
    ids = {s.record_id for s in specs}
    assert len(ids) == N_RECORDS
    dev_ids = {s.record_id for s in build_corpus_specs()} | {
        s.record_id for s in build_review_specs([SourceSpec("ptbxl", f"r{i}") for i in range(85)])
    }
    assert not ids & dev_ids
    assert Counter(stratum_of(s.record_id) for s in specs) == Counter(STRATA)
    assert len({s.seed_index for s in specs}) == N_RECORDS


def test_noise_type_is_crossed_with_scope_and_snr():
    full = [s for s in bench_specs() if stratum_of(s.record_id) == "full_noise"]
    cells = Counter(
        (s.steps[0]["noise_type"], tuple(s.steps[0]["leads"]), s.steps[0]["snr_db"]) for s in full
    )
    expected = {(nt, SCOPES[sc], snr) for nt in NOISE_TYPES for sc in SCOPES for snr in FULL_SNR_DB}
    assert set(cells) == expected and set(cells.values()) == {1}
    half = [s for s in bench_specs() if stratum_of(s.record_id) == "half_noise"]
    assert {s.steps[0]["snr_db"] for s in half} == {HALF_SNR_DB}
    assert Counter(tuple(s.steps[0]["interval_s"]) for s in half) == {(0, 5): 6, (5, 10): 6}


def test_nstdb_segments_are_held_out_and_never_overlap():
    # The two channels of an NSTDB record are simultaneous, so segments are disjoint per
    # record across both channels, not per (record, channel).
    used: dict[str, list[int]] = {}
    for spec in bench_specs():
        for step in spec.steps:
            sources = step.get("noise_sources") or (
                [step["noise_source"]] if "noise_source" in step else []
            )
            for src in sources:
                used.setdefault(src["record"], []).append(src["start_sample"])
    assert sum(len(v) for v in used.values()) == 54 + 12 + 10  # RA+LL electrode records use two
    for starts in used.values():
        starts = sorted(starts)
        assert starts[0] >= NSTDB_TEST_START  # development sets used offsets < 100 000
        assert starts[-1] + NSTDB_SLOT <= NSTDB_RESAMPLED_LEN
        assert all(b - a >= NSTDB_SLOT for a, b in zip(starts, starts[1:], strict=False))


def test_signals_change_only_where_and_how_the_recipe_says(ecg12):
    for spec in bench_specs():
        signal, label = build_record(ecg12, spec, SEED, 500)
        stratum = stratum_of(spec.record_id)
        if not spec.steps:
            assert np.array_equal(signal, ecg12)
            continue
        assert _derived_consistent(signal), spec.record_id
        step = spec.steps[0]
        changed = {
            name
            for name in CANONICAL_LEAD_ORDER
            if not np.array_equal(signal[LEAD_INDEX[name]], ecg12[LEAD_INDEX[name]])
        }
        assert changed == set(label.corruption_truth.leads_with_any_corruption), spec.record_id
        if "leads" in step:
            # A change to I or II reaches all four derived limb leads; a chest-only change
            # reaches none. Dropping propagate_derived fails the first branch.
            if {"I", "II"} & set(step["leads"]):
                assert set(DERIVED_LIMB_LEADS) <= changed, spec.record_id
            else:
                assert not set(LIMB_LEADS) & changed, spec.record_id
        if stratum in ("full_noise", "half_noise"):
            start, stop = (int(t * 500) for t in step["interval_s"])
            assert np.array_equal(signal[:, :start], ecg12[:, :start])
            assert np.array_equal(signal[:, stop:], ecg12[:, stop:])
            if not {"I", "II"} & set(step["leads"]):
                assert changed == set(step["leads"])


def test_electrode_noise_hits_the_requested_snr_and_reaches_the_chest_leads(ecg12):
    electrode = [s for s in bench_specs() if stratum_of(s.record_id) == "electrode_noise"]
    assert len(electrode) == 8
    for spec in electrode:
        signal, label = build_record(ecg12, spec, SEED, 500)
        step = label.corruption_truth.steps[0]
        assert step.snr_measured_db == pytest.approx(spec.steps[0]["snr_db"], abs=1e-6)
        # A limb electrode moves the Wilson central terminal, so every V lead changes.
        assert set(INDEPENDENT_LEADS[2:]) <= set(step.leads_affected)


def test_lead_reversal_is_a_physical_electrode_swap(ecg12):
    reversal = [s for s in bench_specs() if s.record_id.startswith("nlf_bench1_confounder_rev")]
    assert [s.steps[0]["electrodes"] for s in reversal] == [
        ["LA", "RA"],
        ["LA", "LL"],
        ["RA", "LL"],
    ]
    signal, label = build_record(ecg12, reversal[0], SEED, 500)
    lead = {name: signal[LEAD_INDEX[name]] for name in CANONICAL_LEAD_ORDER}
    orig = {name: ecg12[LEAD_INDEX[name]] for name in CANONICAL_LEAD_ORDER}
    assert np.allclose(lead["I"], -orig["I"])
    assert np.allclose(lead["II"], orig["III"])
    assert np.allclose(lead["aVR"], orig["aVL"])
    assert np.allclose(lead["aVF"], orig["aVF"])
    for v in INDEPENDENT_LEADS[2:]:
        assert np.array_equal(lead[v], orig[v])
    assert not label.expected_behaviour.data_integrity_failure


def test_integrity_faults_propagate_to_derived_limb_leads(ecg12):
    flat_i = next(
        s
        for s in bench_specs()
        if s.steps and s.steps[0]["op"] == "flatline" and s.steps[0]["leads"] == ["I"]
    )
    signal, label = build_record(ecg12, flat_i, SEED, 500)
    assert np.all(signal[LEAD_INDEX["I"]] == 0)
    assert np.allclose(signal[LEAD_INDEX["III"]], ecg12[LEAD_INDEX["II"]])  # III = II - I
    assert label.expected_behaviour.integrity_failure_type == "flatline_zero"


def test_authored_labels_cover_every_changed_limb_lead(ecg12):
    """Every limb lead the recipe changes is authored, with one quality per source lead.

    Integrity faults and limb-electrode noise are authored non-good at every SNR. Noise on
    I or II is authored non-good below +3 dB. At +3 and +6 dB the hypothesis is 'good' by
    design (noise below the set-1 decision boundary), so there the test requires 'good'
    rather than non-good. Electrode swaps are confounders, not noise, and are skipped.
    """
    checked = 0
    for spec in bench_specs():
        if not spec.steps or spec.steps[0]["op"] == "electrode_swap":
            continue
        step = spec.steps[0]
        _, label = build_record(ecg12, spec, SEED, 500)
        stratum = stratum_of(spec.record_id)
        expected = label.expected_behaviour
        changed_limb = {
            ld for ld in label.corruption_truth.leads_with_any_corruption if ld in LIMB_LEADS
        }
        authored = spec.expected["lead_quality"]["overrides"]
        assert {ld for ld in authored if ld in LIMB_LEADS} == changed_limb, spec.record_id
        assert set(expected.derived_leads_invalidated) == changed_limb & set(DERIVED_LIMB_LEADS)
        if not changed_limb:
            continue
        checked += 1
        # Derived leads share the quality of the lead they came from (one value for all).
        assert len({expected.lead_quality[ld] for ld in changed_limb}) == 1, spec.record_id
        hypothesis_good = stratum in ("full_noise", "half_noise") and step["snr_db"] >= 3
        for ld in changed_limb:
            if hypothesis_good:
                assert expected.lead_quality[ld] == "good", (spec.record_id, ld)
            else:
                assert expected.lead_quality[ld] != "good", (spec.record_id, ld)
    assert checked == 5 + 42 + 8  # integrity with I/II, noise on I/II or all, electrode


def test_electrode_noise_authors_the_wct_rule_for_chest_leads(ecg12):
    electrode = [s for s in bench_specs() if stratum_of(s.record_id) == "electrode_noise"]
    for spec in electrode:
        signal, label = build_record(ecg12, spec, SEED, 500)
        snr = spec.steps[0]["snr_db"]
        expected = label.expected_behaviour
        assert "WCT_PROPAGATED_NOISE" in expected.reason_codes
        # The WCT rule: chest leads are borderline only at SNR <= -6 dB, otherwise good.
        chest = {expected.lead_quality[v] for v in CHEST_LEADS}
        assert chest == {"borderline" if snr <= -6 else "good"}, spec.record_id
        assert all(np.any(signal[LEAD_INDEX[v]] != ecg12[LEAD_INDEX[v]]) for v in CHEST_LEADS)


def test_parent_counts_are_validated():
    with pytest.raises(ValueError, match="clean parents"):
        build_bench_specs([], {}, [], master_seed=SEED)


def _row(i, patient, scp="{'NORM': 100.0}", **flags):
    return {
        "ecg_id": str(i),
        "patient_id": str(patient),
        "filename_hr": f"records500/{i:05d}_hr",
        "scp_codes": scp,
        **{k: "" for k in ("baseline_drift", "static_noise", "burst_noise", "electrodes_problems")},
        **flags,
    }


def test_source_selection_excludes_patients_and_never_repeats_one():
    rows, i = [], 0
    for _ in range(N_CLEAN_PARENTS + 20):
        rows.append(_row(i, 1000 + i))
        i += 1
    for code, n in CONFOUNDER_CODES.values():
        for _ in range(n + 2):
            rows.append(_row(i, 1000 + i, scp=f"{{'{code}': 100.0, 'SR': 0.0}}"))
            i += 1
    for flag, n in NATURAL_FLAGS.items():
        for _ in range(n + 1):
            rows.append(_row(i, 1000 + i, **{flag: "yes"}))
            i += 1
    rows.append(_row(i, 1000))  # second ECG of patient 1000
    excluded = {"1001", "1002"}
    clean, confounders, natural = select_bench_sources(rows, excluded_patients=excluded, seed=7)
    chosen = clean + [r for v in confounders.values() for r in v] + natural
    patients = [r["patient_id"] for r in chosen]
    assert len(patients) == len(set(patients)) == N_RECORDS
    assert not excluded & set(patients)
    assert all("AFIB" in r["scp_codes"] for r in confounders["afib"])
    assert not any("AFIB" in r["scp_codes"] or "PACE" in r["scp_codes"] for r in clean)
    with pytest.raises(ValueError, match="eligible"):
        select_bench_sources(rows[:10], excluded_patients=set(), seed=7)


def test_half_record_noise_fades_in_without_a_step(ecg12):
    half = [s for s in bench_specs() if stratum_of(s.record_id) == "half_noise"]
    late = next(s for s in half if s.steps[0]["interval_s"] == [5, 10])
    signal, _ = build_record(ecg12, late, SEED, 500)
    lead = LEAD_INDEX[late.steps[0]["leads"][-1]]
    added = signal[lead] - ecg12[lead]
    assert np.all(added[:2500] == 0)
    # The first added sample is a tiny fraction of the burst, not a baseline jump.
    assert abs(added[2500]) < 0.01 * np.max(np.abs(added))
