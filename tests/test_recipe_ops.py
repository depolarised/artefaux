# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Limb-electrode swaps as exact lead permutations, and the propagate_derived guard."""

from __future__ import annotations

import numpy as np
import pytest

from artefaux.constants import CANONICAL_LEAD_ORDER, LEAD_INDEX
from artefaux.electrode_domain import Electrodes, electrodes_to_leads, leads_to_electrodes
from artefaux.recipes import apply_recipe, synthetic_noise_provider

FS = 500
LIMB = CANONICAL_LEAD_ORDER[:6]
CHEST = CANONICAL_LEAD_ORDER[6:]

# Derived from the electrode potentials: each target lead -> (stored source lead, sign).
# The invariant lead is the one blind to the swap.
SWAP_CASES = [
    pytest.param(
        ("LA", "RA"),
        {
            "I": ("I", -1),
            "II": ("III", 1),
            "III": ("II", 1),
            "aVR": ("aVL", 1),
            "aVL": ("aVR", 1),
            "aVF": ("aVF", 1),
        },
        "aVF",
        id="LA-RA",
    ),
    pytest.param(
        ("LA", "LL"),
        {
            "I": ("II", 1),
            "II": ("I", 1),
            "III": ("III", -1),
            "aVR": ("aVR", 1),
            "aVL": ("aVF", 1),
            "aVF": ("aVL", 1),
        },
        "aVR",
        id="LA-LL",
    ),
    pytest.param(
        ("RA", "LL"),
        {
            "I": ("III", -1),
            "II": ("II", -1),
            "III": ("I", -1),
            "aVR": ("aVF", 1),
            "aVL": ("aVL", 1),
            "aVF": ("aVR", 1),
        },
        "aVL",
        id="RA-LL",
    ),
]


def _swap(sig: np.ndarray, a: str, b: str) -> tuple[np.ndarray, tuple]:
    steps = [{"op": "electrode_swap", "electrodes": [a, b]}]
    out, log = apply_recipe(sig, steps, np.random.default_rng(0), FS, synthetic_noise_provider)
    return out, log[0].leads_affected


def _algebra_swap(sig: np.ndarray, a: str, b: str) -> np.ndarray:
    """Reference: swap the electrode potentials, then rederive every lead."""
    e = leads_to_electrodes(sig)
    pots = {"RA": e.ra, "LA": e.la, "LL": e.ll}
    pots[a], pots[b] = pots[b], pots[a]
    return electrodes_to_leads(
        Electrodes(ra=pots["RA"], la=pots["LA"], ll=pots["LL"], chest=e.chest)
    )


def _non_einthoven(sig: np.ndarray, seed: int = 7) -> np.ndarray:
    """Perturb III/aVR/aVL/aVF independently, as stored PTB-XL leads often are."""
    rng = np.random.default_rng(seed)
    out = sig.copy()
    for name in ("III", "aVR", "aVL", "aVF"):
        out[LEAD_INDEX[name]] += 1e-3 * rng.standard_normal(sig.shape[1])
    return out


def _lead(sig: np.ndarray, name: str) -> np.ndarray:
    return sig[LEAD_INDEX[name]]


@pytest.mark.parametrize(("pair", "perm", "invariant"), SWAP_CASES)
def test_swap_matches_electrode_algebra_on_einthoven_exact(ecg12, pair, perm, invariant):
    out, _ = _swap(ecg12, *pair)
    expected = _algebra_swap(ecg12, *pair)
    for name in CANONICAL_LEAD_ORDER:
        assert np.allclose(_lead(out, name), _lead(expected, name), rtol=0, atol=1e-12), name


@pytest.mark.parametrize(("pair", "perm", "invariant"), SWAP_CASES)
def test_swap_is_exact_signed_permutation_of_stored_leads(ecg12, pair, perm, invariant):
    sig = _non_einthoven(ecg12)
    out, _ = _swap(sig, *pair)
    for target, (source, sign) in perm.items():
        assert np.array_equal(_lead(out, target), sign * _lead(sig, source)), target


