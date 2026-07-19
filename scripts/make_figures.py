#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Generate Artefaux's documentation figures in the ECG house style.

House style: IBM Plex type (falls back gracefully), brand accent ``#6C5CE7`` for
single-series plots plus a colourblind-safe Okabe–Ito palette for the three corpus
groups, no chartjunk, legible at embed size. Worked examples use synthetic parents so
no source signals are redistributed.

    python scripts/make_figures.py --out figures
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from artefaux.constants import SNR_LADDER_DB  # noqa: E402
from artefaux.corpus import build_corpus_specs  # noqa: E402
from artefaux.engineering import build_swing  # noqa: E402
from artefaux.mixing import mix_lead  # noqa: E402
from artefaux.noise_shapes import motion_trace  # noqa: E402
from artefaux.synthetic import synthetic_parent_signal  # noqa: E402

ACCENT = "#6C5CE7"
INK = "#22223B"
MUTED = "#9A9AB0"

# Colourblind-safe categorical palette (Okabe–Ito) for the three corpus groups.
# Used wherever the groups must be told apart at a glance; the brand accent above
# stays for single-series plots. Blue / vermillion / bluish-green are maximally
# separable under deuteranopia and protanopia.
GROUP_ORDER = ("naturally_poor", "real_noise", "engineering")
GROUP_COLORS = {
    "naturally_poor": "#0072B2",  # blue
    "real_noise": "#D55E00",  # vermillion
    "engineering": "#009E73",  # bluish-green
}
GROUP_PRETTY = {
    "naturally_poor": "Naturally poor\n(PTB-XL quality flags)",
    "real_noise": "Real-noise pairs\n(PTB-XL + NSTDB, low SNR)",
    "engineering": "Engineering extremes\n(single + multi + wild)",
}


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


def _group_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in build_corpus_specs():
        counts[s.group] = counts.get(s.group, 0) + 1
    return counts


def fig_composition(out: Path) -> Path:
    counts = _group_counts()
    values = [counts[k] for k in GROUP_ORDER]
    colors = [GROUP_COLORS[k] for k in GROUP_ORDER]
    pretty = [GROUP_PRETTY[k] for k in GROUP_ORDER]

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    y = np.arange(len(GROUP_ORDER))
    ax.barh(y, values, color=colors, height=0.6)
    for yi, v in zip(y, values, strict=True):
        ax.text(v + 0.6, yi, str(v), va="center", ha="left", fontweight="bold", color=INK)
    ax.set_yticks(y)
    ax.set_yticklabels(pretty)
    ax.set_xlim(0, max(values) + 6)
    ax.set_xlabel("number of stress-test records")
    ax.set_title(f"Artefaux v2 composition — {sum(values)} records (+ paired clean parents)")
    ax.invert_yaxis()
    ax.tick_params(length=0)
    fig.tight_layout()
    path = out / "corpus_composition.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def fig_group_severity(out: Path) -> Path:
    """Per-group discard-vs-keep breakdown — the label-assignment outcome at a glance.

    Discard is the record-level ``noiseguard`` decision authored from the recipe
    (never measured). Each group keeps its palette hue; the solid segment is
    ``discard`` and the faint segment ``keep``, so hue distinguishes the group and
    saturation the outcome (colourblind-safe on both axes).
    """
    tally = {g: {"discard": 0, "keep": 0} for g in GROUP_ORDER}
    for spec in build_corpus_specs():
        key = "discard" if spec.expected.get("noiseguard_discard", False) else "keep"
        tally[spec.group][key] += 1

    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    y = np.arange(len(GROUP_ORDER))
    for yi, g in zip(y, GROUP_ORDER, strict=True):
        n_disc, n_keep = tally[g]["discard"], tally[g]["keep"]
        ax.barh(yi, n_disc, color=GROUP_COLORS[g], height=0.6)
        ax.barh(yi, n_keep, left=n_disc, color=GROUP_COLORS[g], alpha=0.3, height=0.6)
        if n_disc:
            ax.text(
                n_disc / 2,
                yi,
                str(n_disc),
                va="center",
                ha="center",
                color="white",
                fontweight="bold",
                fontsize=9,
            )
        if n_keep:
            ax.text(
                n_disc + n_keep / 2,
                yi,
                str(n_keep),
                va="center",
                ha="center",
                color=INK,
                fontsize=9,
            )
    ax.set_yticks(y)
    ax.set_yticklabels([GROUP_PRETTY[g].split("\n")[0] for g in GROUP_ORDER])
    ax.set_xlim(0, max(sum(v.values()) for v in tally.values()) + 4)
    ax.set_xlabel("number of records")
    ax.set_title("Records expected to be discarded vs kept, by group")
    ax.invert_yaxis()
    ax.tick_params(length=0)
    # Legend: solid = discard, faint = keep (neutral proxies so it reads in greyscale too).
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(facecolor=INK, label="discard (noiseguard)"),
            Patch(facecolor=INK, alpha=0.3, label="keep"),
        ],
        loc="upper right",
        frameon=False,
        fontsize=9,
    )
    fig.tight_layout()
    path = out / "group_severity.png"
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
    for fn in (fig_composition, fig_group_severity, fig_snr_ladder, fig_overload_example):
        print("wrote", fn(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
