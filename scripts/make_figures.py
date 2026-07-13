#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Generate Torsade's documentation figures in the ECG house style.

House style: IBM Plex type (falls back gracefully), single accent ``#6C5CE7``,
colourblind-safe, no chartjunk, legible at embed size. Worked examples use
synthetic parents so no source signals are redistributed.

    python scripts/make_figures.py --out figures
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from torsade.constants import SNR_LADDER_DB  # noqa: E402
from torsade.corpus import build_corpus_specs  # noqa: E402
from torsade.engineering import build_swing  # noqa: E402
from torsade.mixing import mix_lead  # noqa: E402
from torsade.noise_shapes import motion_trace  # noqa: E402
from torsade.synthetic import synthetic_parent_signal  # noqa: E402

ACCENT = "#6C5CE7"
INK = "#22223B"
MUTED = "#9A9AB0"


def _style() -> None:
    plt.rcParams.update(
        {
            "font.family": ["IBM Plex Sans", "DejaVu Sans"],
            "font.size": 10,
            "axes.edgecolor": INK,
            "axes.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "figure.dpi": 150,
        }
    )


def fig_composition(out: Path) -> Path:
    counts: dict[str, int] = {}
    for s in build_corpus_specs():
        counts[s.group] = counts.get(s.group, 0) + 1
    labels = ["naturally_poor", "real_noise", "engineering"]
    values = [counts[k] for k in labels]
    pretty = [
        "Naturally poor\n(Challenge 2011 + noisy PTB-XL)",
        "Real-noise pairs\n(PTB-XL + NSTDB)",
        "Engineering extremes\n(single + multi-lead)",
    ]

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    y = np.arange(len(labels))
    ax.barh(y, values, color=ACCENT, height=0.6)
    for yi, v in zip(y, values, strict=True):
        ax.text(v + 0.6, yi, str(v), va="center", ha="left", fontweight="bold", color=INK)
    ax.set_yticks(y)
    ax.set_yticklabels(pretty)
    ax.set_xlim(0, max(values) + 6)
    ax.set_xlabel("number of stress-test records")
    ax.set_title(f"Torsade v1 composition — {sum(values)} records (+ paired clean parents)")
    ax.invert_yaxis()
    ax.tick_params(length=0)
    fig.tight_layout()
    path = out / "corpus_composition.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_snr_ladder(out: Path) -> Path:
    fs = 500
    parent = synthetic_parent_signal(seed=1)
    lead = parent[6]  # V1
    t = np.arange(lead.size) / fs
    rng = np.random.default_rng(0)
    noise = motion_trace(lead.size, fs, rng)
    ladder = sorted(SNR_LADDER_DB, reverse=True)

    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    offset = 0.0
    step = max(np.ptp(lead), 2.0) * 2.2
    for snr in ladder:
        res = mix_lead(lead, noise, snr)
        ax.plot(t, res.signal + offset, color=ACCENT, lw=0.7)
        ax.text(
            t[-1] + 0.05,
            offset,
            f"{snr:+d} dB",
            va="center",
            ha="left",
            color=INK,
            fontweight="bold",
        )
        offset -= step
    ax.set_yticks([])
    ax.set_xlim(0, t[-1] + 1.0)
    ax.set_xlabel("time (s)")
    ax.set_title("Real-noise SNR ladder (V1; NSTDB-style electrode motion)")
    ax.spines["left"].set_visible(False)
    ax.tick_params(length=0)
    fig.tight_layout()
    path = out / "snr_ladder.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_overload_example(out: Path) -> Path:
    fs = 500
    parent = synthetic_parent_signal(seed=2)
    idx = 8  # V3
    res = build_swing(parent, "V3", p2p_mv=30.0, rng=np.random.default_rng(3), fs=fs, rail_mv=5.0)
    t = np.arange(parent.shape[1]) / fs

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(t, parent[idx], color=MUTED, lw=0.8, label="clean parent")
    ax.plot(t, res.signal[idx], color=ACCENT, lw=0.8, label="overload → rail clip")
    ax.axhline(5.0, color=INK, lw=0.6, ls="--")
    ax.axhline(-5.0, color=INK, lw=0.6, ls="--")
    ax.text(t[-1], 5.0, " rail", va="bottom", ha="right", fontsize=8, color=INK)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("V3 (mV)")
    ax.set_title("Engineering extreme: overload swing clipped at the acquisition rail")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.tick_params(length=0)
    fig.tight_layout()
    path = out / "overload_example.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="make_figures", description=__doc__)
    p.add_argument("--out", default="figures")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _style()
    for fn in (fig_composition, fig_snr_ladder, fig_overload_example):
        print("wrote", fn(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
