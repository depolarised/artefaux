# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Command-line entry points for Torsade."""

from __future__ import annotations

import argparse
from pathlib import Path

from .build import generate_corpus

DEFAULT_MASTER_SEED = 20260713

# NSTDB and Challenge 2011 are small and directly downloadable; PTB-XL(+) are
# large and are fetched separately (see docs/GENERATION.md).
DOWNLOADABLE = {
    "nstdb": "nstdb",
    "challenge2011": "challenge-2011/1.0.0",
}


def generate_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="torsade-generate", description="Generate the Torsade noise & lead-failure corpus."
    )
    p.add_argument("--out", required=True, help="Output directory for records/labels/manifest.")
    p.add_argument("--sources", default=None, help="Root dir with ptbxl/ nstdb/ challenge2011/.")
    p.add_argument("--master-seed", type=int, default=DEFAULT_MASTER_SEED)
    p.add_argument(
        "--synthetic",
        action="store_true",
        help="Build from synthetic parents/noise (no PhysioNet download needed).",
    )
    args = p.parse_args(argv)
    manifest = generate_corpus(
        args.out,
        master_seed=args.master_seed,
        sources_dir=args.sources,
        synthetic=args.synthetic,
    )
    print(
        f"Generated {len(manifest.entries)} records into {args.out}: {manifest.counts_by_group()}"
    )
    return 0


def download_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="torsade-download", description="Download the small open PhysioNet noise sources."
    )
    p.add_argument("--out", required=True, help="Root dir to download into.")
    p.add_argument(
        "--datasets",
        nargs="*",
        default=list(DOWNLOADABLE),
        choices=list(DOWNLOADABLE),
        help="Which small datasets to fetch (PTB-XL is fetched separately).",
    )
    args = p.parse_args(argv)

    import wfdb

    out = Path(args.out)
    for name in args.datasets:
        target = out / name
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {name} -> {target} ...")
        wfdb.dl_database(DOWNLOADABLE[name], str(target))
    print("Done. Fetch PTB-XL (500 Hz) and PTB-XL+ separately; see docs/GENERATION.md.")
    return 0
