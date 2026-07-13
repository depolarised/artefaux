#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Download NSTDB — the only noise source not in a local PhysioNet mirror.

PTB-XL (500 Hz), PTB-XL+, and MACECGDB are read from the local mirror under
``/data/physionet`` (see docs/GENERATION.md), so this fetches only NSTDB.
Thin wrapper around ``torsade.cli:download_main``.
"""

from __future__ import annotations

import sys

from torsade.cli import download_main

if __name__ == "__main__":
    raise SystemExit(download_main(sys.argv[1:]))
