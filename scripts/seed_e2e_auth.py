#!/usr/bin/env python3
"""Seed the E2E test database with auth-separation test data.

Inserts the admin user directly into PG (bypassing the API bootstrap
chicken-and-egg), then uses the REST API to create a viewer, service
accounts, models, and model-access grants.

Writes seed data to frontend/e2e/.seed-data.json for Playwright to consume.

Usage:
    python scripts/seed_e2e_auth.py [--base-url http://localhost:8001]
"""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg2

from yaai.server.auth.passwords import hash_password

# Defaults matching docker-compose.test.yml
DEFAULT_BASE_URL = "http://localhost:8001"
PG_DSN = "postgresql://aimon:testpass@localhost:5433/aimonitoring_test"

OWNER_USERNAME = "admin"
OWNER_PASSWORD = os.environ.get("E2E_OWNER_PASSWORD", "owner-pass-123")
OWNER_EMAIL = "admin@e2e-test.local"

VIEWER_USERNAME = "viewer"
VIEWER_PASSWORD = os.environ.get("E2E_VIEWER_PASSWORD", "viewer-pass-123")
VIEWER_EMAIL = "viewer@e2e-test.local"


def _wait_for_health(base_url: str, retries: int = 30, interval: float = 2.0) -> None:
    """Poll /health until the backend is ready."""
    url = f"{base_url}/health"
    for i in range(retries):
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code == 200:
                print(f"  Backend healthy after {i + 1} attempt(s)")
                return
        except httpx.ConnectError:
            pass
        time.sleep(interval)
    print("ERROR: Backend did not become healthy", file=sys.stderr)
    sys.exit(1)


