# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Binding resolved PTB-XL ids into the corpus specs (the select -> generate seam)."""

from __future__ import annotations

import csv

import pytest

from artefaux.build import resolve_source_ids
from artefaux.corpus import build_corpus_specs


def _write_ids(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _make_source_ids(tmp_path, n_clean, n_noisy):
    d = tmp_path / "source_ids"
    d.mkdir()
    _write_ids(
        d / "ptbxl_clean.csv",
        ["ecg_id", "filename_hr"],
        [[i, f"records500/00000/{i:05d}_hr"] for i in range(n_clean)],
    )
    _write_ids(
        d / "ptbxl_noisy.csv",
        ["ecg_id", "filename_hr", "quality_flags"],
        [[1000 + i, f"records500/10000/{1000 + i:05d}_hr", "static_noise"] for i in range(n_noisy)],
    )
    return d


def test_resolve_binds_every_spec_in_group_order(tmp_path):
    d = _make_source_ids(tmp_path, n_clean=70, n_noisy=15)
    specs = resolve_source_ids(build_corpus_specs(), d)

    assert all(s.source.record_id is not None for s in specs)

    # naturally-poor <- noisy pool (in order), and the real flags come along.
    poor = [s for s in specs if s.group == "naturally_poor"]
    assert poor[0].source.record_id == "records500/10000/01000_hr"
    assert poor[0].source.ptbxl_quality_flags == ("static_noise",)

    # real-noise + engineering <- clean pool, contiguous and in order.
    clean_consumers = [s for s in specs if s.group != "naturally_poor"]
    assert clean_consumers[0].source.record_id == "records500/00000/00000_hr"
    assert clean_consumers[-1].source.record_id == "records500/00000/00069_hr"
    assert len({s.source.record_id for s in clean_consumers}) == len(clean_consumers)


def test_resolve_is_pure_leaves_input_specs_untouched(tmp_path):
    d = _make_source_ids(tmp_path, n_clean=70, n_noisy=15)
    original = build_corpus_specs()
    resolve_source_ids(original, d)
    assert all(s.source.record_id is None for s in original)  # frozen: no mutation


def test_resolve_raises_when_selection_too_small(tmp_path):
    d = _make_source_ids(tmp_path, n_clean=10, n_noisy=15)
    with pytest.raises(ValueError, match="clean PTB-XL ids"):
        resolve_source_ids(build_corpus_specs(), d)


def test_resolve_raises_when_ids_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="make select"):
        resolve_source_ids(build_corpus_specs(), tmp_path / "does_not_exist")