@pytest.mark.parametrize(("pair", "perm", "invariant"), SWAP_CASES)
def test_non_einthoven_swap_keeps_invariant_and_chest_bit_identical(ecg12, pair, perm, invariant):
    sig = _non_einthoven(ecg12)
    out, _ = _swap(sig, *pair)
    assert np.array_equal(_lead(out, invariant), _lead(sig, invariant))
    for name in CHEST:
        assert np.array_equal(_lead(out, name), _lead(sig, name)), name


@pytest.mark.parametrize(("pair", "perm", "invariant"), SWAP_CASES)
@pytest.mark.parametrize("source", ["exact", "non_einthoven"])
def test_leads_affected_is_exactly_the_stored_leads_that_change(
    ecg12, pair, perm, invariant, source
):
    sig = ecg12 if source == "exact" else _non_einthoven(ecg12)
    _, affected = _swap(sig, *pair)
    assert affected == tuple(ld for ld in LIMB if ld != invariant)


@pytest.mark.parametrize(("pair", "perm", "invariant"), SWAP_CASES)
def test_swapping_twice_restores_limb_leads_exactly(ecg12, pair, perm, invariant):
    sig = _non_einthoven(ecg12)
    steps = [{"op": "electrode_swap", "electrodes": list(pair)}] * 2
    out, _ = apply_recipe(sig, steps, np.random.default_rng(0), FS, synthetic_noise_provider)
    assert np.array_equal(out, sig)


@pytest.mark.parametrize("electrodes", [["RA", "RA"], ["RA", "V1"]])
def test_swap_rejects_non_limb_or_repeated_electrodes(ecg12, electrodes):
    with pytest.raises(ValueError, match="electrode_swap"):
        _swap(ecg12, *electrodes)


def test_propagating_step_that_edits_derived_leads_raises(ecg12):
    steps = [
        {
            "op": "nstdb_mix",
            "noise_type": "em",
            "leads": "all",
            "interval_s": [0, 10],
            "snr_db": 0,
            "propagate_derived": True,
        }
    ]
    with pytest.raises(ValueError, match="propagate_derived"):
        apply_recipe(ecg12, steps, np.random.default_rng(0), FS, synthetic_noise_provider)


def test_propagating_step_limited_to_I_and_II_propagates_derived_leads(ecg12):
    steps = [
        {
            "op": "nstdb_mix",
            "noise_type": "em",
            "leads": ["I", "II"],
            "interval_s": [0, 10],
            "snr_db": 0,
            "propagate_derived": True,
        }
    ]
    out, log = apply_recipe(ecg12, steps, np.random.default_rng(0), FS, synthetic_noise_provider)
    d_i = _lead(out, "I") - _lead(ecg12, "I")
    d_ii = _lead(out, "II") - _lead(ecg12, "II")
    assert np.allclose(_lead(out, "III") - _lead(ecg12, "III"), d_ii - d_i)
    assert set(log[0].params["derived_leads_propagated"]) == {"III", "aVR", "aVL", "aVF"}
    for name in CHEST:
        assert np.array_equal(_lead(out, name), _lead(ecg12, name)), name


def test_all_lead_step_without_propagation_still_changes_derived_leads(ecg12):
    steps = [
        {
            "op": "nstdb_mix",
            "noise_type": "em",
            "leads": "all",
            "interval_s": [0, 10],
            "snr_db": 0,
        }
    ]
    out, log = apply_recipe(ecg12, steps, np.random.default_rng(0), FS, synthetic_noise_provider)
    assert "III" in log[0].leads_affected
    assert not np.array_equal(_lead(out, "III"), _lead(ecg12, "III"))


def test_electrode_noise_with_no_power_is_refused(ecg12):
    step = {
        "op": "electrode_nstdb",
        "electrodes": ["RA"],
        "noise_type": "em",
        "noise_sources": [{"record": "em", "channel": 0, "start_sample": 0}],
        "interval_s": [0, 10],
        "snr_db": 0,
    }
    silent = lambda step, n, rng: np.zeros(n)  # noqa: E731
    with pytest.raises(ValueError, match="no signal or noise power"):
        apply_recipe(ecg12, [step], np.random.default_rng(0), 500, silent)
