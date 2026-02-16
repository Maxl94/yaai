import pytest

from yaai.server.drift.chi_squared import ChiSquared
from yaai.server.drift.js_divergence import JSDivergence
from yaai.server.drift.ks_test import KSTest
from yaai.server.drift.psi import PSI
from yaai.server.drift.registry import get_metric


def test_default_numerical():
    metric = get_metric(None, "numerical")
    assert isinstance(metric, PSI)


def test_default_categorical():
    metric = get_metric(None, "categorical")
    assert isinstance(metric, ChiSquared)


def test_explicit_ks_test():
    metric = get_metric("ks_test", "numerical")
    assert isinstance(metric, KSTest)


def test_explicit_js_divergence():
    metric = get_metric("js_divergence", "categorical")
    assert isinstance(metric, JSDivergence)


def test_unknown_metric():
    with pytest.raises(ValueError, match="Unknown metric"):
        get_metric("nonexistent", "numerical")


def test_unknown_data_type_no_default():
    with pytest.raises(ValueError, match="No default metric"):
        get_metric(None, "unknown_type")
