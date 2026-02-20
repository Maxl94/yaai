# YAAI Monitoring

<p align="center">
  <img src="assets/banner-bordered.svg" alt="YAAI Monitoring" width="320">
</p>

**Yet Another AI Monitoring** -- because the existing ones didn't fit and building your own seemed like a good idea at the time.

---

Most ML monitoring tools make you configure dashboards by hand, wire up custom pipelines, and learn their specific way of thinking before you see any value. YAAI takes a different approach: tell it what your model's inputs and outputs look like, send data, and everything else -- dashboards, drift detection, scheduled checks, alerting -- happens automatically.

![Models Overview](screenshots/models.jpeg)

## The idea in 30 seconds

```
1. Define your model schema     "age is numerical, region is categorical, ..."
2. Send inference data           POST /api/v1/inferences  { inputs, outputs }
3. Dashboards appear             per-feature histograms and bar charts, auto-generated
4. Drift detection runs          scheduled jobs compare distributions over time
5. Alerts fire when things shift "PSI for 'age' jumped to 0.32 -- threshold is 0.2"
```

No pipeline integration. No YAML property mappings. No dashboard builder.
The schema is the config.

> [!TIP]
> **New here?** Start with the **[Getting Started](getting-started.md)** guide -- it takes you from zero to dashboards in five minutes.

## Documentation

<div class="grid cards" markdown>

- **[Getting Started](getting-started.md)** -- from zero to dashboards in five minutes
- **[Server Setup](server-setup.md)** -- local development with PostgreSQL, env vars, authentication
- **[Deployment](deployment.md)** -- Docker Compose, pip install, Google Cloud SQL
- **[Core Concepts](concepts.md)** -- models, versions, schemas, drift -- how the pieces fit
- **[Drift Detection Guide](drift-guide.md)** -- PSI, KS test, Chi-squared, JSD explained with visuals
- **[Architecture](architecture.md)** -- system design, tech stack, how the backend is structured
- **[REST API Reference](reference/api.md)** -- full OpenAPI spec, auto-generated from the server
- **[Python SDK Reference](reference/sdk.md)** -- async client docs, auto-generated from source

</div>

## When to use YAAI

- You want monitoring running in minutes, not days
- You prefer REST APIs over SDK-heavy integrations
- You don't want to build dashboards manually
- You need drift detection without becoming a statistician
- You value simplicity over feature completeness

## When NOT to use YAAI

- You need deep ML pipeline integration -- look at [Evidently](https://github.com/evidentlyai/evidently)
- You want custom drift algorithms beyond the standard four
- You need multi-tenant SaaS deployment
- You need battle-tested production stability -- this is young software
