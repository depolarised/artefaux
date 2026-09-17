# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Convert the Artefaux v2 WFDB stress corpus into internal GRIASCII (``.asc``).

Local tool, **not** part of the shipped self-contained generator. Like
``scripts/reports/render_ecg_review.py`` it depends on the internal ``ecg-suite``
package ``ecg-io`` (install into the Artefaux venv with
``uv pip install -e ../../ecg-suite/ecg-io``) and on an already-built corpus under
``out/artefaux-v2/records``. It reads each record through the public ``ecg_io``
reader API and re-emits the canonical ``(12, T)`` millivolt signal as a
Glasgow/GRIANLYS ASCII v1.5 file that ``ecg_io``'s own parser decodes back
bit-exactly.

Why this is faithful to the report
----------------------------------
Artefaux writes WFDB with an ADC gain of ``1000 LSB/mV`` and baseline ``0``, so
the physical millivolt signal returned by ``ecg_io.read_ecg`` is exactly
``adc / 1000``. Writing GRIASCII with the matching calibration of ``1000 LSB/mV``
and integer ADC counts ``round(mV * 1000)`` reproduces the original int16 ADC
samples with zero loss. The converter verifies this per record by parsing each
emitted file back with ``ecg_io``'s parser and asserting the decoded millivolt
signal matches the source within a fraction of one LSB.

Two decode paths, one caveat
----------------------------
``ecg_io``'s low-level parser (``parse_glasgow_ascii_file``) returns raw
millivolts and is what this tool verifies against. The high-level
``read_ecg(*.asc)`` GRIasc reader additionally subtracts each lead's median for
DC removal — a documented reader behaviour — so it will re-centre records that
carry a deliberate baseline offset. The written signal itself is unaltered; only
that reader's view is DC-removed.

Signals only
------------
GRIASCII is a signal container. The three-layer Artefaux labels and the manifest
remain the authoritative metadata (rhythm class, corruption truth, expected
behaviour); this tool does not fold them into the ``.asc`` header. It writes a
``griasc_index.csv`` next to the output recording the calibration, sample count
and measured round-trip error for every record, for audit.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
from ecg_io import read_ecg
from ecg_io._glasgow_ascii import parse_glasgow_ascii_file

# Canonical 12-lead order — the Artefaux signal invariant.
CANONICAL_LEADS: tuple[str, ...] = (
    "I",
    "II",
    "III",
    "aVR",
    "aVL",
    "aVF",
    "V1",
    "V2",
    "V3",
    "V4",
    "V5",
    "V6",
)

# ADC gain Artefaux writes into WFDB (LSB per mV); reused as the GRIASCII
# calibration so the ASCII ADC counts equal the source int16 samples exactly.
CALIBRATION_LSB_PER_MV = 1000

# v1.5 header line indices consumed by ``ecg_io._glasgow_ascii`` ``_parse_v15``.
# Every other line up to DATA_START is ignored by the parser and left blank.
_V15_DATA_START = 23
_V15_SLOTS = {
    0: "## 1.5",
    # 1: patient id            (filled per record)
    # 4: sex                   (blank — synthetic corpus, no patient data)
    6: "0",  # age in days
    7: "00/00/0000,00/00/0000",  # dob, recording date
    8: "00:00:00",  # recording time
    # 16: recording type       (blank)
    17: "1" * len(CANONICAL_LEADS),  # lead availability mask
    18: ",".join(CANONICAL_LEADS),  # lead names
    19: str(CALIBRATION_LSB_PER_MV),  # calibration
    # 20: sampling rate         (filled per record)
    # 21: samples per lead      (filled per record)
    22: str(len(CANONICAL_LEADS)),  # number of leads
}


class ConversionError(RuntimeError):
    """Raised when a record cannot be converted or fails round-trip verification."""


def signal_to_griasc_v15(
    signal: np.ndarray,
    *,
    sample_rate_hz: float,
    record_id: str,
    lead_names: tuple[str, ...] = CANONICAL_LEADS,
    calibration_lsb_per_mv: int = CALIBRATION_LSB_PER_MV,
) -> str:
    """Render a canonical ``(n_leads, T)`` millivolt array as GRIASCII v1.5 text.

    Parameters
    ----------
    signal:
        ``(n_leads, T)`` array in millivolts, canonical lead order.
    sample_rate_hz:
        Sampling rate; written verbatim and must be a positive integer number
        of hertz (the Artefaux invariant is 500 Hz).
    record_id:
        Written as the patient/recording id on header line 1.
    lead_names:
        Lead names for header line 18; must match ``signal`` row order.
    calibration_lsb_per_mv:
        ADC gain; samples are stored as ``round(mV * calibration)``.

    Returns
    -------
    str
        The full ``.asc`` file contents (no trailing newline).
    """
    if signal.ndim != 2:
        raise ConversionError(f"{record_id}: signal must be 2-D, got shape {signal.shape}")
    n_leads, n_samples = signal.shape
    if n_leads != len(lead_names):
        raise ConversionError(f"{record_id}: {n_leads} leads but {len(lead_names)} lead names")
    if not np.all(np.isfinite(signal)):
        raise ConversionError(f"{record_id}: signal has non-finite samples")

    sr_int = int(round(sample_rate_hz))
    if sr_int != sample_rate_hz or sr_int <= 0:
        raise ConversionError(f"{record_id}: non-integer/non-positive rate {sample_rate_hz!r}")

    adc = np.round(signal * calibration_lsb_per_mv).astype(np.int64)
    if adc.min() < np.iinfo(np.int16).min or adc.max() > np.iinfo(np.int16).max:
        raise ConversionError(
            f"{record_id}: ADC counts exceed int16 range "
            f"[{adc.min()}, {adc.max()}] at {calibration_lsb_per_mv} LSB/mV"
        )

    header = [""] * _V15_DATA_START
    for idx, value in _V15_SLOTS.items():
        header[idx] = value
    header[1] = record_id
    header[18] = ",".join(lead_names)
    header[20] = str(sr_int)
    header[21] = str(n_samples)

    # GRIASCII sample layout is lead-major: all samples of lead 0, then lead 1…
    body = "\n".join(str(v) for v in adc.reshape(-1))
    return "\n".join(header) + "\n" + body


