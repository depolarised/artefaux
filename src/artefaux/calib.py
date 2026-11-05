# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The ``calib-v1`` calibration corpus: definition, labels and generation checks.

Thresholds of a quality gate are fitted on this corpus and selected on its holdout, never on
the reviewed ECGs (dev-log ADR-0018 amendment 2; ``docs/CALIB_V1.md``). Three properties matter:

* **Noise is drawn independently per lead**, from NSTDB minutes no review set used, so nothing
  can rely on the identical inter-lead noise of review set 1 (a generation artefact there).
* **Noise type is crossed with lead scope**, which set 1 locked together.
* **Labels come from the Amendment 2 table and the mined repeat rule**, computed from the recipe
  alone. They are extrapolated from reader behaviour on set 1; they are not recipe truth, and
  no quality gate's output can reach them.

The definition is data-independent: :func:`calib_plan` needs no files, so the label file and
its hash can be recomputed anywhere. PTB-XL parents are bound afterwards
(:func:`bind_parents`) and cannot change a label. The CLI wrapper is
``scripts/generate_calib_corpus.py``.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .benchmark import (
    FULL_SNR_DB,
    NOISE_TYPES,
    NSTDB_RESAMPLED_LEN,
    NSTDB_SLOT,
    SCOPES,
    _age,
    _scp,
)
from .constants import CANONICAL_LEAD_ORDER, CHEST_LEADS, DERIVED_LIMB_LEADS, LEAD_INDEX, TARGET_FS
from .labels import RecordLabel
from .mixing import measured_snr_db
from .recipes import RecordSpec, SourceSpec
from .review_coding import DISPLAYED_LEADS
from .selection import _dedupe_by_patient, is_clean, quality_flags

CALIB_ID = "artefaux-calib"
CALIB_VERSION = "1.0.0"
MASTER_SEED = 20261104
SELECTION_SEED = 20261105
OFFSET_SEED = 20261106
SEED_INDEX_BASE = 5000
N_SAMPLES = 5000
MIN_AGE_YEARS = 18
DISPLAYED = DISPLAYED_LEADS

#: Review sets 1 and 2 drew offsets below 100 000 samples at 500 Hz (their segments end before
#: 105 000), on channel 0 and on both channels. calib-v1 stays on channel 1 from 300 000 on.
NSTDB_CHANNEL = 1
NSTDB_MIN_START = 300_000
#: Noise minutes do not cross the split, so holdout noise is unseen as well as holdout patients.
NSTDB_REGIONS = {
    "calib": (NSTDB_MIN_START, 660_000),
    "holdout": (660_000, NSTDB_RESAMPLED_LEN),
}

#: The mined repeat rule (``docs/CALIB_V1.md``): repeat at 7 or more of the 8 displayed leads
#: unusable. The readers split at exactly 6, so that count is grey for the repeat endpoint.
REPEAT_MIN_UNUSABLE = 7
REPEAT_MAX_KEEP = 5

ELECTRODES = ("RA", "LA", "LL")
ELECTRODE_MOTION_RMS_MV = (0.5, 1.0, 2.0)
ELECTRODE_DC_MV = 4.0
_ELECTRODE_DISPLAYED = {"RA": ("I", "II"), "LA": ("I",), "LL": ("II",)}
LEAD_OFF_CASES = (("I",), ("II",), ("V2",), ("V5",), ("V1", "V2"), ("V4", "V5", "V6"))
COUPLED_CASES = {("V1", "V2"): {"V1": 0.8, "V2": 0.7}, ("V4", "V5"): {"V4": 0.8, "V5": 0.7}}
COUPLED_SNR_DB = (0, 6)
NATURAL_COUNTS = {
    "electrodes_problems": 8,
    "burst_noise": 12,
    "baseline_drift": 10,
    "static_noise": 10,
}
N_CLEAN_CONTROLS = 60
REPLICATES = {
    "noise": 5,
    "electrode_motion": 5,
    "electrode_dc": 4,
    "lead_off": 4,
    "coupled": 5,
    "compound": 4,
}
SNR_TOLERANCE_DB = 0.5
#: Three stored samples at 1 uV resolution enter each lead-algebra check.
ALGEBRA_TOLERANCE_MV = 0.003
RMS_TOLERANCE = 0.05

