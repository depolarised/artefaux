# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Blinded noise benchmark: the held-out test-set definition (block T1).

Review sets 1 and 2 are development data. This module defines the separate, frozen test
block that compares quality gates (signalguard, Uni-G) against an adjudicated expert
reference. Its design follows the set-1 synthesis (``docs/BENCHMARK.md``):

* noise type is **crossed** with lead scope (set 1 confounded them);
* recorded NSTDB noise is drawn from minutes the development sets never used;
* changes to I or II are carried into the derived limb leads, as a cart would;
* non-noise confounders and data-integrity faults are separate strata.

The definition is data-independent: callers pass already-selected parents. Expected
labels are authored hypotheses only. The reference standard is the expert review.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence

import numpy as np

from .constants import CHEST_LEADS, DERIVED_LIMB_LEADS
from .recipes import RecordSpec, SourceSpec
from .selection import _dedupe_by_patient, is_clean, quality_flags

BENCH_ID = "artefaux-bench"
BENCH_VERSION = "1.0.0"
BLOCK = "T1"
SCHEMA_VERSION = 1
N_RECORDS = 120
SEED_INDEX_BASE = 3000

NOISE_TYPES = ("em", "ma", "bw")
#: One common ladder for every noise type and scope, spanning the set-1 boundary
#: (decisions changed between -6 and +2 dB) with a margin on each side.
FULL_SNR_DB = (-9, -6, -3, 0, 3, 6)
HALF_SNR_DB = -6
#: Raised-cosine fade at noise edges inside the record (half-record cases), so a noise
#: burst does not begin with an instantaneous baseline step.
NOISE_TAPER_S = 0.25
INDEPENDENT_LEADS = ("I", "II", *CHEST_LEADS)
LIMB_LEADS = ("I", "II", *DERIVED_LIMB_LEADS)
SCOPES: dict[str, tuple[str, ...]] = {
    "limb": ("I", "II"),
    "chest": CHEST_LEADS,
    "all": INDEPENDENT_LEADS,
}
HALVES = ((0, 5), (5, 10))
ELECTRODE_CONFIGS = (("RA",), ("LA",), ("LL",), ("RA", "LL"))
ELECTRODE_SNR_DB = (-6, 0)
#: Limb leads whose samples move when one limb electrode is noised (electrode algebra,
#: ``electrode_domain.electrodes_to_leads``). RA is absent from III and LA from II, so
#: III and II are not reached by RA and LA respectively; aVR, aVL and aVF reach all three.
ELECTRODE_LIMB_LEADS: dict[str, tuple[str, ...]] = {
    "RA": ("I", "II", "aVR", "aVL", "aVF"),
    "LA": ("I", "III", "aVR", "aVL", "aVF"),
    "LL": ("II", "III", "aVR", "aVL", "aVF"),
}
REVERSALS = (("LA", "RA"), ("LA", "LL"), ("RA", "LL"))

#: Development sets drew NSTDB offsets from [0, 100 000) samples at 500 Hz (first 200 s).
#: The benchmark uses only later, non-overlapping slots of each NSTDB record.
NSTDB_TEST_START = 120_000
NSTDB_RESAMPLED_LEN = 902_778  # 650 000 samples at 360 Hz, resampled to 500 Hz
NSTDB_SLOT = 5_500  # 10 s of noise plus a 0.5 s guard

#: GRIASCII v1.5 header lines (1-based, as in the Glasgow specification) for the Uni-G
#: inputs: a complete adult 12-lead request using the specification's suggested defaults.
#: Line 10 matters most: left blank, Uni-G reads V1-V3 as paediatric V4R/V1/V2.
UNIG_HEADER_LINES: dict[int, str] = {
    5: "U",  # sex unknown
    6: "U",  # race unknown
    7: "18262",  # age 50 years in days: adult noise thresholds, no parent information
    8: "00/00/0000,00/00/0000",  # dates unknown, so line 7 is used
    9: "00:00:00",
    10: "Adult",  # electrode positioning
    11: "0 0",  # drugs undefined
    12: "0 0",  # clinical diagnosis undefined
    13: "50",  # mains filter (PTB-XL was recorded on 50 Hz mains)
    14: "50 100",  # bradycardia / tachycardia limits (specification defaults)
    15: "QTcHodge",
    16: "0 0",  # no pacemaker information: library spike detection runs
    17: "12Lead",
}

