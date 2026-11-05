# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The calib-v1 definition: noise provenance, the Amendment 2 labels, the split and the freeze."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from artefaux.benchmark import NSTDB_RESAMPLED_LEN
from artefaux.calib import (
    DISPLAYED,
    N_SAMPLES,
    NSTDB_CHANNEL,
    NSTDB_MIN_START,
    NSTDB_REGIONS,
    REPEAT_MIN_UNUSABLE,
    bind_parents,
    calib_plan,
    design_tables,
    development_patients,
    labels_csv_text,
    labels_sha256,
    lead_labels,
    noise_lead_label,
    repeat_label,
    segment_provider,
    select_calib_sources,
    verify_labels_file,
    verify_record,
)
from artefaux.constants import CANONICAL_LEAD_ORDER, CHEST_LEADS, LEAD_INDEX, TARGET_FS
from artefaux.recipes import build_record
from artefaux.synthetic import synthetic_parent_signal

REPO = Path(__file__).resolve().parents[1]
CALIB_DOC = REPO / "docs" / "CALIB_V1.md"
PLAN = calib_plan()
BY_CELL: dict[str, list] = {}
for _entry in PLAN:
    BY_CELL.setdefault(_entry.cell, []).append(_entry)


def _noise_sources(entry):
    return [s["noise_source"] for s in entry.spec.steps if s["op"] == "nstdb_mix"]


# --- Composition -------------------------------------------------------------------


def test_at_least_400_records_with_unique_ids_and_seed_indices():
    assert len(PLAN) >= 400
    assert len({e.spec.record_id for e in PLAN}) == len(PLAN)
    assert len({e.spec.seed_index for e in PLAN}) == len(PLAN)


@pytest.mark.parametrize("noise", ["em", "ma", "bw"])
@pytest.mark.parametrize("scope", ["limb", "chest", "all"])
@pytest.mark.parametrize("snr", [-9, -6, -3, 0, 3, 6])
def test_noise_type_is_fully_crossed_with_scope_and_each_cell_reaches_both_splits(
    noise, scope, snr
):
    entries = BY_CELL[f"noise/{noise}/{scope}/{snr:+d}"]
    assert {e.split for e in entries} == {"calib", "holdout"}


def test_every_family_of_the_plan_is_present():
    families = {e.family for e in PLAN}
    assert families == {
        "noise",
        "electrode_motion",
        "electrode_dc",
        "lead_off",
        "coupled",
        "compound",
        "natural",
        "clean",
    }
    assert sum(e.family == "clean" for e in PLAN) == 60
    assert sum(e.family == "natural" for e in PLAN) == 40
    for electrode in ("RA", "LA", "LL"):
        for amp in ("0.5", "1.0", "2.0"):
            assert BY_CELL[f"electrode_motion/{electrode}/{amp}"]


def test_every_cell_reaches_both_splits():
    for cell, entries in BY_CELL.items():
        assert {e.split for e in entries} == {"calib", "holdout"}, cell


# --- Noise provenance --------------------------------------------------------------


def test_noise_is_channel_1_outside_the_development_offsets_and_never_wraps():
    n = 0
    for entry in PLAN:
        for src in _noise_sources(entry):
            n += 1
            assert src["channel"] == NSTDB_CHANNEL == 1
            assert src["start_sample"] >= NSTDB_MIN_START >= 100_000 + N_SAMPLES
            assert src["start_sample"] + N_SAMPLES <= NSTDB_RESAMPLED_LEN
    assert n > 1000


def test_calib_and_holdout_draw_noise_from_disjoint_regions():
    spans = {"calib": [], "holdout": []}
    for entry in PLAN:
        for src in _noise_sources(entry):
            spans[entry.split].append((src["record"], src["start_sample"]))
    assert spans["calib"] and spans["holdout"]
    calib_hi, holdout_lo = NSTDB_REGIONS["calib"][1], NSTDB_REGIONS["holdout"][0]
    assert calib_hi <= holdout_lo
    assert max(s for _, s in spans["calib"]) + N_SAMPLES <= calib_hi
    assert min(s for _, s in spans["holdout"]) >= holdout_lo


