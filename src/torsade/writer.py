# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Write canonical signals to WFDB.

``ecg-io`` is readers-only, so Torsade emits WFDB directly via ``wfdb.wrsamp``.
We pass an explicit ADC gain and baseline rather than letting wfdb infer them from
the data, so that a fully-NaN "digital-missing" lead still writes cleanly (gain
inference fails on an all-NaN channel). NaN samples are stored as the WFDB invalid
marker and read back as NaN.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .constants import CANONICAL_LEAD_ORDER, N_LEADS, UNIT

#: Digital units per mV. 1000 gives a ±32.767 mV range in 16-bit — comfortably
#: beyond any rail Torsade uses — at 1 µV resolution.
ADC_GAIN_PER_MV: float = 1000.0


def write_wfdb(
    record_id: str,
    signal: np.ndarray,
    fs: int,
    out_dir: str | Path,
    *,
    lead_names: tuple[str, ...] = CANONICAL_LEAD_ORDER,
    comments: list[str] | None = None,
    fmt: str = "16",
) -> Path:
    """Write a ``(12, T)`` mV array as ``<record_id>.hea`` / ``.dat``.

    Returns the extensionless record path.
    """
    import wfdb

    signal = np.asarray(signal, dtype=np.float64)
    if signal.shape[0] != N_LEADS:
        raise ValueError(f"expected ({N_LEADS}, T), got {signal.shape}")
    if len(lead_names) != N_LEADS:
        raise ValueError(f"expected {N_LEADS} lead names, got {len(lead_names)}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wfdb.wrsamp(
        record_name=record_id,
        fs=int(fs),
        units=[UNIT] * N_LEADS,
        sig_name=list(lead_names),
        p_signal=signal.T,
        fmt=[fmt] * N_LEADS,
        adc_gain=[ADC_GAIN_PER_MV] * N_LEADS,
        baseline=[0] * N_LEADS,
        write_dir=str(out_dir),
        comments=comments or [],
    )
    return out_dir / record_id
