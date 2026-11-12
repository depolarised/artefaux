#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Package a phase's GRIASCII files for an independent Uni-G run at Glasgow.

The pack holds only the ``griasc/*.asc`` files (adult Uni-G header, checked here), a blank
results sheet, SHA-256 checksums and a README. It leaves out ``inputs.csv``: its
``missing_channels`` column would reveal answers. The archive is a ``.tar.zst`` with sorted
entries, a fixed timestamp and numeric owner 0, so it is reproducible. Encrypt it before
sending (symmetric gpg, AES256, with a passphrase generated locally and sent separately).
Local tooling; output is gitignored and needs GNU tar with zstd.

Usage::

    .venv/bin/python scripts/package_glasgow_pack.py \\
        --tool-inputs reports/review_packs/phase2/tool_inputs --set 2 --date 2026-11-12
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import subprocess
from pathlib import Path

from artefaux.benchmark import UNIG_HEADER_LINES

REPO = Path(__file__).resolve().parents[1]
LEADS = ("I", "II", "V1", "V2", "V3", "V4", "V5", "V6")
README = """Artefaux ECG set {set}

Contents
  griasc/*.asc                         {n} ECGs ({first} ... {last})
  {results}     results sheet
  SHA256SUMS.txt                       checksums

Format
  GRIASCII v1.5, 12 leads, 500 Hz, 10 s, 1000 LSB/mV.
  Research signals derived from open PhysioNet databases, with no patient identifiers.
  Every file has the same header: adult positioning, nominal age 50 years, sex unknown,
  50 Hz mains filter. Line 2 holds the ECG code.{gaps}

Please return
  The completed sheet, the program version and options used, and the raw output files
  if that is easy.

Results sheet
  Enter the program's output for each ECG.

  I, II, V1 ... V6: usable | unusable
    unusable: the output marks the lead as unavailable or leaves it out of the analysis.
    usable: any other lead, including a noisy lead that is kept.
    Fill these in when Repeat ECG is yes as well.

  Repeat ECG: yes | no | failed
    yes: "Technically unsatisfactory tracing" (2/68), "Recording unsuitable for analysis"
    (13/3), or all eight leads unavailable.
    no: the program analysed the ECG and gave none of these.
    failed: the program crashed or wrote no output. Leave the lead columns blank.

  Comments: optional, e.g. a noisy lead that the program kept.

Codes restart in each review set, so please keep "set {set}" with these results.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tool-inputs", type=Path, required=True)
    parser.add_argument("--set", required=True, help="review set label, e.g. 1 or 2")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD stamped on archive entries")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    ascs = sorted((args.tool_inputs / "griasc").glob("*.asc"))
    if not ascs:
        parser.error(f"no GRIASCII files under {args.tool_inputs / 'griasc'}")
    codes = [p.stem for p in ascs]
    stem = f"artefaux{len(codes)}_set{args.set}"
    out = args.out or REPO / f"reports/review_packs/brian_unig_set{args.set}"
    out.mkdir(parents=True, exist_ok=True)
    for path, code in zip(ascs, codes, strict=True):
        header = path.read_text(encoding="utf-8").split("\n", 23)[:23]
        if header[1] != code or any(header[k - 1] != v for k, v in UNIG_HEADER_LINES.items()):
            raise ValueError(f"{path}: header is not the adult Uni-G header for {code}")
        (out / "griasc").mkdir(exist_ok=True)
        shutil.copyfile(path, out / "griasc" / path.name)

    results = f"{stem}_unig_results.csv"
    with (out / results).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Blind ECG code", *LEADS, "Repeat ECG", "Comments"])
        writer.writerows([code, *[""] * (len(LEADS) + 2)] for code in codes)
    consecutive = codes == [f"REV-{i:03d}" for i in range(1, len(codes) + 1)]
    gaps = "" if consecutive else "\n  The codes are not consecutive: they are the readers' codes."
    (out / "README.txt").write_text(
        README.format(
            set=args.set,
            n=len(codes),
            first=codes[0],
            last=codes[-1],
            results=f"{results:<32}",
            gaps=gaps,
        ),
        encoding="utf-8",
    )
    files = [Path("README.txt"), Path(results)] + [Path("griasc") / p.name for p in ascs]
    sums = [f"{hashlib.sha256((out / f).read_bytes()).hexdigest()}  {f}" for f in files[2:]]
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    files.insert(2, Path("SHA256SUMS.txt"))

    target = out / f"{stem}_griasc.tar.zst"
    subprocess.run(
        [
            "tar", "--zstd", "-cf", str(target), "-C", str(out),
            "--sort=name", f"--mtime={args.date} 00:00Z", "--owner=0", "--group=0",
            "--numeric-owner", "--mode=go-w,a+rX", f"--transform=s,^,{stem}_griasc/,",
            *map(str, files),
        ],
        check=True,
    )  # fmt: skip
    listed = subprocess.run(
        ["tar", "--zstd", "-tf", str(target)], check=True, capture_output=True, text=True
    ).stdout.split()
    if sorted(listed) != sorted(f"{stem}_griasc/{f}" for f in files):
        raise RuntimeError(f"archive verification failed: {target}")
    print(f"Prepared {target} ({len(codes)} ECGs, {target.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