def test_each_lead_gets_its_own_non_overlapping_segment():
    for entry in PLAN:
        if entry.family != "noise":
            continue
        steps = entry.spec.steps
        assert all(len(s["leads"]) == 1 for s in steps)
        leads = [s["leads"][0] for s in steps]
        assert len(set(leads)) == len(leads)
        starts = sorted(s["noise_source"]["start_sample"] for s in steps)
        assert all(b - a >= N_SAMPLES for a, b in zip(starts, starts[1:], strict=False))
        assert {s["noise_source"]["record"] for s in steps} == {entry.spec.steps[0]["noise_type"]}


def test_only_limb_channels_propagate_to_the_derived_leads():
    for entry in PLAN:
        if entry.family == "noise":
            for step in entry.spec.steps:
                assert step["propagate_derived"] == (step["leads"][0] in ("I", "II"))


# --- Amendment 2 label table -------------------------------------------------------


@pytest.mark.parametrize(
    ("noise", "snr", "label"),
    [
        ("em", -9, "unusable"),
        ("em", -6, "unusable"),
        ("em", -3, "unusable"),
        ("em", 0, "unusable"),
        ("em", 3, "usable"),
        ("em", 6, "usable"),
        ("ma", -9, "grey"),
        ("ma", -6, "grey"),
        ("ma", -3, "usable"),
        ("ma", 0, "usable"),
        ("ma", 3, "usable"),
        ("ma", 6, "usable"),
        ("bw", -9, "unusable"),
        ("bw", -6, "grey"),
        ("bw", -3, "usable"),
        ("bw", 0, "usable"),
        ("bw", 3, "usable"),
        ("bw", 6, "usable"),
    ],
)
def test_noise_table(noise, snr, label):
    assert noise_lead_label(noise, snr) == label
    for scope, leads in (("limb", DISPLAYED[:2]), ("chest", CHEST_LEADS), ("all", DISPLAYED)):
        entry = BY_CELL[f"noise/{noise}/{scope}/{snr:+d}"][0]
        labels = lead_labels(entry)
        for lead in DISPLAYED:
            expected = label if lead in leads else "usable"
            assert labels[lead][0] == expected, (scope, lead)


@pytest.mark.parametrize(
    ("electrode", "carrying", "untouched"),
    [("LL", ("II",), ("I",)), ("LA", ("I",), ("II",)), ("RA", ("I", "II"), ())],
)
@pytest.mark.parametrize(
    ("amp", "label"), [("0.5", "grey"), ("1.0", "unusable"), ("2.0", "unusable")]
)
def test_limb_electrode_motion_marks_the_leads_carrying_it(
    electrode, carrying, untouched, amp, label
):
    labels = lead_labels(BY_CELL[f"electrode_motion/{electrode}/{amp}"][0])
    for lead in (*carrying, *CHEST_LEADS):
        assert labels[lead][0] == label
    for lead in untouched:
        assert labels[lead][0] == "usable"


@pytest.mark.parametrize("electrode", ["RA", "LA", "LL"])
def test_dc_electrode_offset_is_usable_everywhere(electrode):
    labels = lead_labels(BY_CELL[f"electrode_dc/{electrode}/4.0"][0])
    assert all(labels[lead][0] == "usable" for lead in DISPLAYED)


@pytest.mark.parametrize(("cell", "label"), [("V1+V2/+0", "unusable"), ("V1+V2/+6", "grey")])
def test_coupled_precordial(cell, label):
    labels = lead_labels(BY_CELL[f"coupled/{cell}"][0])
    assert labels["V1"][0] == labels["V2"][0] == label
    assert labels["V3"][0] == labels["I"][0] == "usable"


