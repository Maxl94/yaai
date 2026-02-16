from yaai.server.drift.js_divergence import JSDivergence


def test_identical_distributions():
    reference = ["a", "b", "c"] * 100
    actual = ["a", "b", "c"] * 100
    result = JSDivergence().compute(reference, actual)
    assert result.metric_value < 0.01
    assert result.is_drifted is False
    assert result.metric_name == "js_divergence"


def test_completely_different():
    reference = ["a"] * 300
    actual = ["b"] * 300
    result = JSDivergence().compute(reference, actual)
    assert result.metric_value > 0.5
    assert result.is_drifted is True


def test_slightly_different():
    reference = ["a"] * 100 + ["b"] * 100 + ["c"] * 100
    actual = ["a"] * 110 + ["b"] * 95 + ["c"] * 95
    result = JSDivergence().compute(reference, actual)
    assert result.metric_value < 0.1
    assert result.is_drifted is False


def test_empty_data():
    result = JSDivergence().compute([], ["a", "b"])
    assert result.is_drifted is False
    assert "error" in result.details


def test_single_category():
    result = JSDivergence().compute(["a"] * 100, ["a"] * 100)
    assert result.is_drifted is False


def test_custom_threshold():
    reference = ["a"] * 100 + ["b"] * 100
    actual = ["a"] * 150 + ["b"] * 50
    result = JSDivergence().compute(reference, actual, threshold=0.01)
    assert result.is_drifted is True


def test_details_structure():
    reference = ["x", "y"] * 100
    actual = ["x", "y"] * 100
    result = JSDivergence().compute(reference, actual)
    assert "jsd_value" in result.details
    assert "categories" in result.details
    assert "reference_count" in result.details
