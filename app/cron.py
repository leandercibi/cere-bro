from __future__ import annotations

import logging
import subprocess

from app.tools.errors import ToolError
from app.tools.tasks import query_tasks
from app.tools.workout import query_workouts, sync_workouts
from lib.config import Settings

logger = logging.getLogger(__name__)


async def job_hevy_sync(settings: Settings) -> None:
    """Nightly: pull new workouts from Hevy."""
    result = await sync_workouts(user_id=settings.telegram_allowed_user_id, settings=settings)
    logger.info("Hevy sync: %s", result)


async def job_morning_tasks(settings: Settings, bot) -> None:
    """Morning: push due/overdue tasks to Telegram."""
    try:
        result = await query_tasks("today", user_id=settings.telegram_allowed_user_id, settings=settings)
        tasks = result.get("tasks", [])
        if not tasks:
            return
        lines = [f"• {t['description']}" + (f" (due {t['due_at'][:10]})" if t.get("due_at") else "") for t in tasks]
        text = "📋 Tasks for today:\n" + "\n".join(lines)
        await bot.send_message(chat_id=settings.telegram_allowed_user_id, text=text)
    except ToolError:
        pass


async def job_journal_prompt(settings: Settings, bot) -> None:
    """Evening: prompt user to journal."""
    await bot.send_message(
        chat_id=settings.telegram_allowed_user_id,
        text="📓 How was your day? (reply to log a journal entry)",
    )


async def job_workout_check(settings: Settings, bot) -> None:
    """Evening: remind user if no workout logged today."""
    try:
        result = await query_workouts("today", user_id=settings.telegram_allowed_user_id, settings=settings)
        if result.get("workouts"):
            return  # already worked out — skip
    except ToolError:
        pass
    await bot.send_message(
        chat_id=settings.telegram_allowed_user_id,
        text="💪 No workout logged today. Did you train?",
    )


async def job_obsidian_git_commit(settings: Settings) -> None:
    """Late night: commit vault changes to git."""
    vault = str(settings.vault_root)
    subprocess.run(["git", "-C", vault, "add", "-A"], check=False)
    subprocess.run(["git", "-C", vault, "commit", "-m", "auto: daily vault commit"], check=False)


def register_jobs(scheduler, settings: Settings, bot) -> None:
    """Register all cron jobs with the APScheduler instance."""
    tz = settings.tz

    scheduler.add_job(job_hevy_sync, "cron", hour=2, minute=0, timezone=tz,
                      args=[settings], id="hevy_sync")
    scheduler.add_job(job_morning_tasks, "cron", hour=8, minute=0, timezone=tz,
                      args=[settings, bot], id="morning_tasks")
    scheduler.add_job(job_journal_prompt, "cron", hour=22, minute=0, timezone=tz,
                      args=[settings, bot], id="journal_prompt")
    scheduler.add_job(job_workout_check, "cron", hour=20, minute=0, timezone=tz,
                      args=[settings, bot], id="workout_check")
    scheduler.add_job(job_obsidian_git_commit, "cron", hour=23, minute=55, timezone=tz,
                      args=[settings], id="obsidian_git")
