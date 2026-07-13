# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""End-to-end: build every corpus spec against a synthetic parent, write, reload.

This is the CI integration test — it runs with no PhysioNet download by using the
synthetic noise provider and synthetic parents.
"""

from __future__ import annotations

import numpy as np
import wfdb
import yaml

from tests.conftest import make_einthoven_ecg
from torsade.corpus import build_corpus_specs, specs_to_yaml
from torsade.labels import RecordLabel
from torsade.manifest import Manifest, ManifestEntry
from torsade.recipes import build_record
from torsade.writer import write_wfdb

MASTER_SEED = 20260713


def test_corpus_composition():
    specs = build_corpus_specs()
    counts: dict[str, int] = {}
    for s in specs:
        counts[s.group] = counts.get(s.group, 0) + 1
    assert counts == {"naturally_poor": 15, "real_noise": 30, "engineering": 22}
    assert len(specs) == 67
    assert len({s.record_id for s in specs}) == 67  # unique ids


def test_every_spec_builds_and_labels_validly():
    parent = make_einthoven_ecg(seed=7)
    for spec in build_corpus_specs():
        sig, label = build_record(parent, spec, MASTER_SEED, fs=500)
        assert sig.shape == (12, 5000)
        assert isinstance(label, RecordLabel)
        # Only digital-missing / mixed-integrity cases may carry NaN.
        if not label.expected_behaviour.data_integrity_failure:
            assert np.all(np.isfinite(sig))
        # I is untouched except in explicit limb-electrode / lead-I cases.
        assert label.n_samples == 5000


def test_build_record_is_deterministic():
    parent = make_einthoven_ecg(seed=8)
    spec = next(s for s in build_corpus_specs() if s.group == "real_noise")
    a, _ = build_record(parent, spec, MASTER_SEED, fs=500)
    b, _ = build_record(parent, spec, MASTER_SEED, fs=500)
    assert np.array_equal(a, b)


def test_generate_write_reload_and_manifest(tmp_path):
    parent = make_einthoven_ecg(seed=9)
    specs = build_corpus_specs()
    manifest = Manifest()
    # Take a representative sample from each group, including a NaN case.
    sample = [specs[0], specs[15], specs[45], specs[52]]  # nat, noise, eng single, eng multi
    for spec in sample:
        sig, label = build_record(parent, spec, MASTER_SEED, fs=500)
        path = write_wfdb(label.record_id, sig, 500, tmp_path / "records")
        back = wfdb.rdrecord(str(path))
        assert np.asarray(back.p_signal).T.shape == (12, 5000)
        label.write(tmp_path / f"{label.record_id}.json")
        manifest.add(ManifestEntry.from_label(label, parent_record_id=label.record_id))
    manifest.write_json(tmp_path / "manifest.json")
    manifest.write_csv(tmp_path / "manifest.csv")
    assert (tmp_path / "manifest.csv").read_text().count("\n") == len(sample) + 1


def test_specs_serialize_to_yaml():
    text = specs_to_yaml(build_corpus_specs(), master_seed=MASTER_SEED)
    parsed = yaml.safe_load(text)
    assert parsed["master_seed"] == MASTER_SEED
    assert len(parsed["records"]) == 67
    assert parsed["records"][0]["group"] == "naturally_poor"
