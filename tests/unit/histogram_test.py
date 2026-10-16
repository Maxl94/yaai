import numpy as np
import pytest

from yaai.server.services.histogram import (
    BinSpec,
    build_histogram,
    build_histograms_shared,
    compute_bin_edges,
    count_values,
)


def _outlier_values() -> np.ndarray:
    rng = np.random.default_rng(0)
    return np.append(rng.uniform(0, 1, 499), 1000.0)


def test_empty_input_returns_no_buckets():
    assert compute_bin_edges(np.array([])) is None
    assert build_histogram(np.array([])) == []


def test_nan_and_inf_are_ignored():
    values = np.array([1.0, 2.0, np.nan, np.inf, 3.0])
    buckets = build_histogram(values, num_bins=2)
    assert sum(b.count for b in buckets) == 3


def test_all_nan_returns_no_buckets():
    assert build_histogram(np.array([np.nan, np.nan])) == []


def test_constant_values_produce_single_bucket():
    buckets = build_histogram(np.array([5.0] * 10))
    assert len(buckets) == 1
    assert (buckets[0].range_start, buckets[0].range_end, buckets[0].count) == (5.0, 5.0, 10)
    assert not buckets[0].is_underflow
    assert not buckets[0].is_overflow


def test_single_value_produces_single_bucket():
    buckets = build_histogram(np.array([3.5]))
    assert [b.count for b in buckets] == [1]


def test_outlier_goes_to_overflow_bucket_and_all_bins_present():
    values = _outlier_values()
    buckets = build_histogram(values, num_bins=20)

    overflow = buckets[-1]
    assert overflow.is_overflow
    assert overflow.range_end == 1000.0
    assert overflow.count >= 1
    assert not any(b.is_underflow for b in buckets)

    regular = [b for b in buckets if not b.is_overflow and not b.is_underflow]
    assert len(regular) == 20
    assert regular[-1].range_end < 2  # the bulk is not squashed by the outlier
    assert sum(b.count for b in buckets) == 500


def test_regular_bins_are_contiguous_and_include_empty_bins():
    values = np.concatenate([np.zeros(50), np.ones(50)])
    buckets = build_histogram(values, num_bins=10)
    assert len(buckets) == 10
    assert any(b.count == 0 for b in buckets)
    for left, right in zip(buckets, buckets[1:], strict=False):
        assert left.range_end == pytest.approx(right.range_start)


def test_underflow_bucket_is_first():
    values = np.append(np.random.default_rng(1).uniform(10, 11, 99), -500.0)
    buckets = build_histogram(values)
    assert buckets[0].is_underflow
    assert buckets[0].range_start == -500.0
    assert buckets[0].count >= 1
    assert not any(b.is_overflow for b in buckets)


def test_short_tails_extend_bins_to_min_max_without_tail_buckets():
    values = np.random.default_rng(4).uniform(0, 1, 200)
    buckets = build_histogram(values, num_bins=20)
    assert len(buckets) == 20
    assert buckets[0].range_start == pytest.approx(values.min(), abs=1e-5)
    assert buckets[-1].range_end == pytest.approx(values.max(), abs=1e-5)
    assert sum(b.count for b in buckets) == 200


def test_no_tail_buckets_when_percentiles_cover_range_exactly():
    spec = BinSpec.create(0.0, 10.0, 5, 0.0, 10.0)
    assert not spec.has_underflow
    assert not spec.has_overflow


def test_upper_edge_is_inclusive_in_last_bin():
    spec = BinSpec.create(0.0, 10.0, 5, 0.0, 10.0)
    under, counts, over = count_values(np.array([0.0, 10.0, 10.0]), spec)
    assert (under, counts, over) == (0, [1, 0, 0, 0, 2], 0)


def test_tiny_range_labels_are_distinct():
    values = np.linspace(0.001, 0.01, 50)
    buckets = build_histogram(values, num_bins=20)
    assert len(buckets) == 20
    starts = [b.range_start for b in buckets]
    assert len(set(starts)) == 20
    assert starts[0] == pytest.approx(0.001)
    assert sum(b.count for b in buckets) == 50


def test_large_offset_with_small_spread_keeps_edges_distinct():
    values = 1.7e9 + np.arange(101, dtype=float)
    buckets = build_histogram(values, num_bins=20)
    assert len(buckets) == 20
    starts = [b.range_start for b in buckets]
    assert starts == sorted(set(starts))
    assert all(b.range_start < b.range_end for b in buckets)
    assert (buckets[0].range_start, buckets[-1].range_end) == (1.7e9, 1.7e9 + 100)
    assert sum(b.count for b in buckets) == 101


def test_edges_are_rounded_relative_to_bin_width():
    spec = BinSpec.create(0.0, 1.0, 3, 0.0, 1.0)
    assert spec.edge_decimals == 4
    assert spec.round_edge(1 / 3) == 0.3333
    assert BinSpec.create(5.0, 5.0, 20, 5.0, 5.0).round_edge(5.123456789) == 5.123456789


def test_p1_equals_p99_falls_back_to_min_max():
    values = np.array([1.0] * 100 + [2.0])
    buckets = build_histogram(values, num_bins=4)
    assert buckets[0].range_start == 1.0
    assert buckets[-1].range_end == 2.0
    assert sum(b.count for b in buckets) == 101
    assert not any(b.is_overflow or b.is_underflow for b in buckets)


def test_shared_histograms_use_identical_edges():
    a = np.random.default_rng(2).uniform(0, 1, 100)
    b = np.append(np.random.default_rng(3).uniform(5, 6, 99), 500.0)
    hist_a, hist_b = build_histograms_shared(a, b, num_bins=10)

    assert [(x.range_start, x.range_end) for x in hist_a] == [(x.range_start, x.range_end) for x in hist_b]
    assert sum(x.count for x in hist_a) == 100
    assert sum(x.count for x in hist_b) == 100


def test_shared_histograms_with_one_empty_side():
    hist_a, hist_b = build_histograms_shared(np.array([1.0, 2.0, 3.0]), np.array([]), num_bins=3)
    assert sum(x.count for x in hist_a) == 3
    assert hist_b == []


def test_shared_histograms_both_empty():
    assert build_histograms_shared(np.array([]), np.array([])) == ([], [])
