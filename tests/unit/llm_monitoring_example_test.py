"""Unit tests for scripts/llm_monitoring_example.py."""

import importlib.util
import random
import statistics
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from yaai.schemas.inference import InferenceBatchCreate
from yaai.schemas.model import DataType, FieldDirection, SchemaFieldCreate
from yaai.server.drift.registry import METRIC_REGISTRY
from yaai.server.services.schema_helpers import validate_record

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "llm_monitoring_example.py"
_spec = importlib.util.spec_from_file_location("llm_monitoring_example", _SCRIPT)
example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(example)

_NUMERICAL_METRICS = {"psi", "ks_test"}
_CATEGORICAL_METRICS = {"chi_squared", "js_divergence"}


def _rng(seed: int) -> random.Random:
    return random.Random(seed)  # noqa: S311 - synthetic test data


def _values(records: list[dict], direction: str, field: str) -> list:
    return [r[direction][field] for r in records]


class TestSchemaFields:
    def test_all_fields_are_valid_schema_field_creates(self):
        for field in example.LLM_SCHEMA_FIELDS:
            assert isinstance(field, SchemaFieldCreate)
            # Round-trip through validation to be sure the definition is accepted by the API schema
            SchemaFieldCreate.model_validate(field.model_dump())

    def test_field_names_are_unique(self):
        names = [f.field_name for f in example.LLM_SCHEMA_FIELDS]
        assert len(names) == len(set(names))

    def test_metrics_exist_and_match_data_type(self):
        for field in example.LLM_SCHEMA_FIELDS:
            assert field.drift_metric in METRIC_REGISTRY
            allowed = _NUMERICAL_METRICS if field.data_type == DataType.NUMERICAL else _CATEGORICAL_METRICS
            assert field.drift_metric in allowed, field.field_name
            assert field.alert_threshold is not None
            assert field.alert_threshold > 0

    def test_schema_has_no_free_text_field(self):
        categorical = [f.field_name for f in example.LLM_SCHEMA_FIELDS if f.data_type == DataType.CATEGORICAL]
        assert set(categorical) == {"llm_model", "route", "error", "finish_reason"}
        assert not {"prompt", "completion", "response", "text", "content"} & {
            f.field_name for f in example.LLM_SCHEMA_FIELDS
        }

    def test_job_settings_use_valid_values(self):
        assert example.JOB_SETTINGS["comparison_type"] in {"vs_reference", "rolling_window"}
        assert len(str(example.JOB_SETTINGS["schedule"]).split()) == 5


class TestEstimateCost:
    def test_uses_price_table(self):
        # flash: 0.30 in / 2.50 out per 1M tokens
        assert example.estimate_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000) == pytest.approx(2.80)

    def test_zero_tokens_cost_nothing(self):
        assert example.estimate_cost_usd("gemini-2.5-pro", 0, 0) == 0.0

    def test_unknown_model_raises(self):
        with pytest.raises(KeyError):
            example.estimate_cost_usd("unknown-model", 10, 10)


