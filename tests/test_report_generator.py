# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""The corpus report must enumerate every record and never disagree with its sources."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GEN_PATH = REPO / "scripts" / "reports" / "generate_corpus_report.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("artefaux_report_generator", GEN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The generator resolves concrete PTB-XL ids from recipes/source_ids/. Those are
# committed, so the report is regenerable in CI without any PhysioNet data.
_HAVE_IDS = (REPO / "recipes" / "source_ids" / "ptbxl_clean.csv").exists()
gen_only = pytest.mark.skipif(
    not _HAVE_IDS, reason="recipes/source_ids not resolved (run `make select`)"
)


@gen_only
def test_report_enumerates_all_records():
    gen = _load_generator()
    text = gen.build_report()
    from artefaux.corpus import build_corpus_specs

    specs = build_corpus_specs()
    assert len(specs) == 85
    for spec in specs:
        # ids are wrapped with zero-width spaces for line-breaking; strip them before matching.
        assert spec.record_id in text.replace("​", ""), f"{spec.record_id} missing from report"


@gen_only
def test_report_has_no_stale_challenge_references():
    gen = _load_generator()
    assert "challenge2011" not in gen.build_report().lower()


@gen_only
def test_report_bad_leads_agree_with_manifest():
    """Data-honesty invariant: the report's bad-leads formula must match manifest.json."""
    gen = _load_generator()
    manifest = json.loads((REPO / "manifest.json").read_text())
    n_bad = {r["record_id"]: r["n_bad_leads"] for r in manifest["records"]}
    for spec, label in gen._rows():
        assert gen._n_bad_leads(label) == n_bad[spec.record_id], spec.record_id


@gen_only
def test_report_composition_counts():
    gen = _load_generator()
    text = gen.build_report()
    # Roster section headers and the total must be present and correct.
    assert "## 5. Full record roster" in text
    for header in ("Naturally poor (15)", "Real-noise SNR-ladder pairs (30)"):
        assert header in text
    assert "**85**" in text