#: Parents must be adults (PTB-XL codes ages over 89 as 300, which still qualifies).
MIN_AGE_YEARS = 18

#: Confounder parents, selected by PTB-XL SCP code from quality-clean records
#: (VCLVH: voltage criteria for LVH, i.e. high QRS amplitude).
CONFOUNDER_CODES: dict[str, tuple[str, int]] = {
    "afib": ("AFIB", 3),
    "paced": ("PACE", 2),
    "low_voltage": ("LVOLT", 2),
    "high_voltage": ("VCLVH", 2),
}
#: Naturally poor parents by PTB-XL quality flag (more severe flags weighted up).
NATURAL_FLAGS: dict[str, int] = {
    "burst_noise": 3,
    "electrodes_problems": 3,
    "baseline_drift": 2,
    "static_noise": 2,
}

STRATA = {
    "clean": 12,
    "confounder": 12,
    "full_noise": 54,
    "half_noise": 12,
    "electrode_noise": 8,
    "integrity": 12,
    "natural": 10,
}
N_CLEAN_PARENTS = (
    STRATA["clean"]
    + STRATA["full_noise"]
    + STRATA["half_noise"]
    + STRATA["electrode_noise"]
    + STRATA["integrity"]
    + len(REVERSALS)
)

#: Data-integrity faults: (op, leads, extra step fields, half interval or None).
INTEGRITY_CASES: tuple[tuple[str, tuple[str, ...], dict, tuple[int, int] | None], ...] = (
    ("flatline", ("I",), {}, None),
    ("flatline", ("V3",), {}, None),
    ("lead_off", ("II",), {}, None),
    ("lead_off", ("V5",), {}, None),
    ("lead_off", ("V1", "V2"), {}, None),
    ("lead_off", ("V4",), {}, (5, 10)),
    ("lead_off", ("I",), {}, (0, 5)),
    ("constant_adc", ("V1",), {"value_mv": 1.5}, None),
    ("constant_adc", ("V4",), {"value_mv": -0.8}, None),
    ("constant_adc", ("I", "II"), {"value_mv": 0.6}, None),
    ("swing", ("V2",), {"p2p_mv": 12.0, "rail_mv": 5.0}, None),
    ("swing", ("I", "II"), {"p2p_mv": 10.0, "rail_mv": 5.0}, None),
)
_INTEGRITY_TYPE = {
    "flatline": "flatline_zero",
    "lead_off": "lead_off",
    "constant_adc": "constant_adc",
    "swing": "rail_saturation",
}


def assign_noise_slots(
    n_uses: Mapping[tuple[str, int], int], seed: int
) -> dict[tuple[str, int], list[int]]:
    """Distinct, non-overlapping NSTDB start samples, outside dev use, one pool per record.

    Keys are (NSTDB record, channel). The two channels of a record are simultaneous
    recordings of the same noise, so a slot is never reused on either channel: each
    record draws all its uses from one pool, which is then dealt out to its channels in
    sorted order. Records are iterated sorted, so the draw is deterministic.
    """
    slots = np.arange(NSTDB_TEST_START, NSTDB_RESAMPLED_LEN - NSTDB_SLOT, NSTDB_SLOT)
    rng = np.random.default_rng([seed, 1])
    out: dict[tuple[str, int], list[int]] = {}
    for record in sorted({rec for rec, _ in n_uses}):
        keys = sorted(key for key in n_uses if key[0] == record)
        need = sum(n_uses[key] for key in keys)
        if need > slots.size:
            raise ValueError(f"not enough NSTDB slots for record {record}: need {need}")
        picked = rng.choice(slots, size=need, replace=False)
        at = 0
        for key in keys:
            out[key] = sorted(int(s) for s in picked[at : at + n_uses[key]])
            at += n_uses[key]
    return out


