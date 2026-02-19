# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build-only

# Stage 2: Python backend + static frontend
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached unless pyproject.toml or uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra server

# Copy source and install the project at build time
COPY README.md ./
COPY yaai/ yaai/
RUN uv sync --frozen --no-dev --extra server

COPY --from=frontend-build /app/frontend/dist yaai/server/static

# Run as non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD [".venv/bin/uvicorn", "yaai.server.main:app", "--host", "0.0.0.0", "--port", "8000"]