class TestGenerateCallMetadata:
    def test_count_and_structure(self):
        records = example.generate_call_metadata(50, drifted=False, rng=_rng(1))
        assert len(records) == 50
        for record in records:
            assert set(record) == {"inputs", "outputs"}

    def test_zero_records(self):
        assert example.generate_call_metadata(0, drifted=False, rng=_rng(1)) == []

    def test_every_schema_field_is_present_with_correct_type(self):
        records = example.generate_call_metadata(100, drifted=True, rng=_rng(1))
        for record in records:
            for field in example.LLM_SCHEMA_FIELDS:
                direction = "inputs" if field.direction == FieldDirection.INPUT else "outputs"
                value = record[direction][field.field_name]
                if field.data_type == DataType.NUMERICAL:
                    assert isinstance(value, (int, float)) and not isinstance(value, bool)
                else:
                    assert isinstance(value, str)

    def test_records_validate_against_schema(self):
        records = example.generate_call_metadata(100, drifted=True, rng=_rng(1))
        for record in records:
            assert validate_record(example.LLM_SCHEMA_FIELDS, record["inputs"], record["outputs"]).valid

    def test_only_schema_fields_are_sent_and_no_raw_text(self):
        records = example.generate_call_metadata(100, drifted=True, rng=_rng(1))
        expected = {f.field_name for f in example.LLM_SCHEMA_FIELDS}
        for record in records:
            sent = set(record["inputs"]) | set(record["outputs"])
            assert sent == expected
            # Short labels only: any string value must be a known category, not free text
            labels = {v for v in [*record["inputs"].values(), *record["outputs"].values()] if isinstance(v, str)}
            assert all(len(label) <= 30 and " " not in label for label in labels)

    def test_error_flag_is_string_boolean(self):
        records = example.generate_call_metadata(200, drifted=True, rng=_rng(1))
        assert set(_values(records, "outputs", "error")) <= {"true", "false"}

    def test_total_tokens_and_cost_are_consistent(self):
        records = example.generate_call_metadata(50, drifted=False, rng=_rng(1))
        for r in records:
            assert r["outputs"]["total_tokens"] == r["inputs"]["prompt_tokens"] + r["outputs"]["completion_tokens"]
            expected = example.estimate_cost_usd(
                r["inputs"]["llm_model"], r["inputs"]["prompt_tokens"], r["outputs"]["completion_tokens"]
            )
            assert r["outputs"]["cost_usd"] == expected

    def test_same_seed_is_reproducible(self):
        a = example.generate_call_metadata(20, drifted=False, rng=_rng(7))
        b = example.generate_call_metadata(20, drifted=False, rng=_rng(7))
        assert a == b

    def test_drifted_period_is_shifted(self):
        rng = _rng(3)
        base = example.generate_call_metadata(1000, drifted=False, rng=rng)
        drifted = example.generate_call_metadata(1000, drifted=True, rng=rng)

        assert statistics.mean(_values(drifted, "inputs", "prompt_tokens")) > 1.5 * statistics.mean(
            _values(base, "inputs", "prompt_tokens")
        )
        assert statistics.mean(_values(drifted, "outputs", "latency_ms")) > statistics.mean(
            _values(base, "outputs", "latency_ms")
        )
        assert statistics.mean(_values(drifted, "outputs", "cost_usd")) > statistics.mean(
            _values(base, "outputs", "cost_usd")
        )
        assert "gemini-2.5-pro" not in _values(base, "inputs", "llm_model")
        assert "gemini-2.5-pro" in _values(drifted, "inputs", "llm_model")
        assert _values(drifted, "outputs", "error").count("true") > _values(base, "outputs", "error").count("true")

    def test_without_window_end_no_timestamps(self):
        records = example.generate_call_metadata(5, drifted=False, rng=_rng(1))
        assert all("timestamp" not in r for r in records)

    def test_timestamps_fall_inside_window(self):
        end = datetime(2026, 1, 2, tzinfo=UTC)
        records = example.generate_call_metadata(
            10, drifted=True, rng=_rng(1), window_end=end, window=timedelta(hours=24)
        )
        stamps = [datetime.fromisoformat(r["timestamp"]) for r in records]
        assert all(end - timedelta(hours=24) <= s <= end for s in stamps)
        assert stamps == sorted(stamps)

    def test_records_are_accepted_by_batch_schema(self):
        records = example.generate_call_metadata(10, drifted=True, rng=_rng(1), window_end=datetime.now(UTC))
        InferenceBatchCreate(model_version_id=uuid.uuid4(), records=records)