def _clean_db(dsn: str) -> None:
    """Truncate all application tables so the seed is idempotent."""
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                TRUNCATE model_access, api_keys, service_accounts,
                         refresh_tokens, drift_results, notifications,
                         job_runs, job_configs, ground_truth,
                         reference_data, inference_data, schema_fields,
                         model_versions, models, users
                CASCADE
                """
            )
        conn.commit()
        print("  Cleaned all application tables")
    finally:
        conn.close()


def _insert_admin_user(dsn: str) -> None:
    """Insert the admin user directly into PG using bcrypt-hashed password."""
    hashed = hash_password(OWNER_PASSWORD)

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE username = %s", (OWNER_USERNAME,))
            if cur.fetchone():
                print(f"  Admin user '{OWNER_USERNAME}' already exists, skipping insert")
                return
            cur.execute(
                """
                INSERT INTO users (id, username, email, hashed_password, role, auth_provider, is_active, created_at, updated_at)
                VALUES (gen_random_uuid(), %s, %s, %s, 'OWNER', 'LOCAL', true, now(), now())
                """,
                (OWNER_USERNAME, OWNER_EMAIL, hashed),
            )
        conn.commit()
        print(f"  Inserted admin user '{OWNER_USERNAME}'")
    finally:
        conn.close()


def _login(client: httpx.Client, base_url: str, username: str, password: str) -> str:
    """Login and return the access token."""
    r = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, f"Login failed for {username}: {r.status_code} {r.text}"
    return r.json()["data"]["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed E2E auth test data")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--pg-dsn", default=PG_DSN)
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")

    print("1. Waiting for backend health...")
    _wait_for_health(base_url)

    print("2. Cleaning existing data (idempotent re-run)...")
    _clean_db(args.pg_dsn)

    print("3. Inserting admin user directly into PG...")
    _insert_admin_user(args.pg_dsn)

    client = httpx.Client(timeout=30.0)

    print("4. Logging in as admin...")
    admin_token = _login(client, base_url, OWNER_USERNAME, OWNER_PASSWORD)
    headers = _auth_headers(admin_token)

    print("5. Creating viewer user...")
    r = client.post(
        f"{base_url}/api/v1/auth/users",
        json={
            "username": VIEWER_USERNAME,
            "password": VIEWER_PASSWORD,
            "email": VIEWER_EMAIL,
            "role": "viewer",
        },
        headers=headers,
    )
    assert r.status_code in (201, 409), f"Create viewer failed: {r.status_code} {r.text}"

    print("6. Creating service accounts...")
    sa1_resp = client.post(
        f"{base_url}/api/v1/auth/service-accounts",
        json={"name": "e2e-sa-1", "auth_type": "api_key"},
        headers=headers,
    )
    assert sa1_resp.status_code == 201, f"Create SA-1 failed: {sa1_resp.text}"
    sa1_data = sa1_resp.json()["data"]
    sa1_id = sa1_data["service_account"]["id"]
    sa1_key = sa1_data["raw_key"]
    print(f"  SA-1: {sa1_id}")

    sa2_resp = client.post(
        f"{base_url}/api/v1/auth/service-accounts",
        json={"name": "e2e-sa-2", "auth_type": "api_key"},
        headers=headers,
    )
    assert sa2_resp.status_code == 201, f"Create SA-2 failed: {sa2_resp.text}"
    sa2_data = sa2_resp.json()["data"]
    sa2_id = sa2_data["service_account"]["id"]
    sa2_key = sa2_data["raw_key"]
    print(f"  SA-2: {sa2_id}")

    print("7. Creating models...")
    model_a_resp = client.post(
        f"{base_url}/api/v1/models",
        json={"name": "E2E-Model-A"},
        headers=headers,
    )
    assert model_a_resp.status_code == 201, f"Create Model-A failed: {model_a_resp.text}"
    model_a_id = model_a_resp.json()["data"]["id"]
    print(f"  Model-A: {model_a_id}")

    model_b_resp = client.post(
        f"{base_url}/api/v1/models",
        json={"name": "E2E-Model-B"},
        headers=headers,
    )
    assert model_b_resp.status_code == 201, f"Create Model-B failed: {model_b_resp.text}"
    model_b_id = model_b_resp.json()["data"]["id"]
    print(f"  Model-B: {model_b_id}")

    print("8. Granting model access...")
    r = client.post(
        f"{base_url}/api/v1/auth/models/{model_a_id}/access",
        json={"service_account_id": sa1_id},
        headers=headers,
    )
    assert r.status_code == 201, f"Grant SA-1 -> Model-A failed: {r.text}"
    print("  SA-1 -> Model-A")

    r = client.post(
        f"{base_url}/api/v1/auth/models/{model_b_id}/access",
        json={"service_account_id": sa2_id},
        headers=headers,
    )
    assert r.status_code == 201, f"Grant SA-2 -> Model-B failed: {r.text}"
    print("  SA-2 -> Model-B")

    print("9. Creating version on Model-A with schema...")
    r = client.post(
        f"{base_url}/api/v1/models/{model_a_id}/versions",
        json={
            "version": "v1.0",
            "schema": [
                {"direction": "input", "field_name": "age", "data_type": "numerical"},
                {"direction": "input", "field_name": "gender", "data_type": "categorical"},
                {"direction": "output", "field_name": "score", "data_type": "numerical"},
            ],
        },
        headers=headers,
    )
    assert r.status_code == 201, f"Create version failed: {r.text}"
    version_a_id = r.json()["data"]["id"]
    print(f"  Version: {version_a_id}")

    print("10. Uploading reference data (100 records)...")
    ref_records = [
        {
            "inputs": {"age": 25 + i, "gender": "male" if i % 2 == 0 else "female"},
            "outputs": {"score": 0.5},
        }
        for i in range(100)
    ]
    r = client.post(
        f"{base_url}/api/v1/models/{model_a_id}/versions/{version_a_id}/reference-data",
        json={"records": ref_records},
        headers=headers,
    )
    assert r.status_code == 201, f"Upload reference data failed: {r.text}"

    print("11. Ingesting inference data (shifted ages for drift)...")
    now = datetime.now(UTC)
    for i in range(100):
        client.post(
            f"{base_url}/api/v1/inferences",
            json={
                "model_version_id": version_a_id,
                "inputs": {"age": 200 + i, "gender": "male" if i % 2 == 0 else "female"},
                "outputs": {"score": 0.5},
                "timestamp": (now - timedelta(minutes=i)).isoformat(),
            },
            headers=headers,
        )

    print("12. Triggering drift detection...")
    r = client.get(
        f"{base_url}/api/v1/models/{model_a_id}/versions/{version_a_id}/jobs",
        headers=headers,
    )
    assert r.status_code == 200, f"List jobs failed: {r.text}"
    job_a_id = r.json()["data"][0]["id"]
    print(f"  Job: {job_a_id}")

    r = client.post(f"{base_url}/api/v1/jobs/{job_a_id}/trigger", headers=headers)
    assert r.status_code == 201, f"Trigger job failed: {r.text}"
    run_status = r.json()["data"]["status"]
    print(f"  Drift run status: {run_status}")

    seed_data = {
        "owner": {"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
        "viewer": {"username": VIEWER_USERNAME, "password": VIEWER_PASSWORD},
        "sa1": {"id": sa1_id, "key": sa1_key, "name": "e2e-sa-1"},
        "sa2": {"id": sa2_id, "key": sa2_key, "name": "e2e-sa-2"},
        "model_a": {"id": model_a_id, "name": "E2E-Model-A"},
        "model_b": {"id": model_b_id, "name": "E2E-Model-B"},
        "version_a": {"id": version_a_id, "version": "v1.0"},
        "job_a": {"id": job_a_id},
    }

    out_path = Path(__file__).resolve().parent.parent / "frontend" / "e2e" / ".seed-data.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(seed_data, indent=2) + "\n")
    print(f"13. Wrote seed data to {out_path}")

    client.close()
    print("Done.")


if __name__ == "__main__":
    main()