def test_lead_off_and_compound_mark_exactly_the_leads_carrying_the_fault():
    labels = lead_labels(BY_CELL["lead_off/V1+V2"][0])
    assert [ld for ld in DISPLAYED if labels[ld][0] == "unusable"] == ["V1", "V2"]
    labels = lead_labels(BY_CELL["compound/C"][0])
    assert [ld for ld in DISPLAYED if labels[ld][0] == "unusable"] == ["II", "V1", "V6"]


@pytest.mark.parametrize("family", ["clean", "natural"])
def test_clean_and_naturally_poor_are_usable(family):
    entry = next(e for e in PLAN if e.family == family)
    labels = lead_labels(entry)
    assert all(labels[lead][0] == "usable" for lead in DISPLAYED)
    assert repeat_label(labels)[0] == "keep"


def test_undisplayed_derived_leads_are_never_scored():
    for entry in PLAN[::25]:
        labels = lead_labels(entry)
        assert set(labels) == set(CANONICAL_LEAD_ORDER)
        for lead in ("III", "aVR", "aVL", "aVF"):
            assert labels[lead][0] == "not_displayed"


# --- Repeat rule -------------------------------------------------------------------


def _counted(unusable: int, grey: int) -> dict:
    labels = dict.fromkeys(DISPLAYED, ("usable", ""))
    leads = list(DISPLAYED)
    for lead in leads[:unusable]:
        labels[lead] = ("unusable", "")
    for lead in leads[unusable : unusable + grey]:
        labels[lead] = ("grey", "")
    return labels


@pytest.mark.parametrize(
    ("unusable", "grey", "label"),
    [
        (8, 0, "repeat"),
        (7, 0, "repeat"),
        (7, 1, "repeat"),
        (6, 0, "grey"),  # the readers split at exactly 6
        (6, 2, "grey"),
        (0, 8, "grey"),  # could be anything from 0 to 8
        (0, 7, "grey"),
        (0, 6, "grey"),
        (5, 0, "keep"),
        (3, 2, "keep"),
        (0, 5, "keep"),
        (5, 1, "grey"),
        (0, 0, "keep"),
    ],
)
def test_repeat_rule_counts_displayed_leads(unusable, grey, label):
    assert REPEAT_MIN_UNUSABLE == 7
    assert repeat_label(_counted(unusable, grey))[0] == label


@pytest.mark.parametrize(
    ("cell", "label"),
    [
        ("noise/em/all/+0", "repeat"),
        ("noise/em/all/+3", "keep"),
        ("noise/em/chest/-9", "grey"),
        ("noise/em/limb/-9", "keep"),
        ("noise/ma/all/-9", "grey"),
        ("noise/ma/limb/-9", "keep"),
        ("noise/ma/all/-3", "keep"),
        ("noise/bw/all/-9", "repeat"),
        ("noise/bw/all/-6", "grey"),
        ("electrode_motion/LL/1.0", "repeat"),
        ("electrode_motion/LL/0.5", "grey"),
        ("electrode_motion/RA/2.0", "repeat"),
        ("electrode_dc/LL/4.0", "keep"),
        ("lead_off/V4+V5+V6", "keep"),
        ("coupled/V1+V2/+0", "keep"),
        ("compound/A", "repeat"),
        ("compound/B", "repeat"),
        ("compound/C", "keep"),
        ("compound/D", "keep"),
        ("compound/E", "repeat"),
    ],
)
def test_repeat_label_on_the_corpus(cell, label):
    assert repeat_label(lead_labels(BY_CELL[cell][0]))[0] == label


# --- Label file and freeze ---------------------------------------------------------


def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def test_label_file_covers_every_record_with_12_leads_and_a_repeat_row():
    rows = _rows(labels_csv_text(PLAN))
    assert len(rows) == 13 * len(PLAN)
    grey = [r for r in rows if r["label"] == "grey"]
    assert grey, "grey cells must be written, as not scored"
    assert {r["label"] for r in rows} == {
        "unusable",
        "usable",
        "grey",
        "not_displayed",
        "repeat",
        "keep",
    }


