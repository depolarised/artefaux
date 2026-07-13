# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Command-line entry points for Torsade."""

from __future__ import annotations

import argparse
from pathlib import Path

from .build import (
    DEFAULT_MACECGDB_DIR,
    DEFAULT_NSTDB_DIR,
    DEFAULT_PTBXL_DIR,
    DEFAULT_SOURCE_IDS_DIR,
    generate_corpus,
)

DEFAULT_MASTER_SEED = 20260713


def generate_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="torsade-generate", description="Generate the Torsade noise & lead-failure corpus."
    )
    p.add_argument("--out", required=True, help="Output directory for records/labels/manifest.")
    p.add_argument("--ptbxl-dir", default=str(DEFAULT_PTBXL_DIR), help="PTB-XL 1.0.3 root.")
    p.add_argument("--macecgdb-dir", default=str(DEFAULT_MACECGDB_DIR), help="MACECGDB 1.0.0 root.")
    p.add_argument("--nstdb-dir", default=str(DEFAULT_NSTDB_DIR), help="NSTDB 1.0.0 root.")
    p.add_argument(
        "--source-ids-dir",
        default=str(DEFAULT_SOURCE_IDS_DIR),
        help="Directory of resolved PTB-XL ids (from `make select`).",
    )
    p.add_argument("--master-seed", type=int, default=DEFAULT_MASTER_SEED)
    p.add_argument(
        "--synthetic",
        action="store_true",
        help="Build from synthetic parents/noise (no data needed).",
    )
    args = p.parse_args(argv)
    manifest = generate_corpus(
        args.out,
        master_seed=args.master_seed,
        ptbxl_dir=args.ptbxl_dir,
        macecgdb_dir=args.macecgdb_dir,
        nstdb_dir=args.nstdb_dir,
        source_ids_dir=args.source_ids_dir,
        synthetic=args.synthetic,
    )
    print(
        f"Generated {len(manifest.entries)} records into {args.out}: {manifest.counts_by_group()}"
    )
    return 0


def download_main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="torsade-download",
        description="Download NSTDB (the only source not in the local PhysioNet mirror).",
    )
    p.add_argument("--out", required=True, help="Directory to download NSTDB into.")
    args = p.parse_args(argv)

    import wfdb

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"Downloading NSTDB -> {out} ...")
    wfdb.dl_database("nstdb", str(out))
    print("Done. PTB-XL, PTB-XL+, and MACECGDB are expected in the local PhysioNet mirror.")
    return 0
