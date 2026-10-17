# LLM & Agent Monitoring (metadata)

YAAI does not need to understand text to monitor an LLM application. Everything that tends to change first when an LLM app degrades -- prompt size, token usage, latency, cost, model mix, error rate -- is a plain number or a short label. Send those as inference data and the regular [drift detection](drift-guide.md) and dashboards work unchanged.

This recipe is **Phase 1: metadata drift**. It needs no server changes and no extra dependencies, just the [Python SDK](reference/sdk.md) (or plain REST).

> [!IMPORTANT]
> **Send metadata only -- never raw prompts or completions.** YAAI has no data retention for inference data: whatever you send is stored until the model is deleted. Prompts and completions routinely contain personal or confidential data, so this recipe keeps them out of YAAI by design. Counts, lengths, durations and short labels are enough for drift detection. Monitoring the *content* of traces is a separate, privacy-gated topic (Phase 2) and not covered here.

## Why metadata drift is useful

| What changes | What you see in the metadata |
|---|---|
| A feature ships longer prompts (more context, RAG chunks) | `prompt_tokens`, `prompt_length_chars` shift up, `cost_usd` and `latency_ms` follow |
| Traffic gets routed to a different or fallback model | `llm_model` distribution shifts, latency and cost change |
| A provider has an incident or rate-limits you | `error` rate and `latency_ms` rise, `finish_reason` changes |
| A prompt change makes answers longer or truncated | `completion_tokens` shifts, `finish_reason="length"` increases |
| An agent starts looping or calling more tools | `tool_count` / `agent_steps`, `latency_ms`, `total_tokens` rise |
| Users use the app differently | `route` / `use_case` distribution shifts |

These shifts do not tell you *why* answers got worse, but they tell you *that* something changed and *when* -- usually before users complain.

## Recommended schema

Every field must be present in every record (`null` is accepted as a value). Only add optional fields to the schema if you can send them with each call.

### Inputs

| Field | Type | Meaning |
|---|---|---|
| `prompt_tokens` | numerical | Input tokens as reported by the provider |
| `prompt_length_chars` | numerical | Length of the prompt in characters (`len(prompt)`, the text itself is not sent) |
| `llm_model` | categorical | Model name, e.g. `gemini-2.5-flash` |
| `route` | categorical | Use case / endpoint / agent name, e.g. `chat`, `summarize` |
| `tool_count` | numerical | *Optional.* Number of tool calls in the request (or `agent_steps` for agents) |

### Outputs

