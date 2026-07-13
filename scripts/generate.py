#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Generate the Torsade corpus. Thin wrapper around ``torsade.cli:generate_main``.

Examples
--------
    python scripts/generate.py --synthetic --out out/smoke
    python scripts/generate.py --sources data/sources --out out/torsade-v1
"""

from __future__ import annotations

import sys

from torsade.cli import generate_main

if __name__ == "__main__":
    raise SystemExit(generate_main(sys.argv[1:]))