def _mock_client(existing_models: list | None = None) -> MagicMock:
    model = MagicMock(id=uuid.uuid4())
    model.name = "llm-app-metadata"
    version = MagicMock(id=uuid.uuid4())
    client = MagicMock()
    client.list_models = AsyncMock(return_value=existing_models or [])
    client.create_model = AsyncMock(return_value=model)
    client.get_or_create_version = AsyncMock(return_value=version)
    client.add_reference_data = AsyncMock(return_value=MagicMock(ingested=25))
    client.add_inferences = AsyncMock(return_value=MagicMock(ingested=25, failed=0, errors=[]))
    client.get_version_job = AsyncMock(return_value={"id": str(uuid.uuid4()), "name": "job"})
    client.update_job = AsyncMock(return_value={"id": "j", "name": "job"})
    client.trigger_job = AsyncMock(return_value={"status": "completed"})
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestOrchestration:
    async def test_get_or_create_model_reuses_existing(self):
        existing = MagicMock()
        existing.name = "llm-app-metadata"
        client = _mock_client([existing])

        result = await example.get_or_create_model(client, "llm-app-metadata")

        assert result is existing
        client.create_model.assert_not_called()

    async def test_get_or_create_model_creates_when_missing(self):
        client = _mock_client()

        await example.get_or_create_model(client, "llm-app-metadata")

        client.create_model.assert_awaited_once()

    async def test_send_in_batches_splits_records(self):
        client = _mock_client()
        client.add_inferences = AsyncMock(
            side_effect=lambda _id, recs: MagicMock(ingested=len(recs), failed=0, errors=[])
        )
        records = [{"inputs": {}, "outputs": {}}] * (example.BATCH_SIZE + 5)

        ingested, failed = await example.send_in_batches(client, uuid.uuid4(), records)

        assert (ingested, failed) == (len(records), 0)
        assert client.add_inferences.await_count == 2

    async def test_send_in_batches_reports_rejected_records(self, capsys):
        client = _mock_client()
        client.add_inferences = AsyncMock(
            return_value=MagicMock(ingested=0, failed=2, errors=["Record 0: missing field 'latency_ms'"])
        )

        ingested, failed = await example.send_in_batches(client, uuid.uuid4(), [{"inputs": {}, "outputs": {}}] * 2)

        assert (ingested, failed) == (0, 2)
        out = capsys.readouterr().out
        assert "2 records rejected" in out
        assert "missing field 'latency_ms'" in out

    async def test_get_or_create_model_conflict_gives_actionable_error(self):
        client = _mock_client()
        response = httpx.Response(409, request=httpx.Request("POST", "http://x/models"))
        client.create_model = AsyncMock(
            side_effect=httpx.HTTPStatusError("409", request=response.request, response=response)
        )

        with pytest.raises(example.ExampleError, match="--model-name"):
            await example.get_or_create_model(client, "taken")

    async def test_get_or_create_model_reraises_other_http_errors(self):
        client = _mock_client()
        response = httpx.Response(500, request=httpx.Request("POST", "http://x/models"))
        client.create_model = AsyncMock(
            side_effect=httpx.HTTPStatusError("500", request=response.request, response=response)
        )

        with pytest.raises(httpx.HTTPStatusError):
            await example.get_or_create_model(client, "name")

    async def test_run_prints_error_message_of_failed_drift_run(self, monkeypatch, capsys):
        client = _mock_client()
        client.trigger_job = AsyncMock(
            return_value={"status": "failed", "error_message": "No reference data available"}
        )
        monkeypatch.setattr(example, "YaaiClient", lambda *a, **k: client)

        await example.run(example.parse_args(["--records", "5", "--api-key", "k"]))

        assert "No reference data available" in capsys.readouterr().out

    async def test_configure_job_without_job_returns_none(self):
        client = _mock_client()
        client.get_version_job = AsyncMock(return_value=None)

        assert await example.configure_job(client, uuid.uuid4(), uuid.uuid4()) is None
        client.update_job.assert_not_called()

    async def test_configure_job_applies_settings(self):
        client = _mock_client()

        await example.configure_job(client, uuid.uuid4(), uuid.uuid4())

        _, kwargs = client.update_job.call_args
        assert kwargs == example.JOB_SETTINGS

    async def test_run_sends_reference_then_inferences_then_triggers_job(self, monkeypatch):
        client = _mock_client()
        monkeypatch.setattr(example, "YaaiClient", lambda *a, **k: client)
        args = example.parse_args(["--records", "25", "--api-key", "k"])

        await example.run(args)

        schema = client.get_or_create_version.call_args.kwargs["schema_fields"]
        assert schema == example.LLM_SCHEMA_FIELDS
        assert len(client.add_reference_data.call_args.args[2]) == 25
        assert len(client.add_inferences.call_args.args[1]) == 25
        client.trigger_job.assert_awaited_once()


class TestParseArgs:
    def test_defaults(self, monkeypatch):
        args = example.parse_args([])
        assert args.base_url == example.DEFAULT_BASE_URL
        assert args.records == 1000

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("YAAI_API_KEY", "from-env")
        # Default is evaluated at parse time, so it picks up the patched env
        assert example.parse_args([]).api_key == "from-env"

    def test_cli_api_key_overrides_env(self, monkeypatch):
        monkeypatch.setenv("YAAI_API_KEY", "from-env")
        assert example.parse_args(["--api-key", "cli"]).api_key == "cli"

    @pytest.mark.parametrize("value", ["0", "-5", "50001", "abc"])
    def test_records_must_be_within_bounds(self, value):
        with pytest.raises(SystemExit):
            example.parse_args(["--records", value])

    def test_records_upper_bound_is_accepted(self):
        assert example.parse_args(["--records", str(example.MAX_RECORDS)]).records == example.MAX_RECORDS