def test_labels_do_not_depend_on_parents(ptbxl_rows):
    clean, natural = select_calib_sources(ptbxl_rows, excluded_patients=set(), seed=1)
    bound = bind_parents(PLAN, clean, natural, seed=2)
    assert labels_csv_text(bound) == labels_csv_text(PLAN)
    assert all(e.spec.source.record_id for e in bound)


def test_definition_is_deterministic():
    assert labels_sha256(calib_plan()) == labels_sha256(PLAN)
    assert [e.spec.steps for e in calib_plan()] == [e.spec.steps for e in PLAN]


def test_frozen_sha_in_the_docs_matches_the_definition():
    doc = (REPO / "docs" / "CALIB_V1.md").read_text()
    match = re.search(r"`labels\.csv` sha256: `([0-9a-f]{64})`", doc)
    assert match, "docs/CALIB_V1.md must record the sha256 of labels.csv"
    assert match.group(1) == labels_sha256(PLAN)


def test_design_tables_in_the_docs_match_the_definition():
    doc = (REPO / "docs" / "CALIB_V1.md").read_text()
    assert design_tables(PLAN) in doc


def test_verify_labels_file_detects_tampering(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text(labels_csv_text(PLAN), newline="")
    assert verify_labels_file(path, PLAN) == labels_sha256(PLAN)
    text = path.read_text().replace("noise/em/all/+0", "noise/em/all/+3", 1)
    path.write_text(text, newline="")
    with pytest.raises(ValueError, match="labels"):
        verify_labels_file(path, PLAN)


def test_generator_definition_and_label_modules_do_not_import_the_tool():
    code = (
        "import sys; import artefaux.calib, artefaux.ptbxl_curator, artefaux.bench_scoring;"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('signalguard', 'noiseguard')];"
        "raise SystemExit(repr(bad) if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for path in (
        REPO / "src/artefaux/calib.py",
        REPO / "src/artefaux/ptbxl_curator.py",
        REPO / "scripts/generate_calib_corpus.py",
        REPO / "scripts/build_curator_table.py",
    ):
        text = path.read_text()
        assert not re.search(r"^\s*(from|import)\s+(signalguard|noiseguard)", text, re.M), path


# --- Parents -----------------------------------------------------------------------


@pytest.fixture
def ptbxl_rows():
    rows = []
    for i in range(1, 1200):
        rows.append(
            {
                "ecg_id": str(i),
                "patient_id": f"{i}.0",
                "age": "60.0",
                "scp_codes": "{'NORM': 100.0, 'SR': 0.0}",
                "filename_hr": f"records500/00000/{i:05d}_hr",
                "baseline_drift": ", V6" if 700 <= i < 750 else "",
                "static_noise": ", I-AVF," if 750 <= i < 800 else "",
                "burst_noise": "alles" if 800 <= i < 850 else "",
                "electrodes_problems": "V4" if 850 <= i < 900 else "",
            }
        )
    rows.append({**rows[0], "ecg_id": "5000", "filename_hr": "records500/05000/05000_hr"})
    rows.append({**rows[1], "ecg_id": "5001", "age": "12.0"})
    return rows


def test_selection_excludes_patients_children_and_repeats(ptbxl_rows):
    excluded = {f"{i}.0" for i in range(1, 11)}
    ptbxl_rows.append({**ptbxl_rows[20], "ecg_id": "6000", "patient_id": "9000.0", "age": "12.0"})
    clean, natural = select_calib_sources(ptbxl_rows, excluded_patients=excluded, seed=9)
    chosen = [*clean, *(r for rows in natural.values() for r in rows)]
    patients = [r["patient_id"] for r in chosen]
    assert len(patients) == len(set(patients))
    assert not set(patients) & excluded
    assert "9000.0" not in patients
    assert {flag: len(rows) for flag, rows in natural.items()} == {
        "burst_noise": 12,
        "electrodes_problems": 8,
        "baseline_drift": 10,
        "static_noise": 10,
    }