def _quality_for_snr(snr: float) -> str:
    return "bad" if snr <= -3 else "borderline" if snr < 3 else "good"


def _lead_expectation(
    overrides: Mapping[str, str],
    *,
    whole: bool,
    record_quality: str,
    discard: bool = False,
    derived: Sequence[str] = (),
    reason_codes: Sequence[str] = (),
) -> dict:
    """Expected block whose per-lead lists all derive from one quality map.

    A lead is unusable when authored ``bad``; it is rejected only for whole-record
    faults, matching the set-1 convention that partial-record noise does not reject.
    """
    bad = [ld for ld, quality in overrides.items() if quality == "bad"]
    return {
        "record_quality": record_quality,
        "lead_quality": {"default": "good", "overrides": dict(overrides)},
        "rejected_leads": bad if whole else [],
        "derived_leads_invalidated": list(derived),
        "reason_codes": list(reason_codes),
        "noiseguard_bad_leads": bad,
        "noiseguard_discard": discard,
    }


def _hypothesis(leads: Sequence[str], snr: float, interval: tuple[int, int]) -> dict:
    """Authored expectation, calibrated loosely on set 1. Not a reference standard.

    A change to I or II reaches all four derived limb leads (Einthoven: III = II - I,
    aVR = -(I + II) / 2, aVL = I - II / 2, aVF = II - I / 2), so each takes the quality
    of the noised lead it came from.
    """
    whole = tuple(interval) == (0, 10)
    quality = _quality_for_snr(snr)
    derived = DERIVED_LIMB_LEADS if {"I", "II"} & set(leads) else ()
    discard = whole and set(leads) == set(INDEPENDENT_LEADS) and snr <= 0
    return _lead_expectation(
        dict.fromkeys((*leads, *derived), quality),
        whole=whole,
        record_quality="reject" if discard else "diagnostic" if snr >= 3 else "limited",
        discard=discard,
        derived=derived,
    )


def _integrity_expected(op: str, leads: Sequence[str], interval) -> dict:
    both_limb = {"I", "II"} <= set(leads)
    derived = DERIVED_LIMB_LEADS if {"I", "II"} & set(leads) else ()
    expected = _lead_expectation(
        dict.fromkeys((*leads, *derived), "bad"),
        whole=interval is None,
        record_quality="rhythm_only" if both_limb else "limited",
        discard=both_limb,
        derived=derived,
    )
    return {
        **expected,
        "data_integrity_failure": True,
        "integrity_failure_type": _INTEGRITY_TYPE[op],
    }


def _electrode_expected(electrodes: Sequence[str], snr: float) -> dict:
    """Authored expectation for limb-electrode noise over the whole record.

    Limb leads reached by the electrodes take the SNR quality of the hypothesis.
    Every V lead changes through the Wilson central terminal at one third of the
    electrode amplitude. Its authored quality is ``borderline`` only at SNR <= -6 dB and
    ``good`` otherwise: a rule chosen by the author, not measured, and it is the place
    where a chest-lead hypothesis can disagree with the expert review.
    """
    limb = tuple(ld for ld in LIMB_LEADS if any(ld in ELECTRODE_LIMB_LEADS[e] for e in electrodes))
    derived = tuple(ld for ld in DERIVED_LIMB_LEADS if ld in limb)
    chest = "borderline" if snr <= -6 else "good"
    overrides = {**dict.fromkeys(limb, _quality_for_snr(snr)), **dict.fromkeys(CHEST_LEADS, chest)}
    return _lead_expectation(
        overrides,
        whole=True,
        record_quality="diagnostic" if snr >= 3 else "limited",
        derived=derived,
        reason_codes=("WCT_PROPAGATED_NOISE",),
    )


_CLEAN_EXPECTED = {"record_quality": "diagnostic", "lead_quality": {"default": "good"}}