| Field | Type | Meaning |
|---|---|---|
| `completion_tokens` | numerical | Output tokens as reported by the provider |
| `total_tokens` | numerical | `prompt_tokens + completion_tokens` |
| `latency_ms` | numerical | Wall-clock duration of the call |
| `cost_usd` | numerical | Estimated cost, see [Computing cost](#computing-cost) |
| `error` | categorical | `"true"` / `"false"` -- send a string, so both values show up as categories |
| `finish_reason` | categorical | `stop`, `length`, `tool_call`, ... (use `error` or `unknown` when there is none) |
| `user_feedback` | categorical | *Optional.* e.g. `up` / `down` / `none`, only if collected synchronously |

### Drift metric and alert threshold per field

Metric names are the ones accepted by `drift_metric` (`psi`, `ks_test`, `chi_squared`, `js_divergence`). Thresholds are set per field with `alert_threshold` and have the semantics described in the [drift guide](drift-guide.md): a field is flagged when its score is **greater than** the threshold.

| Field type | `drift_metric` | `alert_threshold` | Notes |
|---|---|---|---|
| Numerical (tokens, lengths, latency, cost, tool count) | `psi` | `0.2` (default) | 0.1--0.2 is "worth watching", above 0.2 is a significant shift |
| Categorical (`llm_model`, `route`, `finish_reason`) | `js_divergence` | `0.1` (default) | Score is the Jensen-Shannon distance (0--1) |
| Categorical, rare class (`error`) | `js_divergence` | `0.05` | A rise in the error rate from 2 % to 5 % scores only 0.070, below the default 0.1, so use a lower threshold for rare classes |

For reference, the Jensen-Shannon distance (base 2, as computed in `yaai/server/drift/js_divergence.py`) of the error rate against a 2 % baseline is 0.070 at 5 % errors (flagged with 0.05, not with 0.1), 0.149 at 10 % and 0.175 at 12 % (flagged with both).

Why not `ks_test` / `chi_squared` everywhere? Both report `1 - p_value` with a default threshold of `0.95`, so with thousands of calls per window they flag even tiny, harmless shifts. PSI and JS divergence measure the *size* of a shift, which is what you want to alert on. Use `chi_squared` / `ks_test` if you explicitly want a significance test.

```python
from yaai.schemas.model import SchemaFieldCreate

SchemaFieldCreate(
    direction="input",
    field_name="prompt_tokens",
    data_type="numerical",
    drift_metric="psi",
    alert_threshold=0.2,
)
SchemaFieldCreate(
    direction="output",
    field_name="error",
    data_type="categorical",
    drift_metric="js_divergence",
    alert_threshold=0.05,
)
```

The complete field list is `LLM_SCHEMA_FIELDS` in [`scripts/llm_monitoring_example.py`](https://github.com/Maxl94/yaai/blob/main/scripts/llm_monitoring_example.py).

> [!NOTE]
> The schema is locked after the first drift job has run. Tune thresholds with the field threshold endpoint or create a new version if you need to change fields.

## Recommended drift job

Creating a model version automatically creates one drift job. Adjust it with `update_job`:

```python
job = await client.get_version_job(model.id, version.id)
await client.update_job(
    job["id"],
    name="LLM metadata daily drift check",
    schedule="0 2 * * *",          # cron: daily at 02:00
    comparison_type="vs_reference",  # or "rolling_window"
    window_size="1d",               # compare the last day ...
    min_samples=200,                # ... extended automatically until at least 200 calls are in the window
    is_active=True,
)
```

Which comparison fits depends on what "normal" means for you:

- **`vs_reference`** (recommended to start): compare each day to a baseline you upload with `add_reference_data`, e.g. one representative week of production traffic. Catches slow drift that a rolling comparison would absorb.
- **`rolling_window`**: compare each day to the previous day. Needs no baseline, but only catches abrupt changes. A job supports one comparison type, not both.

Use `trigger_job` to run it on demand and `backfill_job` to compute historical runs.

## Computing cost

Providers report token counts, not prices. Keep a small, user-maintained price table and multiply:

```python
--8<-- "scripts/llm_reporter_example.py:imports"

--8<-- "scripts/llm_reporter_example.py:cost"
```

A model without a price entry gets `cost_usd = null` (accepted by the schema) and one warning in the log instead of an exception. The prices in the scripts are illustrative. When your provider changes prices, `cost_usd` will shift and drift detection will report it -- which is usually what you want to know, but keep it in mind when interpreting alerts.

## Wrapping an LLM call without slowing the app

Timing a call is cheap. Sending it must not sit on the request path: collect records in memory and flush them in batches with `add_inferences` (up to 10,000 records per call). The reporter below is the tested code from [`scripts/llm_reporter_example.py`](https://github.com/Maxl94/yaai/blob/main/scripts/llm_reporter_example.py) -- copy it into the same module as the cost helper above. It guarantees:

- **Telemetry never breaks the app.** Errors while sending, an unknown model in the price table or missing token counts are logged as warnings. An exception from your LLM call is re-raised unchanged.
- **Bounded memory.** When the queue is full (`max_queue`) new records are dropped and counted in a warning. Throughput is bounded by `max_queue` per `flush_seconds`, and a full batch wakes the worker early.
- **No silent data loss.** YAAI answers `201` even when it rejects records (e.g. a missing schema field); the reporter logs the `failed` count with the first server-side errors.
- **Bounded shutdown.** `stop()` flushes what is left and waits at most `stop_timeout` seconds (default 10), then gives up with a warning. Create the `YaaiClient` with a short `timeout` so an unreachable server cannot block the worker.

```python
--8<-- "scripts/llm_reporter_example.py:reporter"
```

Usage:

```python
async with YaaiClient(base_url, api_key=api_key, timeout=5.0) as client:
    reporter = MetadataReporter(client, version.id)
    reporter.start()
    try:
        with tracked_call(reporter, llm_model="gemini-2.5-flash", route="chat", prompt=prompt) as call:
            response = await llm.generate(prompt)
            call["prompt_tokens"] = response.usage.prompt_tokens
            call["completion_tokens"] = response.usage.completion_tokens
            call["finish_reason"] = response.finish_reason
    finally:
        await reporter.stop()  # on shutdown: flush what is left
```

Notes:

- Failed calls usually have no token usage; missing counts are reported as `0` tokens, and cancelled calls count as errors. If errors are frequent, this pulls the token distributions down -- that is a correct reflection of what was sent, but keep it in mind when reading the numbers.
- Records carry the current time by default. Pass `"timestamp"` (ISO 8601) in a record if you send them later than they happened.
- For multi-process deployments, each process runs its own reporter; batches are independent.

## Runnable example

[`scripts/llm_monitoring_example.py`](https://github.com/Maxl94/yaai/blob/main/scripts/llm_monitoring_example.py) uses only the SDK and the standard library. It creates (or reuses) the model, creates the version with the schema above, uploads a baseline as reference data, sends a deliberately shifted period (longer prompts, a slower model, more errors), configures the drift job and triggers a run.

```bash
export YAAI_API_KEY=yaam_...
python scripts/llm_monitoring_example.py --base-url http://localhost:8000/api/v1 --records 1000
```

| Option | Default | Description |
|--------|---------|-------------|
| `--base-url` | http://localhost:8000/api/v1 | YAAI API base URL |
| `--api-key` | env `YAAI_API_KEY` | Service account API key |
| `--records` | 1000 | Records per period (baseline and shifted), 1..50000 |
| `--model-name` | llm-app-metadata | Model name (reused if visible to the key; otherwise choose another name) |
| `--version` | v1 | Version label (reused if it exists) |
| `--seed` | 42 | Random seed for the synthetic data |

It never sends text. Re-running it replaces the reference data and appends more inferences to the same version. `--records` is limited to 1--50,000 because the baseline is uploaded in one request (server default `REFERENCE_DATA_MAX_RECORDS`). The script prints rejected record counts and, if the drift run fails, the error message.

**API key:** with authentication enabled, use an API key of a **service account** (or an owner), because creating a model requires one of those roles; models created by a service account are accessible to it (see [Server setup](server-setup.md#6-authentication)). With `AUTH_ENABLED=false` any value works. Without a key the SDK falls back to Google Application Default Credentials. If the model name already exists but is not visible to the key, the script stops with an actionable message -- pick another `--model-name` or grant the service account access.

## Mapping from OpenTelemetry GenAI semantic conventions

If your application is already instrumented with OpenTelemetry, the [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) carry the same information. A native OpenTelemetry integration is **not** part of YAAI today (it would add a dependency); it is a possible future option. Until then a small exporter or span processor in your own code can map spans to the schema above:

| OpenTelemetry attribute / span property | YAAI field |
|---|---|
| `gen_ai.usage.input_tokens` | `prompt_tokens` |
| `gen_ai.usage.output_tokens` | `completion_tokens` |
| input + output tokens | `total_tokens` |
| `gen_ai.response.model` (or `gen_ai.request.model`) | `llm_model` |
| span duration (`end_time - start_time`) | `latency_ms` |
| `gen_ai.response.finish_reasons` (first entry) | `finish_reason` |
| `error.type` present / span status `ERROR` | `error` |
| `gen_ai.operation.name`, `gen_ai.agent.name` or your own attribute | `route` |
| number of child spans with `gen_ai.operation.name = execute_tool` | `tool_count` |
| computed from tokens x price table | `cost_usd` |

Attribute names in the GenAI conventions are still evolving, so check the current spec before relying on them. Do not map attributes that contain message content (prompts, completions, tool arguments).