def test_too_few_parents_raises_rather_than_shrinking_the_corpus(ptbxl_rows):
    with pytest.raises(ValueError, match="eligible parents"):
        select_calib_sources(ptbxl_rows[:300], excluded_patients=set(), seed=1)


def test_no_patient_crosses_the_split_and_binding_is_deterministic(ptbxl_rows):
    clean, natural = select_calib_sources(ptbxl_rows, excluded_patients=set(), seed=3)
    first = bind_parents(PLAN, clean, natural, seed=4)
    second = bind_parents(PLAN, clean, natural, seed=4)
    assert [e.spec.source.record_id for e in first] == [e.spec.source.record_id for e in second]
    other = bind_parents(PLAN, clean, natural, seed=5)
    assert [e.spec.source.record_id for e in first] != [e.spec.source.record_id for e in other]
    splits: dict[str, set] = {}
    for entry in first:
        splits.setdefault(entry.spec.source.record_id, set()).add(entry.split)
    assert all(len(v) == 1 for v in splits.values())
    assert len(splits) == len(first)
    for entry in first:
        if entry.family == "natural":
            assert entry.stratum.removeprefix("natural_") in entry.spec.source.ptbxl_quality_flags
        else:
            assert entry.spec.source.ptbxl_quality_flags == ()


def test_development_patients_reads_ids_and_checks_the_count(tmp_path):
    set1 = tmp_path / "ptbxl_clean.csv"
    set1.write_text("ecg_id,filename_hr\n1,a\n2,b\n")
    set2 = tmp_path / "source_ids.csv"
    set2.write_text("record_id,patient_id,rhythm_class,scp_codes\nx,30.0,sinus,{}\n")
    rows = [
        {"filename_hr": "a", "patient_id": "10.0"},
        {"filename_hr": "b", "patient_id": "20.0"},
        {"filename_hr": "c", "patient_id": "40.0"},
    ]
    assert development_patients(rows, [set1], set2, expected=3) == {"10.0", "20.0", "30.0"}
    with pytest.raises(ValueError, match="development patients"):
        development_patients(rows, [set1], set2, expected=170)


# --- Signals: synthetic parent and seeded fake noise (no PhysioNet data) -------------


def _fake_loader(calls):
    def load(noise_type: str, channel: int) -> np.ndarray:
        calls.append((noise_type, channel))
        return np.random.default_rng(zip_seed(noise_type, channel)).standard_normal(
            NSTDB_RESAMPLED_LEN
        )

    return load


def zip_seed(noise_type: str, channel: int) -> list[int]:
    return [ord(noise_type[0]), ord(noise_type[1]), channel]


@pytest.fixture(scope="module")
def provider():
    calls: list = []
    prov = segment_provider(_fake_loader(calls))
    prov.calls = calls
    return prov


def _build(cell, provider, rep=0, seed=123):
    entry = BY_CELL[cell][rep]
    parent = synthetic_parent_signal(seed=entry.spec.seed_index)
    assert parent.shape == (12, N_SAMPLES)
    signal, label = build_record(parent, entry.spec, seed, TARGET_FS, noise_provider=provider)
    return entry, parent, signal, label


def test_provider_reads_each_channel_once_and_slices_without_wrapping(provider):
    a = provider(
        {
            "noise_type": "em",
            "noise_source": {"record": "em", "channel": 1, "start_sample": 300000},
        },
        N_SAMPLES,
        None,
    )
    b = provider(
        {
            "noise_type": "em",
            "noise_source": {"record": "em", "channel": 1, "start_sample": 300000},
        },
        N_SAMPLES,
        None,
    )
    assert np.array_equal(a, b)
    assert provider.calls.count(("em", 1)) == 1
    with pytest.raises(ValueError, match="wrap"):
        provider(
            {
                "noise_type": "em",
                "noise_source": {
                    "record": "em",
                    "channel": 1,
                    "start_sample": NSTDB_RESAMPLED_LEN - 10,
                },
            },
            N_SAMPLES,
            None,
        )