def build_bench_specs(
    clean: Sequence[SourceSpec],
    confounders: Mapping[str, Sequence[SourceSpec]],
    natural: Sequence[SourceSpec],
    *,
    master_seed: int,
) -> list[RecordSpec]:
    """The 120-record T1 definition, in stratum order (blinding reorders it later)."""
    if len(clean) != N_CLEAN_PARENTS:
        raise ValueError(f"need {N_CLEAN_PARENTS} clean parents, got {len(clean)}")
    for name, (_, count) in CONFOUNDER_CODES.items():
        if len(confounders.get(name, ())) != count:
            raise ValueError(f"need {count} '{name}' confounder parents")
    if len(natural) != STRATA["natural"]:
        raise ValueError(f"need {STRATA['natural']} naturally poor parents")
    parents = [*clean, *(s for name in CONFOUNDER_CODES for s in confounders[name]), *natural]
    ids = [s.record_id for s in parents]
    if None in ids or len(set(ids)) != len(ids):
        raise ValueError("benchmark parents must be resolved and distinct")

    # Noise-slot demand per NSTDB record and channel, in a fixed pre-pass.
    noise_plan = []  # (stratum, args) for every noised record, in order
    for nt in NOISE_TYPES:
        for scope in SCOPES:
            for snr in FULL_SNR_DB:
                noise_plan.append(("full", (nt, scope, snr)))
    for nt in NOISE_TYPES:
        for half in HALVES:
            for scope in ("all", "chest"):
                noise_plan.append(("half", (nt, scope, half)))
    for cfg in ELECTRODE_CONFIGS:
        for snr in ELECTRODE_SNR_DB:
            noise_plan.append(("electrode", (cfg, snr)))
    demand: dict[tuple[str, int], int] = {}
    channels = []
    for i, (kind, args) in enumerate(noise_plan):
        if kind == "electrode":
            use = [("em", (i + k) % 2) for k in range(len(args[0]))]
        else:
            use = [(args[0], i % 2)]
        channels.append(use)
        for key in use:
            demand[key] = demand.get(key, 0) + 1
    slots = assign_noise_slots(demand, master_seed)
    cursor = dict.fromkeys(demand, 0)

    def take(key):
        start = slots[key][cursor[key]]
        cursor[key] += 1
        return {"record": key[0], "channel": key[1], "start_sample": start}

    specs: list[RecordSpec] = []
    clean_iter = iter(clean)

    def add(stratum, source, steps=(), expected=None, group="real_noise"):
        index = len(specs)
        specs.append(
            RecordSpec(
                record_id=f"nlf_bench1_{stratum}_{index + 1:03d}",
                group=group,
                source=source,
                seed_index=SEED_INDEX_BASE + index,
                steps=tuple(steps),
                expected=expected or dict(_CLEAN_EXPECTED),
                has_clean_parent=bool(steps),
            )
        )

    for _ in range(STRATA["clean"]):
        add("clean", next(clean_iter), group="control")

    for (kind, args), use in zip(noise_plan, channels, strict=True):
        if kind == "full":
            nt, scope, snr = args
            leads, interval = SCOPES[scope], (0, 10)
        elif kind == "half":
            nt, scope, interval = args
            leads, snr = SCOPES[scope], HALF_SNR_DB
        else:
            continue
        add(
            f"{kind}_{nt}_{scope}",
            next(clean_iter),
            steps=[
                {
                    "op": "nstdb_mix",
                    "noise_type": nt,
                    "noise_source": take(use[0]),
                    "leads": list(leads),
                    "interval_s": list(interval),
                    "snr_db": snr,
                    "taper_s": NOISE_TAPER_S,
                    "propagate_derived": bool({"I", "II"} & set(leads)),
                }
            ],
            expected=_hypothesis(leads, snr, interval),
        )

    for (kind, args), use in zip(noise_plan, channels, strict=True):
        if kind != "electrode":
            continue
        cfg, snr = args
        add(
            f"electrode_{'_'.join(cfg).lower()}",
            next(clean_iter),
            steps=[
                {
                    "op": "electrode_nstdb",
                    "electrodes": list(cfg),
                    "noise_type": "em",
                    "noise_sources": [take(key) for key in use],
                    "interval_s": [0, 10],
                    "snr_db": snr,
                }
            ],
            expected=_electrode_expected(cfg, snr),
            group="engineering",
        )

    for op, leads, extra, interval in INTEGRITY_CASES:
        step = {"op": op, "leads": list(leads), **extra, "propagate_derived": True}
        if interval is not None:
            step["interval_s"] = list(interval)
        add(
            f"integrity_{op}",
            next(clean_iter),
            steps=[step],
            expected=_integrity_expected(op, leads, interval),
            group="engineering",
        )

    for a, b in REVERSALS:
        add(
            "confounder_reversal",
            next(clean_iter),
            steps=[{"op": "electrode_swap", "electrodes": [a, b]}],
            expected={**_CLEAN_EXPECTED, "reason_codes": ["LEAD_REVERSAL_SUSPECTED"]},
            group="control",
        )
    for name in CONFOUNDER_CODES:
        for source in confounders[name]:
            add(f"confounder_{name}", source, group="control")

    for source in natural:
        add(
            "natural",
            source,
            expected={"record_quality": "limited", "lead_quality": {"default": "good"}},
            group="naturally_poor",
        )

    if len(specs) != N_RECORDS:
        raise AssertionError(f"definition produced {len(specs)} records, expected {N_RECORDS}")
    return specs


