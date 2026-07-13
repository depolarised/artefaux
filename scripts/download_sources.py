#!/usr/bin/env python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Download the small open PhysioNet noise sources (NSTDB, CinC Challenge 2011).

PTB-XL (500 Hz) and PTB-XL+ are large and are fetched separately — see
docs/GENERATION.md. Thin wrapper around ``torsade.cli:download_main``.
"""

from __future__ import annotations

import sys

from torsade.cli import download_main

if __name__ == "__main__":
    raise SystemExit(download_main(sys.argv[1:]))
