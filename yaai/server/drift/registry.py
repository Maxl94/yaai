"""Drift metric registry and lookup."""

from __future__ import annotations

from yaai.server.drift.base import DriftMetric
from yaai.server.drift.chi_squared import ChiSquared
from yaai.server.drift.js_divergence import JSDivergence
from yaai.server.drift.ks_test import KSTest
from yaai.server.drift.psi import PSI

# Metric name → class
METRIC_REGISTRY: dict[str, type[DriftMetric]] = {
    "psi": PSI,
    "ks_test": KSTest,
    "chi_squared": ChiSquared,
    "js_divergence": JSDivergence,
}

# Default metric per data type
DEFAULT_METRICS: dict[str, str] = {
    "numerical": "psi",
    "categorical": "chi_squared",
}


def get_metric(metric_name: str | None, data_type: str) -> DriftMetric:
    """Get a drift metric instance by name, falling back to the default for the data type."""
    name = metric_name or DEFAULT_METRICS.get(data_type)
    if name is None:
        msg = f"No default metric for data type: {data_type}"
        raise ValueError(msg)
    cls = METRIC_REGISTRY.get(name)
    if cls is None:
        msg = f"Unknown metric: {name}"
        raise ValueError(msg)
    return cls()
