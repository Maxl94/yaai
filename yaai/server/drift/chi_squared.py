from __future__ import annotations

from scipy import stats

from yaai.server.drift.base import CategoricalDriftMetric, CategoricalPreprocessed, DriftOutput


class ChiSquared(CategoricalDriftMetric):
    """Chi-squared test for categorical feature drift.

    Uses pseudocounts to handle unseen categories. Reports 1 - p_value.
    Default threshold: 0.95.
    """

    name = "chi_squared"
    default_threshold = 0.95  # 1 - p_value threshold (higher = more drift)

    def _compute_categorical(self, data: CategoricalPreprocessed, threshold: float) -> DriftOutput:
        """Compute chi-squared test from preprocessed categorical data."""
        total_actual = float(data.act_freq.sum())
        total_ref = float(data.ref_freq.sum())

        # Compute expected proportions from reference, add pseudocount for unseen categories
        ref_pcts = (data.ref_freq / total_ref * 100).tolist()
        act_pcts = (data.act_freq / total_actual * 100).tolist()

        # Add pseudocount to both to handle zero-frequency categories
        pseudocount = 0.5
        ref_adj = data.ref_freq + pseudocount
        act_adj = data.act_freq + pseudocount

        # Scale expected to match adjusted actual total
        adj_total_actual = float(act_adj.sum())
        adj_total_ref = float(ref_adj.sum())
        expected = ref_adj * (adj_total_actual / adj_total_ref)

        statistic, p_value = stats.chisquare(act_adj, f_exp=expected)

        categories = [
            {"value": str(cat), "expected_pct": round(ref_pcts[i], 2), "actual_pct": round(act_pcts[i], 2)}
            for i, cat in enumerate(data.all_categories)
        ]

        # Report 1 - p_value so higher = more drift (consistent with PSI/JS)
        score = round(1.0 - float(p_value), 6)

        return DriftOutput(
            metric_name=self.name,
            metric_value=score,
            is_drifted=bool(score > threshold),
            details={
                "statistic": round(float(statistic), 6),
                "p_value": round(float(p_value), 6),
                "categories": categories,
                "reference_count": data.ref_count,
                "inference_count": data.act_count,
            },
        )
