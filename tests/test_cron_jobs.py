from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.config import Settings


@pytest.fixture
def settings(tmp_path):
    s = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="x",
        TELEGRAM_ALLOWED_USER_ID=42,
        OPENROUTER_API_KEY="x",
        HEVY_API_KEY="x",
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=tmp_path / "vault",
        TIMEZONE="UTC",
    )
    import app.db as db
    db.init_db(s.db_path)
    (tmp_path / "vault").mkdir(exist_ok=True)
    return s


async def test_hevy_nightly_sync_job_calls_sync_workouts(settings):
    from app.cron import job_hevy_sync
    with patch("app.cron.sync_workouts", new=AsyncMock(return_value={"synced_workouts": 2, "message": "ok"})) as mock_sync:
        await job_hevy_sync(settings)
    mock_sync.assert_called_once_with(user_id=settings.telegram_allowed_user_id, settings=settings)


async def test_morning_tasks_push_sends_telegram_message(settings):
    from app.cron import job_morning_tasks
    mock_bot = AsyncMock()
    with patch("app.cron.query_tasks", new=AsyncMock(return_value={"tasks": [{"description": "buy milk", "due_at": None, "completed": False}]})):
        await job_morning_tasks(settings, mock_bot)
    mock_bot.send_message.assert_called_once()
    text = mock_bot.send_message.call_args[1]["text"]
    assert "buy milk" in text


async def test_journal_prompt_sends_at_10pm(settings):
    from app.cron import job_journal_prompt
    mock_bot = AsyncMock()
    await job_journal_prompt(settings, mock_bot)
    mock_bot.send_message.assert_called_once()
    text = mock_bot.send_message.call_args[1]["text"]
    assert text  # non-empty prompt


async def test_workout_check_skips_if_hevy_has_today(settings):
    from app.cron import job_workout_check
    mock_bot = AsyncMock()
    with patch("app.cron.query_workouts", new=AsyncMock(return_value={"workouts": [{"title": "Push", "started_at": "2026-06-03T10:00:00", "duration_s": 3600, "total_volume_kg": 1000, "est_calories_kcal": 300}]})):
        await job_workout_check(settings, mock_bot)
    mock_bot.send_message.assert_not_called()


async def test_obsidian_git_commit_runs(settings):
    from app.cron import job_obsidian_git_commit
    with patch("app.cron.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        await job_obsidian_git_commit(settings)
    assert mock_run.called
