# Contributing

Thanks for considering a contribution! This guide will help you get set up and explains how we work.

## Prerequisites

You'll need the following installed on your machine:

- **Python 3.12+** — the backend language ([python.org](https://www.python.org/downloads/))
- **Node.js 20+** — for the Vue frontend ([nodejs.org](https://nodejs.org/))
- **Docker** — to run PostgreSQL locally ([docker.com](https://www.docker.com/get-started/))
- **[uv](https://docs.astral.sh/uv/)** — a fast Python package manager (install with `curl -LsSf https://astral.sh/uv/install.sh | sh`)

## Setup

Follow the [Server Setup](https://maxl94.github.io/yaai/server-setup/) guide to get the backend and frontend running locally. The short version:

```bash
git clone https://github.com/Maxl94/yaai.git
cd yaai
docker compose up db -d
uv sync
cd frontend && npm ci && cd ..
cp .env.example .env

# Backend (terminal 1)
uv run uvicorn yaai.server.main:app --reload --reload-dir yaai --host 0.0.0.0 --port 8000

# Frontend (terminal 2)
cd frontend && npm run dev
```

Open **http://localhost:3000** in your browser.

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
DATABASE_URL="postgresql+asyncpg://aimon:changeme@localhost:5431/aimonitoring" \
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
