#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Resolve concrete PTB-XL parent record IDs from the user's PTB-XL copy.

Reads ``ptbxl_database.csv`` and writes deterministic selections to
``recipes/source_ids/``. Challenge-2011 record IDs are taken from that database's
``RECORDS`` file. Run this once against your local PhysioNet copy before
``make regenerate``; the selection is seeded and reproducible.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from torsade.selection import quality_flags, select_ptbxl

SEED = 20260713
N_CLEAN = 30 + 22  # real-noise parents + engineering parents
N_NOISY = 5  # noisy PTB-XL naturally-poor records


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="select_sources", description=__doc__)
    p.add_argument("--ptbxl", required=True, help="PTB-XL root (contains ptbxl_database.csv).")
    p.add_argument("--challenge2011", default=None, help="CinC Challenge 2011 root (RECORDS file).")
    args = p.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    out_dir = repo / "recipes" / "source_ids"
    out_dir.mkdir(parents=True, exist_ok=True)

    db = Path(args.ptbxl) / "ptbxl_database.csv"
    if not db.exists():
        raise SystemExit(f"ptbxl_database.csv not found at {db}")
    with open(db, newline="") as fh:
        rows = list(csv.DictReader(fh))

    clean, noisy = select_ptbxl(rows, n_clean=N_CLEAN, n_noisy=N_NOISY, seed=SEED)

    def write_ids(name: str, selected, with_flags: bool = False) -> None:
        with open(out_dir / name, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                ["ecg_id", "filename_hr", "quality_flags"]
                if with_flags
                else ["ecg_id", "filename_hr"]
            )
            for r in selected:
                base = [r.get("ecg_id"), r.get("filename_hr")]
                if with_flags:
                    base.append("|".join(quality_flags(r)))
                w.writerow(base)

    write_ids("ptbxl_clean.csv", clean)
    write_ids("ptbxl_noisy.csv", noisy, with_flags=True)
    print(f"Wrote {len(clean)} clean + {len(noisy)} noisy PTB-XL ids to {out_dir}")

    if args.challenge2011:
        records = Path(args.challenge2011) / "RECORDS"
        if records.exists():
            names = [ln.strip() for ln in records.read_text().splitlines() if ln.strip()][:10]
            (out_dir / "challenge2011.csv").write_text("record\n" + "\n".join(names) + "\n")
            print(f"Wrote {len(names)} Challenge-2011 ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