_OVERLOAD = {"op": "swing", "p2p_mv": 30.0, "rail_mv": 5.0}
#: Modelled on the set-1 compound records. NaN channels and intermittent lead-off are replaced
#: by flatline and lead-off: GRIASCII cannot carry NaN, and readers called the latter artificial.
COMPOUND_CASES: dict[str, tuple[dict, ...]] = {
    "A": (
        {"op": "electrode", "electrode": "LA", "kind": "motion", "amplitude_mv": 1.0},
        {**_OVERLOAD, "leads": ["V3"]},
        {"op": "lead_off", "leads": ["V6"]},
        {
            "op": "step_recovery",
            "leads": ["II"],
            "step_mv": 4.0,
            "tau_s": 1.5,
            "propagate_derived": True,
        },
    ),
    "B": (
        {"op": "electrode", "electrode": "LA", "kind": "motion", "amplitude_mv": 0.8},
        {"op": "swing", "leads": ["V2"], "p2p_mv": 8.0},
        {"op": "lead_off", "leads": ["V5"]},
    ),
    "C": (
        {"op": "flatline", "leads": ["V1"]},
        {"op": "swing", "leads": ["V6"], "p2p_mv": 25.0, "rail_mv": 5.0},
        {
            "op": "step_recovery",
            "leads": ["II"],
            "step_mv": 3.0,
            "tau_s": 1.5,
            "propagate_derived": True,
        },
    ),
    "D": (
        {"op": "flatline", "leads": ["I"], "propagate_derived": True},
        {"op": "flatline", "leads": ["V6"]},
        {**_OVERLOAD, "leads": ["V3"]},
        {"op": "lead_off", "leads": ["V4"]},
    ),
    "E": (
        {"op": "electrode", "electrode": "RA", "kind": "motion", "amplitude_mv": 1.0},
        {**_OVERLOAD, "leads": ["V3"]},
        {"op": "lead_off", "leads": ["V6"]},
    ),
}
#: What the readers actually saw on set 1, for the reader-evidence column.
_SET1_NOISE_SCOPE = {"em": "all", "ma": "limb", "bw": "chest"}
_SET1_SNR_RANGE_DB = (-6, 2)
_DIRECT_ELECTRODE_MOTION = {("LL", 1.0), ("LA", 1.0)}
_DIRECT_COUPLED = {(("V1", "V2"), 0), (("V4", "V5"), 6)}


@dataclass(frozen=True)
class CalibEntry:
    """One record of the plan: its recipe plus what is needed to label and report it."""

    spec: RecordSpec
    family: str
    stratum: str
    cell: str
    split: str
    reader_evidence: str  # "direct", "extrapolated" or "none"


# --- The Amendment 2 label table ----------------------------------------------------


def noise_lead_label(noise_type: str, snr_db: float) -> str:
    """Label of a lead carrying NSTDB noise at ``snr_db`` (ADR-0018 amendment 2)."""
    if noise_type == "em":
        return "unusable" if snr_db <= 0 else "usable" if snr_db >= 3 else _off_ladder(snr_db)
    if noise_type == "ma":
        return "grey" if snr_db <= -6 else "usable" if snr_db >= -3 else _off_ladder(snr_db)
    if noise_type == "bw":
        if snr_db <= -9:
            return "unusable"
        if snr_db == -6:
            return "grey"
        return "usable" if snr_db >= -3 else _off_ladder(snr_db)
    raise ValueError(f"unknown noise type {noise_type!r}")


def _off_ladder(snr_db: float) -> str:
    raise ValueError(f"the label table has no answer at {snr_db} dB")


def electrode_motion_label(amplitude_mv: float) -> str:
    """Label of a lead carrying limb-electrode motion of this RMS amplitude."""
    if amplitude_mv >= 1.0:
        return "unusable"
    if amplitude_mv == 0.5:
        return "grey"
    raise ValueError(f"the label table has no answer at {amplitude_mv} mV")


def coupled_label(snr_db: float) -> str:
    """Label of a lead carrying coupled precordial noise."""
    if snr_db == 0:
        return "unusable"
    if snr_db == 6:
        return "grey"
    raise ValueError(f"the label table has no answer at {snr_db} dB")