@pytest.mark.parametrize(
    "cell",
    [
        "noise/em/all/+0",
        "noise/ma/limb/-6",
        "noise/bw/chest/-9",
        "electrode_motion/LL/1.0",
        "electrode_motion/RA/2.0",
        "electrode_dc/LA/4.0",
        "lead_off/I",
        "coupled/V4+V5/+0",
        "compound/A",
        "compound/D",
        "clean",
    ],
)
def test_built_records_pass_the_generation_checks(cell, provider):
    entry, parent, signal, label = _build(cell, provider)
    result = verify_record(entry, label, signal, parent)
    assert result["mask_ok"] is True


def test_derived_leads_stay_einthoven_consistent_with_independent_limb_noise(provider):
    _, parent, signal, _ = _build("noise/em/limb/-6", provider)

    def residual(x):
        return x[LEAD_INDEX["III"]] - (x[LEAD_INDEX["II"]] - x[LEAD_INDEX["I"]])

    assert np.allclose(residual(signal), residual(parent), atol=1e-9)
    assert np.array_equal(signal[LEAD_INDEX["V1"]], parent[LEAD_INDEX["V1"]])
    noise_i = signal[LEAD_INDEX["I"]] - parent[LEAD_INDEX["I"]]
    noise_ii = signal[LEAD_INDEX["II"]] - parent[LEAD_INDEX["II"]]
    assert abs(np.corrcoef(noise_i, noise_ii)[0, 1]) < 0.2


def test_noise_differs_between_all_eight_displayed_leads(provider):
    _, parent, signal, _ = _build("noise/em/all/-3", provider)
    noise = np.stack([signal[LEAD_INDEX[ld]] - parent[LEAD_INDEX[ld]] for ld in DISPLAYED])
    corr = np.corrcoef(noise)
    assert np.max(np.abs(corr[np.triu_indices(8, 1)])) < 0.2


@pytest.mark.parametrize(
    ("electrode", "lead", "sign"), [("LL", "II", -1), ("LA", "I", -1), ("RA", "I", 1)]
)
def test_electrode_motion_reaches_chest_leads_through_the_wilson_terminal(
    electrode, lead, sign, provider
):
    _, parent, signal, _ = _build(f"electrode_motion/{electrode}/1.0", provider)
    delta = signal - parent
    for chest in CHEST_LEADS:
        assert np.allclose(delta[LEAD_INDEX[chest]], sign * delta[LEAD_INDEX[lead]] / 3, atol=1e-9)
    assert np.std(delta[LEAD_INDEX[lead]]) == pytest.approx(1.0, abs=0.1)


def test_verify_record_refuses_a_change_outside_the_truth_mask(provider):
    entry, parent, signal, label = _build("noise/ma/limb/-3", provider)
    tampered = signal.copy()
    tampered[LEAD_INDEX["V4"], 100] += 0.5
    with pytest.raises(ValueError, match="outside"):
        verify_record(entry, label, tampered, parent)


def test_verify_record_refuses_the_wrong_snr(provider):
    entry, parent, signal, label = _build("noise/ma/limb/-3", provider)
    tampered = signal.copy()
    tampered[LEAD_INDEX["I"]] = parent[LEAD_INDEX["I"]] + 3 * (signal - parent)[LEAD_INDEX["I"]]
    with pytest.raises(ValueError, match="SNR"):
        verify_record(entry, label, tampered, parent)


# --- Integrity check of a generated corpus ------------------------------------------