def _verify_roundtrip(
    asc_path: Path,
    source_mv: np.ndarray,
    *,
    calibration_lsb_per_mv: int,
) -> float:
    """Parse ``asc_path`` back with ``ecg_io`` and return the max abs error in mV.

    Uses the low-level parser (no DC removal) so the comparison is against the
    raw written millivolts. Also asserts lead identity and order are preserved.
    """
    parsed = parse_glasgow_ascii_file(asc_path)
    names = [lead.name for lead in parsed.leads]
    if names != list(CANONICAL_LEADS):
        raise ConversionError(
            f"{asc_path.name}: decoded lead order {names} != canonical "
            f"(a zeroed limb lead may have been re-derived from I/II)"
        )
    decoded = np.array([lead.data for lead in parsed.leads], dtype=np.float64)
    if decoded.shape != source_mv.shape:
        raise ConversionError(
            f"{asc_path.name}: decoded shape {decoded.shape} != source {source_mv.shape}"
        )
    err = float(np.max(np.abs(decoded - source_mv)))
    tol = 0.5 / calibration_lsb_per_mv  # half an LSB
    if err > tol:
        raise ConversionError(
            f"{asc_path.name}: round-trip error {err:.6g} mV exceeds {tol:.6g} mV"
        )
    return err


def convert_record(
    record_path: Path,
    out_dir: Path,
    *,
    calibration_lsb_per_mv: int = CALIBRATION_LSB_PER_MV,
) -> dict[str, object]:
    """Convert one WFDB record to GRIASCII and verify the round-trip.

    Returns an index row (record_id, path, fs, n_samples, calibration, error_mv).
    """
    record_id = record_path.name
    rec = read_ecg(record_path, format_name="WFDB")
    lead_names = rec.lead_names or CANONICAL_LEADS
    text = signal_to_griasc_v15(
        rec.signal,
        sample_rate_hz=rec.sample_rate_hz,
        record_id=record_id,
        lead_names=lead_names,
        calibration_lsb_per_mv=calibration_lsb_per_mv,
    )
    asc_path = out_dir / f"{record_id}.asc"
    asc_path.write_text(text + "\n", encoding="utf-8")

    err = _verify_roundtrip(asc_path, rec.signal, calibration_lsb_per_mv=calibration_lsb_per_mv)
    return {
        "record_id": record_id,
        "asc_file": asc_path.name,
        "fs": int(round(rec.sample_rate_hz)),
        "n_samples": rec.n_samples,
        "calibration_lsb_per_mv": calibration_lsb_per_mv,
        "roundtrip_max_abs_error_mv": f"{err:.3e}",
    }


def _resolve_record_ids(manifest: Path, records_dir: Path, include_clean: bool) -> list[str]:
    ids: list[str] = []
    with manifest.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rid = row["record_id"]
            ids.append(rid)
            if include_clean:
                parent = row.get("parent_record_id") or ""
                if parent and (records_dir / f"{parent}.hea").exists():
                    ids.append(parent)
    # Preserve manifest order, drop duplicate clean parents.
    seen: set[str] = set()
    return [rid for rid in ids if not (rid in seen or seen.add(rid))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("out/artefaux-v2"),
        help="Built corpus root containing records/ and manifest (default: out/artefaux-v2)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifest.csv"),
        help="Manifest CSV listing the stress records (default: manifest.csv)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/artefaux-v2-griasc"),
        help="Output directory (default: out/artefaux-v2-griasc)",
    )
    parser.add_argument(
        "--include-clean",
        action="store_true",
        help="Also convert the paired clean parents referenced by the manifest.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Convert only the first N records (smoke check).",
    )
    args = parser.parse_args(argv)

    records_dir = args.corpus / "records"
    if not records_dir.is_dir():
        parser.error(f"records directory not found: {records_dir}")
    if not args.manifest.is_file():
        parser.error(f"manifest not found: {args.manifest}")

    record_ids = _resolve_record_ids(args.manifest, records_dir, args.include_clean)
    if args.limit is not None:
        record_ids = record_ids[: args.limit]

    out_records = args.out / "records"
    out_records.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    worst = 0.0
    for rid in record_ids:
        record_path = records_dir / rid
        if not (records_dir / f"{rid}.hea").exists():
            print(f"  ! missing WFDB record, skipping: {rid}", file=sys.stderr)
            continue
        row = convert_record(record_path, out_records)
        worst = max(worst, float(row["roundtrip_max_abs_error_mv"]))
        rows.append(row)
        print(f"  {rid}: {row['n_samples']} samples, err={row['roundtrip_max_abs_error_mv']} mV")

    index_path = args.out / "griasc_index.csv"
    with index_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"\nConverted {len(rows)} record(s) → {out_records}\n"
        f"Index: {index_path}\n"
        f"Worst round-trip error across corpus: {worst:.3e} mV "
        f"(≤ {0.5 / CALIBRATION_LSB_PER_MV:.3e} mV = ½ LSB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
