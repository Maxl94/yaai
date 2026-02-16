import numpy as np

from yaai.server.drift.ks_test import KSTest


def test_identical_distributions():
    rng = np.random.default_rng(42)
    data = rng.normal(50, 10, 1000).tolist()
    result = KSTest().compute(data, data)
    assert result.is_drifted is False
    assert result.metric_name == "ks_test"
    assert result.metric_value < 0.95  # low score = no drift (1 - high p-value)


def test_different_distributions():
    rng = np.random.default_rng(42)
    reference = rng.normal(50, 10, 1000).tolist()
    actual = rng.normal(70, 10, 1000).tolist()
    result = KSTest().compute(reference, actual)
    assert result.is_drifted is True
    assert result.metric_value > 0.95  # high score = drift (1 - low p-value)


def test_custom_threshold():
    rng = np.random.default_rng(42)
    reference = rng.normal(50, 10, 1000).tolist()
    actual = rng.normal(52, 10, 1000).tolist()
    # Low threshold means very sensitive to differences
    result = KSTest().compute(reference, actual, threshold=0.5)
    # With such a low threshold, even slight difference triggers
    assert result.is_drifted is True


def test_insufficient_data():
    result = KSTest().compute([1], [2])
    assert result.is_drifted is False
    assert "error" in result.details


def test_empty_data():
    result = KSTest().compute([], [1, 2, 3])
    assert result.is_drifted is False


def test_details_structure():
    rng = np.random.default_rng(42)
    ref = rng.normal(50, 10, 500).tolist()
    act = rng.normal(50, 10, 500).tolist()
    result = KSTest().compute(ref, act)
    assert "statistic" in result.details
    assert "p_value" in result.details
    assert "reference_count" in result.details
    assert "inference_count" in result.details
