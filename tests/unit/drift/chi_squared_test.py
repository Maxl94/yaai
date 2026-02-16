from yaai.server.drift.chi_squared import ChiSquared


def test_identical_distributions():
    reference = ["a", "b", "c"] * 100
    actual = ["a", "b", "c"] * 100
    result = ChiSquared().compute(reference, actual)
    assert result.is_drifted is False
    assert result.metric_name == "chi_squared"
    assert result.metric_value < 0.95  # low score = no drift (1 - high p-value)


def test_different_distributions():
    reference = ["a"] * 100 + ["b"] * 100 + ["c"] * 100
    actual = ["a"] * 250 + ["b"] * 30 + ["c"] * 20
    result = ChiSquared().compute(reference, actual)
    assert result.is_drifted is True
    assert result.metric_value > 0.95  # high score = drift (1 - low p-value)


def test_new_category_in_actual():
    reference = ["a", "b", "c"] * 100
    actual = ["a", "b", "c", "d"] * 75
    result = ChiSquared().compute(reference, actual)
    # d appears in actual but not in reference, should detect difference
    assert result.is_drifted is True


def test_empty_reference():
    result = ChiSquared().compute([], ["a", "b"])
    assert result.is_drifted is False
    assert "error" in result.details


def test_single_category():
    result = ChiSquared().compute(["a"] * 100, ["a"] * 100)
    assert result.is_drifted is False
    assert "error" in result.details


def test_custom_threshold():
    reference = ["a"] * 100 + ["b"] * 100
    actual = ["a"] * 110 + ["b"] * 90
    # Threshold 0.01 means score > 0.01 triggers drift (very sensitive)
    result = ChiSquared().compute(reference, actual, threshold=0.01)
    # Even minor difference triggers with low threshold
    assert result.is_drifted is True


def test_details_structure():
    reference = ["x", "y", "z"] * 50
    actual = ["x", "y", "z"] * 50
    result = ChiSquared().compute(reference, actual)
    assert "statistic" in result.details
    assert "p_value" in result.details
    assert "categories" in result.details
    assert len(result.details["categories"]) == 3
