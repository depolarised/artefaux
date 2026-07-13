# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Deterministic seeding and provenance serialization."""

from __future__ import annotations

import json

import numpy as np

from torsade.provenance import (
    Provenance,
    record_rng,
    seed_for_record,
    sha256_file,
)


def test_record_rng_is_deterministic_and_independent():
    a = record_rng(42, 0).standard_normal(5)
    a_again = record_rng(42, 0).standard_normal(5)
    b = record_rng(42, 1).standard_normal(5)
    assert np.array_equal(a, a_again)
    assert not np.array_equal(a, b)


def test_seed_for_record_is_stable():
    assert seed_for_record(42, 3) == seed_for_record(42, 3)
    assert seed_for_record(42, 3) != seed_for_record(42, 4)


def test_provenance_roundtrips(tmp_path):
    src = tmp_path / "rec.dat"
    src.write_bytes(b"synthetic source bytes")
    prov = Provenance(master_seed=42)
    prov.record_source_hash("ptbxl_00001", src)
    out = tmp_path / "provenance.json"
    prov.write(out)
    loaded = json.loads(out.read_text())
    assert loaded["master_seed"] == 42
    assert loaded["source_file_hashes"]["ptbxl_00001"] == sha256_file(src)
    assert any(s["dataset"] == "nstdb" for s in loaded["sources"])