def _step_displayed_leads(step: Mapping) -> tuple[str, ...]:
    if step["op"] == "electrode":
        return (*_ELECTRODE_DISPLAYED[step["electrode"]], *CHEST_LEADS)
    if step["op"] == "precordial":
        leads: Iterable[str] = step["shared_weights"]
    else:
        leads = step["leads"]
    return tuple(ld for ld in leads if ld in DISPLAYED)


def lead_labels(entry: CalibEntry) -> dict[str, tuple[str, str]]:
    """``lead -> (label, rule)`` from the recipe alone, for all twelve leads.

    Labels are ``unusable``, ``usable``, ``grey`` (not scored) or ``not_displayed``: readers saw
    the eight independent leads, so the derived limb leads carry no reader judgement.
    """
    labels = {ld: ("not_displayed", "derived_not_displayed") for ld in DERIVED_LIMB_LEADS}
    labels |= {ld: ("usable", "untouched") for ld in DISPLAYED}
    for step in entry.spec.steps:
        leads = _step_displayed_leads(step)
        if entry.family == "compound":
            label, rule = "unusable", "compound_fault"
        elif entry.family == "noise":
            label = noise_lead_label(step["noise_type"], step["snr_db"])
            rule = f"{step['noise_type']}_{step['snr_db']:+d}dB"
        elif entry.family == "electrode_motion":
            label = electrode_motion_label(step["amplitude_mv"])
            rule = f"electrode_motion_{step['amplitude_mv']}mV"
        elif entry.family == "electrode_dc":
            label, rule = "usable", "dc_electrode_offset"
        elif entry.family == "lead_off":
            label, rule = "unusable", "lead_off"
        elif entry.family == "coupled":
            label = coupled_label(step["snr_db"])
            rule = f"coupled_{step['snr_db']:+d}dB"
        else:
            raise ValueError(f"{entry.spec.record_id}: no label rule for family {entry.family}")
        for lead in leads:
            labels[lead] = (label, rule)
    if entry.family == "natural":
        labels |= {ld: ("usable", "naturally_poor") for ld in DISPLAYED}
    elif entry.family == "clean":
        labels |= {ld: ("usable", "clean") for ld in DISPLAYED}
    return labels


def repeat_label(labels: Mapping[str, tuple[str, str]]) -> tuple[str, str]:
    """Record label from the mined rule: ``repeat``, ``keep`` or ``grey`` (not scored).

    ``repeat`` needs at least :data:`REPEAT_MIN_UNUSABLE` unusable displayed leads whatever the
    grey leads turn out to be; ``keep`` needs that no grey lead could lift the count above
    :data:`REPEAT_MAX_KEEP`. Anything between is not scored.
    """
    values = [labels[ld][0] for ld in DISPLAYED]
    unusable, grey = values.count("unusable"), values.count("grey")
    rule = f"unusable={unusable},grey={grey}"
    if unusable >= REPEAT_MIN_UNUSABLE:
        return "repeat", rule
    if unusable + grey <= REPEAT_MAX_KEEP:
        return "keep", rule
    return "grey", rule


def _expected(labels: Mapping[str, tuple[str, str]], repeat: str) -> dict:
    """The truth-log view of the labels. ``labels.csv`` is the authority."""
    quality = {"unusable": "bad", "grey": "borderline", "usable": "good"}
    overrides = {ld: quality[labels[ld][0]] for ld in DISPLAYED}
    bad = [ld for ld, q in overrides.items() if q == "bad"]
    any_fault = any(q != "good" for q in overrides.values())
    return {
        "record_quality": (
            "reject" if repeat == "repeat" else "limited" if any_fault else "diagnostic"
        ),
        "lead_quality": {"default": "good", "overrides": overrides},
        "rejected_leads": bad,
        "noiseguard_bad_leads": bad,
        "noiseguard_discard": repeat == "repeat",
    }


# --- The plan ----------------------------------------------------------------------


def _split_of(replicate: int) -> str:
    """Three of every five replicates fit; two select."""
    return "holdout" if replicate % 5 >= 3 else "calib"


