# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ioannis Valasakis <tungolcild@gmail.com>
"""Agreement and diagnostic-accuracy statistics for review synthesis and benchmark scoring.

Pure functions over plain sequences: no tool imports, no I/O. The same code scores a
program against the expert reference and one reader against another, so the two are
directly comparable.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from math import sqrt

import numpy as np
from scipy import optimize, stats

_Z95 = 1.959963984540054


def wilson_ci(successes: int, n: int, z: float = _Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion; ``(nan, nan)`` when ``n == 0``."""
    if n == 0:
        return float("nan"), float("nan")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True)
class BinaryCounts:
    tp: int
    fp: int
    fn: int
    tn: int

    @classmethod
    def from_pairs(cls, predicted: Sequence[bool], reference: Sequence[bool]) -> BinaryCounts:
        if len(predicted) != len(reference):
            raise ValueError("predicted and reference must have the same length")
        p = np.asarray(predicted, dtype=bool)
        r = np.asarray(reference, dtype=bool)
        return cls(
            tp=int(np.sum(p & r)),
            fp=int(np.sum(p & ~r)),
            fn=int(np.sum(~p & r)),
            tn=int(np.sum(~p & ~r)),
        )

    def _ratio(self, num: int, den: int) -> dict:
        lo, hi = wilson_ci(num, den)
        return {"value": num / den if den else float("nan"), "lo": lo, "hi": hi, "n": den}

    def metrics(self) -> dict[str, dict]:
        """Sensitivity, specificity, PPV and NPV with Wilson 95% CIs, plus F1."""
        f1_den = 2 * self.tp + self.fp + self.fn
        return {
            "sensitivity": self._ratio(self.tp, self.tp + self.fn),
            "specificity": self._ratio(self.tn, self.tn + self.fp),
            "ppv": self._ratio(self.tp, self.tp + self.fp),
            "npv": self._ratio(self.tn, self.tn + self.fn),
            "f1": {"value": 2 * self.tp / f1_den if f1_den else float("nan"), "n": f1_den},
        }


def _confusion(a: Sequence[Hashable], b: Sequence[Hashable], categories: Sequence[Hashable]):
    if len(a) != len(b):
        raise ValueError("ratings must have the same length")
    index = {c: i for i, c in enumerate(categories)}
    unknown = ({*a} | {*b}) - set(index)
    if unknown:
        raise ValueError(f"ratings outside the category list: {sorted(map(str, unknown))}")
    table = np.zeros((len(categories), len(categories)))
    for x, y in zip(a, b, strict=True):
        table[index[x], index[y]] += 1
    return table


def cohen_kappa(
    a: Sequence[Hashable],
    b: Sequence[Hashable],
    categories: Sequence[Hashable],
    *,
    weights: str | None = None,
) -> float:
    """Cohen's kappa; ``weights="linear"`` gives the ordinal weighted kappa.

    ``categories`` fixes the order (and therefore the ordinal distances) explicitly.
    Returns ``nan`` when chance agreement is total (a single category used by both).
    """
    table = _confusion(a, b, categories)
    n = table.sum()
    if n == 0:
        return float("nan")
    k = len(categories)
    i, j = np.indices((k, k))
    if weights is None:
        disagreement = (i != j).astype(float)
    elif weights == "linear":
        disagreement = np.abs(i - j) / max(k - 1, 1)
    else:
        raise ValueError("weights must be None or 'linear'")
    observed = (disagreement * table).sum() / n
    expected = (disagreement * np.outer(table.sum(1), table.sum(0))).sum() / (n * n)
    if expected == 0:
        return float("nan")
    return float(1 - observed / expected)


