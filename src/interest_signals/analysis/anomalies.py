"""Spike dependency (D31) and volatility (D32)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from interest_signals import config
from interest_signals.analysis.trends import LogFit, log_offset


def mad(values: np.ndarray) -> float:
    return float(np.median(np.abs(values - np.median(values))))


def spike_positions(ys: list[float]) -> list[int]:
    """Indices (into ys) of months whose log value sits far above the local rolling median.

    A spike needs both: robust z = 0.6745 * (residual - median residual) / MAD > SPIKE_Z, and a
    value at least 50% above the local median (log residual > SPIKE_MIN_LOG_RESIDUAL). The second
    condition keeps ordinary noise in very smooth series from counting as event-driven spikes."""
    if len(ys) < config.SPIKE_ROLLING_WINDOW:
        return []
    logs = np.log(np.asarray(ys, dtype=float) + log_offset(ys))
    local = (
        pd.Series(logs)
        .rolling(config.SPIKE_ROLLING_WINDOW, center=True, min_periods=3)
        .median()
        .to_numpy()
    )
    residual = logs - local
    spread = mad(residual)
    big = residual > config.SPIKE_MIN_LOG_RESIDUAL
    if spread == 0:
        return [i for i in range(len(ys)) if big[i]]
    z = 0.6745 * (residual - np.median(residual)) / spread
    return [i for i in range(len(ys)) if big[i] and z[i] > config.SPIKE_Z]


def spike_ratio(ys: list[float]) -> float | None:
    median = float(np.median(ys)) if ys else 0.0
    return float(max(ys)) / median if median > 0 else None


def top_2_share(ys: list[float]) -> float | None:
    total = float(sum(ys))
    if total <= 0 or len(ys) < 3:
        return None
    return float(sum(sorted(ys, reverse=True)[:2])) / total


def volatility(xs: list[int], ys: list[float], fit: LogFit | None) -> float | None:
    """1.4826 * MAD of log residuals around the Theil-Sen line (robust sigma of log changes)."""
    if fit is None or len(ys) < 3:
        return None
    logs = np.log(np.asarray(ys, dtype=float) + fit.offset)
    line = fit.intercept + fit.stat.slope_log * np.asarray(xs, dtype=float)
    return 1.4826 * mad(logs - line)
