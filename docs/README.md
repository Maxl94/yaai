# YAAI Monitoring — Documentation

## Overview

YAAI Monitoring (Yet Another AI Monitoring) is a self-hosted platform for automated ML model monitoring. It differentiates from existing tools by being **schema-driven** — you define your model's input/output schema once, and dashboards, drift detection, and alerting are generated automatically.

## Screenshots

### Models Overview
![Models](screenshots/models.jpeg)

### Model Versions
![Model Versions](screenshots/model_versions.jpeg)

### Version Dashboard
![Version Dashboard](screenshots/model_version_dashboard.jpeg)

### Schema Definition
![Schema](screenshots/model_version_schema.jpeg)

### Data Comparison
![Data Comparison](screenshots/model_version_data_compare.jpeg)

### Drift Overview
![Drift Overview](screenshots/model_version_drift.jpeg)

### Drift Dashboard
![Drift Dashboard](screenshots/drift_dashboard.jpeg)

### Scheduled Jobs
![Jobs](screenshots/model_version_jobs.jpeg)

### All Jobs Overview
![All Jobs](screenshots/all_jobs.jpeg)

## Documentation Index

### Architecture

- [Architecture Overview](architecture.md) — system design, tech stack, component layout

### Guides

- [Getting Started](getting-started.md) — quick start guide
- [Server Setup](server-setup.md) — local development setup
- [Deployment](deployment.md) — production deployment
- [Configuration](configuration.md) — environment variables and settings
- [Concepts](concepts.md) — models, versions, schemas, drift detection
- [Drift Guide](drift-guide.md) — how drift metrics work (PSI, KS, Chi-squared, JSD), handling non-tabular models

### Reference

- [API Reference](reference/api.md) — REST API (OpenAPI / Swagger)
- [SDK Reference](reference/sdk.md) — Python client library
