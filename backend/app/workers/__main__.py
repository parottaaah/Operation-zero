"""Worker entry point: ``python -m app.workers.runner``."""

import asyncio
import logging

from app.core.config import settings
from app.workers.runner import run_forever

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

if __name__ == "__main__":
    asyncio.run(run_forever())
