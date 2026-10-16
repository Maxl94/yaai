#!/usr/bin/env python3
"""LLM metadata monitoring example (SDK only, no extra dependencies).

Demonstrates the recipe from docs/llm-monitoring.md: monitor an LLM application by sending per-call
*metadata* (token counts, latency, cost, model name, error flag, ...) to YAAI and let the regular drift
detection run on it.

Privacy: this script, like the recipe, never sends prompts or completions -- only numbers and short labels.

What it does:
  1. Creates (or reuses) the model and the model version with the recommended LLM metadata schema.
  2. Uploads a baseline period as reference data.
  3. Sends a "current" period with a deliberate shift (longer prompts, slower model, more errors) as inferences.
  4. Configures the version's drift job (daily, vs. reference) and triggers one run.

Authentication:
  Pass --api-key or set YAAI_API_KEY. Without a key the SDK falls back to Google ADC (requires yaai[gcp]).

Usage:
    YAAI_API_KEY=yaam_... python scripts/llm_monitoring_example.py
    python scripts/llm_monitoring_example.py --base-url http://localhost:8000/api/v1 --api-key yaam_... --records 2000
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import uuid
from datetime import UTC, datetime, timedelta

from yaai import YaaiClient
from yaai.schemas.model import DataType, FieldDirection, ModelRead, SchemaFieldCreate

DEFAULT_BASE_URL = "http://localhost:8000/api/v1"
DEFAULT_MODEL_NAME = "llm-app-metadata"
DEFAULT_VERSION = "v1"
BATCH_SIZE = 1000

# Illustrative USD prices per 1M tokens as (input, output). Not real prices -- maintain your own table.
PRICE_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}

# Relative speed per model (output tokens per second) used by the synthetic generator.
_TOKENS_PER_SECOND: dict[str, float] = {
    "gemini-2.5-flash-lite": 250.0,
    "gemini-2.5-flash": 150.0,
    "gemini-2.5-pro": 60.0,
}

_ROUTES = ["chat", "summarize", "extract"]
_FINISH_REASONS = ["stop", "length", "tool_call"]


def _numerical(direction: FieldDirection, name: str, threshold: float = 0.2) -> SchemaFieldCreate:
    return SchemaFieldCreate(
        direction=direction,
        field_name=name,
        data_type=DataType.NUMERICAL,
        drift_metric="psi",
        alert_threshold=threshold,
    )


def _categorical(direction: FieldDirection, name: str, threshold: float = 0.1) -> SchemaFieldCreate:
    return SchemaFieldCreate(
        direction=direction,
        field_name=name,
        data_type=DataType.CATEGORICAL,
        drift_metric="js_divergence",
        alert_threshold=threshold,
    )


# PSI > 0.2 is the usual "significant shift" level. For categoricals, js_divergence (a 0..1 distance) is more
# robust than chi-squared for rare classes such as errors, which therefore get a lower threshold.
LLM_SCHEMA_FIELDS: list[SchemaFieldCreate] = [
    _numerical(FieldDirection.INPUT, "prompt_tokens"),
    _numerical(FieldDirection.INPUT, "prompt_length_chars"),
    _numerical(FieldDirection.INPUT, "tool_count"),
    _categorical(FieldDirection.INPUT, "llm_model"),
    _categorical(FieldDirection.INPUT, "route"),
    _numerical(FieldDirection.OUTPUT, "completion_tokens"),
    _numerical(FieldDirection.OUTPUT, "total_tokens"),
    _numerical(FieldDirection.OUTPUT, "latency_ms"),
    _numerical(FieldDirection.OUTPUT, "cost_usd"),
    _categorical(FieldDirection.OUTPUT, "error", threshold=0.05),
    _categorical(FieldDirection.OUTPUT, "finish_reason"),
]

# Drift job settings; field names match the keyword arguments of YaaiClient.update_job().
JOB_SETTINGS: dict[str, object] = {
    "name": "LLM metadata daily drift check",
    "schedule": "0 2 * * *",
    "comparison_type": "vs_reference",
    "window_size": "1d",
    "min_samples": 200,
    "is_active": True,
}

# Synthetic traffic profiles: baseline vs. a deliberately shifted period.
_PROFILES: dict[str, dict] = {
    "baseline": {
        "prompt_mu": 6.0,
        "model_weights": {"gemini-2.5-flash": 0.85, "gemini-2.5-flash-lite": 0.15},
        "route_weights": [0.6, 0.25, 0.15],
        "error_rate": 0.02,
        "finish_weights": [0.93, 0.05, 0.02],
    },
    "drifted": {
        "prompt_mu": 6.6,
        "model_weights": {"gemini-2.5-pro": 0.35, "gemini-2.5-flash": 0.55, "gemini-2.5-flash-lite": 0.10},
        "route_weights": [0.4, 0.2, 0.4],
        "error_rate": 0.12,
        "finish_weights": [0.75, 0.2, 0.05],
    },
}


def estimate_cost_usd(llm_model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Compute the cost of one call from token counts and the price table.

    Args:
        llm_model: Model name, must be a key of ``PRICE_PER_1M_TOKENS``.
        prompt_tokens: Number of input tokens.
        completion_tokens: Number of output tokens.

    Returns:
        Cost in USD rounded to 8 decimals.

    Raises:
        KeyError: If the model has no entry in the price table.
    """
    price_in, price_out = PRICE_PER_1M_TOKENS[llm_model]
    return round((prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000, 8)


def _generate_record(rng: random.Random, profile: dict, timestamp: datetime | None) -> dict:
    """Build one synthetic metadata record in the ``{"inputs": ..., "outputs": ...}`` batch format."""
    models = list(profile["model_weights"])
    llm_model = rng.choices(models, weights=list(profile["model_weights"].values()))[0]

    prompt_tokens = max(1, round(rng.lognormvariate(profile["prompt_mu"], 0.5)))
    completion_tokens = max(1, round(rng.lognormvariate(5.0, 0.6)))
    latency_ms = 250 + completion_tokens / _TOKENS_PER_SECOND[llm_model] * 1000 * rng.lognormvariate(0.0, 0.2)
    is_error = rng.random() < profile["error_rate"]

    record = {
        "inputs": {
            "prompt_tokens": prompt_tokens,
            "prompt_length_chars": round(prompt_tokens * rng.uniform(3.5, 4.5)),
            "tool_count": rng.choices([0, 1, 2, 3], weights=[0.5, 0.3, 0.15, 0.05])[0],
            "llm_model": llm_model,
            "route": rng.choices(_ROUTES, weights=profile["route_weights"])[0],
        },
        "outputs": {
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_ms": round(latency_ms, 1),
            "cost_usd": estimate_cost_usd(llm_model, prompt_tokens, completion_tokens),
            "error": "true" if is_error else "false",
            "finish_reason": "error"
            if is_error
            else rng.choices(_FINISH_REASONS, weights=profile["finish_weights"])[0],
        },
    }
    if timestamp is not None:
        record["timestamp"] = timestamp.isoformat()
    return record


def generate_call_metadata(
    count: int,
    *,
    drifted: bool,
    rng: random.Random,
    window_end: datetime | None = None,
    window: timedelta = timedelta(hours=24),
) -> list[dict]:
    """Generate synthetic LLM call metadata (numbers and short labels only, never text).

    Args:
        count: Number of records to generate.
        drifted: If True, shift prompt size, model mix, route mix, error rate and finish reasons.
        rng: Random source, pass a seeded ``random.Random`` for reproducible output.
        window_end: If given, records get ISO timestamps spread evenly over the ``window`` ending here.
        window: Length of the timestamp window.

    Returns:
        Records in the ``{"inputs": {...}, "outputs": {...}}`` format of ``YaaiClient.add_inferences()``.
    """
    profile = _PROFILES["drifted" if drifted else "baseline"]
    step = window / max(count, 1)
    records = []
    for i in range(count):
        timestamp = window_end - window + step * i if window_end is not None else None
        records.append(_generate_record(rng, profile, timestamp))
    return records


async def get_or_create_model(client: YaaiClient, name: str) -> ModelRead:
    """Return the model with the given name, creating it if it does not exist yet."""
    for model in await client.list_models():
        if model.name == name:
            return model
    return await client.create_model(name, "LLM application metadata monitoring (no prompt or completion content).")


async def send_in_batches(client: YaaiClient, version_id: uuid.UUID, records: list[dict]) -> int:
    """Send inference records in batches and return the number of ingested records."""
    ingested = 0
    for start in range(0, len(records), BATCH_SIZE):
        result = await client.add_inferences(version_id, records[start : start + BATCH_SIZE])
        ingested += result.ingested
    return ingested


async def configure_job(client: YaaiClient, model_id: uuid.UUID, version_id: uuid.UUID) -> dict | None:
    """Apply ``JOB_SETTINGS`` to the version's drift job. Returns the job, or None if there is none."""
    job = await client.get_version_job(model_id, version_id)
    if job is None:
        return None
    return await client.update_job(job["id"], **JOB_SETTINGS)


async def run(args: argparse.Namespace) -> None:
    """Create the model/version, upload baseline and current data, and trigger a drift run."""
    rng = random.Random(args.seed)  # noqa: S311 - synthetic data, not security relevant
    now = datetime.now(UTC)

    async with YaaiClient(args.base_url, api_key=args.api_key) as client:
        model = await get_or_create_model(client, args.model_name)
        version = await client.get_or_create_version(
            model.id, args.version, schema_fields=LLM_SCHEMA_FIELDS, description="LLM call metadata"
        )
        print(f"Model {model.name} ({model.id}), version {args.version} ({version.id})")

        reference = generate_call_metadata(args.records, drifted=False, rng=rng)
        ref_result = await client.add_reference_data(model.id, version.id, reference)
        print(f"Uploaded {ref_result.ingested} reference records (baseline)")

        current = generate_call_metadata(args.records, drifted=True, rng=rng, window_end=now)
        ingested = await send_in_batches(client, version.id, current)
        print(f"Sent {ingested} inference records (shifted period)")

        job = await configure_job(client, model.id, version.id)
        if job is None:
            print("No drift job found for this version, skipping drift run")
            return
        run_info = await client.trigger_job(job["id"])
        print(f"Triggered drift job '{job['name']}': status={run_info['status']}")
        print(f"Open the drift results of version {version.id} in the YAAI UI to inspect the shifted fields.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Send synthetic LLM call metadata to YAAI and run drift detection.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"YAAI API base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("YAAI_API_KEY"),
        help="API key (default: env YAAI_API_KEY; without a key Google ADC is used)",
    )
    parser.add_argument("--records", type=_positive_int, default=1000, help="Records per period (default: 1000)")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME, help=f"Model name (default: {DEFAULT_MODEL_NAME})")
    parser.add_argument("--version", default=DEFAULT_VERSION, help=f"Version label (default: {DEFAULT_VERSION})")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    return parser.parse_args(argv)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value}")
    return parsed


def main() -> None:
    """Main entry point for the script."""
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
