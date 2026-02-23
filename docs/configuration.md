# Configuration Reference

All settings are read from environment variables (or a `.env` file in the working directory).
No restart-free reloading — the server must be restarted for changes to take effect.

---

## Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://aimon:changeme@localhost:5431/aimonitoring` | Async SQLAlchemy connection string. Must use the `+asyncpg` driver suffix. |
| `BASE_URL` | `http://localhost:8000` | Public base URL of the server (used in generated links). |

!!! warning "Production credentials"
    The default password `changeme` triggers a startup warning.  In production the server will **refuse to start** (`ENVIRONMENT=production`) unless `DATABASE_URL` is overridden with secure credentials.

### Cloud SQL (Google Cloud)

When `CLOUD_SQL_INSTANCE` is set the server uses the [Cloud SQL Python Connector](https://github.com/GoogleCloudPlatform/cloud-sql-python-connector) instead of a direct TCP connection.

| Variable | Default | Description |
|---|---|---|
| `CLOUD_SQL_INSTANCE` | *(unset)* | Cloud SQL instance connection name, e.g. `project:region:instance`. Setting this enables the connector. |
| `CLOUD_SQL_DATABASE` | `aimonitoring` | Database name inside the Cloud SQL instance. |
| `CLOUD_SQL_USER` | *(empty)* | Database user. Leave empty when using IAM authentication. |
| `CLOUD_SQL_IP_TYPE` | `public` | IP type used by the connector — `public` or `private`. |
| `CLOUD_SQL_IAM_AUTH` | `true` | Use IAM-based authentication (recommended). Set to `false` for password auth. |

---

## Dashboard performance

The dashboard computes distribution statistics (histograms, means, std, etc.) over the
most-recent **N** inference records rather than all historical data.  This keeps response
times low regardless of how many records are stored.

| Variable | Default | Description |
|---|---|---|
| `DASHBOARD_MAX_SAMPLES` | `50000` | Maximum inference rows used per dashboard panel. The **most recent** rows are selected so the view reflects current model behaviour. Counts and min/max in the response are always exact; distribution shape and mean/std are based on the sample (statistically representative at this size). Increase if you need higher precision; decrease to improve latency on slower hardware. |

### What is exact vs. sampled

When the time window contains more records than `DASHBOARD_MAX_SAMPLES` each panel
includes a `sample_info` object:

```json
{
  "sample_size": 50000,
  "total_count": 1800000,
  "is_sampled": true
}
```

| Statistic | Source | Notes |
|---|---|---|
| `total_count` (record count) | **Exact** — full population `COUNT(*)` | Uses the `(model_version_id, timestamp)` index, no JSON read required. |
| `min` / `max` | Sample | Most-recent N records. Getting all-time exact min/max requires a full JSON-column scan (same cost as the unsampled query), which negates the performance gain. For monitoring, recent bounds are more meaningful than historical outliers. |
| `mean`, `std`, `median` | Sample | Statistically representative at 50k rows. |
| Histogram bucket counts | Sample | Shape is accurate; absolute counts reflect sample size. |
| Category percentages | Sample | Ratios are unaffected by sample size. |

---

## Drift detection

| Variable | Default | Description |
|---|---|---|
| `DRIFT_MAX_SAMPLES` | `10000` | Maximum inference or reference records loaded into memory for drift metric computation (KS, PSI, chi-squared). Statistical tests give reliable results well below this threshold. Increase for higher precision; at 10k the error vs. the true p-value is negligible for monitoring purposes. |

---

## Reference data

| Variable | Default | Description |
|---|---|---|
| `REFERENCE_DATA_MAX_RECORDS` | `50000` | Hard cap on the number of records accepted in a single reference-data upload (`POST …/reference-data`). Requests exceeding this limit are rejected with HTTP 422. Uploading reference data is a **replace** operation — each successful upload replaces all previously stored reference records for that model version. |

!!! tip "Choosing a reference set size"
    Statistical drift tests (KS, PSI, chi-squared) produce stable results with as few as
    1 000 – 5 000 reference records.  50 000 is conservative.  Very large reference sets
    increase drift-job memory usage without meaningfully improving detection accuracy.

---

## Environment file

Place a `.env` file in the directory where the server starts:

```dotenv
DATABASE_URL=postgresql+asyncpg://user:password@db-host:5432/aimonitoring
DASHBOARD_MAX_SAMPLES=100000
DRIFT_MAX_SAMPLES=20000
REFERENCE_DATA_MAX_RECORDS=50000
```

All variables are optional — unset variables use the defaults shown above.
