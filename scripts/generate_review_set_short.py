#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Package the short set 2: 30 of the 85 set-2 ECGs for Peter and Derek.

The subset is ``artefaux.review.select_short_set``, a stratified draw from the
recipes alone, so it never depends on a program's output. Pages are copied from
the set-2 overflow PDF already handed out, and each record keeps its set-2
``REV`` code, so answers map to the existing private key.

Local review tooling: needs the private set-2 output, the set-2 handoff, mutool,
xlwt==1.3.0 and xlrd==2.0.2. The selection with strata is written privately
under ``out/``; the reviewer packages carry only blind codes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from artefaux.provenance import sha256_file
from artefaux.review import SHORT_QUOTAS, SHORT_SEED, select_short_set, write_review_files

REPO = Path(__file__).resolve().parents[1]
N = sum(SHORT_QUOTAS.values())
STEM = f"artefaux{N}"
README = f"""Artefaux independent ECG review - Set 2, short version ({N} recordings)

This replaces the full 85-recording Set 2: please review these {N} only.
DTC = Derek; PWM = Peter. Use the XLS sheet matching your initials.
The XLS is plain: one heading row and data rows, with no colours or theme.
PDF: {STEM}_set2_blind_overflow.pdf, one recording per page.
Each recording keeps its Set 2 code (printed on its page), so codes are not
consecutive and the page number is not the code.
Each recording has 12 leads at 500 Hz for 10 seconds. The PDF displays
the eight independent leads (I, II, V1-V6), each for the full 10 seconds.
Display: 25 mm/s, 10 mm/mV, raw signal with no display filtering.
Waveform overflow is enabled: traces may extend beyond their allocated
lead bands.

Record unsuitable leads, whether either 5-second half is usable (say
which half), comments, and your decision. Leave Agreed handling blank.
Set 1 and Set 2 have separate REV codes: always retain the set number.
No source identifiers, corruption labels, or answer key are included.
"""


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def page_code(pdf: Path, page: int) -> str:
    text = subprocess.run(
        ["mutool", "draw", "-F", "txt", str(pdf), str(page)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    codes = {word for word in text.split() if word.startswith("REV-")}
    if len(codes) != 1:
        raise RuntimeError(f"{pdf} page {page}: expected one REV code, found {sorted(codes)}")
    return codes.pop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "out/artefaux-review-set2")
    parser.add_argument("--share-dir", type=Path, default=REPO / "reports/review_packs")
    args = parser.parse_args()
    if shutil.which("mutool") is None:
        parser.error("mutool is required to copy PDF pages")

    full = args.share_dir / "set2"
    dest = args.share_dir / "set2_short"
    private = args.out / "short"
    full_pdf = full / "artefaux85_set2_blind_overflow.pdf"
    sheets = [full / f"artefaux85{r}_set2.{x}" for r in ("PWM", "DTC") for x in ("csv", "xls")]
    originals = [full_pdf, *sheets]
    before = {str(p): sha256_file(p) for p in originals}

    recipes_path = args.out / "recipes.json"
    recipes = json.loads(recipes_path.read_text())
    key = {row["record_id"]: row for row in read_csv(args.out / "PRIVATE_blind_key.csv")}
    steps = {r["record_id"]: r["steps"] for r in recipes}
    if len(steps) != 85 or set(steps) != set(key):
        raise RuntimeError("recipes.json and the private key must cover the same 85 records")

    chosen = select_short_set(steps)
    rows = sorted(
        (
            {
                "blind_code": key[rid]["blind_code"],
                "full_set_page": int(key[rid]["page"]),
                "record_id": rid,
                "stratum": stratum,
                "inclusion_probability": f"{prob:.6f}",
            }
            for rid, stratum, prob in chosen
        ),
        key=lambda row: row["full_set_page"],
    )
    codes = [row["blind_code"] for row in rows]
    for row in rows:  # the key's page/code mapping must match the PDF that was handed out
        if page_code(full_pdf, row["full_set_page"]) != row["blind_code"]:
            raise RuntimeError(f"page {row['full_set_page']} does not show {row['blind_code']}")

    dest.mkdir(parents=True, exist_ok=True)
    pdf = dest / f"{STEM}_set2_blind_overflow.pdf"
    pages = ",".join(str(row["full_set_page"]) for row in rows)
    subprocess.run(["mutool", "merge", "-o", str(pdf), str(full_pdf), pages], check=True)
    shown = [page_code(pdf, page) for page in range(1, N + 1)]
    if shown != codes:
        raise RuntimeError("short PDF pages do not match the selected codes")

    for reviewer in ("PWM", "DTC"):
        previous = {
            row[0]: row
            for row in csv.reader((full / f"artefaux85{reviewer}_set2.csv").open(encoding="utf-8"))
        }
        sheet = [previous[code] for code in codes]  # carries any answers already given
        write_review_files(
            dest / f"{STEM}{reviewer}_set2", reviewer, sheet, dataset=f"Set2 short {N}"
        )
    (dest / "README.txt").write_text(README, encoding="utf-8")

    for reviewer in ("PWM", "DTC"):
        target = args.share_dir / f"{STEM}{reviewer}_set2_review.zip"
        files = [pdf, dest / "README.txt"] + [
            dest / f"{STEM}{reviewer}_set2.{x}" for x in ("xls", "csv")
        ]
        with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=path.name)
        with ZipFile(target) as archive:
            if archive.testzip() is not None:
                raise RuntimeError(f"archive verification failed: {target}")
        print(f"Prepared {target} ({target.stat().st_size / 1e6:.1f} MB)", flush=True)

    private.mkdir(parents=True, exist_ok=True)
    with (private / "selection.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "seed": SHORT_SEED,
        "quotas": SHORT_QUOTAS,
        "recipes_sha256": sha256_file(recipes_path),
        "codes": codes,
        "codes_sha256": hashlib.sha256("\n".join(codes).encode()).hexdigest(),
        "pdf_sha256": sha256_file(pdf),
    }
    (private / "selection.json").write_text(json.dumps(summary, indent=2) + "\n")
    if any(sha256_file(Path(p)) != digest for p, digest in before.items()):
        raise RuntimeError("a full set-2 handoff file was modified")
    print(f"Selected {N}: codes_sha256 {summary['codes_sha256']}", flush=True)


if __name__ == "__main__":
    main()