def _load_generator():
    path = REPO / "scripts" / "generate_calib_corpus.py"
    spec = importlib.util.spec_from_file_location("generate_calib_corpus_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(out: Path, rows: list[dict]) -> None:
    with (out / "checksums.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["file", "sha256"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def small_corpus(tmp_path, monkeypatch):
    """A three-record corpus and a generator whose plan and frozen digest match it."""
    gen = _load_generator()
    out, ptbxl = tmp_path / "corpus", tmp_path / "ptbxl"
    (out / "records").mkdir(parents=True)
    ptbxl.mkdir()
    (ptbxl / "ptbxl_database.csv").write_text("ecg_id,patient_id\n")
    plan = [
        SimpleNamespace(
            spec=SimpleNamespace(record_id=rid, source=SimpleNamespace(record_id=f"src/{rid}")),
            split="calib",
        )
        for rid in ("a", "b", "c")
    ]
    with (out / "records.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["record_id", "source_record_id", "split", "patient_id"]
        )
        writer.writeheader()
        for i, entry in enumerate(plan):
            rid = entry.spec.record_id
            writer.writerow(
                {
                    "record_id": rid,
                    "source_record_id": f"src/{rid}",
                    "split": "calib",
                    "patient_id": str(i),
                }
            )
    rows = []
    for entry in plan:
        for suffix in (".hea", ".dat"):
            name = f"records/{entry.spec.record_id}{suffix}"
            (out / name).write_text(name)
            rows.append({"file": name, "sha256": _sha(out / name)})
    _write_manifest(out, rows)
    monkeypatch.setattr(gen, "_bound_plan", lambda args, metadata: (plan, set()))
    monkeypatch.setattr(gen, "verify_labels_file", lambda path, p: "labels-sha")
    monkeypatch.setattr(gen, "FROZEN_CHECKSUMS_SHA256", _sha(out / "checksums.csv"), raising=False)
    args = SimpleNamespace(out=out, ptbxl_dir=ptbxl, set2_sources=None)
    return gen, args, out, rows, monkeypatch


def test_verify_accepts_an_intact_corpus(small_corpus):
    gen, args, *_ = small_corpus
    gen.verify(args)


def test_verify_refuses_a_duplicate_row_hiding_an_altered_record(small_corpus):
    # The row count still matches: only the exact file list exposes the omission. The digest is
    # re-pinned to the forged manifest so this exercises the coverage check alone.
    gen, args, out, rows, monkeypatch = small_corpus
    (out / rows[-1]["file"]).write_text("altered")
    _write_manifest(out, [*rows[:-1], rows[0]])
    monkeypatch.setattr(gen, "FROZEN_CHECKSUMS_SHA256", _sha(out / "checksums.csv"), raising=False)
    with pytest.raises(SystemExit, match="does not list exactly"):
        gen.verify(args)


def test_verify_refuses_a_manifest_rewritten_to_match_an_altered_record(small_corpus):
    gen, args, out, rows, _ = small_corpus
    (out / rows[0]["file"]).write_text("altered")
    _write_manifest(out, [{**rows[0], "sha256": _sha(out / rows[0]["file"])}, *rows[1:]])
    with pytest.raises(SystemExit, match="frozen digest"):
        gen.verify(args)


def test_verify_refuses_a_record_file_the_manifest_does_not_list(small_corpus):
    gen, args, out, *_ = small_corpus
    (out / "records" / "stray.dat").write_text("stray")
    with pytest.raises(SystemExit, match="stray"):
        gen.verify(args)


def test_frozen_manifest_digest_in_the_generator_matches_the_docs():
    assert _load_generator().FROZEN_CHECKSUMS_SHA256 in CALIB_DOC.read_text(encoding="utf-8")


def test_the_public_design_document_carries_no_per_record_reader_detail():
    # This repository is public; set-1 codes joined to recipes and answers stay in the atlas.
    assert not re.search(r"REV-\d", CALIB_DOC.read_text(encoding="utf-8"))
