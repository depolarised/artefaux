# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Synthetic, Einthoven-consistent parent ECGs.

Used for smoke-testing generation without any PhysioNet download and for the
worked examples in the figures. Not part of the released corpus — real parents
come from PTB-XL / CinC Challenge 2011.
"""

from __future__ import annotations

import numpy as np

from .constants import CANONICAL_LEAD_ORDER
from .electrode_domain import derive_limb_leads_from_I_II


def synthetic_parent_signal(seed: int, fs: int = 500, seconds: float = 10.0) -> np.ndarray:
    """A synthetic ``(12, T)`` mV ECG whose limb leads satisfy Einthoven's law."""
    rng = np.random.default_rng(seed)
    n = int(round(fs * seconds))
    t = np.arange(n) / fs

    def beats(amp: float, width: float = 0.02) -> np.ndarray:
        sig = np.zeros_like(t)
        for k in range(int(seconds)):
            sig += amp * np.exp(-((t - (k + 0.3)) ** 2) / (2 * width**2))
        return sig

    lead_i = beats(1.0) + 0.05 * np.sin(2 * np.pi * 0.20 * t)
    lead_ii = beats(1.5) + 0.05 * np.sin(2 * np.pi * 0.15 * t)
    iii, avr, avl, avf = derive_limb_leads_from_I_II(lead_i, lead_ii)
    chest = {f"V{k + 1}": beats(0.8 + 0.15 * k) + 0.02 * rng.standard_normal(n) for k in range(6)}
    leads = {"I": lead_i, "II": lead_ii, "III": iii, "aVR": avr, "aVL": avl, "aVF": avf, **chest}
    return np.stack([leads[name] for name in CANONICAL_LEAD_ORDER], axis=0)
