import numpy as np

from yaai.server.drift.psi import PSI


def test_identical_distributions():
    rng = np.random.default_rng(42)
    data = rng.normal(50, 10, 1000).tolist()
    result = PSI().compute(data, data)
    assert result.metric_value < 0.1
    assert result.is_drifted is False
    assert result.metric_name == "psi"


def test_shifted_distribution():
    rng = np.random.default_rng(42)
    reference = rng.normal(50, 10, 1000).tolist()
    actual = rng.normal(70, 10, 1000).tolist()
    result = PSI().compute(reference, actual)
    assert result.metric_value > 0.2
    assert result.is_drifted is True


def test_slightly_shifted():
    rng = np.random.default_rng(42)
    reference = rng.normal(50, 10, 1000).tolist()
    actual = rng.normal(52, 10, 1000).tolist()
    result = PSI().compute(reference, actual)
    # Slight shift should produce low PSI
    assert result.metric_value < 0.2
    assert result.is_drifted is False


def test_custom_threshold():
    rng = np.random.default_rng(42)
    reference = rng.normal(50, 10, 1000).tolist()
    actual = rng.normal(55, 10, 1000).tolist()
    # Use a very low threshold so it triggers
    result = PSI().compute(reference, actual, threshold=0.01)
    assert result.is_drifted is True


def test_empty_reference():
    result = PSI().compute([], [1, 2, 3])
    assert result.is_drifted is False
    assert "error" in result.details


def test_empty_actual():
    result = PSI().compute([1, 2, 3], [])
    assert result.is_drifted is False
    assert "error" in result.details


def test_all_same_values():
    result = PSI().compute([5.0] * 100, [5.0] * 100)
    assert result.is_drifted is False


def test_details_contain_buckets():
    rng = np.random.default_rng(42)
    reference = rng.normal(50, 10, 500).tolist()
    actual = rng.normal(50, 10, 500).tolist()
    result = PSI().compute(reference, actual)
    assert "buckets" in result.details
    assert "total_psi" in result.details
    assert "reference_count" in result.details
    assert "inference_count" in result.details
    assert len(result.details["buckets"]) > 0