def _noise_offsets(index: int, split: str, n: int) -> list[int]:
    """``n`` start samples, mutually non-overlapping, inside the split's NSTDB region.

    Distinct slots are at least :data:`NSTDB_SLOT` apart and the jitter is at most
    ``NSTDB_SLOT - N_SAMPLES``, so segments of a record cannot overlap and none leaves its region.
    A slot may recur across records of a split: NSTDB is too short for 8 fresh segments per record.
    """
    low, high = NSTDB_REGIONS[split]
    slots = np.arange(low, high - NSTDB_SLOT + 1, NSTDB_SLOT)
    rng = np.random.default_rng([OFFSET_SEED, index])
    picked = rng.choice(slots, size=n, replace=False)
    jitter = rng.integers(0, NSTDB_SLOT - N_SAMPLES + 1, size=n)
    return [int(s + j) for s, j in zip(picked, jitter, strict=True)]


def _noise_steps(index: int, split: str, noise: str, leads: Sequence[str], snr: int) -> list[dict]:
    offsets = _noise_offsets(index, split, len(leads))
    return [
        {
            "op": "nstdb_mix",
            "noise_type": noise,
            "noise_source": {"record": noise, "channel": NSTDB_CHANNEL, "start_sample": start},
            "leads": [lead],
            "interval_s": [0, 10],
            "snr_db": snr,
            "propagate_derived": lead in ("I", "II"),
        }
        for lead, start in zip(leads, offsets, strict=True)
    ]


def _noise_evidence(noise: str, scope: str, snr: int) -> str:
    if _SET1_NOISE_SCOPE[noise] != scope:
        return "none"
    low, high = _SET1_SNR_RANGE_DB
    return "direct" if low <= snr <= high else "extrapolated"


def _electrode_motion_evidence(electrode: str, amp: float) -> str:
    if electrode == "RA" or amp == 0.5:
        return "none"
    return "direct" if (electrode, amp) in _DIRECT_ELECTRODE_MOTION else "extrapolated"


def calib_plan() -> list[CalibEntry]:
    """The whole corpus definition, in a fixed order. Sources stay unresolved."""
    rows: list[tuple[str, str, str, str, list, str, str]] = []

    def add(family, stratum, cell, evidence, steps=None, group="engineering", replicates=None):
        for replicate in range(REPLICATES[family] if replicates is None else replicates):
            rows.append((family, stratum, cell, evidence, steps, group, _split_of(replicate)))

    for noise in NOISE_TYPES:
        for scope in SCOPES:
            for snr in FULL_SNR_DB:
                add(
                    "noise",
                    f"noise_{noise}_{scope}",
                    f"noise/{noise}/{scope}/{snr:+d}",
                    _noise_evidence(noise, scope, snr),
                    (noise, SCOPES[scope], snr),
                    "real_noise",
                )
    for electrode in ELECTRODES:
        for amp in ELECTRODE_MOTION_RMS_MV:
            step = {"op": "electrode", "electrode": electrode, "kind": "motion"}
            add(
                "electrode_motion",
                f"electrode_motion_{electrode.lower()}",
                f"electrode_motion/{electrode}/{amp}",
                _electrode_motion_evidence(electrode, amp),
                [{**step, "amplitude_mv": amp}],
            )
    for electrode in ELECTRODES:
        step = {"op": "electrode", "electrode": electrode, "kind": "offset"}
        add(
            "electrode_dc",
            f"electrode_dc_{electrode.lower()}",
            f"electrode_dc/{electrode}/{ELECTRODE_DC_MV}",
            "direct",
            [{**step, "amplitude_mv": ELECTRODE_DC_MV}],
        )
    for leads in LEAD_OFF_CASES:
        limb = {"I", "II"} & set(leads)
        add(
            "lead_off",
            "lead_off",
            f"lead_off/{'+'.join(leads)}",
            "extrapolated" if limb else "direct",
            [{"op": "lead_off", "leads": list(leads), "propagate_derived": bool(limb)}],
        )
    for leads, weights in COUPLED_CASES.items():
        for snr in COUPLED_SNR_DB:
            add(
                "coupled",
                "coupled",
                f"coupled/{'+'.join(leads)}/{snr:+d}",
                "direct" if (leads, snr) in _DIRECT_COUPLED else "extrapolated",
                [{"op": "precordial", "shared_weights": dict(weights), "snr_db": snr}],
            )
    for name, steps in COMPOUND_CASES.items():
        add(
            "compound",
            "compound",
            f"compound/{name}",
            "none" if name == "E" else "extrapolated",
            [dict(s) for s in steps],
        )
    for flag, count in NATURAL_COUNTS.items():
        add(
            "natural",
            f"natural_{flag}",
            f"natural/{flag}",
            "direct",
            [],
            "naturally_poor",
            replicates=count,
        )
    add("clean", "clean", "clean", "extrapolated", [], "control", replicates=N_CLEAN_CONTROLS)

    plan: list[CalibEntry] = []
    for index, (family, stratum, cell, evidence, steps, group, split) in enumerate(rows):
        if family == "noise":
            noise, leads, snr = steps
            steps = _noise_steps(index, split, noise, leads, snr)
        spec = RecordSpec(
            record_id=f"calib1_{index + 1:04d}_{stratum}",
            group=group,
            source=SourceSpec("ptbxl"),
            seed_index=SEED_INDEX_BASE + index,
            steps=tuple(steps),
        )
        entry = CalibEntry(spec, family, stratum, cell, split, evidence)
        labels = lead_labels(entry)
        expected = _expected(labels, repeat_label(labels)[0])
        plan.append(replace(entry, spec=replace(spec, expected=expected)))
    return plan


