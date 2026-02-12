# Contributing

## Setup

Prerequisites: Python 3.12+, Node.js 20+, Docker, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/mballuff/ai-monitoring.git
cd ai-monitoring
docker compose up db -d
uv sync
cd frontend && npm ci && cd ..
```

Run the backend with `uv run uvicorn backend.app.main:app --reload --reload-dir backend` and the frontend with `cd frontend && npm run dev`.

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

1. Fork the repo and create a feature branch
2. Make your changes with tests
3. Ensure CI passes (`uv run pytest`, `uv run ruff check .`, `cd frontend && npm run type-check`)
4. Open a PR focused on a single change

## Bugs & Feature Requests

Open an issue. For bugs, include steps to reproduce and environment details.

## License

By contributing, you agree that your contributions will be licensed under the [Elastic License 2.0](LICENSE).