def percent_agreement(a: Sequence[Hashable], b: Sequence[Hashable]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("ratings must be non-empty and the same length")
    return float(np.mean([x == y for x, y in zip(a, b, strict=True)]))


def pabak(a: Sequence[Hashable], b: Sequence[Hashable], n_categories: int) -> float:
    """Prevalence- and bias-adjusted kappa: ``(k·p_o − 1)/(k − 1)``."""
    return float((n_categories * percent_agreement(a, b) - 1) / (n_categories - 1))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the two discordant-pair counts."""
    if b + c == 0:
        return 1.0
    return float(min(1.0, 2 * stats.binom.cdf(min(b, c), b + c, 0.5)))


def paired_difference_ci(
    first: Sequence[bool], second: Sequence[bool], z: float = _Z95
) -> tuple[float, float, float]:
    """Newcombe (1998, method 10) CI for ``P(first) − P(second)`` on paired binary data.

    Returns ``(difference, lo, hi)``.
    """
    x = np.asarray(first, dtype=bool)
    y = np.asarray(second, dtype=bool)
    if x.shape != y.shape or x.size == 0:
        raise ValueError("paired samples must be non-empty and the same length")
    n = x.size
    a, b = int(np.sum(x & y)), int(np.sum(x & ~y))
    c, d = int(np.sum(~x & y)), int(np.sum(~x & ~y))
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson_ci(a + b, n, z)
    l2, u2 = wilson_ci(a + c, n, z)
    den = (a + b) * (c + d) * (a + c) * (b + d)
    # Newcombe's method 10 corrects the phi estimate for continuity when ad > bc.
    cross = a * d - b * c
    if cross > 0:
        cross = max(cross - n / 2, 0.0)
    phi = cross / sqrt(den) if den else 0.0
    delta = p1 - p2
    lo = delta - sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    hi = delta + sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return float(delta), float(max(-1.0, lo)), float(min(1.0, hi))


def cluster_bootstrap_ci(
    statistic: Callable[[np.ndarray], float],
    clusters: Sequence[Hashable],
    *,
    n_resamples: int = 2000,
    seed: int,
    level: float = 0.95,
) -> tuple[float, float]:
    """Percentile CI of ``statistic(unit_indices)`` resampling whole clusters (records).

    ``statistic`` receives the integer indices of the resampled units (with repeats) and
    returns a scalar; resamples where it is undefined (``nan``) are dropped.
    """
    labels = np.asarray(clusters)
    ids = list(dict.fromkeys(labels.tolist()))
    members = [np.flatnonzero(labels == cid) for cid in ids]
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(n_resamples):
        draw = rng.integers(0, len(ids), len(ids))
        value = statistic(np.concatenate([members[k] for k in draw]))
        if np.isfinite(value):
            values.append(value)
    if not values:
        return float("nan"), float("nan")
    tail = (1 - level) / 2 * 100
    lo, hi = np.percentile(values, [tail, 100 - tail])
    return float(lo), float(hi)


def jaccard(a: set, b: set) -> float:
    """Jaccard index of two lead sets; two empty sets agree perfectly (1.0)."""
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _interval_bounds(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Observed levels bracketing the 50% crossing of a monotone decreasing outcome.

    ``lo`` is the highest SNR at which every unit is unusable and ``hi`` the lowest at
    which every unit is usable; the crossing lies between them. ``nan`` marks an open side.
    """
    levels = np.unique(x)
    all_unusable = [v for v in levels if y[x == v].all()]
    all_usable = [v for v in levels if not y[x == v].any()]
    lo = float(max(all_unusable)) if all_unusable else float("nan")
    hi = float(min(all_usable)) if all_usable else float("nan")
    return lo, hi


def fit_snr50(snr_db: Sequence[float], unusable: Sequence[bool]) -> dict:
    """Logistic fit of ``P(unusable)`` on SNR; returns intercept, slope and ``snr50``.

    ``snr50`` is the SNR at which half the units are judged unusable. It is reported only
    when the maximum-likelihood fit converged and the slope is negative (dose–response).
    The interval for it is left to a cluster bootstrap in the caller, so ``snr50_lo`` and
    ``snr50_hi`` are ``nan`` on this path.

    Under (quasi-)complete separation the maximum-likelihood estimate does not exist, so
    no point estimate is given. A separated outcome that falls with SNR (unusable at low
    SNR, usable at high SNR; ties at one level allowed) sets ``separated`` and returns
    interval-censored bounds ``snr50_lo``/``snr50_hi`` from the observed levels, with
    ``nan`` on an open side. A separated outcome that rises with SNR has no dose–response
    and every ``snr50`` field is ``nan``. ``converged`` is True only for a fitted MLE.

    A constant outcome or constant SNR is not fitted: every estimate is ``nan`` and
    ``separated`` is False.
    """
    x = np.asarray(snr_db, dtype=float)
    y = np.asarray(unusable, dtype=bool)
    result = {
        "intercept": float("nan"),
        "slope": float("nan"),
        "snr50": float("nan"),
        "snr50_lo": float("nan"),
        "snr50_hi": float("nan"),
        "separated": False,
        "converged": False,
        "n": x.size,
    }
    if x.size < 3 or y.all() or not y.any() or x.min() == x.max():
        return result
    if x[y].max() <= x[~y].min():
        lo, hi = _interval_bounds(x, y)
        result.update(separated=True, snr50_lo=lo, snr50_hi=hi)
        return result
    if x[y].min() >= x[~y].max():
        result["separated"] = True
        return result

    target = y.astype(float)

    def neg_log_lik(theta: np.ndarray) -> float:
        eta = theta[0] + theta[1] * x
        return float(np.sum(np.logaddexp(0.0, eta) - target * eta))

    fit = optimize.minimize(neg_log_lik, x0=np.zeros(2), method="BFGS")
    result["converged"] = bool(fit.success)
    if not fit.success:
        return result
    intercept, slope = (float(v) for v in fit.x)
    result.update(intercept=intercept, slope=slope)
    if slope < 0:
        result["snr50"] = -intercept / slope
    return result