def stratum_of(record_id: str) -> str:
    """The stratum key embedded in a benchmark record id."""
    body = record_id.removeprefix("nlf_bench1_").rsplit("_", 1)[0]
    for name in ("clean", "natural", "integrity", "confounder"):
        if body.startswith(name):
            return name
    if body.startswith("full"):
        return "full_noise"
    if body.startswith("half"):
        return "half_noise"
    if body.startswith("electrode"):
        return "electrode_noise"
    raise ValueError(f"not a benchmark record id: {record_id}")


# --- Parent selection (pure; rows are ptbxl_database.csv dicts) ---------------------


def _scp(row: Mapping[str, object]) -> dict:
    value = row.get("scp_codes", "{}")
    return value if isinstance(value, dict) else ast.literal_eval(str(value))


def _age(row: Mapping[str, object]) -> float:
    try:
        return float(row.get("age", ""))
    except ValueError:
        return float("nan")


def select_bench_sources(
    rows: Sequence[Mapping[str, object]],
    *,
    excluded_patients: set,
    seed: int,
) -> tuple[list[Mapping], dict[str, list[Mapping]], list[Mapping]]:
    """Pick (clean, confounders, natural) parents: one ECG per patient, none excluded.

    Confounders need a quality-clean record carrying the SCP code (PTB-XL records form
    statements such as LVOLT with likelihood 0, so presence is the criterion);
    clean parents carry none of the confounder codes. Patients never repeat across strata.
    """
    # Adults only: every Uni-G input declares adult positioning and an adult age, so a
    # paediatric parent would be analysed under the wrong assumptions.
    pool = [
        r for r in rows if r.get("patient_id") not in excluded_patients and _age(r) >= MIN_AGE_YEARS
    ]
    rng = np.random.default_rng([seed, 2])
    used: set = set()

    def draw(candidates, n, label):
        candidates = [r for r in _dedupe_by_patient(candidates) if r["patient_id"] not in used]
        if len(candidates) < n:
            raise ValueError(f"only {len(candidates)} eligible parents for {label}, need {n}")
        picked = [candidates[i] for i in sorted(rng.permutation(len(candidates))[:n].tolist())]
        used.update(r["patient_id"] for r in picked)
        return picked

    clean_pool = [r for r in pool if is_clean(r)]
    confounders = {}
    for name, (code, count) in CONFOUNDER_CODES.items():
        confounders[name] = draw(
            [r for r in clean_pool if code in _scp(r)], count, f"confounder {name}"
        )
    codes = {code for code, _ in CONFOUNDER_CODES.values()}
    natural = []
    for flag, count in NATURAL_FLAGS.items():
        natural += draw([r for r in pool if quality_flags(r) == (flag,)], count, f"natural {flag}")
    clean = draw(
        [r for r in clean_pool if not codes & set(_scp(r))], N_CLEAN_PARENTS, "clean parents"
    )
    return clean, confounders, natural
