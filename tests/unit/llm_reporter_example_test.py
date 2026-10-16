"""Unit tests for scripts/llm_reporter_example.py (the reporter embedded in docs/llm-monitoring.md)."""

import asyncio
import importlib.util
import logging
import re
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "llm_reporter_example.py"
_spec = importlib.util.spec_from_file_location("llm_reporter_example", _SCRIPT)
reporter_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reporter_module)

MetadataReporter = reporter_module.MetadataReporter
tracked_call = reporter_module.tracked_call
LOGGER_NAME = reporter_module.logger.name


def _client(add_inferences: AsyncMock | None = None) -> MagicMock:
    client = MagicMock()
    client.add_inferences = add_inferences or AsyncMock(return_value=MagicMock(ingested=0, failed=0, errors=[]))
    return client


def _reporter(client: MagicMock, **kwargs) -> MetadataReporter:
    return MetadataReporter(client, uuid.uuid4(), **kwargs)


def _sent_records(client: MagicMock) -> list[dict]:
    return [r for call in client.add_inferences.call_args_list for r in call.args[1]]


@pytest.fixture(autouse=True)
def _reset_price_warnings():
    reporter_module._warned_unpriced_models.clear()


class TestEstimateCost:
    def test_known_model(self):
        assert reporter_module.estimate_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000) == pytest.approx(2.80)

    def test_unknown_model_returns_none_and_warns_once(self, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert reporter_module.estimate_cost_usd("mystery", 1, 1) is None
            assert reporter_module.estimate_cost_usd("mystery", 1, 1) is None
        assert [r.getMessage() for r in caplog.records].count(
            "No price for model 'mystery', cost_usd is reported as null"
        ) == 1


class TestReporterFlush:
    async def test_stop_flushes_remaining_records(self):
        client = _client()
        reporter = _reporter(client, flush_seconds=60.0)
        reporter.start()
        for i in range(5):
            reporter.record({"n": i})

        await reporter.stop()

        assert _sent_records(client) == [{"n": i} for i in range(5)]

    async def test_stop_without_start_flushes(self):
        client = _client()
        reporter = _reporter(client)
        reporter.record({"n": 1})

        await reporter.stop()

        assert _sent_records(client) == [{"n": 1}]

    async def test_stop_waits_for_in_flight_flush(self):
        async def slow(_version_id, records):
            await asyncio.sleep(0.2)
            return MagicMock(ingested=len(records), failed=0, errors=[])

        client = _client(AsyncMock(side_effect=slow))
        reporter = _reporter(client, batch_size=2, flush_seconds=60.0)
        reporter.start()
        reporter.record({"n": 1})
        reporter.record({"n": 2})  # full batch wakes the worker, which starts a slow request
        await asyncio.sleep(0.05)
        reporter.record({"n": 3})

        await reporter.stop()

        assert _sent_records(client) == [{"n": 1}, {"n": 2}, {"n": 3}]

    async def test_stop_times_out_when_server_hangs(self, caplog):
        async def hang(_version_id, _records):
            await asyncio.sleep(60)

        client = _client(AsyncMock(side_effect=hang))
        reporter = _reporter(client, flush_seconds=60.0, stop_timeout=0.1)
        reporter.start()
        reporter.record({"n": 1})

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            await asyncio.wait_for(reporter.stop(), timeout=5)

        assert "timed out" in caplog.text
        assert reporter._task.done()

    async def test_send_error_is_logged_not_raised(self, caplog):
        client = _client(AsyncMock(side_effect=RuntimeError("down")))
        reporter = _reporter(client)
        reporter.record({"n": 1})

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            await reporter.stop()

        assert "Failed to send 1 metadata records" in caplog.text

    async def test_drain_aborts_after_first_failed_batch(self):
        client = _client(AsyncMock(side_effect=RuntimeError("down")))
        reporter = _reporter(client, batch_size=1)
        for i in range(5):
            reporter.record({"n": i})

        await reporter.stop()

        assert client.add_inferences.await_count == 1

    async def test_rejected_records_are_logged_with_server_errors(self, caplog):
        result = MagicMock(ingested=0, failed=1, errors=["Record 0: missing field 'latency_ms'"])
        reporter = _reporter(_client(AsyncMock(return_value=result)))
        reporter.record({"n": 1})

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            await reporter.stop()

        assert "rejected 1 of 1" in caplog.text
        assert "missing field 'latency_ms'" in caplog.text

    async def test_full_queue_drops_new_records_and_warns_on_flush(self, caplog):
        client = _client()
        reporter = _reporter(client, max_queue=2)
        for i in range(4):
            reporter.record({"n": i})  # must not raise

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            await reporter.stop()

        assert _sent_records(client) == [{"n": 0}, {"n": 1}]
        assert "dropped 2 records" in caplog.text


class TestTrackedCall:
    async def test_records_metadata_without_prompt_text(self):
        reporter = _reporter(_client())

        with tracked_call(reporter, llm_model="gemini-2.5-flash", route="chat", prompt="secret prompt") as call:
            call["prompt_tokens"] = 1000
            call["completion_tokens"] = 500
            call["finish_reason"] = "stop"

        record = reporter._queue.get_nowait()
        assert record["inputs"] == {
            "prompt_tokens": 1000,
            "prompt_length_chars": len("secret prompt"),
            "llm_model": "gemini-2.5-flash",
            "route": "chat",
            "tool_count": 0,
        }
        assert record["outputs"]["total_tokens"] == 1500
        assert record["outputs"]["cost_usd"] == pytest.approx((1000 * 0.30 + 500 * 2.50) / 1_000_000)
        assert record["outputs"]["error"] == "false"
        assert record["outputs"]["finish_reason"] == "stop"
        assert "secret prompt" not in str(record)

    async def test_original_exception_is_reraised_and_counted_as_error(self):
        reporter = _reporter(_client())
        original = ValueError("provider failed")

        with (
            pytest.raises(ValueError) as exc_info,
            tracked_call(reporter, llm_model="gemini-2.5-flash", route="r", prompt=""),
        ):
            raise original

        assert exc_info.value is original
        outputs = reporter._queue.get_nowait()["outputs"]
        assert outputs["error"] == "true"
        assert outputs["finish_reason"] == "error"

    async def test_unknown_model_does_not_raise(self):
        reporter = _reporter(_client())

        with tracked_call(reporter, llm_model="unpriced", route="r", prompt="p"):
            pass

        assert reporter._queue.get_nowait()["outputs"]["cost_usd"] is None

    async def test_unknown_model_does_not_replace_original_exception(self):
        reporter = _reporter(_client())

        with (
            pytest.raises(ValueError, match="boom"),
            tracked_call(reporter, llm_model="unpriced", route="r", prompt="p"),
        ):
            raise ValueError("boom")

    async def test_none_token_counts_are_treated_as_zero(self):
        reporter = _reporter(_client())

        with tracked_call(reporter, llm_model="gemini-2.5-flash", route="r", prompt="p") as call:
            call["prompt_tokens"] = None
            call["completion_tokens"] = None

        record = reporter._queue.get_nowait()
        assert record["inputs"]["prompt_tokens"] == 0
        assert record["outputs"]["total_tokens"] == 0
        assert record["outputs"]["cost_usd"] == 0.0

    async def test_cancellation_is_reraised_and_counted_as_error(self):
        reporter = _reporter(_client())

        with (
            pytest.raises(asyncio.CancelledError),
            tracked_call(reporter, llm_model="gemini-2.5-flash", route="r", prompt=""),
        ):
            raise asyncio.CancelledError

        assert reporter._queue.get_nowait()["outputs"]["error"] == "true"

    async def test_record_failure_is_logged_not_raised(self, caplog):
        reporter = MagicMock()
        reporter.record.side_effect = RuntimeError("boom")

        with (
            caplog.at_level(logging.WARNING, logger=LOGGER_NAME),
            tracked_call(reporter, llm_model="m", route="r", prompt="p"),
        ):
            pass

        assert "Could not record LLM call metadata" in caplog.text


class TestDocSnippets:
    def test_doc_embeds_tested_script_sections(self):
        doc = (_ROOT / "docs" / "llm-monitoring.md").read_text()
        script = _SCRIPT.read_text()
        embedded = re.findall(r'--8<-- "scripts/llm_reporter_example\.py:(\w+)"', doc)

        assert set(embedded) == {"imports", "cost", "reporter"}
        for section in embedded:
            assert f"# --8<-- [start:{section}]" in script
            assert f"# --8<-- [end:{section}]" in script
