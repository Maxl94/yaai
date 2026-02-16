# Contributing

Thanks for considering a contribution! This guide will help you get set up and explains how we work.

## Prerequisites

You'll need the following installed on your machine:

- **Python 3.12+** — the backend language ([python.org](https://www.python.org/downloads/))
- **Node.js 20+** — for the Vue frontend ([nodejs.org](https://nodejs.org/))
- **Docker** — to run PostgreSQL locally ([docker.com](https://www.docker.com/get-started/))
- **[uv](https://docs.astral.sh/uv/)** — a fast Python package manager (install with `curl -LsSf https://astral.sh/uv/install.sh | sh`)

## Setup

There are two ways to run YAAI locally — see the [Development section in the README](README.md#development) for a comparison table. In short:

- **Local dev servers (recommended):** Frontend + backend run separately with hot-reload. Google OAuth won't work (different origins) — use API key or local accounts instead.
- **Docker Compose:** Everything runs in containers on one port. Google OAuth works, but no hot-reload.

Most contributors will want the local dev servers. Here's the setup:

```bash
# 1. Clone the repo
git clone https://github.com/Maxl94/yaai.git
cd yaai

# 2. Start ONLY the database in Docker (not the full stack!)
#    'docker compose up' without 'db' also starts the backend and blocks port 8000.
docker compose up db -d

# 3. Install dependencies
uv sync                          # backend (SDK + server + dev tools)
cd frontend && npm ci && cd ..   # frontend

# 4. Set up environment for local development
#    The example file has Google OAuth disabled and API key auth enabled — that's fine for dev.
cp .env.example .env
```

### Running the backend

```bash
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai --host 0.0.0.0 --port 8000
```

The API server starts on **http://localhost:8000**. Interactive API docs are at **http://localhost:8000/docs**.

> **"Address already in use"?** Port 8000 is already taken — most likely by the Docker backend container. Make sure you started only `docker compose up db -d` (not the full stack). Check with `lsof -i :8000` and stop the conflicting process, or use a different port (e.g. `--port 8001`). If you change the backend port, also update the proxy target in `frontend/vite.config.ts`.

### Running the frontend (separate terminal)

```bash
cd frontend && npm run dev
```

The Vue dev server runs on **http://localhost:3000** and proxies `/api` requests to the backend on port 8000. Open **http://localhost:3000** in your browser.

### Loading demo data (optional)

If you want to see the app with data right away:

```bash
uv run scripts/generate_demo_data.py --drop-all --mode full --dataset all
```

## Running Tests

Before pushing your changes, make sure everything passes:

```bash
# Backend tests
uv run pytest

# Linting (code style)
uv run ruff check .

# Frontend type-checking
cd frontend && npm run type-check
```

## Database Migrations

YAAI uses [Alembic](https://alembic.sqlalchemy.org/) for schema migrations. Migrations are applied automatically on startup, so users deploying the app never need to think about it.

If you change a SQLAlchemy model (add/remove/rename a column, create a new table, etc.), you need to generate a migration:

```bash
# Make sure the database is running and matches the current HEAD migration
docker compose up db -d

# Generate the migration
DATABASE_URL_SYNC="postgresql://aimon:changeme@localhost:5431/aimonitoring" \
  uv run alembic revision --autogenerate -m "short description of change"
```

This creates a new file in `yaai/server/alembic/versions/`. Review it -- autogenerate is good but not perfect. Check that it captures your changes correctly and doesn't include unintended operations.

Then commit the migration file along with your model changes.

## Commits

This project uses [Conventional Commits](https://www.conventionalcommits.org/). All commit messages **must** follow this format:

```
<type>(optional scope): <description>
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

Examples:
```
feat(api): add endpoint for metric export
fix: resolve null pointer in dashboard chart
docs: update setup instructions
```

PRs with non-conforming commit messages will not be merged.

## Pull Requests

1. Fork the repo and create a feature branch (`git checkout -b feat/my-feature`)
2. Make your changes with tests
3. Run the checks listed in [Running Tests](#running-tests)
4. Open a PR focused on a single change

Keep PRs small and focused — one logical change per PR makes reviews faster for everyone.

## Bugs & Feature Requests

Open an issue. For bugs, include steps to reproduce and environment details (OS, Python version, browser).

## License

By contributing, you agree that your contributions will be licensed under the [Elastic License 2.0](LICENSE).
