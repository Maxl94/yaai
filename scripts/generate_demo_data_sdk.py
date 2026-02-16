#!/usr/bin/env python3
"""
Demo Data Generator — SDK version.

Same as generate_demo_data.py but uses the yaai Python SDK instead of raw
HTTP calls.  Useful for testing the SDK end-to-end and as a usage example.

Datasets:
  - california_housing : California house price prediction (regression, 8 features, 20k samples)
  - wine               : Wine cultivar classification (3 classes, 13 chemical features)
  - breast_cancer      : Tumor malignancy classification (binary, 30 cell-nucleus features)
  - all                : Generate all three datasets

Authentication:
  Set API_KEY env var to authenticate with an API key (recommended).
  Without API_KEY, the client falls back to Google ADC (requires yaai[gcp]).

Usage:
    API_KEY=your_api_key python scripts/generate_demo_data_sdk.py --mode full --dataset all
    python scripts/generate_demo_data_sdk.py --mode full --dataset wine
    python scripts/generate_demo_data_sdk.py --drop-all
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sklearn.datasets import fetch_california_housing, load_breast_cancer, load_wine
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from yaai import YaaiClient
from yaai.schemas.model import SchemaFieldCreate

# Load .env file from project root if available
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

BASE_URL = "http://localhost:8000/api/v1"

# ---------------------------------------------------------------------------
# Dataset registry
# ---------------------------------------------------------------------------

DATASETS = {
    "california_housing": {
        "loader": fetch_california_housing,
        "model_name": "house-price-predictor",
        "description": "Predicts California median house values from census block-group features (income, age, rooms, location).",
        "version": "v1.0",
        "task": "regression",
        "output_name": "predicted_price",
    },
    "wine": {
        "loader": load_wine,
        "model_name": "wine-classifier",
        "description": "Classifies wines into 3 cultivar classes from 13 chemical analysis measurements (alcohol, flavanoids, color, etc.).",
        "version": "v1.0",
        "task": "classification",
        "output_name": "predicted_cultivar",
    },
    "breast_cancer": {
        "loader": load_breast_cancer,
        "model_name": "tumor-classifier",
        "description": "Classifies breast tumors as malignant or benign from 30 digitized cell-nucleus measurements.",
        "version": "v1.0",
        "task": "classification",
        "output_name": "predicted_diagnosis",
    },
}


def sanitize_feature_name(name: str) -> str:
    """Make feature names API-safe (no spaces or slashes)."""
    return name.replace(" ", "_").replace("/", "_").lower()


# ---------------------------------------------------------------------------
# ML helpers
# ---------------------------------------------------------------------------


def load_and_train(dataset_key: str):
    """Load a sklearn dataset and train a quick RandomForest model."""
    config = DATASETS[dataset_key]
    data = config["loader"]()
    X, y = data.data, data.target
    feature_names = [sanitize_feature_name(n) for n in data.feature_names]
    target_names = [str(n) for n in data.target_names] if hasattr(data, "target_names") else None

    if config["task"] == "regression":
        model = RandomForestRegressor(n_estimators=50, random_state=42)
    else:
        model = RandomForestClassifier(n_estimators=50, random_state=42)

    model.fit(X, y)
    return X, y, feature_names, target_names, model


def apply_drift(X: np.ndarray, drift_factor: float, rng: np.random.Generator) -> np.ndarray:
    """Apply realistic drift: per-feature mean shift + increased noise."""
    X_drifted = X.copy()
    col_stds = np.std(X_drifted, axis=0)

    # Deterministic per-feature drift directions (seeded from column index)
    n_features = X_drifted.shape[1]
    directions = np.array([1 if i % 3 != 0 else -1 for i in range(n_features)])

    # Shift means
    shifts = col_stds * drift_factor * 0.5 * directions
    X_drifted += shifts

    # Add proportional noise
    noise_scale = col_stds * drift_factor * 0.15
    noise = rng.normal(0, 1, X_drifted.shape) * noise_scale
    X_drifted += noise

    return X_drifted


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------


def build_schema(feature_names: list[str], config: dict) -> list[SchemaFieldCreate]:
    """Build SDK schema objects from feature names and task type."""
    schema = []
    for name in feature_names:
        schema.append(SchemaFieldCreate(field_name=name, direction="input", data_type="numerical"))

    if config["task"] == "classification":
        schema.append(SchemaFieldCreate(field_name=config["output_name"], direction="output", data_type="categorical"))
        schema.append(SchemaFieldCreate(field_name="confidence", direction="output", data_type="numerical"))
    else:
        schema.append(SchemaFieldCreate(field_name=config["output_name"], direction="output", data_type="numerical"))

    return schema


def make_records_batch(
    X_batch: np.ndarray,
    model,
    feature_names: list[str],
    config: dict,
    target_names: list[str] | None,
) -> list[dict]:
    """Convert a batch of rows into API records with model predictions (one predict call)."""
    # Single batched prediction call — avoids per-row overhead
    predictions = model.predict(X_batch)
    probas = model.predict_proba(X_batch) if config["task"] == "classification" else None

    # Round all features at once
    X_rounded = np.round(X_batch, 6)

    records = []
    output_name = config["output_name"]
    is_classification = config["task"] == "classification"

    for i in range(len(X_batch)):
        inputs = {name: float(X_rounded[i, j]) for j, name in enumerate(feature_names)}

        if is_classification and probas is not None:
            label = target_names[int(predictions[i])] if target_names else str(int(predictions[i]))
            outputs = {output_name: label, "confidence": round(float(np.max(probas[i])), 4)}
        else:
            outputs = {output_name: round(float(predictions[i]), 4)}

        records.append({"inputs": inputs, "outputs": outputs})

    return records


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------


def _generate_week_records(
    X: np.ndarray,
    model,
    feature_names: list[str],
    config: dict,
    target_names: list[str] | None,
    week_start: datetime,
    drift_factor: float,
    records_per_day: int,
    rng: np.random.Generator,
) -> list[dict]:
    """Generate one week of inference records with optional drift."""
    all_X = []
    timestamps = []
    for day in range(7):
        current_date = week_start + timedelta(days=day)
        day_indices = rng.choice(X.shape[0], size=records_per_day, replace=True)
        X_day = X[day_indices].copy()

        if drift_factor > 0:
            X_day = apply_drift(X_day, drift_factor, rng)

        all_X.append(X_day)
        for _ in range(records_per_day):
            timestamps.append(
                current_date
                + timedelta(
                    hours=int(rng.integers(0, 24)),
                    minutes=int(rng.integers(0, 60)),
                    seconds=int(rng.integers(0, 60)),
                )
            )

    X_week = np.vstack(all_X)
    records = make_records_batch(X_week, model, feature_names, config, target_names)
    for rec, ts in zip(records, timestamps, strict=True):
        rec["timestamp"] = ts.isoformat()
    return records


async def generate_dataset(
    client: YaaiClient,
    dataset_key: str,
    weeks: int = 8,
    records_per_day: int = 50,
) -> None:
    config = DATASETS[dataset_key]

    print(f"\n{'=' * 60}")
    print(f"  {config['model_name']}  ({config['task']})")
    print(f"  {config['description']}")
    print(f"{'=' * 60}")

    # ---- 1. Load & train ----
    print("\n[1/6] Loading dataset and training model...")
    X, y, feature_names, target_names, model = load_and_train(dataset_key)
    print(f"  Dataset: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"  Model: {type(model).__name__} (50 trees)")
    print(f"  Training score: {model.score(X, y):.4f}")

    # ---- 2. Create model + version ----
    print("\n[2/6] Creating model and version...")
    schema = build_schema(feature_names, config)

    # Check for existing model with same name
    existing_models = await client.list_models()
    api_model = None
    for m in existing_models:
        if m.name == config["model_name"]:
            print(f"  Found existing model: {m.id}")
            api_model = m
            break

    if api_model is None:
        api_model = await client.create_model(config["model_name"], config["description"])
        print(f"  Created model: {api_model.id}")

    version_obj = await client.create_model_version(
        model_id=api_model.id,
        version=config["version"],
        schema_fields=schema,
    )
    version_id = version_obj.id
    print(f"  Version: {version_id}")
    print(f"  Schema: {len(schema)} fields ({len(feature_names)} inputs + {len(schema) - len(feature_names)} outputs)")

    rng = np.random.default_rng(42)

    # ---- 3. Reference data (no drift, clean baseline) ----
    print("\n[3/6] Uploading reference data...")
    n_ref = min(500, max(100, X.shape[0] // 5))
    ref_indices = rng.choice(X.shape[0], size=n_ref, replace=False)

    ref_records = make_records_batch(X[ref_indices], model, feature_names, config, target_names)
    ref_result = await client.add_reference_data(api_model.id, version_id, ref_records)
    print(f"  Uploaded {ref_result.ingested} reference records (clean baseline)")

    # ---- 4. Inference data: random weeks with drift ----
    print("\n[4/6] Generating inference data with sporadic drift...")
    start_date = datetime.now() - timedelta(weeks=weeks)
    total_created = 0

    # Randomly select ~25% of weeks to have drift
    drift_probability = 0.25
    max_drift_factor = 0.25  # Cap drift at 25%

    # Pre-determine which weeks have drift (for reproducibility)
    drift_weeks = set()
    for week in range(weeks):
        if rng.random() < drift_probability:
            drift_weeks.add(week)

    # Ensure at least 1 drift week if we have enough weeks
    if len(drift_weeks) == 0 and weeks >= 4:
        drift_weeks.add(int(rng.integers(weeks // 2, weeks)))

    for week in range(weeks):
        if week in drift_weeks:
            drift_factor = rng.uniform(0.05, max_drift_factor)
        else:
            drift_factor = 0.0

        week_start = start_date + timedelta(weeks=week)
        week_records = _generate_week_records(
            X,
            model,
            feature_names,
            config,
            target_names,
            week_start,
            drift_factor,
            records_per_day,
            rng,
        )

        batch_result = await client.add_inferences(version_id, week_records)
        total_created += batch_result.ingested
        drift_label = f"drift {drift_factor:.0%}" if drift_factor > 0 else "baseline"
        print(f"  Week {week + 1:2d}: {batch_result.ingested:5d} records  ({drift_label})")

    # ---- 5. Backfill drift detection ----
    print("\n[5/6] Running drift backfill for historical data...")
    job = await client.get_version_job(api_model.id, version_id)
    total_runs = 0
    if job and job["is_active"]:
        result = await client.backfill_job(job["id"])
        runs = result["runs_created"]
        total_runs += runs
        print(f"    Job '{job['name']}': {runs} backfill runs")
    print(f"  Created {total_runs} historical drift runs")

    # ---- 6. Summary ----
    print("\n[6/6] Done!")
    print(f"  Reference:  {ref_result.ingested} records")
    print(f"  Inference:  {total_created} records across {weeks} weeks")
    print(f"  Backfill:   {total_runs} drift runs")
    print(f"  Dashboard:  http://localhost:3000/models/{api_model.id}/versions/{version_id}/dashboard")


async def drop_all_models(client: YaaiClient) -> int:
    models = await client.list_models()
    deleted = 0
    for m in models:
        try:
            await client.delete_model(m.id)
            print(f"  Deleted: {m.name} ({m.id})")
            deleted += 1
        except Exception as e:
            print(f"  Failed to delete {m.name}: {e}")
    return deleted


async def run(args: argparse.Namespace) -> None:
    api_key = os.environ.get("API_KEY")
    if api_key:
        print("  Using API key from API_KEY environment variable")
    else:
        print("  No API_KEY set, falling back to Google ADC")

    async with YaaiClient(args.api_url, api_key=api_key) as client:
        # Test connection
        try:
            await client.list_models()
        except Exception as e:
            print(f"Cannot connect to API at {args.api_url}: {e}")
            print("Make sure the backend is running (docker compose up)")
            sys.exit(1)

        if args.drop_all:
            print("\nDeleting all existing models...")
            deleted = await drop_all_models(client)
            print(f"Deleted {deleted} models\n")
            if not args.mode:
                return

        if args.mode == "full":
            datasets = list(DATASETS.keys()) if args.dataset == "all" else [args.dataset]

            for ds_key in datasets:
                await generate_dataset(
                    client=client,
                    dataset_key=ds_key,
                    weeks=args.weeks,
                    records_per_day=args.records_per_day,
                )

            print(f"\n{'=' * 60}")
            print("All done! View your models at http://localhost:3000/models")
            print(f"{'=' * 60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Generate demo data using the yaai SDK (same output as generate_demo_data.py).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Datasets:
  california_housing  California house price prediction (regression, 8 features)
  wine                Wine cultivar classification (3 classes, 13 features)
  breast_cancer       Tumor malignancy classification (binary, 30 features)
  all                 Generate all three datasets

Examples:
  API_KEY=... %(prog)s --mode full --dataset all
  API_KEY=... %(prog)s --mode full --dataset wine --weeks 12 --records-per-day 80
  %(prog)s --drop-all
  %(prog)s --drop-all --mode full --dataset all
        """,
    )

    parser.add_argument("--mode", choices=["full"], help="Generation mode")
    parser.add_argument("--drop-all", action="store_true", help="Delete all existing models first")
    parser.add_argument(
        "--dataset",
        choices=["all", "california_housing", "wine", "breast_cancer"],
        default="all",
        help="Which dataset(s) to generate (default: all)",
    )
    parser.add_argument("--weeks", type=int, default=8, help="Weeks of inference data (default: 8)")
    parser.add_argument("--records-per-day", type=int, default=50, help="Records per day (default: 50)")
    parser.add_argument("--api-url", type=str, default=BASE_URL, help=f"API base URL (default: {BASE_URL})")

    args = parser.parse_args()

    if not args.drop_all and not args.mode:
        parser.error("Either --mode or --drop-all is required")

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
