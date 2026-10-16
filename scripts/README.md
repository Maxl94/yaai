# Demo Data Scripts

Scripts for generating demo data in the AI Monitoring platform.

## Prerequisites

Make sure the backend is running:
```bash
docker compose up -d
```

The scripts use `httpx` which is already included in the project's virtual environment.

## generate_demo_data.py

Generate demo data for testing and demonstration purposes.

### Modes

| Mode | Description |
|------|-------------|
| `full` | Creates model, version, reference data, and weeks of inference data with gradual drift |

### Usage

```bash
# Basic usage with defaults (1 numerical, 1 categorical, 1 prediction)
python scripts/generate_demo_data.py --mode full

# Custom feature counts
python scripts/generate_demo_data.py --mode full --numerical 3 --categorical 2 --predictions 1

# Custom model name and version
python scripts/generate_demo_data.py --mode full --model-name "fraud-detector" --version "v1.0"

# Full customization
python scripts/generate_demo_data.py --mode full \
    --numerical 5 \
    --categorical 3 \
    --predictions 2 \
    --model-name "my-model" \
    --version "v2.0" \
    --weeks 12 \
    --records-per-day 200
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--mode` | required | Generation mode (`full`) |
| `--numerical` | 1 | Number of numerical input features |
| `--categorical` | 1 | Number of categorical input features |
| `--predictions` | 1 | Number of prediction outputs |
| `--model-name` | auto | Model name (auto-generated if not provided) |
| `--version` | auto | Version string (auto-generated if not provided) |
| `--weeks` | 8 | Number of weeks of data to generate |
| `--records-per-day` | 100 | Number of inference records per day |
| `--api-url` | http://localhost:8000/api/v1 | Backend API URL |

### What `full` mode creates

1. **Model** - A new model with auto-generated or specified name
2. **Version** - A model version with the generated schema
3. **Reference Data** - Week 1 data with no drift (baseline)
4. **Production Data** - Weeks 2-8 with gradually increasing drift
5. **Drift Job** - A daily drift detection job

### Example Output

```
============================================================
Generating Full Demo Data
============================================================
Model: fraud-detector
Version: v1.2.5
Numerical features: 2
Categorical features: 2
Predictions: 1
Weeks of data: 8
Records per day: 100
============================================================

Schema fields: ['amount', 'score', 'category', 'region', 'probability']

[1/5] Creating model...
  ✓ Model created: abc123...

[2/5] Creating version...
  ✓ Version created: def456...

[3/5] Generating reference data (week 1)...
  ✓ Created 700 reference records

[4/5] Generating production data with drift...
  ✓ Week 2: 700 records (drift factor: 0.15)
  ✓ Week 3: 700 records (drift factor: 0.30)
  ...

[5/5] Creating drift detection job...
  ✓ Job created: ghi789...

============================================================
Demo data generation complete!
============================================================
```

## llm_monitoring_example.py

Runnable example for [LLM & Agent Monitoring](../docs/llm-monitoring.md). Uses only the SDK and the standard library and sends **metadata only** (token counts, latency, cost, model name, error flag) -- never prompts or completions.

It creates (or reuses) a model, creates a version with the recommended LLM metadata schema, uploads a baseline as reference data, sends a deliberately shifted period (longer prompts, a slower model, more errors), configures the drift job and triggers a run.

```bash
YAAI_API_KEY=yaam_... python scripts/llm_monitoring_example.py --base-url http://localhost:8000/api/v1 --records 1000
```

| Option | Default | Description |
|--------|---------|-------------|
| `--base-url` | http://localhost:8000/api/v1 | YAAI API base URL |
| `--api-key` | env `YAAI_API_KEY` | API key (without one the SDK uses Google ADC) |
| `--records` | 1000 | Records per period (baseline and shifted) |
| `--model-name` | llm-app-metadata | Model name (reused if it exists) |
| `--version` | v1 | Version label (reused if it exists) |
| `--seed` | 42 | Random seed for the synthetic data |

## Future Modes

Additional modes planned for future implementation:

- `incremental` - Add more data to existing model/version
- `drift-spike` - Generate data with sudden drift spike
- `seasonal` - Generate data with seasonal patterns
- `anomaly` - Generate data with anomalous records
