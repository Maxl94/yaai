from __future__ import annotations

from scipy import stats

from yaai.server.drift.base import DriftOutput, NumericalDriftMetric, NumericalPreprocessed


class KSTest(NumericalDriftMetric):
    """Kolmogorov-Smirnov test for numerical feature drift.

    Reports 1 - p_value so higher values indicate more drift.
    Default threshold: 0.95.
    """

    name = "ks_test"
    default_threshold = 0.95  # 1 - p_value threshold (higher = more drift)

    def _compute_numerical(self, data: NumericalPreprocessed, threshold: float) -> DriftOutput:
        """Compute KS test from preprocessed numerical data."""
        # KS test requires at least 2 samples in each distribution
        if data.ref_count < 2 or data.act_count < 2:
            return DriftOutput(
                metric_name=self.name,
                metric_value=0.0,
                is_drifted=False,
                details={
                    "error": "Insufficient data (need >= 2 samples)",
                    "reference_count": data.ref_count,
                    "inference_count": data.act_count,
                },
            )

        statistic, p_value = stats.ks_2samp(data.ref, data.act)

        # Report 1 - p_value so higher = more drift (consistent with PSI/JS)
        score = round(1.0 - float(p_value), 6)

        return DriftOutput(
            metric_name=self.name,
            metric_value=score,
            is_drifted=bool(score > threshold),
            details={
                "statistic": round(float(statistic), 6),
                "p_value": round(float(p_value), 6),
                "reference_count": data.ref_count,
                "inference_count": data.act_count,
            },
        )
