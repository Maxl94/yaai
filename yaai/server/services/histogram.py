"""Robust histogram binning shared by dashboard and comparison services.

Bins are equal-width.  Where a tail extends far beyond the [p1, p99] core of the
data (more than ``TAIL_FACTOR`` times the core width), the bins stop at the percentile
and the values beyond it are collected in an underflow / overflow bucket, so a few
outliers cannot squash the bulk of the distribution into a single bar.  Otherwise the
bins extend to the data min / max.
All regular bins are always returned (including empty ones) so that the
frontend can render a true linear x-axis.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from yaai.server.schemas.dashboard import HistogramBucket

DEFAULT_NUM_BINS = 20
LOWER_PERCENTILE = 1.0
UPPER_PERCENTILE = 99.0
TAIL_FACTOR = 0.5
_SIGNIFICANT_DIGITS = 6


def round_edge(value: float) -> float:
    """Round an edge to a fixed number of significant digits (safe for tiny and huge ranges)."""
    return float(f"{value:.{_SIGNIFICANT_DIGITS}g}")


@dataclass(frozen=True)
class BinSpec:
    """Bin layout: ``num_bins`` equal-width bins in ``[lower, upper]`` plus optional tail buckets.

    Attributes:
        lower: Lower edge of the first regular bin.
        upper: Upper edge of the last regular bin.
        num_bins: Number of regular bins (1 when ``lower == upper``).
        data_min: Smallest observed value.
        data_max: Largest observed value.
    """

    lower: float
    upper: float
    num_bins: int
    data_min: float
    data_max: float

    @classmethod
    def create(cls, lower: float, upper: float, num_bins: int, data_min: float, data_max: float) -> BinSpec:
        """Create a spec, collapsing to a single bin for a degenerate (zero-width) range."""
        return cls(lower, upper, 1 if lower == upper else num_bins, data_min, data_max)

    @property
    def has_underflow(self) -> bool:
        """True if values below ``lower`` exist."""
        return self.data_min < self.lower

    @property
    def has_overflow(self) -> bool:
        """True if values above ``upper`` exist."""
        return self.data_max > self.upper

    @property
    def edges(self) -> np.ndarray:
        """Edges of the regular bins (``num_bins + 1`` values)."""
        return np.linspace(self.lower, self.upper, self.num_bins + 1)


def compute_bin_edges(
    values: np.ndarray,
    num_bins: int = DEFAULT_NUM_BINS,
    lower_pct: float = LOWER_PERCENTILE,
    upper_pct: float = UPPER_PERCENTILE,
) -> BinSpec | None:
    """Compute a robust bin layout from the p1-p99 range of ``values``.

    Each side is clipped to its percentile only if the tail beyond it is longer than
    ``TAIL_FACTOR`` times the p1-p99 width; otherwise the bins extend to the data min / max.
    Without a p1-p99 width (percentiles coincide) the min-max range is used. A single
    bin is used if all values are identical.

    Args:
        values: Numeric values; NaN and infinite values are ignored.
        num_bins: Number of regular bins.
        lower_pct: Lower percentile (0-100) bounding the regular bins.
        upper_pct: Upper percentile (0-100) bounding the regular bins.

    Returns:
        The bin layout, or None if there are no finite values.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None

    data_min, data_max = float(arr.min()), float(arr.max())
    p_low, p_high = (float(p) for p in np.percentile(arr, [lower_pct, upper_pct]))
    lower, upper = data_min, data_max
    core = p_high - p_low
    if core > 0:
        if p_low - data_min > TAIL_FACTOR * core:
            lower = p_low
        if data_max - p_high > TAIL_FACTOR * core:
            upper = p_high
    return BinSpec.create(lower, upper, num_bins, data_min, data_max)


def count_values(values: np.ndarray, spec: BinSpec) -> tuple[int, list[int], int]:
    """Count values into underflow, regular bins and overflow.

    The upper edge of the last regular bin is inclusive, so ``v == upper`` is not an overflow.

    Returns:
        Tuple ``(underflow_count, bin_counts, overflow_count)``.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    underflow = int((arr < spec.lower).sum())
    overflow = int((arr > spec.upper).sum())
    inside = arr[(arr >= spec.lower) & (arr <= spec.upper)]
    counts = np.histogram(inside, bins=spec.edges)[0]
    return underflow, [int(c) for c in counts], overflow


def buckets_from_counts(spec: BinSpec, underflow: int, bin_counts: list[int], overflow: int) -> list[HistogramBucket]:
    """Assemble histogram buckets: optional underflow, all regular bins, optional overflow."""
    edges = spec.edges
    buckets: list[HistogramBucket] = []
    if spec.has_underflow:
        buckets.append(
            HistogramBucket(
                range_start=round_edge(spec.data_min),
                range_end=round_edge(spec.lower),
                count=underflow,
                is_underflow=True,
            )
        )
    buckets.extend(
        HistogramBucket(range_start=round_edge(float(edges[i])), range_end=round_edge(float(edges[i + 1])), count=c)
        for i, c in enumerate(bin_counts)
    )
    if spec.has_overflow:
        buckets.append(
            HistogramBucket(
                range_start=round_edge(spec.upper),
                range_end=round_edge(spec.data_max),
                count=overflow,
                is_overflow=True,
            )
        )
    return buckets


def build_histogram(values: np.ndarray, num_bins: int = DEFAULT_NUM_BINS) -> list[HistogramBucket]:
    """Build a histogram with all bins (including empty ones) and tail buckets for outliers."""
    spec = compute_bin_edges(values, num_bins)
    if spec is None:
        return []
    return buckets_from_counts(spec, *count_values(values, spec))


def build_histograms_shared(
    values_a: np.ndarray, values_b: np.ndarray, num_bins: int = DEFAULT_NUM_BINS
) -> tuple[list[HistogramBucket], list[HistogramBucket]]:
    """Build two histograms on identical edges, computed from the combined data.

    A side without values yields an empty bucket list.
    """
    a = np.asarray(values_a, dtype=float)
    b = np.asarray(values_b, dtype=float)
    spec = compute_bin_edges(np.concatenate([a, b]), num_bins)
    if spec is None:
        return [], []
    hist_a = buckets_from_counts(spec, *count_values(a, spec)) if a.size else []
    hist_b = buckets_from_counts(spec, *count_values(b, spec)) if b.size else []
    return hist_a, hist_b
