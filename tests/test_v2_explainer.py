# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The v2 explainer must describe every group and never disagree with the manifest."""

from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GEN_PATH = REPO / "scripts" / "reports" / "generate_v2_explainer.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("artefaux_v2_explainer", GEN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explainer_has_group_sections_and_criteria():
    text = _load_generator().build_explainer()
    assert "Artefaux v2" in text
    for title in ("Naturally poor", "Real-noise", "Engineering extremes"):
        assert title in text
    assert "How labels are assigned" in text
    # groups made visually distinct via the colour-coded figures
    assert "corpus_composition.png" in text
    assert "group_severity.png" in text
    # label-criteria specifics
    assert "data_integrity_failure" in text
    assert "strip8" in text


def test_explainer_snr_band_table_matches_definition():
    from artefaux.constants import SNR_LADDER_DB

    text = _load_generator().build_explainer()
    for snr in SNR_LADDER_DB:
        assert f"| {snr:+d} |" in text  # every ladder level is in the SNR→label table


def test_explainer_tallies_agree_with_manifest():
    """Data-honesty: the explainer's per-group counts must match manifest.json."""
    gen = _load_generator()
    tallies = gen._tallies()

    manifest = json.loads((REPO / "manifest.json").read_text())
    expected = defaultdict(lambda: {"n": 0, "discard": 0, "integrity": 0})
    for r in manifest["records"]:
        e = expected[r["group"]]
        e["n"] += 1
        e["discard"] += int(r["expected_noiseguard_discard"])
        e["integrity"] += int(r["data_integrity_failure"])

    for group, exp in expected.items():
        assert tallies[group]["n"] == exp["n"], group
        assert tallies[group]["discard"] == exp["discard"], group
        assert tallies[group]["integrity"] == exp["integrity"], group
