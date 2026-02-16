from __future__ import annotations

import numpy as np

from yaai.server.drift.base import DriftOutput, NumericalDriftMetric, NumericalPreprocessed

EPSILON = 1e-4


class PSI(NumericalDriftMetric):
    """Population Stability Index for numerical feature drift.

    Uses decile bucketing from the reference distribution.
    Score range: 0 to unbounded (higher = more drift).
    Default threshold: 0.2.
    """

    name = "psi"
    default_threshold = 0.2

    def _compute_numerical(self, data: NumericalPreprocessed, threshold: float) -> DriftOutput:
        """Compute PSI from preprocessed numerical data."""
        # Use 10 equal-frequency buckets (deciles) based on reference
        num_buckets = min(10, data.ref_count)
        quantiles = np.linspace(0, 100, num_buckets + 1)
        bucket_boundaries = np.percentile(data.ref, quantiles)
        # Ensure unique boundaries
        bucket_boundaries = np.unique(bucket_boundaries)

        if len(bucket_boundaries) < 2:
            return DriftOutput(
                metric_name=self.name,
                metric_value=0.0,
                is_drifted=False,
                details={
                    "error": "All reference values identical",
                    "reference_count": data.ref_count,
                    "inference_count": data.act_count,
                },
            )

        # Extend boundaries to cover both distributions
        combined_min = min(float(data.ref.min()), float(data.act.min()))
        combined_max = max(float(data.ref.max()), float(data.act.max()))
        if bucket_boundaries[0] > combined_min:
            bucket_boundaries = np.concatenate([[combined_min], bucket_boundaries])
        if bucket_boundaries[-1] < combined_max:
            bucket_boundaries = np.concatenate([bucket_boundaries, [combined_max]])

        ref_counts = np.histogram(data.ref, bins=bucket_boundaries)[0]
        act_counts = np.histogram(data.act, bins=bucket_boundaries)[0]

        ref_pcts = ref_counts / ref_counts.sum()
        act_pcts = act_counts / act_counts.sum()

        # Replace zeros with epsilon to avoid division by zero
        ref_pcts = np.where(ref_pcts == 0, EPSILON, ref_pcts)
        act_pcts = np.where(act_pcts == 0, EPSILON, act_pcts)

        psi_contributions = (act_pcts - ref_pcts) * np.log(act_pcts / ref_pcts)
        total_psi = float(np.sum(psi_contributions))

        buckets = [
            {
                "range": f"{bucket_boundaries[i]:.2f}-{bucket_boundaries[i + 1]:.2f}",
                "expected_pct": round(float(ref_pcts[i]) * 100, 2),
                "actual_pct": round(float(act_pcts[i]) * 100, 2),
                "psi_contribution": round(float(psi_contributions[i]), 6),
            }
            for i in range(len(bucket_boundaries) - 1)
        ]

        return DriftOutput(
            metric_name=self.name,
            metric_value=round(total_psi, 6),
            is_drifted=total_psi > threshold,
            details={
                "buckets": buckets,
                "total_psi": round(total_psi, 6),
                "reference_count": data.ref_count,
                "inference_count": data.act_count,
            },
        )
