# Architecture Overview

## System Components

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (SPA)                    │
│                                                     │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Model   │  │   Model      │  │   Drift       │  │
│  │ Overview │  │  Dashboard   │  │   Results     │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP
                       ▼
┌─────────────────────────────────────────────────────┐
│                  Backend (FastAPI)                   │
│                                                     │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │  REST API  │  │  Dashboard  │  │  Drift       │  │
│  │  (CRUD)    │  │  Engine     │  │  Engine      │  │
│  └────────────┘  └─────────────┘  └──────────────┘  │
│                                                     │
│  ┌────────────┐  ┌─────────────┐                    │
│  │  Schema    │  │    Job      │                    │
│  │ Validator  │  │  Scheduler  │                    │
│  └────────────┘  └─────────────┘                    │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │   PostgreSQL    │
              │                 │
              │  models         │
              │  versions       │
              │  schema_fields  │
              │  inferences     │
              │  reference_data │
              │  ground_truth   │
              │  job_configs    │
              │  job_runs       │
              │  drift_results  │
              │  notifications  │
              └─────────────────┘
```

## Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Backend framework** | FastAPI | Async, auto-generated OpenAPI docs, Pydantic integration |
| **ORM** | SQLAlchemy 2.0 | Native JSONB support, async via `asyncpg`, mature ecosystem |
| **Database** | PostgreSQL | JSONB for flexible data, strong aggregation functions |
| **Job scheduler** | APScheduler | Lightweight, cron support, runs in-process (no Redis/Celery needed) |
| **Drift computation** | scipy + numpy | `scipy.stats` has KS test, chi-squared; numpy for PSI calculation |
| **Frontend framework** | Vue 3 | Composition API, TypeScript, simple mental model |
| **UI components** | Vuetify 3 | Tables, cards, forms, navigation — all needed components |
| **Charts** | Apache ECharts (vue-echarts) | Overlaid histograms, grouped bars, line charts, strong tooltips |

## Deployment

In production (Docker), everything runs as a single process: FastAPI serves the REST API, the Vue frontend as static files, and APScheduler runs drift detection jobs -- all backed by one PostgreSQL database. No Redis, no Celery, no separate worker processes.

```bash
docker compose up -d   # starts PostgreSQL + YAAI server
```

For development, the backend and frontend run separately -- see [Getting Started](getting-started.md).
