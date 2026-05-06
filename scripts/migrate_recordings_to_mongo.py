"""
One-time migration: read recordings/*.json from disk and insert into MongoDB.

Idempotent — duplicate call_ids are silently skipped (write_call returns False).

Usage:
    python -m scripts.migrate_recordings_to_mongo
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    from agent.mongo_writer import MongoWriter
    from config import settings

    writer = MongoWriter.instance()
    await writer.connect()

    if not writer._enabled:
        logger.error(
            "MongoWriter is disabled — set MONGODB_URI in .env and retry."
        )
        sys.exit(1)

    recordings_dir = Path(settings.recording_dir).resolve()
    files = sorted(recordings_dir.glob("*.json"))

    if not files:
        logger.info("No recordings found in %s", recordings_dir)
        return

    inserted = skipped = errors = 0
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            ok = await writer.write_call(recording=doc, phone=None, candidate_name=None)
            if ok:
                inserted += 1
                logger.info("Inserted %s", path.name)
            else:
                skipped += 1
                logger.debug("Skipped (duplicate) %s", path.name)
        except Exception as exc:
            errors += 1
            logger.error("Failed %s: %s", path.name, exc)

    await writer.close()
    logger.info(
        "Migration complete: %d inserted, %d skipped, %d errors (total %d files)",
        inserted, skipped, errors, len(files),
    )


if __name__ == "__main__":
    asyncio.run(main())
