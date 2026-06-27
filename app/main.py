"""Cerebro v2 entry point."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot_v2 import build_app
from app.cron import register_jobs
from lib.config import get_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    logger = logging.getLogger("cerebro")

    settings = get_settings()

    from lib.db import init_db
    init_db(settings.db_path)

    app = build_app(settings)
    logger.info(
        "cerebro starting (user=%s, model=%s)",
        settings.telegram_allowed_user_id,
        settings.llm_model,
    )

    scheduler = AsyncIOScheduler()
    register_jobs(scheduler, settings, app.bot)

    async def on_startup(app):
        scheduler.start()

    async def on_shutdown(app):
        scheduler.shutdown(wait=False)

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    app.run_polling()


if __name__ == "__main__":
    main()
