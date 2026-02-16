from __future__ import annotations

from scipy.spatial.distance import jensenshannon

from yaai.server.drift.base import CategoricalDriftMetric, CategoricalPreprocessed, DriftOutput


class JSDivergence(CategoricalDriftMetric):
    """Jensen-Shannon divergence for categorical feature drift.

    Uses scipy's jensenshannon distance (base-2 log).
    Score range: 0 to 1. Default threshold: 0.1.
    """

    name = "js_divergence"
    default_threshold = 0.1

    def _compute_categorical(self, data: CategoricalPreprocessed, threshold: float) -> DriftOutput:
        """Compute JS divergence from preprocessed categorical data."""
        # Normalize to probability distributions
        ref_prob = data.ref_freq / data.ref_freq.sum()
        act_prob = data.act_freq / data.act_freq.sum()

        # scipy jensenshannon returns the distance (sqrt of divergence) using log base 2
        jsd_value = float(jensenshannon(ref_prob, act_prob, base=2))

        categories = [
            {
                "value": str(cat),
                "reference_pct": round(float(ref_prob[i]) * 100, 2),
                "actual_pct": round(float(act_prob[i]) * 100, 2),
            }
            for i, cat in enumerate(data.all_categories)
        ]

        return DriftOutput(
            metric_name=self.name,
            metric_value=round(jsd_value, 6),
            is_drifted=jsd_value > threshold,
            details={
                "jsd_value": round(jsd_value, 6),
                "categories": categories,
                "reference_count": data.ref_count,
                "inference_count": data.act_count,
            },
        )
