from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass, field

import numpy as np


@dataclass
class DriftOutput:
    """Result container for a single drift computation."""

    metric_name: str
    metric_value: float
    is_drifted: bool
    details: dict = field(default_factory=dict)


@dataclass
class CategoricalPreprocessed:
    """Preprocessed categorical data for drift computation."""

    all_categories: list
    ref_freq: np.ndarray
    act_freq: np.ndarray
    ref_count: int
    act_count: int


class DriftMetric(ABC):
    """Abstract base for all drift detection metrics.

    Implements a template method pattern where common validation
    and threshold resolution is handled in the base class.
    """

    name: str
    default_threshold: float

    def compute(self, reference: list, actual: list, threshold: float | None = None) -> DriftOutput:
        """Compute drift between reference and actual distributions.

        This method handles common validation and threshold resolution,
        then delegates to _compute_impl for metric-specific logic.

        Args:
            reference: Reference/baseline values.
            actual: Current/actual values to compare.
            threshold: Override threshold. Uses default_threshold if None.

        Returns:
            DriftOutput with metric value, drift flag, and details.
        """
        resolved_threshold = threshold if threshold is not None else self.default_threshold

        if not reference or not actual:
            return self._empty_data_output(len(reference or []), len(actual or []))

        return self._compute_impl(reference, actual, resolved_threshold)

    def _empty_data_output(self, ref_count: int, actual_count: int) -> DriftOutput:
        """Return a DriftOutput indicating insufficient data."""
        return DriftOutput(
            metric_name=self.name,
            metric_value=0.0,
            is_drifted=False,
            details={"error": "Insufficient data", "reference_count": ref_count, "inference_count": actual_count},
        )

    @abstractmethod
    def _compute_impl(self, reference: list, actual: list, threshold: float) -> DriftOutput:
        """Subclass-specific drift computation logic.

        Args:
            reference: Reference/baseline values (guaranteed non-empty).
            actual: Current/actual values to compare (guaranteed non-empty).
            threshold: The resolved threshold to use for drift detection.

        Returns:
            DriftOutput with metric value, drift flag, and details.
        """


class CategoricalDriftMetric(DriftMetric):
    """Base class for categorical drift metrics with shared preprocessing."""

    def _compute_impl(self, reference: list, actual: list, threshold: float) -> DriftOutput:
        """Preprocess categorical data and delegate to subclass."""
        preprocessed = self._preprocess_categorical(reference, actual)

        if preprocessed is None:
            return DriftOutput(
                metric_name=self.name,
                metric_value=0.0,
                is_drifted=False,
                details={
                    "error": "Fewer than 2 categories",
                    "reference_count": len(reference),
                    "inference_count": len(actual),
                },
            )

        return self._compute_categorical(preprocessed, threshold)

    @staticmethod
    def _preprocess_categorical(reference: list, actual: list) -> CategoricalPreprocessed | None:
        """Preprocess categorical data into aligned frequency arrays."""
        ref_counts = Counter(reference)
        act_counts = Counter(actual)

        all_categories = sorted(set(ref_counts.keys()) | set(act_counts.keys()))

        if len(all_categories) < 2:
            return None

        ref_freq = np.array([ref_counts.get(c, 0) for c in all_categories], dtype=float)
        act_freq = np.array([act_counts.get(c, 0) for c in all_categories], dtype=float)

        return CategoricalPreprocessed(
            all_categories=all_categories,
            ref_freq=ref_freq,
            act_freq=act_freq,
            ref_count=len(reference),
            act_count=len(actual),
        )

    @abstractmethod
    def _compute_categorical(self, data: CategoricalPreprocessed, threshold: float) -> DriftOutput:
        """Compute the categorical drift metric from preprocessed data."""


@dataclass
class NumericalPreprocessed:
    """Preprocessed numerical data for drift computation."""

    ref: np.ndarray
    act: np.ndarray
    ref_count: int
    act_count: int


class NumericalDriftMetric(DriftMetric):
    """Base class for numerical drift metrics with shared preprocessing."""

    def _compute_impl(self, reference: list, actual: list, threshold: float) -> DriftOutput:
        """Preprocess numerical data and delegate to subclass."""
        ref = np.array(reference, dtype=float)
        act = np.array(actual, dtype=float)

        data = NumericalPreprocessed(
            ref=ref,
            act=act,
            ref_count=len(ref),
            act_count=len(act),
        )

        return self._compute_numerical(data, threshold)

    @abstractmethod
    def _compute_numerical(self, data: NumericalPreprocessed, threshold: float) -> DriftOutput:
        """Compute the numerical drift metric from preprocessed data."""
