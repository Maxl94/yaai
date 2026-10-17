"""Non-blocking reporter for LLM call metadata (SDK only, no extra dependencies).

The code between the ``--8<--`` markers is embedded in docs/llm-monitoring.md and covered by
tests/unit/llm_reporter_example_test.py. Copy it into your application and adapt it.

Privacy: only numbers and short labels are reported, never prompts or completions.
"""

from __future__ import annotations

# --8<-- [start:imports]
import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from yaai import YaaiClient

logger = logging.getLogger(__name__)
# --8<-- [end:imports]

# --8<-- [start:cost]
# USD per 1M tokens: (input, output) -- illustrative values, fill in your provider's current prices
PRICE_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}
_warned_unpriced_models: set[str] = set()


def estimate_cost_usd(llm_model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Return the estimated cost in USD, or None (sent as null) if the model has no price yet."""
    prices = PRICE_PER_1M_TOKENS.get(llm_model)
    if prices is None:
        if llm_model not in _warned_unpriced_models:
            _warned_unpriced_models.add(llm_model)
            logger.warning("No price for model %r, cost_usd is reported as null", llm_model)
        return None
    return (prompt_tokens * prices[0] + completion_tokens * prices[1]) / 1_000_000


# --8<-- [end:cost]


# --8<-- [start:reporter]
class MetadataReporter:
    """Batches LLM call metadata in memory and sends it to YAAI in the background.

    Telemetry problems (server down, rejected records, full queue) are logged as warnings and never raised
    into the application. Create the YaaiClient with a short ``timeout`` so an unreachable server cannot
    block the worker for long. Use it from a single event loop.
    """

    def __init__(
        self,
        client: YaaiClient,
        version_id: uuid.UUID,
        *,
        batch_size: int = 100,
        flush_seconds: float = 10.0,
        max_queue: int = 10_000,
        stop_timeout: float = 10.0,
    ):
        self._client = client
        self._version_id = version_id
        self._batch_size = batch_size
        self._flush_seconds = flush_seconds
        self._stop_timeout = stop_timeout
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_queue)
        self._wakeup = asyncio.Event()
        self._stopping = False
        self._dropped = 0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the background worker. Call from inside a running event loop."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Flush the remaining records and stop the worker, waiting at most ``stop_timeout`` seconds."""
        self._stopping = True
        self._wakeup.set()
        try:
            await asyncio.wait_for(self._shutdown(), self._stop_timeout)
        except TimeoutError:
            logger.warning(
                "Metadata flush timed out after %.1fs, dropping %d queued records",
                self._stop_timeout,
                self._queue.qsize(),
            )

    async def _shutdown(self) -> None:
        if self._task:
            await self._task
        await self._flush()

    def record(self, record: dict) -> None:
        """Queue one record. When the queue is full the new record is dropped. Never raises."""
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            self._dropped += 1
            return
        if self._queue.qsize() >= self._batch_size:
            self._wakeup.set()

    async def _run(self) -> None:
        while not self._stopping:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), self._flush_seconds)
            self._wakeup.clear()
            await self._flush()

    async def _flush(self) -> None:
        if self._dropped:
            logger.warning("Metadata queue was full, dropped %d records", self._dropped)
            self._dropped = 0
        while not self._queue.empty():
            batch = [self._queue.get_nowait() for _ in range(min(self._batch_size, self._queue.qsize()))]
            if not await self._send(batch):
                return  # server unreachable or failing: retry with new records on the next interval

    async def _send(self, batch: list[dict]) -> bool:
        try:
            result = await self._client.add_inferences(self._version_id, batch)
        except Exception:
            logger.warning("Failed to send %d metadata records, dropping them", len(batch), exc_info=True)
            return False
        if result.failed:
            # YAAI answers 201 even if it rejects records, e.g. because a schema field is missing
            logger.warning("YAAI rejected %d of %d metadata records: %s", result.failed, len(batch), result.errors[:3])
        return True


def build_record(
    call: dict, *, llm_model: str, route: str, prompt_length_chars: int, tool_count: int, error: bool, start: float
) -> dict:
    """Build one inference record from the values collected in ``tracked_call``."""
    prompt_tokens = call.get("prompt_tokens") or 0
    completion_tokens = call.get("completion_tokens") or 0
    return {
        "inputs": {
            "prompt_tokens": prompt_tokens,
            "prompt_length_chars": prompt_length_chars,
            "llm_model": llm_model,
            "route": route,
            "tool_count": tool_count,
        },
        "outputs": {
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "cost_usd": estimate_cost_usd(llm_model, prompt_tokens, completion_tokens),
            "error": "true" if error else "false",
            "finish_reason": call.get("finish_reason") or "unknown",
        },
    }


@contextmanager
def tracked_call(
    reporter: MetadataReporter, *, llm_model: str, route: str, prompt: str, tool_count: int = 0
) -> Iterator[dict]:
    """Time an LLM call and report its metadata. Only the prompt *length* is kept, never the text.

    Exceptions from the wrapped call (including cancellation) are re-raised unchanged and counted as errors.
    Failures while building the record are logged and never raised.
    """
    call: dict = {"prompt_tokens": 0, "completion_tokens": 0, "finish_reason": "unknown"}
    error = False
    start = time.perf_counter()
    try:
        yield call  # fill in call[...] from the provider's usage metadata
    except BaseException:
        error = True
        call["finish_reason"] = "error"
        raise
    finally:
        try:
            reporter.record(
                build_record(
                    call,
                    llm_model=llm_model,
                    route=route,
                    prompt_length_chars=len(prompt),
                    tool_count=tool_count,
                    error=error,
                    start=start,
                )
            )
        except Exception:
            logger.warning("Could not record LLM call metadata", exc_info=True)


# --8<-- [end:reporter]
