# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Synthetic noise shapes for engineering controls and precordial coupling.

Real recorded NSTDB noise is the primary artefact source for the corpus (see
:mod:`torsade.mixing`). These synthetic shapes are used only where a *controlled*,
source-free artefact is wanted — precordial cross-talk components and some extreme
engineering swings — and where CI must run without any PhysioNet download. They are
band-limited to physiologically plausible ranges and are clearly labelled synthetic
in the corruption truth.

Mirrors the shapes in the sibling ``noise-swarms`` package; kept self-contained so
Torsade has no cross-package runtime dependency.
"""

from __future__ import annotations

import numpy as np
from scipy import signal as sp_signal

_EPS = 1e-12


def normalize_unit_power(x: np.ndarray) -> np.ndarray:
    """Scale to unit DC-removed mean-square power (returns zeros if degenerate)."""
    centered = x - np.median(x)
    p = float(np.mean(centered**2))
    if p <= _EPS:
        return np.zeros_like(x)
    return centered / np.sqrt(p)


def band_limited(
    n: int, fs: int, low_hz: float, high_hz: float, rng: np.random.Generator
) -> np.ndarray:
    """Zero-phase band-passed white noise, unit power."""
    high_hz = min(high_hz, fs / 2 - 1.0)
    raw = rng.standard_normal(n)
    sos = sp_signal.butter(4, [low_hz, high_hz], btype="bandpass", fs=fs, output="sos")
    return normalize_unit_power(sp_signal.sosfiltfilt(sos, raw))


def motion_trace(n: int, fs: int, rng: np.random.Generator) -> np.ndarray:
    """Electrode-motion-like artefact: low-frequency, nonstationary, unit power."""
    base = band_limited(n, fs, 0.5, 12.0, rng)
    # Nonstationary envelope so bursts resemble contact disturbance, not stationary hum.
    env = 0.4 + 0.6 * np.abs(band_limited(n, fs, 0.1, 1.0, rng))
    return normalize_unit_power(base * env)


def emg_trace(n: int, fs: int, rng: np.random.Generator) -> np.ndarray:
    """Muscle/EMG-like artefact: 20 Hz–120 Hz band, unit power."""
    return band_limited(n, fs, 20.0, 120.0, rng)


def baseline_trace(n: int, fs: int, rng: np.random.Generator) -> np.ndarray:
    """Baseline-wander-like artefact: 0.15 Hz–0.6 Hz, unit power."""
    return band_limited(n, fs, 0.15, 0.6, rng)


def powerline_trace(
    n: int, fs: int, rng: np.random.Generator, *, freq_hz: float = 50.0
) -> np.ndarray:
    """Mains interference: fundamental + 2nd harmonic, random phase, unit power."""
    t = np.arange(n) / fs
    phase = rng.uniform(0, 2 * np.pi)
    x = np.sin(2 * np.pi * freq_hz * t + phase) + 0.25 * np.sin(
        2 * np.pi * 2 * freq_hz * t + phase / 3
    )
    return normalize_unit_power(x)
