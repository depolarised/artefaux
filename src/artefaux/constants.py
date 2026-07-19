# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Canonical constants shared across the Artefaux generation engine.

Every signal that flows through Artefaux is a ``(12, T)`` ``float64`` array in
millivolts, sampled at :data:`TARGET_FS`, with leads in :data:`CANONICAL_LEAD_ORDER`.
These invariants are enforced at load time so that every downstream module can
assume them without re-checking.
"""

from __future__ import annotations

# --- Corpus identity -------------------------------------------------------

# Neutral, non-branded namespace for corpus record IDs: "nlf" = ECG
# Noise & Lead-Failure. Prefixing keeps IDs collision-safe when records are
# pooled with other datasets, without carrying the tool name into the data.
CORPUS_PREFIX = "nlf"

# --- Lead layout -----------------------------------------------------------

CANONICAL_LEAD_ORDER: tuple[str, ...] = (
    "I",
    "II",
    "III",
    "aVR",
    "aVL",
    "aVF",
    "V1",
    "V2",
    "V3",
    "V4",
    "V5",
    "V6",
)
N_LEADS = len(CANONICAL_LEAD_ORDER)

#: name -> canonical index
LEAD_INDEX: dict[str, int] = {name: i for i, name in enumerate(CANONICAL_LEAD_ORDER)}

#: The six limb leads and six chest leads, matching ``noiseguard`` policy groups
#: (limb = indices 0-5, chest = indices 6-11).
LIMB_LEADS: tuple[str, ...] = CANONICAL_LEAD_ORDER[:6]
CHEST_LEADS: tuple[str, ...] = CANONICAL_LEAD_ORDER[6:]
LIMB_LEAD_INDICES: tuple[int, ...] = tuple(range(6))
CHEST_LEAD_INDICES: tuple[int, ...] = tuple(range(6, 12))

#: The four limb leads that are *derived* from I and II (Einthoven/Goldberger).
DERIVED_LIMB_LEADS: tuple[str, ...] = ("III", "aVR", "aVL", "aVF")

#: Physical electrodes we reconstruct for electrode-domain corruption.
LIMB_ELECTRODES: tuple[str, ...] = ("RA", "LA", "LL")

#: Common spellings seen in source headers -> canonical lead name.
LEAD_NAME_ALIASES: dict[str, str] = {
    "i": "I",
    "ii": "II",
    "iii": "III",
    "avr": "aVR",
    "avl": "aVL",
    "avf": "aVF",
    "v1": "V1",
    "v2": "V2",
    "v3": "V3",
    "v4": "V4",
    "v5": "V5",
    "v6": "V6",
}

# --- Sampling & units ------------------------------------------------------

#: All Artefaux records are resampled to this rate (PhysioNet hi-res standard).
TARGET_FS: int = 500

#: MIT-BIH Noise Stress Test Database native sampling rate.
NSTDB_NATIVE_FS: int = 360

#: NSTDB real-noise records: electrode motion, muscle artefact, baseline wander.
NSTDB_NOISE_TYPES: tuple[str, ...] = ("em", "ma", "bw")

#: Standard diagnostic ECG window length (seconds).
WINDOW_SECONDS: float = 10.0

UNIT: str = "mV"

# --- Noise stress ladder ---------------------------------------------------

#: Signal-to-noise ratios (dB) used for real-noise mixing. v2 drops the clean end
#: (+12/+18 dB, which every gate trivially passes) and concentrates the ladder on the
#: accept/reject decision region: four of the five levels are <= 0 dB (discard-grade),
#: with +2 dB as a single near-boundary specificity anchor. This keeps a dose-response
#: across the decision boundary instead of sampling one saturated extreme, following
#: NSTDB-style graded-SNR methodology. See DATASHEET for rationale.
SNR_LADDER_DB: tuple[int, ...] = (-6, -4, -2, 0, 2)

# --- Reference thresholds for deterministic expected-label assignment ------
# These mirror the internal ``signalguard`` catastrophic-artefact thresholds so
# that Artefaux's *expected behaviour* labels are consistent with the gate the
# corpus is meant to exercise. They are used only to author ground-truth labels
# from a known corruption recipe; Artefaux does not import signalguard.

#: Peak-to-peak over any 1 s window above this (mV) is an implausible excursion.
IMPLAUSIBLE_EXCURSION_MV: float = 5.5
#: Baseline range over any 2 s window above this (mV) is a baseline swing.
BASELINE_SWING_MV: float = 1.5
#: Global peak-to-peak below this (mV) is a flatline.
FLATLINE_P2P_MV: float = 0.05
