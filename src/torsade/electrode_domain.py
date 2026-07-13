# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Electrode-domain lead algebra and corruption.

The 12-lead ECG is not twelve independent channels: the limb leads are linear
combinations of three limb-electrode potentials (RA, LA, LL) and the chest leads
are each referenced to Wilson's Central Terminal (WCT), which is itself the mean
of the three limb electrodes. A loose or noisy *electrode* therefore corrupts a
predictable *set* of leads, not one arbitrary trace.

Torsade models this exactly. Given a clean, Einthoven-consistent 12-lead record we
recover the electrode potentials (in the RA-as-reference gauge), add artefact to
one or more electrodes, then rederive all twelve leads. This is the physically
faithful way to simulate an acquired-but-degraded ECG.

**Assumption — the WCT is not truly zero.** The classical WCT ``(RA+LA+LL)/3`` is
an approximation; the real central-terminal potential varies through the cardiac
cycle and with electrode placement. Torsade uses the classical definition and
recomputes it after corruption, which is the standard modelling choice; downstream
users should read this as an idealised electrode model, not a torso forward model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .constants import CANONICAL_LEAD_ORDER, DERIVED_LIMB_LEADS, LEAD_INDEX

# Electrode channel names Torsade can address for corruption.
CHEST_ELECTRODES: tuple[str, ...] = ("C1", "C2", "C3", "C4", "C5", "C6")
ELECTRODE_NAMES: tuple[str, ...] = ("RA", "LA", "LL", *CHEST_ELECTRODES)


def derive_limb_leads_from_I_II(
    lead_i: np.ndarray, lead_ii: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(III, aVR, aVL, aVF)`` derived from I and II (Einthoven/Goldberger).

    These are the same relations embedded in the Glasgow-ASCII reader; kept here as
    the single source of truth for both loading and corruption.
    """
    lead_iii = lead_ii - lead_i
    avr = -(lead_i + lead_ii) / 2.0
    avl = lead_i - lead_ii / 2.0
    avf = lead_ii - lead_i / 2.0
    return lead_iii, avr, avl, avf


@dataclass(frozen=True)
class Electrodes:
    """Electrode potentials in the RA-as-reference gauge (RA ≡ 0).

    Gauge-invariance of all leads (they are electrode *differences*) makes this a
    valid representation: adding any common offset to every electrode cancels out.
    """

    ra: np.ndarray  # (T,) — identically zero in this gauge
    la: np.ndarray  # (T,) — equals lead I
    ll: np.ndarray  # (T,) — equals lead II
    chest: np.ndarray  # (6, T) — chest-electrode potentials C1..C6


def leads_to_electrodes(signal: np.ndarray) -> Electrodes:
    """Recover electrode potentials from a canonical ``(12, T)`` lead array.

    Assumes the limb leads are Einthoven-consistent (true for derived leads in
    PTB-XL / CinC records). III/aVR/aVL/aVF are treated as functions of I and II.
    """
    if signal.shape[0] != 12:
        raise ValueError(f"expected (12, T), got {signal.shape}")
    lead_i = signal[LEAD_INDEX["I"]]
    lead_ii = signal[LEAD_INDEX["II"]]
    ra = np.zeros_like(lead_i)
    la = lead_i.copy()
    ll = lead_ii.copy()
    wct = (ra + la + ll) / 3.0
    chest = np.stack([signal[LEAD_INDEX[f"V{k}"]] + wct for k in range(1, 7)], axis=0)
    return Electrodes(ra=ra, la=la, ll=ll, chest=chest)


def electrodes_to_leads(electrodes: Electrodes) -> np.ndarray:
    """Reconstruct the canonical ``(12, T)`` lead array from electrode potentials."""
    ra, la, ll, chest = electrodes.ra, electrodes.la, electrodes.ll, electrodes.chest
    lead_i = la - ra
    lead_ii = ll - ra
    lead_iii = ll - la
    avr = ra - (la + ll) / 2.0
    avl = la - (ra + ll) / 2.0
    avf = ll - (ra + la) / 2.0
    wct = (ra + la + ll) / 3.0
    out = np.empty((12, ra.shape[0]), dtype=np.float64)
    out[LEAD_INDEX["I"]] = lead_i
    out[LEAD_INDEX["II"]] = lead_ii
    out[LEAD_INDEX["III"]] = lead_iii
    out[LEAD_INDEX["aVR"]] = avr
    out[LEAD_INDEX["aVL"]] = avl
    out[LEAD_INDEX["aVF"]] = avf
    for k in range(6):
        out[LEAD_INDEX[f"V{k + 1}"]] = chest[k] - wct
    return out


@dataclass(frozen=True)
class ElectrodeDomainResult:
    """Outcome of an electrode-domain corruption."""

    signal: np.ndarray  # (12, T) corrupted lead array
    electrodes_corrupted: tuple[str, ...]
    leads_changed: tuple[str, ...]  # leads whose samples actually changed
    derived_leads_invalidated: tuple[str, ...]  # subset of {III,aVR,aVL,aVF}


def corrupt_electrode_domain(
    signal: np.ndarray,
    artefacts: dict[str, np.ndarray],
    *,
    change_tol_mv: float = 1e-9,
) -> ElectrodeDomainResult:
    """Add per-electrode artefact potentials and rederive all twelve leads.

    Parameters
    ----------
    signal
        Clean canonical ``(12, T)`` array in mV.
    artefacts
        Map electrode name (one of :data:`ELECTRODE_NAMES`) to a ``(T,)`` artefact
        potential added to that electrode.
    change_tol_mv
        A lead counts as "changed" if its max absolute deviation exceeds this.
    """
    t = signal.shape[1]
    unknown = set(artefacts) - set(ELECTRODE_NAMES)
    if unknown:
        raise ValueError(f"unknown electrode(s): {sorted(unknown)}")
    for name, art in artefacts.items():
        if art.shape != (t,):
            raise ValueError(f"artefact for {name} must be shape ({t},), got {art.shape}")

    e = leads_to_electrodes(signal)
    ra = e.ra + artefacts.get("RA", 0.0)
    la = e.la + artefacts.get("LA", 0.0)
    ll = e.ll + artefacts.get("LL", 0.0)
    chest = e.chest.copy()
    for k, cname in enumerate(CHEST_ELECTRODES):
        if cname in artefacts:
            chest[k] = chest[k] + artefacts[cname]

    corrupted = electrodes_to_leads(Electrodes(ra=ra, la=la, ll=ll, chest=chest))

    deviation = np.max(np.abs(corrupted - signal), axis=1)
    leads_changed = tuple(
        name for i, name in enumerate(CANONICAL_LEAD_ORDER) if deviation[i] > change_tol_mv
    )
    limb_electrode_touched = bool({"RA", "LA", "LL"} & set(artefacts))
    invalidated = (
        tuple(ld for ld in DERIVED_LIMB_LEADS if ld in leads_changed)
        if limb_electrode_touched
        else ()
    )
    return ElectrodeDomainResult(
        signal=corrupted,
        electrodes_corrupted=tuple(sorted(artefacts)),
        leads_changed=leads_changed,
        derived_leads_invalidated=invalidated,
    )
