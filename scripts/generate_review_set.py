#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Build the second blinded review set and PWM/DTC XLS handoff files.

Local review tooling: requires ecg-io, signalpaper, xlwt==1.3.0, xlrd==2.0.2,
the original review pack, and local PTB-XL/NSTDB sources. Private ground truth
stays under out/; reviewer packages contain only blind codes and signals.
"""

from __future__ import annotations

import argparse
import ast
import csv
import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import wfdb

from artefaux.build import DEFAULT_NSTDB_DIR, DEFAULT_PTBXL_DIR, make_noise_provider
from artefaux.constants import CANONICAL_LEAD_ORDER, LEAD_INDEX, TARGET_FS
from artefaux.loaders import load_wfdb_parent
from artefaux.manifest import Manifest, ManifestEntry
from artefaux.mixing import measured_snr_db
from artefaux.provenance import Provenance, sha256_file
from artefaux.recipes import SourceSpec, build_record
from artefaux.review import (
    BLIND_SEED,
    MASTER_SEED,
    build_review_specs,
    simplify_review_workbook,
    write_review_files,
)
from artefaux.selection import select_ptbxl
from artefaux.writer import write_wfdb

REPO = Path(__file__).resolve().parents[1]

# Reviewer-supplied entries, not inferred from the private de-blinding key.
PWM_EXAMPLE = (
    ("REV-001", "V5", "", "Easy!", "Omit V5", ""),
    (
        "REV-002",
        "",
        "Yes - second 5 secs.",
        "Leads I, II are important to retain if possible.",
        "Analyse second 5 secs",
        "",
    ),
    (
        "REV-003",
        "Program should find lead reversal",
        "This is not noise!",
        "V1 looks very strange and of course lead II.",
        "Ideally, omit I, II and V1.",
        "",
    ),
    ("REV-004", 'Some baseline "wobble"', "", "Need to allow analysis", "Leave as is", ""),
    ("REV-005", "V4, V5, V6 too noisy", "No", "Clear cut omission of V4-V6", "Omit V4-V6", ""),
    ("REV-006", "(data pending)", "", "", "", ""),
)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def compress_review(pdf_path: Path, work_dir: Path) -> None:
    if not shutil.which("gs"):
        return
    work_dir.mkdir(parents=True, exist_ok=True)
    compressed = work_dir / "compressed_review.pdf"
    subprocess.run(
        [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.7",
            "-dPDFSETTINGS=/prepress",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={compressed}",
            str(pdf_path),
        ],
        check=True,
    )
    shutil.move(compressed, pdf_path)


def render_first_overflow(args, dest: Path, key: list[dict]) -> None:
    """Keep the original blind order and diagnostic filtering, enabling overflow."""
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/artefaux-matplotlib")
    from ecg_io import read_ecg
    from signalpaper import from_record, render_pdf_multipage

    scenes = []
    for row in key:
        code = row["blind_code"]
        gain = float(row["gain_mm_per_mV"])
        scenes.append(
            from_record(
                read_ecg(args.original_corpus / "records" / row["record_id"], format_name="WFDB"),
                title=code if gain == 10 else f"{code} · [5 mm/mV]",
                extra_footer="",
                filter_preset="diagnostic",
                gain_mm_per_mV=gain,
                speed_mm_per_second=25.0,
                layout="strip8",
            )
        )
    print("Rendering original 85 blinded pages with waveform overflow", flush=True)
    pdf_path = dest / "artefaux85_set1_blind_overflow.pdf"
    render_pdf_multipage(scenes, pdf_path, show_clipping_banner=False, clip_waveform=False)
    compress_review(pdf_path, args.out)
    # Refresh the previously shared filename as well as the explicit overflow PDF.
    shutil.copy2(pdf_path, dest / "artefaux85_set1_blind.pdf")


def first_workbooks(args) -> None:
    original = read_csv(args.original_comments)
    rows_by_code = {row["Blind ECG code"]: row for row in original}
    key = read_csv(args.original_key)
    key_codes = [row["blind_code"] for row in key]
    if list(rows_by_code) != key_codes or len(key_codes) != 85:
        raise ValueError("original comments and private key must share the same 85 ordered codes")
    dest = args.share_dir / "set1"
    dest.mkdir(parents=True, exist_ok=True)
    for reviewer, name in (("PWM", "Peter"), ("DTC", "Derek")):
        entries = []
        for code in key_codes:
            old = rows_by_code[code]
            entries.append(
                [
                    code,
                    old.get(f"{reviewer} Leads unsuitable", ""),
                    old.get(f"{reviewer} 50% OK?", ""),
                    old.get(f"{reviewer} comments", old.get(f"{name} comments", "")),
                    old.get(f"{reviewer} decision", old.get(f"{name} recommendation", "")),
                    old.get("Agreed handling", ""),
                ]
            )
        if reviewer == "PWM":
            # Keep any existing CSV response; fill only the empty cells supplied
            # in the user's example, including its intentionally pending sixth row.
            for index, example in enumerate(PWM_EXAMPLE):
                if entries[index][0] != example[0]:
                    raise ValueError("sample PWM entries must match the original blind codes")
                entries[index] = [
                    old or supplied for old, supplied in zip(entries[index], example, strict=True)
                ]
        base = dest / f"artefaux85{reviewer}"
        if not base.with_suffix(".xls").exists():
            write_review_files(base, reviewer, entries, dataset="Set 1")
        simplify_review_workbook(base.with_suffix(".xls"))
    render_first_overflow(args, dest, key)
    (dest / "README.txt").write_text(
        "Original 85-ECG review pack. Use the XLS sheet matching your initials.\n"
        "DTC = Derek; PWM = Peter. Row REV-001 corresponds to PDF page 1, and so on.\n"
        "The XLS is plain: one heading row and data rows, with no colours or theme.\n"
        "PDF: artefaux85_set1_blind_overflow.pdf, with the original diagnostic filtering.\n"
        "Display: 25 mm/s, 10 mm/mV; traces may overflow their allocated lead bands.\n"
        "PWM's supplied six example rows are retained in his own sheet.\n"
        "For Derek's independent review, share the DTC sheet and PDF only.\n"
        "The original CSV and PDF have been preserved.\n",
        encoding="utf-8",
    )
    print(f"Prepared original PWM and DTC workbooks in {dest}", flush=True)


def select_sources(args) -> tuple[list[SourceSpec], list[dict]]:
    metadata = read_csv(args.ptbxl_dir / "ptbxl_database.csv")
    original = json.loads((args.original_corpus / "manifest.json").read_text())["records"]
    prior_ids = {r["source_record_id"] for r in original}
    prior_patients = {r["patient_id"] for r in metadata if r["filename_hr"] in prior_ids}
    pool = [r for r in metadata if r["patient_id"] not in prior_patients]
    selected, _ = select_ptbxl(pool, n_clean=85, n_noisy=0, seed=MASTER_SEED)
    if len(selected) != 85 or len({r["patient_id"] for r in selected}) != 85:
        raise ValueError("could not select 85 additional clean parents from distinct patients")
    sources, audit = [], []
    for row in selected:
        codes = ast.literal_eval(row["scp_codes"])
        rhythm = next(
            (
                label
                for code, label in (("AFIB", "afib"), ("AFLT", "flutter"), ("SR", "sinus"))
                if code in codes
            ),
            "unknown",
        )
        source = SourceSpec(
            "ptbxl",
            row["filename_hr"],
            rhythm_class=rhythm,
            age_years=float(row["age"]) if row["age"] else None,
        )
        sources.append(source)
        audit.append(
            {
                "record_id": row["filename_hr"],
                "patient_id": row["patient_id"],
                "rhythm_class": rhythm,
                "scp_codes": row["scp_codes"],
            }
        )
    return sources, audit


def generate_signals(args) -> None:
    if (args.out / "manifest.json").exists():
        if args.reuse_corpus:
            print(f"Reusing generated second cohort in {args.out}", flush=True)
            return
        raise FileExistsError("second corpus exists; use --reuse-corpus to finish packaging")
    args.out.mkdir(parents=True, exist_ok=True)
    records = args.out / "records"
    labels = args.out / "labels"
    labels.mkdir(exist_ok=True)
    sources, source_audit = select_sources(args)
    write_csv(args.out / "source_ids.csv", source_audit)
    specs = build_review_specs(sources)
    recipe_path = args.out / "recipes.json"
    recipe_path.write_text(json.dumps([asdict(s) for s in specs], indent=2) + "\n")
    manifest = Manifest()
    provenance = Provenance(master_seed=MASTER_SEED)
    provenance.sources = [s for s in provenance.sources if s.dataset in ("ptbxl", "nstdb")]
    for name, path in (
        ("ptbxl_metadata", args.ptbxl_dir / "ptbxl_database.csv"),
        ("original_manifest", args.original_corpus / "manifest.json"),
        ("recipes", recipe_path),
        ("review_definition", REPO / "src/artefaux/review.py"),
        ("generation_script", Path(__file__)),
    ):
        provenance.record_source_hash(name, path)
    for noise in ("em", "ma", "bw"):
        for suffix in (".hea", ".dat"):
            provenance.record_source_hash(
                f"nstdb/{noise}{suffix}", args.nstdb_dir / f"{noise}{suffix}"
            )
    provider = make_noise_provider(args.nstdb_dir)
    audit = []
    max_snr_error = 0.0
    for index, spec in enumerate(specs, start=1):
        source_path = args.ptbxl_dir / spec.source.record_id
        parent = load_wfdb_parent(source_path, "ptbxl").signal
        if parent.shape != (12, 5000):
            raise ValueError(f"{source_path}: expected a 10-second, 12-lead, 500 Hz parent")
        for suffix in (".hea", ".dat"):
            provenance.record_source_hash(
                f"ptbxl/{spec.source.record_id}{suffix}", source_path.with_suffix(suffix)
            )
        signal, label = build_record(parent, spec, MASTER_SEED, TARGET_FS, noise_provider=provider)
        if not np.isfinite(signal).all() or np.max(np.abs(signal)) > 32.766:
            raise ValueError(f"{spec.record_id}: non-finite samples or int16 storage overload")
        parent_id = f"{spec.record_id}_clean"
        write_wfdb(parent_id, parent, TARGET_FS, records)
        write_wfdb(spec.record_id, signal, TARGET_FS, records)
        saved = wfdb.rdrecord(str(records / spec.record_id)).p_signal.T
        clean = wfdb.rdrecord(str(records / parent_id)).p_signal.T
        allowed = np.zeros(saved.shape, dtype=bool)
        per_lead_snrs = {}
        if spec.steps:
            recipe = spec.steps[0]
            start, stop = (int(t * TARGET_FS) for t in recipe["interval_s"])
            for lead in recipe["leads"]:
                lead_index = LEAD_INDEX[lead]
                allowed[lead_index, start:stop] = True
                snr = measured_snr_db(
                    clean[lead_index, start:stop],
                    saved[lead_index, start:stop] - clean[lead_index, start:stop],
                )
                per_lead_snrs[lead] = snr
                error = abs(snr - recipe["snr_db"])
                max_snr_error = max(max_snr_error, error)
                if error > 0.5:
                    raise ValueError(
                        f"{spec.record_id}/{lead}: saved SNR differs by {error:.3f} dB"
                    )
            step = label.corruption_truth.steps[0]
            step = replace(
                step,
                snr_measured_db=float(np.mean(list(per_lead_snrs.values()))),
                params={
                    **step.params,
                    "noise_source_channel": recipe["noise_source"]["channel"],
                    "noise_source_offset_fs": TARGET_FS,
                    "measurement_domain": "WFDB readback, contaminated interval only",
                    "snr_measured_db_per_lead": per_lead_snrs,
                    "corruption_domain": "acquisition channel",
                },
            )
            label = replace(label, corruption_truth=replace(label.corruption_truth, steps=(step,)))
        if not np.array_equal(saved[~allowed], clean[~allowed]):
            raise ValueError(
                f"{spec.record_id}: signal changed outside the authored lead/time mask"
            )
        label.write(labels / f"{spec.record_id}.json")
        manifest.add(ManifestEntry.from_label(label, parent_record_id=parent_id))
        recipe = spec.steps[0] if spec.steps else {}
        audit.append(
            {
                "record_id": spec.record_id,
                "batch": "selective_extreme" if index <= 15 else "lower_noise",
                "affected_leads": "|".join(recipe.get("leads", [])),
                "noise_interval_s": "|".join(map(str, recipe.get("interval_s", []))),
                "clean_half": (
                    "second"
                    if recipe.get("interval_s") == [0, 5]
                    else (
                        "first"
                        if recipe.get("interval_s") == [5, 10]
                        else "both" if not recipe else ""
                    )
                ),
                "noise_type": recipe.get("noise_type", "none"),
                "requested_snr_db": recipe.get("snr_db", ""),
                "post_storage_snr_per_lead": json.dumps(per_lead_snrs, sort_keys=True),
                "unchanged_samples_verified": True,
            }
        )
        if index % 10 == 0 or index == 85:
            print(f"Generated and verified {index}/85 second-set ECGs", flush=True)
    manifest.write_json(args.out / "manifest.json")
    manifest.write_csv(args.out / "manifest.csv")
    provenance.write(args.out / "provenance.json")
    write_csv(args.out / "generation_audit.csv", audit)
    (args.out / "verification.json").write_text(
        json.dumps(
            {
                "n_records": 85,
                "n_selective_extreme": 15,
                "n_lower_noise": 70,
                "n_clean_controls": 10,
                "n_distinct_patients": 85,
                "patient_overlap_with_original": 0,
                "all_untargeted_samples_bit_identical": True,
                "max_post_storage_snr_error_db": max_snr_error,
            },
            indent=2,
        )
        + "\n"
    )


def load_converter():
    path = REPO / "scripts/griasc_claude/convert_to_griasc.py"
    spec = importlib.util.spec_from_file_location("artefaux_local_griasc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_and_package(args) -> None:
    # Whole-strip zero-phase high-pass filtering spreads a localized baseline
    # excursion into its otherwise clean half. Show the saved raw samples on all
    # new pages, using the original geometry and clinical calibration.
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/artefaux-matplotlib")
    from ecg_io import read_ecg
    from signalpaper import from_record, render_pdf_multipage

    converter = load_converter()
    records = json.loads((args.out / "manifest.json").read_text())["records"]
    audit = {r["record_id"]: r for r in read_csv(args.out / "generation_audit.csv")}
    records = [records[i] for i in np.random.default_rng(BLIND_SEED).permutation(85)]
    dest = args.share_dir / "set2"
    for folder in (dest, dest / "wfdb", dest / "griasc"):
        folder.mkdir(parents=True, exist_ok=True)
    scenes, key, asc_audit = [], [], []
    for page, entry in enumerate(records, start=1):
        rid, code = entry["record_id"], f"REV-{page:03d}"
        label = json.loads((args.out / "labels" / f"{rid}.json").read_text())
        signal = wfdb.rdrecord(str(args.out / "records" / rid)).p_signal.T
        blind_path = write_wfdb(code, signal, TARGET_FS, dest / "wfdb")
        saved = wfdb.rdrecord(str(blind_path))
        if (
            not np.array_equal(saved.p_signal.T, signal)
            or tuple(saved.sig_name) != CANONICAL_LEAD_ORDER
        ):
            raise ValueError(f"{code}: blinded WFDB export changed the signal or lead order")
        asc_audit.append(converter.convert_record(blind_path, dest / "griasc"))
        scene = from_record(
            read_ecg(blind_path, format_name="WFDB"),
            title=code,
            extra_footer="",
            filter_preset="none",
            gain_mm_per_mV=10.0,
            speed_mm_per_second=25.0,
            layout="strip8",
        )
        if scene.scale.gain_mm_per_mV != 10 or scene.scale.speed_mm_per_second != 25:
            raise ValueError("review PDF scale mismatch")
        scenes.append(scene)
        key.append(
            {
                "page": page,
                "blind_code": code,
                "record_id": rid,
                **{k: v for k, v in audit[rid].items() if k != "record_id"},
                "source_record_id": entry["source_record_id"],
                "expected_record_quality": label["expected_behaviour"]["record_quality"],
                "expected_discard": label["expected_behaviour"]["noiseguard_discard_record"],
            }
        )
    print("Rendering 85 new blinded full-10-second pages with waveform overflow", flush=True)
    pdf_path = dest / "artefaux85_set2_blind_overflow.pdf"
    clips = render_pdf_multipage(scenes, pdf_path, show_clipping_banner=False, clip_waveform=False)
    for row, clipping in zip(key, clips, strict=True):
        row["any_display_clipping"] = False
        row["exceeds_display_band"] = bool(clipping.any_clipped)
        row["waveform_overflow"] = True
    write_csv(args.out / "PRIVATE_blind_key.csv", key)
    write_csv(args.out / "griasc_verification.csv", asc_audit)
    compress_review(pdf_path, args.out)
    shutil.copy2(pdf_path, dest / "artefaux85_set2_blind.pdf")
    empty_rows = [[r["blind_code"], "", "", "", "", ""] for r in key]
    for reviewer in ("PWM", "DTC"):
        base = dest / f"artefaux85{reviewer}_set2"
        if not base.with_suffix(".xls").exists():
            write_review_files(base, reviewer, empty_rows, dataset="Set 2")
        simplify_review_workbook(base.with_suffix(".xls"))
    (dest / "README.txt").write_text(
        "Artefaux independent ECG review - Set 2 (85 additional recordings)\n\n"
        "DTC = Derek; PWM = Peter. Use the XLS sheet matching your initials.\n"
        "The XLS is plain: one heading row and data rows, with no colours or theme.\n"
        "PDF: artefaux85_set2_blind_overflow.pdf.\n"
        "REV-001 is PDF page 1 and wfdb/REV-001.{hea,dat} or griasc/REV-001.asc.\n"
        "Each recording has 12 leads at 500 Hz for 10 seconds. The PDF displays\n"
        "the eight independent leads (I, II, V1-V6), each for the full 10 seconds.\n"
        "Display: 25 mm/s, 10 mm/mV, raw signal with no display filtering.\n"
        "Waveform overflow is enabled: traces may extend beyond their allocated\n"
        "lead bands. The downloadable signals retain the complete amplitude.\n\n"
        "Record unsuitable leads, whether either 5-second half is usable (say\n"
        "which half), comments, and your decision. Leave Agreed handling for\n"
        "joint adjudication. CSV companions preserve the same six columns.\n"
        "Set 1 and Set 2 have separate REV codes: always retain the set number.\n"
        "No source identifiers, corruption labels, or answer key are included.\n",
        encoding="utf-8",
    )
    package_reviews(args)


def package_reviews(args) -> None:
    """Refresh reviewer archives from the current overflow PDFs and response files."""
    first = args.share_dir / "set1"
    dest = args.share_dir / "set2"
    packages = [
        (
            "artefaux85DTC_set1_review.zip",
            first,
            [
                first / name
                for name in (
                    "artefaux85_set1_blind_overflow.pdf",
                    "artefaux85DTC.xls",
                    "artefaux85DTC.csv",
                    "README.txt",
                )
            ],
        ),
    ]
    for reviewer in ("PWM", "DTC"):
        files = [
            dest / "artefaux85_set2_blind_overflow.pdf",
            dest / "README.txt",
            dest / f"artefaux85{reviewer}_set2.xls",
            dest / f"artefaux85{reviewer}_set2.csv",
        ]
        files += sorted((dest / "wfdb").glob("*")) + sorted((dest / "griasc").glob("*.asc"))
        packages.append((f"artefaux85{reviewer}_set2_review.zip", dest, files))
    for name, root, files in packages:
        target = args.share_dir / name
        with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=path.relative_to(root))
        with ZipFile(target) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"archive verification failed: {target}")
        print(f"Prepared {target} ({target.stat().st_size / 1e6:.1f} MB)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "out/artefaux-review-set2")
    parser.add_argument("--share-dir", type=Path, default=REPO / "reports/review_packs")
    parser.add_argument("--ptbxl-dir", type=Path, default=DEFAULT_PTBXL_DIR)
    parser.add_argument("--nstdb-dir", type=Path, default=DEFAULT_NSTDB_DIR)
    parser.add_argument("--original-corpus", type=Path, default=REPO / "out/artefaux-v2")
    parser.add_argument(
        "--original-pdf", type=Path, default=REPO / "reports/artefaux_v2_ecg_review_blind.pdf"
    )
    parser.add_argument(
        "--original-comments",
        type=Path,
        default=REPO / "reports/artefaux_v2_ecg_review_blind.comments.csv",
    )
    parser.add_argument(
        "--original-key", type=Path, default=REPO / "reports/artefaux_v2_ecg_review_blind.key.csv"
    )
    parser.add_argument("--reuse-corpus", action="store_true")
    args = parser.parse_args()
    # Check local-only dependencies before writing output.
    for name in ("xlrd", "xlwt", "ecg_io", "signalpaper"):
        if importlib.util.find_spec(name) is None:
            parser.error(f"missing local review dependency: {name}")
    original_hashes = {
        str(p): sha256_file(p)
        for p in (args.original_comments, args.original_pdf, args.original_key)
    }
    first_workbooks(args)
    generate_signals(args)
    render_and_package(args)
    if any(sha256_file(Path(path)) != digest for path, digest in original_hashes.items()):
        raise RuntimeError("an original review artifact was modified")
    (args.out / "original_artifact_hashes.json").write_text(
        json.dumps(original_hashes, indent=2) + "\n"
    )
    print(
        "Complete: original CSV/PDF/key unchanged; private truth kept outside reviewer packages.",
        flush=True,
    )


if __name__ == "__main__":
    main()
