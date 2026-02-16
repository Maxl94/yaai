#!/usr/bin/env python3
"""
Demo Data Generator using real scikit-learn datasets and trained models.

Loads real ML datasets, trains actual models (RandomForest), then uploads
reference data and weeks of inference data with gradually increasing drift.

Datasets:
  - california_housing : California house price prediction (regression, 8 features, 20k samples)
  - wine               : Wine cultivar classification (3 classes, 13 chemical features)
  - breast_cancer      : Tumor malignancy classification (binary, 30 cell-nucleus features)
  - all                : Generate all three datasets

Authentication (optional):
  Set API_KEY env var to authenticate with an API key (recommended).
  Alternatively, set ADMIN_USERNAME and ADMIN_PASSWORD for login-based auth.

Usage:
    API_KEY=your_api_key python scripts/generate_demo_data.py --mode full --dataset all
    python scripts/generate_demo_data.py --mode full --dataset wine
    python scripts/generate_demo_data.py --mode full --dataset california_housing --weeks 12
    python scripts/generate_demo_data.py --drop-all
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import numpy as np
from sklearn.datasets import fetch_california_housing, load_breast_cancer, load_wine
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

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


def build_schema(feature_names: list[str], config: dict) -> list[dict]:
    """Build API schema from feature names and task type."""
    schema = []
    for name in feature_names:
        schema.append({"field_name": name, "direction": "input", "data_type": "numerical"})

    if config["task"] == "classification":
        schema.append({"field_name": config["output_name"], "direction": "output", "data_type": "categorical"})
        schema.append({"field_name": "confidence", "direction": "output", "data_type": "numerical"})
    else:
        schema.append({"field_name": config["output_name"], "direction": "output", "data_type": "numerical"})

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
# API helpers
# ---------------------------------------------------------------------------


def get_or_create_model(client: httpx.Client, name: str, description: str) -> dict:
    response = client.get(f"{BASE_URL}/models", params={"search": name})
    response.raise_for_status()
    for m in response.json()["data"]:
        if m["name"] == name:
            print(f"  Found existing model: {m['id']}")
            return m

    response = client.post(f"{BASE_URL}/models", json={"name": name, "description": description})
    response.raise_for_status()
    model = response.json()["data"]
    print(f"  Created model: {model['id']}")
    return model


def create_version(client: httpx.Client, model_id: str, version: str, schema: list[dict]) -> dict:
    response = client.post(
        f"{BASE_URL}/models/{model_id}/versions",
        json={"version": version, "schema": schema},
    )
    response.raise_for_status()
    return response.json()["data"]


def upload_reference_data(client: httpx.Client, model_id: str, version_id: str, records: list[dict]) -> int:
    response = client.post(
        f"{BASE_URL}/models/{model_id}/versions/{version_id}/reference-data",
        json={"records": records},
    )
    response.raise_for_status()
    return response.json()["data"]["ingested"]


def create_inferences_batch(client: httpx.Client, version_id: str, records: list[dict]) -> int:
    response = client.post(
        f"{BASE_URL}/inferences/batch",
        json={"model_version_id": version_id, "records": records},
    )
    response.raise_for_status()
    return response.json()["data"]["ingested"]


def backfill_jobs(client: httpx.Client, model_id: str, version_id: str) -> int:
    """Trigger backfill for all active jobs on this version."""
    response = client.get(f"{BASE_URL}/models/{model_id}/versions/{version_id}/jobs")
    response.raise_for_status()
    jobs = response.json()["data"]
    total_runs = 0
    for job in jobs:
        if job["is_active"]:
            resp = client.post(f"{BASE_URL}/jobs/{job['id']}/backfill", timeout=300.0)
            resp.raise_for_status()
            runs = resp.json()["data"]["runs_created"]
            total_runs += runs
            print(f"    Job '{job['name']}': {runs} backfill runs")
    return total_runs


def drop_all_models(client: httpx.Client) -> int:
    response = client.get(f"{BASE_URL}/models", params={"page_size": 100})
    response.raise_for_status()
    deleted = 0
    for m in response.json()["data"]:
        try:
            client.delete(f"{BASE_URL}/models/{m['id']}")
            print(f"  Deleted: {m['name']} ({m['id']})")
            deleted += 1
        except Exception as e:
            print(f"  Failed to delete {m['name']}: {e}")
    return deleted


def get_authenticated_client(base_url: str) -> httpx.Client:
    """Create an httpx client, authenticating if auth is enabled.

    Priority:
      1. API_KEY env var → X-API-Key header
      2. ADMIN_USERNAME/ADMIN_PASSWORD → login for Bearer token
      3. No auth
    """
    client = httpx.Client(timeout=60.0)

    # Check for API key first
    api_key = os.environ.get("API_KEY")
    if api_key:
        client.headers["X-API-Key"] = api_key
        print("  Using API key from API_KEY environment variable")
        return client

    # Fall back to login authentication
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "changeme")

    try:
        config_resp = client.get(f"{base_url}/auth/config")
        config_resp.raise_for_status()
        auth_config = config_resp.json().get("data", {})

        if auth_config.get("enabled", False) and auth_config.get("local_enabled", False):
            login_resp = client.post(
                f"{base_url}/auth/login",
                json={"username": username, "password": password},
            )
            login_resp.raise_for_status()
            token = login_resp.json()["data"]["access_token"]
            client.headers["Authorization"] = f"Bearer {token}"
            print(f"  Authenticated as '{username}'")
    except Exception as e:
        print(f"  Auth not available or failed ({e}), proceeding without auth")

    return client


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
    # Generate all rows for the week in one batch, then predict once
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


def generate_dataset(
    client: httpx.Client,
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
    api_model = get_or_create_model(client, config["model_name"], config["description"])
    version_obj = create_version(client, api_model["id"], config["version"], schema)
    version_id = version_obj["id"]
    print(f"  Version: {version_id}")
    print(f"  Schema: {len(schema)} fields ({len(feature_names)} inputs + {len(schema) - len(feature_names)} outputs)")

    rng = np.random.default_rng(42)

    # ---- 3. Reference data (no drift, clean baseline) ----
    print("\n[3/6] Uploading reference data...")
    n_ref = min(500, max(100, X.shape[0] // 5))
    ref_indices = rng.choice(X.shape[0], size=n_ref, replace=False)

    ref_records = make_records_batch(X[ref_indices], model, feature_names, config, target_names)
    ref_count = upload_reference_data(client, api_model["id"], version_id, ref_records)
    print(f"  Uploaded {ref_count} reference records (clean baseline)")

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
            # Random drift factor between 5% and max_drift_factor
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

        created = create_inferences_batch(client, version_id, week_records)
        total_created += created
        drift_label = f"drift {drift_factor:.0%}" if drift_factor > 0 else "baseline"
        print(f"  Week {week + 1:2d}: {created:5d} records  ({drift_label})")

    # ---- 5. Backfill drift detection ----
    print("\n[5/6] Running drift backfill for historical data...")
    backfill_runs = backfill_jobs(client, api_model["id"], version_id)
    print(f"  Created {backfill_runs} historical drift runs")

    # ---- 6. Summary ----
    print("\n[6/6] Done!")
    print(f"  Reference:  {ref_count} records")
    print(f"  Inference:  {total_created} records across {weeks} weeks")
    print(f"  Backfill:   {backfill_runs} drift runs")
    print(f"  Dashboard:  http://localhost:3000/models/{api_model['id']}/versions/{version_id}/dashboard")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    global BASE_URL  # noqa: PLW0603

    parser = argparse.ArgumentParser(
        description="Generate demo data using real scikit-learn datasets and trained models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Datasets:
  california_housing  California house price prediction (regression, 8 features)
  wine                Wine cultivar classification (3 classes, 13 features)
  breast_cancer       Tumor malignancy classification (binary, 30 features)
  all                 Generate all three datasets

Examples:
  %(prog)s --mode full --dataset all
  %(prog)s --mode full --dataset wine --weeks 12 --records-per-day 80
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
    parser.add_argument("--api-url", type=str, default=None, help=f"API base URL (default: {BASE_URL})")

    args = parser.parse_args()

    if not args.drop_all and not args.mode:
        parser.error("Either --mode or --drop-all is required")

    if args.api_url is not None:
        BASE_URL = args.api_url

    client = get_authenticated_client(BASE_URL)
    try:
        # Test connection
        try:
            client.get(f"{BASE_URL}/models").raise_for_status()
        except httpx.ConnectError:
            print(f"Cannot connect to API at {BASE_URL}")
            print("Make sure the backend is running (docker compose up)")
            sys.exit(1)
        except Exception as e:
            print(f"Error connecting to API: {e}")
            sys.exit(1)

        if args.drop_all:
            print("\nDeleting all existing models...")
            deleted = drop_all_models(client)
            print(f"Deleted {deleted} models\n")
            if not args.mode:
                sys.exit(0)

        if args.mode == "full":
            datasets = list(DATASETS.keys()) if args.dataset == "all" else [args.dataset]

            for ds_key in datasets:
                generate_dataset(
                    client=client,
                    dataset_key=ds_key,
                    weeks=args.weeks,
                    records_per_day=args.records_per_day,
                )

            print(f"\n{'=' * 60}")
            print("All done! View your models at http://localhost:3000/models")
            print(f"{'=' * 60}\n")
    finally:
        client.close()


if __name__ == "__main__":
    main()