# --- Label file ---------------------------------------------------------------------

LABEL_COLUMNS = ("record_id", "split", "family", "cell", "reader_evidence", "item", "label", "rule")


def labels_csv_text(plan: Iterable[CalibEntry]) -> str:
    """The frozen label file: twelve lead rows and a repeat row per record."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(LABEL_COLUMNS)
    for entry in plan:
        head = (entry.spec.record_id, entry.split, entry.family, entry.cell, entry.reader_evidence)
        labels = lead_labels(entry)
        for lead in CANONICAL_LEAD_ORDER:
            writer.writerow((*head, lead, *labels[lead]))
        writer.writerow((*head, "repeat", *repeat_label(labels)))
    return buffer.getvalue()


def labels_sha256(plan: Iterable[CalibEntry]) -> str:
    return hashlib.sha256(labels_csv_text(plan).encode("utf-8")).hexdigest()


def verify_labels_file(path: Path, plan: Iterable[CalibEntry]) -> str:
    """Hash of the label file on disk; raises unless it is what the definition produces."""
    actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    expected = labels_sha256(plan)
    if actual != expected:
        raise ValueError(f"{path}: labels differ from the definition ({actual} vs {expected})")
    return actual


def _md_table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def design_tables(plan: Sequence[CalibEntry]) -> str:
    """Composition tables for ``docs/CALIB_V1.md``, computed from the definition alone."""
    families: dict[str, Counter] = {}
    cells: dict[str, dict] = {}
    for entry in plan:
        families.setdefault(entry.family, Counter())[entry.split] += 1
        labels = lead_labels(entry)
        faulted = sorted({labels[ld][0] for ld in DISPLAYED if labels[ld][1] != "untouched"})
        cell = cells.setdefault(
            entry.cell,
            {
                "label": "/".join(faulted),
                "repeat": repeat_label(labels)[0],
                "evidence": entry.reader_evidence,
                "n": Counter(),
            },
        )
        cell["n"][entry.split] += 1
    lines = _md_table(
        ("Family", "Records", "calib", "holdout"),
        (
            (f, c["calib"] + c["holdout"], c["calib"], c["holdout"])
            for f, c in [*families.items(), ("total", sum(families.values(), Counter()))]
        ),
    )
    lines += [""]
    lines += _md_table(
        ("Cell", "Faulted leads", "Repeat", "calib", "holdout", "Reader evidence"),
        (
            (name, c["label"], c["repeat"], c["n"]["calib"], c["n"]["holdout"], c["evidence"])
            for name, c in cells.items()
        ),
    )
    return "\n".join(lines)


# --- Parents ------------------------------------------------------------------------


def development_patients(
    rows: Sequence[Mapping[str, str]],
    set1_id_files: Sequence[Path],
    set2_sources: Path,
    *,
    expected: int = 170,
) -> set[str]:
    """Patients behind review sets 1 and 2. Only identifiers are read from those files."""
    with_ids: set[str] = set()
    for path in set1_id_files:
        with Path(path).open(newline="") as fh:
            with_ids |= {r["filename_hr"] for r in csv.DictReader(fh)}
    patients = {r["patient_id"] for r in rows if r["filename_hr"] in with_ids}
    with Path(set2_sources).open(newline="") as fh:
        patients |= {r["patient_id"] for r in csv.DictReader(fh)}
    if len(patients) != expected:
        raise ValueError(f"expected {expected} development patients, found {len(patients)}")
    return patients


def select_calib_sources(
    rows: Sequence[Mapping[str, str]],
    *,
    excluded_patients: set[str],
    seed: int,
) -> tuple[list[Mapping[str, str]], dict[str, list[Mapping[str, str]]]]:
    """``(clean, natural by flag)``: adults, one ECG per patient, no patient used twice.

    Clean parents carry no quality flag and keep their natural mix of rhythms: a beat-template
    metric must meet AF, PVC and paced beats during fitting, not only at the final check.
    Naturally poor parents carry exactly one quality flag.
    """
    pool = [
        r for r in rows if r["patient_id"] not in excluded_patients and _age(r) >= MIN_AGE_YEARS
    ]
    rng = np.random.default_rng([seed, 2])
    used: set[str] = set()

    def draw(candidates: list, n: int, label: str) -> list:
        candidates = [r for r in _dedupe_by_patient(candidates) if r["patient_id"] not in used]
        if len(candidates) < n:
            raise ValueError(f"only {len(candidates)} eligible parents for {label}, need {n}")
        picked = [candidates[i] for i in sorted(rng.permutation(len(candidates))[:n].tolist())]
        used.update(r["patient_id"] for r in picked)
        return picked

    natural = {
        flag: draw([r for r in pool if quality_flags(r) == (flag,)], count, f"natural {flag}")
        for flag, count in NATURAL_COUNTS.items()
    }
    n_clean = sum(1 for e in calib_plan() if e.family != "natural")
    return draw([r for r in pool if is_clean(r)], n_clean, "clean parents"), natural


def _source(row: Mapping[str, str]) -> SourceSpec:
    codes = _scp(row)
    rhythm = next(
        (
            name
            for code, name in (("AFIB", "afib"), ("AFLT", "flutter"), ("SR", "sinus"))
            if code in codes
        ),
        "unknown",
    )
    age = _age(row)
    return SourceSpec(
        "ptbxl",
        row["filename_hr"],
        rhythm_class=rhythm,
        age_years=None if np.isnan(age) else age,
        ptbxl_quality_flags=quality_flags(row),
    )


def bind_parents(
    plan: Sequence[CalibEntry],
    clean: Sequence[Mapping[str, str]],
    natural: Mapping[str, Sequence[Mapping[str, str]]],
    *,
    seed: int,
) -> list[CalibEntry]:
    """Deal shuffled parents to the plan: one patient, one record, so one split."""
    rng = np.random.default_rng([seed, 3])
    clean_iter = iter([clean[i] for i in rng.permutation(len(clean))])
    natural_iter = {
        flag: iter([rows[i] for i in rng.permutation(len(rows))]) for flag, rows in natural.items()
    }
    bound = []
    for entry in plan:
        if entry.family == "natural":
            row = next(natural_iter[entry.stratum.removeprefix("natural_")])
        else:
            row = next(clean_iter)
        bound.append(replace(entry, spec=replace(entry.spec, source=_source(row))))
    return bound


# --- Generation checks --------------------------------------------------------------


def segment_provider(load: Callable[[str, int], np.ndarray]) -> Callable:
    """A noise provider slicing whole resampled channels, each loaded once.

    Unlike the loader it never wraps around the end of a record: a wrap would join two unrelated
    stretches of noise, and the plan's offsets are built never to need it.
    """
    channels: dict[tuple[str, int], np.ndarray] = {}

    def provider(step: dict, n: int, rng: np.random.Generator) -> np.ndarray:
        src = step["noise_source"]
        key = (src["record"], int(src["channel"]))
        if key not in channels:
            channels[key] = load(*key)
        start = int(src["start_sample"])
        if start + n > channels[key].shape[0]:
            raise ValueError(f"noise segment at {start} would wrap around {key}")
        return channels[key][start : start + n].copy()

    return provider


def _algebra_residual(signal: np.ndarray) -> np.ndarray:
    """Departure of the stored derived limb leads from Einthoven and Goldberger."""
    lead_i, lead_ii = signal[LEAD_INDEX["I"]], signal[LEAD_INDEX["II"]]
    derived = {
        "III": lead_ii - lead_i,
        "aVR": -(lead_i + lead_ii) / 2.0,
        "aVL": lead_i - lead_ii / 2.0,
        "aVF": lead_ii - lead_i / 2.0,
    }
    return np.stack([signal[LEAD_INDEX[name]] - derived[name] for name in DERIVED_LIMB_LEADS])


def verify_record(
    entry: CalibEntry, label: RecordLabel, saved: np.ndarray, clean: np.ndarray
) -> dict[str, object]:
    """Check one stored record against its truth log; raise on any failure.

    Every sample outside the logged lead/time mask equals the parent; stored SNR matches the
    request; derived limb leads obey the lead algebra; electrode faults reach V1-V6 through the
    Wilson central terminal; no two displayed leads share a noise segment.
    """
    rid = entry.spec.record_id
    if not np.isfinite(saved).all():
        raise ValueError(f"{rid}: non-finite samples")
    allowed = np.zeros(saved.shape, dtype=bool)
    snr_error = 0.0
    for step in label.corruption_truth.steps:
        start, stop = 0, saved.shape[1]
        if step.interval_s is not None:
            start, stop = (int(round(t * TARGET_FS)) for t in step.interval_s)
        for lead in step.leads_affected:
            allowed[LEAD_INDEX[lead], start:stop] = True
        if step.op == "nstdb_mix":
            for lead in step.params["leads"]:
                i = LEAD_INDEX[lead]
                snr = measured_snr_db(
                    clean[i, start:stop], saved[i, start:stop] - clean[i, start:stop]
                )
                error = abs(snr - step.snr_requested_db)
                if error > SNR_TOLERANCE_DB:
                    raise ValueError(
                        f"{rid}/{lead}: stored SNR {snr:.2f} vs {step.snr_requested_db} dB"
                    )
                snr_error = max(snr_error, error)
    if not np.array_equal(saved[~allowed], clean[~allowed]):
        raise ValueError(f"{rid}: signal changed outside the truth-log mask")

    has_electrode = any(s["op"] == "electrode" for s in entry.spec.steps)
    target = np.zeros_like(clean[:4]) if has_electrode else _algebra_residual(clean)
    if np.max(np.abs(_algebra_residual(saved) - target)) > ALGEBRA_TOLERANCE_MV:
        raise ValueError(f"{rid}: derived limb leads break the lead algebra")

    delta = saved - clean
    rms_error = 0.0
    if entry.family in ("electrode_motion", "electrode_dc"):
        step = entry.spec.steps[0]
        electrode = step["electrode"]
        witness, sign = {"RA": ("I", 1), "LA": ("I", -1), "LL": ("II", -1)}[electrode]
        expected = sign * delta[LEAD_INDEX[witness]] / 3.0
        for lead in CHEST_LEADS:
            if np.max(np.abs(delta[LEAD_INDEX[lead]] - expected)) > ALGEBRA_TOLERANCE_MV:
                raise ValueError(f"{rid}/{lead}: electrode fault does not follow the WCT")
        if entry.family == "electrode_motion":
            witness_delta = delta[LEAD_INDEX[witness]]
            rms = float(np.sqrt(np.mean((witness_delta - np.median(witness_delta)) ** 2)))
            rms_error = abs(rms / step["amplitude_mv"] - 1.0)
            if rms_error > RMS_TOLERANCE:
                raise ValueError(f"{rid}: electrode RMS {rms:.3f} vs {step['amplitude_mv']} mV")

    max_corr = 0.0
    if entry.family == "noise" and len(entry.spec.steps) > 1:
        leads = [s["leads"][0] for s in entry.spec.steps]
        corr = np.corrcoef(np.stack([delta[LEAD_INDEX[ld]] for ld in leads]))
        max_corr = float(np.max(np.abs(corr[np.triu_indices(len(leads), 1)])))
        if max_corr > 0.999:
            raise ValueError(f"{rid}: two leads share one noise segment")
    return {
        "mask_ok": True,
        "snr_error_db": snr_error,
        "electrode_rms_error": rms_error,
        "max_noise_corr": max_corr,
    }
