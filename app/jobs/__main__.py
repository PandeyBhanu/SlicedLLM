"""Standalone worker: `python -m app.jobs` (set RUN_WORKER_IN_APP=false on the API process)."""

import asyncio

from app.core.logging import setup_logging
from app.db.session import get_session_factory
from app.jobs.worker import JobWorker


async def main() -> None:
    setup_logging()
    await JobWorker(get_session_factory()).run_forever()


if __name__ == "__main__":
    asyncio.run(main())
