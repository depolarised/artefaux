# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""GRIASCII header lines for Uni-G (local tooling: needs the ecg-suite ``ecg_io`` package)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ecg_io")

from artefaux.benchmark import UNIG_HEADER_LINES  # noqa: E402

CONVERTER = Path(__file__).resolve().parents[1] / "scripts/griasc_claude/convert_to_griasc.py"


def _converter():
    spec = importlib.util.spec_from_file_location("griasc_converter_under_test", CONVERTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_header_is_unchanged_and_overrides_land_on_spec_lines(ecg12):
    conv = _converter()
    plain = conv.signal_to_griasc_v15(ecg12, sample_rate_hz=500, record_id="T1-001").split("\n")
    assert plain[6] == "0" and plain[9] == ""  # earlier exports: age 0, positioning blank
    text = conv.signal_to_griasc_v15(
        ecg12, sample_rate_hz=500, record_id="T1-001", header_lines=UNIG_HEADER_LINES
    ).split("\n")
    for line, value in UNIG_HEADER_LINES.items():
        assert text[line - 1] == value, line
    assert text[9] == "Adult" and text[1] == "T1-001"
    assert text[23:] == plain[23:]  # samples untouched
    assert int(text[23]) == int(np.round(ecg12[0, 0] * 1000))


@pytest.mark.parametrize("line", [1, 2, 18, 23, 0])
def test_reserved_header_lines_cannot_be_overridden(ecg12, line):
    conv = _converter()
    with pytest.raises(conv.ConversionError, match="not overridable"):
        conv.signal_to_griasc_v15(
            ecg12, sample_rate_hz=500, record_id="T1-001", header_lines={line: "x"}
        )
