# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The corpus manifest — one scannable row per record.

The manifest is the index a user reads before touching a single signal: what each
record is, where its parent came from, what was done to it, and what a good gate
should do. It ships (metadata, not signals) as both JSON and CSV.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from .labels import RecordLabel

CSV_COLUMNS = (
    "record_id",
    "group",
    "source_dataset",
    "source_record_id",
    "parent_record_id",
    "rhythm_class",
    "corruption_ops",
    "snr_db",
    "expected_record_quality",
    "expected_noiseguard_discard",
    "data_integrity_failure",
    "n_bad_leads",
    "fs",
    "n_samples",
)


@dataclass(frozen=True)
class ManifestEntry:
    record_id: str
    group: str
    source_dataset: str
    source_record_id: str | None
    parent_record_id: str | None
    rhythm_class: str | None
    corruption_ops: tuple[str, ...]
    snr_db: tuple[float, ...]
    expected_record_quality: str
    expected_noiseguard_discard: bool
    data_integrity_failure: bool
    n_bad_leads: int
    fs: int
    n_samples: int

    @classmethod
    def from_label(
        cls, label: RecordLabel, *, parent_record_id: str | None = None
    ) -> ManifestEntry:
        ct = label.corruption_truth
        eb = label.expected_behaviour
        snrs = tuple(s.snr_requested_db for s in ct.steps if s.snr_requested_db is not None)
        n_bad = sum(1 for q in eb.lead_quality.values() if q == "bad")
        return cls(
            record_id=label.record_id,
            group=label.group,
            source_dataset=label.clinical_parent.source_dataset,
            source_record_id=label.clinical_parent.source_record_id,
            parent_record_id=parent_record_id,
            rhythm_class=label.clinical_parent.rhythm_class,
            corruption_ops=tuple(s.op for s in ct.steps),
            snr_db=snrs,
            expected_record_quality=eb.record_quality,
            expected_noiseguard_discard=eb.noiseguard_discard_record,
            data_integrity_failure=eb.data_integrity_failure,
            n_bad_leads=n_bad,
            fs=label.fs,
            n_samples=label.n_samples,
        )

    def as_csv_row(self) -> dict:
        return {
            "record_id": self.record_id,
            "group": self.group,
            "source_dataset": self.source_dataset,
            "source_record_id": self.source_record_id or "",
            "parent_record_id": self.parent_record_id or "",
            "rhythm_class": self.rhythm_class or "",
            "corruption_ops": "|".join(self.corruption_ops),
            "snr_db": "|".join(str(x) for x in self.snr_db),
            "expected_record_quality": self.expected_record_quality,
            "expected_noiseguard_discard": int(self.expected_noiseguard_discard),
            "data_integrity_failure": int(self.data_integrity_failure),
            "n_bad_leads": self.n_bad_leads,
            "fs": self.fs,
            "n_samples": self.n_samples,
        }


class Manifest:
    def __init__(self) -> None:
        self._entries: list[ManifestEntry] = []

    def add(self, entry: ManifestEntry) -> None:
        self._entries.append(entry)

    def extend(self, entries: Iterable[ManifestEntry]) -> None:
        self._entries.extend(entries)

    @property
    def entries(self) -> tuple[ManifestEntry, ...]:
        return tuple(self._entries)

    def counts_by_group(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self._entries:
            out[e.group] = out.get(e.group, 0) + 1
        return out

    def write_json(self, path: str | Path) -> None:
        payload = {
            "n_records": len(self._entries),
            "counts_by_group": self.counts_by_group(),
            "records": [asdict(e) for e in self._entries],
        }
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def write_csv(self, path: str | Path) -> None:
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(CSV_COLUMNS))
            writer.writeheader()
            for e in self._entries:
                writer.writerow(e.as_csv_row())
