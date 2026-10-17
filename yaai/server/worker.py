"""Headless worker — runs the scheduled drift jobs without serving HTTP.

Run it with the same image as the API, which then runs with SCHEDULER_ENABLED=false
and can scale horizontally. Run a single worker instance; the advisory lock only
prevents overlapping runs, not repeated ones.

Usage:
    python -m yaai.server.worker
"""

import asyncio
import logging
import os
import signal
import sys

from yaai.server import startup
from yaai.server.migrate import SchemaNotUpToDateError

# The API registers all ORM models via its routers; the worker must do it itself so relationships resolve
from yaai.server.models import auth, inference, job, model, project  # noqa: F401

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run(stop: asyncio.Event) -> None:
    """Start the scheduler and block until ``stop`` is set, then shut down cleanly."""
    cloud_sql = await startup.init_database()
    try:
        await startup.start_scheduler()
        logger.info("Worker started.")
        await stop.wait()
    finally:
        await startup.shutdown(cloud_sql)
    logger.info("Worker stopped.")


async def _run_until_signalled() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await run(stop)


def main() -> None:
    """Run the worker until SIGTERM/SIGINT; exit non-zero if startup fails."""
    try:
        asyncio.run(_run_until_signalled())
    except SchemaNotUpToDateError:
        sys.exit(1)  # already logged by init_database
    except Exception:
        logger.exception("Worker failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
