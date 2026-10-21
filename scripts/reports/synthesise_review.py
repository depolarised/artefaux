#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Synthesise returned blinded reviews (PWM, DTC) against the private key and recipe truth.

Local review tooling. Reads the returned workbooks without modifying them (their SHA-256 is
recorded), codes each free-text response with :mod:`artefaux.review_coding` plus explicit
overrides, and writes a private synthesis under ``out/review-synthesis/set<N>/``:
``coding.csv`` (blind codes only), ``joined.csv`` (with truth), ``synthesis.md`` and a figure.

Set 1::

    .venv/bin/python scripts/reports/synthesise_review.py --set 1

Set 2, when returned (pass the returned workbook paths)::

    .venv/bin/python scripts/reports/synthesise_review.py --set 2 --pwm <file> --dtc <file>
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from artefaux.provenance import sha256_file
from artefaux.review_coding import (
    CODERS,
    DISPLAYED_LEADS,
    CodedResponse,
    apply_overrides,
    read_overrides,
)
from artefaux.scoring import (
    BinaryCounts,
    cohen_kappa,
    jaccard,
    pabak,
    percent_agreement,
)

REPO = Path(__file__).resolve().parents[2]
SETS = {
    "1": {
        "pwm": REPO / "reports/review_packs/set1/artefaux85_PWM.xlsx",
        "dtc": REPO / "reports/review_packs/set1/artefaux85_DTC .xls",
        "key": REPO / "reports/artefaux_v2_ecg_review_blind.key.csv",
        "corpus": REPO / "out/artefaux-v2",
    },
    "2": {
        "pwm": None,
        "dtc": None,
        "key": REPO / "out/artefaux-review-set2/PRIVATE_blind_key.csv",
        "corpus": REPO / "out/artefaux-review-set2",
    },
}
DECISION3 = ("analysable", "partial", "repeat")


def read_sheet(path: Path) -> list[dict[str, str]]:
    """First worksheet as dicts keyed by the heading row; values as stripped text."""
    if path.suffix.lower() == ".xlsx":
        import openpyxl

        sheet = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = [["" if v is None else str(v) for v in r] for r in sheet.iter_rows(values_only=True)]
    else:
        import xlrd

        with xlrd.open_workbook(path) as book:
            sheet = book.sheet_by_index(0)
            rows = [[str(v) for v in sheet.row_values(i)] for i in range(sheet.nrows)]
    header = [h.strip() for h in rows[0]]
    return [
        {h: v.strip() for h, v in zip(header, r, strict=False)}
        for r in rows[1:]
        if any(v.strip() for v in r)
    ]


def decision3(c: CodedResponse) -> str:
    return "repeat" if c.repeat_ecg else c.overall if c.overall != "rhythm_only" else "repeat"


def truth_for(label: dict) -> dict:
    ct = label["corruption_truth"]
    steps = ct["steps"]
    ops = [s["op"] for s in steps]
    noise = next((s for s in steps if s["op"] == "nstdb_mix"), None)
    return {
        "group": label["group"],
        "ops": "+".join(ops) if ops else "none",
        "corrupted_leads": [ld for ld in DISPLAYED_LEADS if ld in ct["leads_with_any_corruption"]],
        "noise_type": noise["noise_type"] if noise else "",
        "snr_db": noise["snr_requested_db"] if noise else None,
        "n_leads_noised": len(noise["leads_affected"]) if noise else 0,
        "interval_s": noise["interval_s"] if noise else None,
        "expected_quality": label["expected_behaviour"]["record_quality"],
        "integrity": label["expected_behaviour"]["data_integrity_failure"],
        "ptbxl_flags": label["clinical_parent"]["ptbxl_quality_flags"],
    }


def hf_residual_uv(signal: np.ndarray, fs: int = 500) -> np.ndarray:
    """Per-lead RMS (µV) above 40 Hz: a crude, filter-free index of high-frequency noise."""
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, 40, btype="highpass", fs=fs, output="sos")
    return np.sqrt(np.mean(sosfiltfilt(sos, signal, axis=1) ** 2, axis=1)) * 1000


def ci_text(metric: dict) -> str:
    return f"{fmt(metric['value'])} ({fmt(metric['lo'])}–{fmt(metric['hi'])})"


def cell(c: CodedResponse) -> str:
    """Compact decision text: ``partial V1;V2 second_half``."""
    parts = [decision3(c), ";".join(c.unusable_leads)]
    if c.usable_section != "full":
        parts.append(c.usable_section)
    return " ".join(p for p in parts if p)


def fmt(x: float, d: int = 2) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:.{d}f}"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def figure(joined: list[dict], path: Path) -> None:
    """Reader decision against SNR for every real-noise record, one row per noise/scope."""
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/artefaux-matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": ["IBM Plex Sans", "DejaVu Sans"],
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.edgecolor": "#22223B",
            "axes.linewidth": 0.8,
        }
    )
    colours = {"analysable": "#BBBBC8", "partial": "#E69F00", "repeat": "#6C5CE7"}
    rows = [
        r for r in joined if r["group"] == "real_noise" and r["snr_db"] is not None and r["reader"]
    ]
    # Broadest scope first, so panels read from whole-record to single-region noise.
    strata = sorted(
        {(r["noise_type"], r["n_leads_noised"]) for r in rows}, key=lambda k: (-k[1], k[0])
    )
    names = {"em": "Electrode motion", "ma": "Muscle", "bw": "Baseline wander"}
    fig, axes = plt.subplots(len(strata), 1, figsize=(6.4, 1.15 * len(strata) + 0.9), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, (nt, nl) in zip(axes, strata, strict=True):
        sub = [r for r in rows if r["noise_type"] == nt and r["n_leads_noised"] == nl]
        limb = all(ld in ("I", "II") for r in sub for ld in r["corrupted_leads"])
        where = "all 12 leads" if nl == 12 else "limb leads" if limb else "chest leads"
        for yi, reader in enumerate(("DTC", "PWM")):
            pts = [r for r in sub if r["reader"] == reader]
            by_snr = defaultdict(list)
            for r in pts:
                by_snr[r["snr_db"]].append((r["blind_code"], r["decision3"]))
            for snr, entries in by_snr.items():
                # Order by record so vertically aligned dots are the same record for both readers.
                decs = [dec for _, dec in sorted(entries)]
                offsets = np.linspace(-0.35, 0.35, len(decs)) if len(decs) > 1 else [0.0]
                for off, dec in zip(offsets, decs, strict=True):
                    ax.scatter(
                        snr + off,
                        yi,
                        s=46,
                        color=colours[dec],
                        edgecolor="white",
                        linewidth=0.6,
                        zorder=3,
                    )
        ax.set_yticks([0, 1], ["Derek", "Peter"])
        ax.set_ylim(-0.7, 1.7)
        ax.tick_params(axis="y", length=0)
        ax.set_title(f"{names.get(nt, nt)} · noise in {where}", loc="left", fontsize=9)
    axes[-1].set_xlabel("Requested SNR in the corrupted leads (dB)")
    axes[-1].set_xticks(sorted({r["snr_db"] for r in rows}))
    handles = [
        plt.Line2D([], [], marker="o", ls="", color=c, markersize=7, label=lab)
        for lab, c in (
            ("Analyse as is", colours["analysable"]),
            ("Omit leads / use one half", colours["partial"]),
            ("Repeat ECG", colours["repeat"]),
        )
    ]
    fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", choices=sorted(SETS), required=True)
    parser.add_argument("--pwm", type=Path)
    parser.add_argument("--dtc", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    cfg = SETS[args.set]
    paths = {"PWM": args.pwm or cfg["pwm"], "DTC": args.dtc or cfg["dtc"]}
    if not all(paths.values()):
        parser.error("pass --pwm and --dtc for a set without default workbook paths")
    out = args.out or REPO / f"out/review-synthesis/set{args.set}"
    out.mkdir(parents=True, exist_ok=True)

    hashes = {r: sha256_file(p) for r, p in paths.items()}
    key = {r["blind_code"]: r for r in csv.DictReader(cfg["key"].open(encoding="utf-8"))}
    coded = []
    for reader, path in paths.items():
        for row in read_sheet(path):
            if row.get("Blind ECG code") in key:
                coded.append(CODERS[reader](row))
    overrides = read_overrides(out / "overrides.csv")
    coded = apply_overrides(coded, overrides)
    if {r: sha256_file(p) for r, p in paths.items()} != hashes:
        raise RuntimeError("a returned workbook changed while being read")
    by = {(c.reader, c.blind_code): c for c in coded}
    codes = sorted(key)
    missing = [(r, c) for r in paths for c in codes if (r, c) not in by]
    if missing:
        raise ValueError(f"responses missing for {len(missing)} reader/code pairs: {missing[:5]}")

    with (out / "coding.csv").open("w", newline="", encoding="utf-8") as fh:
        rows = [c.as_row() for c in sorted(coded, key=lambda c: (c.blind_code, c.reader))]
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    truth = {
        code: truth_for(
            json.loads((cfg["corpus"] / "labels" / f"{key[code]['record_id']}.json").read_text())
        )
        for code in codes
    }
    joined = []
    for code in codes:
        for reader in paths:
            c = by[(reader, code)]
            joined.append(
                {
                    "blind_code": code,
                    "record_id": key[code]["record_id"],
                    "reader": reader,
                    "decision3": decision3(c),
                    **c.as_row(),
                    **truth[code],
                }
            )
    with (out / "joined.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(joined[0]))
        w.writeheader()
        w.writerows(joined)

    p = [by[("PWM", c)] for c in codes]
    d = [by[("DTC", c)] for c in codes]
    md = [f"# Review synthesis — set {args.set}", ""]
    md += [
        "Private coordinator document: contains reader judgements joined to the de-blinding key.",
        "",
        f"- Records: {len(codes)}; readers: PWM (Peter), DTC (Derek).",
        f"- Workbooks (SHA-256): PWM `{hashes['PWM'][:16]}…`, DTC `{hashes['DTC'][:16]}…`.",
        f"- Coding: automatic draft from `artefaux.review_coding`, {len(overrides)} explicit "
        "override rows (`overrides.csv`). **Verify `coding.csv` before citing any number.**",
        "- Per-lead convention: a repeat-ECG decision makes every displayed lead unusable.",
        "",
        "## 1. Reader decisions",
        "",
    ]
    counts = {r: Counter(decision3(by[(r, c)]) for c in codes) for r in paths}
    md.append(
        table(
            ["Decision", "PWM", "DTC"], [[k, counts["PWM"][k], counts["DTC"][k]] for k in DECISION3]
        )
    )
    sec = {r: Counter(by[(r, c)].usable_section for c in codes) for r in paths}
    md += [
        "",
        f"Half-record choices: PWM {sec['PWM']['first_half'] + sec['PWM']['second_half']}, "
        f"DTC {sec['DTC']['first_half'] + sec['DTC']['second_half']}.",
        "",
        "## 2. Inter-reader agreement",
        "",
    ]
    d3p, d3d = [decision3(x) for x in p], [decision3(x) for x in d]
    rp, rd = [x.repeat_ecg for x in p], [x.repeat_ecg for x in d]
    lead_p = [x.lead_unusable(ld) for x in p for ld in DISPLAYED_LEADS]
    lead_d = [x.lead_unusable(ld) for x in d for ld in DISPLAYED_LEADS]
    both_keep = [(a, b) for a, b in zip(p, d, strict=True) if not a.repeat_ecg and not b.repeat_ecg]
    jac = [jaccard(set(a.unusable_leads), set(b.unusable_leads)) for a, b in both_keep]
    sec_pairs = [(a.usable_section, b.usable_section) for a, b in both_keep]
    rep2 = Counter(zip(rp, rd, strict=True))
    md.append(
        table(
            ["Item", "Units", "Agreement", "Cohen κ", "PABAK"],
            [
                [
                    "3-way decision",
                    len(codes),
                    fmt(percent_agreement(d3p, d3d)),
                    fmt(cohen_kappa(d3p, d3d, DECISION3)),
                    fmt(pabak(d3p, d3d, 3)),
                ],
                [
                    "Repeat ECG (yes/no)",
                    len(codes),
                    fmt(percent_agreement(rp, rd)),
                    fmt(cohen_kappa(rp, rd, [True, False])),
                    fmt(pabak(rp, rd, 2)),
                ],
                [
                    "Lead unusable (8 displayed leads)",
                    len(lead_p),
                    fmt(percent_agreement(lead_p, lead_d)),
                    fmt(cohen_kappa(lead_p, lead_d, [True, False])),
                    fmt(pabak(lead_p, lead_d, 2)),
                ],
                [
                    "Usable section (both keep)",
                    len(sec_pairs),
                    fmt(percent_agreement(*zip(*sec_pairs, strict=True))),
                    "",
                    "",
                ],
            ],
        )
    )
    md += [
        "",
        f"Repeat ECG: both {rep2[(True, True)]}, PWM only {rep2[(True, False)]}, "
        f"DTC only {rep2[(False, True)]}, neither {rep2[(False, False)]}. "
        f"Mean lead-set Jaccard where neither repeats: {fmt(float(np.mean(jac)))} (n={len(jac)}).",
        "",
        "Records where exactly one reader asks for a repeat:",
        "",
    ]
    md.append(
        table(
            ["Code", "Recipe", "PWM", "DTC"],
            [
                [
                    c,
                    f"{truth[c]['ops']} {truth[c]['noise_type']} {fmt(truth[c]['snr_db'], 0)}",
                    cell(a),
                    cell(b),
                ]
                for c, a, b in zip(codes, p, d, strict=True)
                if a.repeat_ecg != b.repeat_ecg
            ],
        )
    )

    md += ["", "## 3. Authored expected labels against the readers", ""]
    exp_rows = []
    for q in ("diagnostic", "limited", "rhythm_only", "reject"):
        sub = [i for i, c in enumerate(codes) if truth[c]["expected_quality"] == q]
        if sub:
            exp_rows.append(
                [
                    q,
                    len(sub),
                    sum(rp[i] and rd[i] for i in sub),
                    sum(rp[i] != rd[i] for i in sub),
                    sum(not rp[i] and not rd[i] for i in sub),
                ]
            )
    md.append(
        table(["Authored record_quality", "n", "Both repeat", "One repeats", "Neither"], exp_rows)
    )

    md += ["", "## 4. Readers against recipe truth, per displayed lead", ""]
    fam_rows = []
    families = sorted({truth[c]["group"] for c in codes})
    for reader, coded_list in (("PWM", p), ("DTC", d)):
        for fam in [*families, "all"]:
            idx = [i for i, c in enumerate(codes) if fam in ("all", truth[c]["group"])]
            ref = [ld in truth[codes[i]]["corrupted_leads"] for i in idx for ld in DISPLAYED_LEADS]
            pred = [coded_list[i].lead_unusable(ld) for i in idx for ld in DISPLAYED_LEADS]
            m = BinaryCounts.from_pairs(pred, ref).metrics()
            fam_rows.append(
                [
                    reader,
                    fam,
                    len(idx),
                    ci_text(m["sensitivity"]),
                    ci_text(m["specificity"]),
                ]
            )
    md.append(
        table(
            ["Reader", "Group", "Records", "P(unusable | corrupted)", "P(usable | untouched)"],
            fam_rows,
        )
    )
    md += [
        "",
        "Corrupted means the recipe changed the lead at all; it is not a usability claim. "
        "Wilson 95% CIs ignore clustering within records and are indicative only.",
        "",
        "## 5. Real noise: decision by noise type, scope and SNR",
        "",
    ]
    noise_rows = []
    for c in sorted(
        (c for c in codes if truth[c]["snr_db"] is not None),
        key=lambda c: (truth[c]["noise_type"], truth[c]["n_leads_noised"], truth[c]["snr_db"]),
    ):
        t = truth[c]
        noise_rows.append(
            [
                c,
                t["noise_type"],
                ",".join(t["corrupted_leads"]) if t["n_leads_noised"] < 12 else "all 12",
                fmt(t["snr_db"], 0),
                cell(by[("PWM", c)]),
                cell(by[("DTC", c)]),
            ]
        )
    md.append(table(["Code", "Noise", "Leads noised", "SNR dB", "PWM", "DTC"], noise_rows))
    scopes = Counter(
        (truth[c]["noise_type"], truth[c]["n_leads_noised"])
        for c in codes
        if truth[c]["snr_db"] is not None
    )
    if len({nl for (_, nl) in scopes}) > 1 and all(
        len({nl for (nt2, nl) in scopes if nt2 == nt}) == 1 for nt, _ in scopes
    ):
        md += [
            "",
            "**Confound:** each noise type was applied to exactly one lead scope in this set, so "
            "the effect of noise type cannot be separated from the number and location of noised "
            "leads.",
        ]
    figure(joined, out / "decision_by_snr.png")
    md += [
        "",
        "![Reader decision by SNR](decision_by_snr.png)",
        "",
        "*Each dot is one reader's coded decision on one record (real-noise group only). Records "
        "sharing an SNR are offset horizontally by up to ±0.35 dB for visibility, in the same "
        "order for both readers, so vertically aligned dots are the same record; the x position "
        "is otherwise the requested SNR. Source: `joined.csv`.*",
        "",
        "## 6. Engineering and other recipes",
        "",
    ]
    eng_rows = []
    for c in codes:
        t = truth[c]
        if t["snr_db"] is None and t["ops"] != "none":
            eng_rows.append(
                [
                    c,
                    t["ops"],
                    ",".join(t["corrupted_leads"]),
                    t["expected_quality"],
                    cell(by[("PWM", c)]),
                    cell(by[("DTC", c)]),
                    ";".join(sorted(set(by[("PWM", c)].not_noise) | set(by[("DTC", c)].not_noise))),
                ]
            )
    md.append(
        table(
            [
                "Code",
                "Recipe",
                "Displayed leads changed",
                "Authored",
                "PWM",
                "DTC",
                "Not-noise flags",
            ],
            eng_rows,
        )
    )
    md += ["", "## 7. Naturally poor (PTB-XL quality flags, no added corruption)", ""]
    nat = [c for c in codes if truth[c]["ops"] == "none"]
    md.append(
        table(
            ["Code", "PTB-XL flags", "Authored", "PWM", "DTC"],
            [
                [
                    c,
                    ",".join(truth[c]["ptbxl_flags"]),
                    truth[c]["expected_quality"],
                    cell(by[("PWM", c)]),
                    cell(by[("DTC", c)]),
                ]
                for c in nat
            ],
        )
    )

    # Leads I/II: is the high-frequency content natural (clean parents) or added?
    import wfdb

    hf_clean, hf_saved = [], []
    for c in codes:
        rid = key[c]["record_id"]
        rec_dir = cfg["corpus"] / "records"
        if (rec_dir / f"{rid}_clean.hea").exists():
            hf_clean.append(hf_residual_uv(wfdb.rdrecord(str(rec_dir / f"{rid}_clean")).p_signal.T))
        saved = np.nan_to_num(wfdb.rdrecord(str(rec_dir / rid)).p_signal.T)
        untouched = np.array(
            [
                ld not in truth[c]["corrupted_leads"]
                for ld in ("I", "II", "V1", "V2", "V3", "V4", "V5", "V6")
            ]
        )
        hf = hf_residual_uv(saved)[[0, 1, 6, 7, 8, 9, 10, 11]]
        hf_saved.append(np.where(untouched, hf, np.nan))
    lead_idx = [0, 1, 6, 7, 8, 9, 10, 11]
    md += [
        "",
        "## 8. Leads I and II: high-frequency content (>40 Hz RMS, µV, median over records)",
        "",
    ]
    rows = []
    if hf_clean:
        clean = np.array(hf_clean)[:, lead_idx]
        rows.append(
            ["Clean parents", len(hf_clean), *[fmt(v, 1) for v in np.nanmedian(clean, axis=0)]]
        )
    sv = np.array(hf_saved)
    rows.append(
        [
            "Review records, recipe-untouched leads only",
            len(hf_saved),
            *[fmt(v, 1) for v in np.nanmedian(sv, axis=0)],
        ]
    )
    md.append(table(["Signals", "n", *DISPLAYED_LEADS], rows))
    (out / "synthesis.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Wrote {out / 'synthesis.md'}, coding.csv, joined.csv and decision_by_snr.png")


if __name__ == "__main__":
    main()
