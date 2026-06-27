from __future__ import annotations

from pathlib import Path

import pytest

import app.db as db
from app.tools.errors import ToolError
from app.tools.tasks import complete_task, log_task, query_tasks
from lib.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="x",
        TELEGRAM_ALLOWED_USER_ID=1,
        OPENROUTER_API_KEY="x",
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=tmp_path / "vault",
        TIMEZONE="UTC",
    )
    db.init_db(s.db_path)
    return s


async def test_log_task_inserts_row_with_due_date(settings):
    result = await log_task("submit invoice", due="Friday", user_id=1, settings=settings)
    assert result["task_id"] is not None
    assert result["description"] == "submit invoice"
    assert result["due_at"] is not None


async def test_log_task_without_due_date(settings):
    result = await log_task("buy groceries", user_id=1, settings=settings)
    assert result["task_id"] is not None
    assert result["due_at"] is None


async def test_complete_task_by_fragment_match(settings):
    await log_task("call doctor", user_id=1, settings=settings)
    result = await complete_task("doctor", user_id=1, settings=settings)
    assert result["description"] == "call doctor"


async def test_complete_task_not_found_raises_tool_error(settings):
    with pytest.raises(ToolError):
        await complete_task("nonexistent task", user_id=1, settings=settings)


async def test_query_tasks_open_returns_all_incomplete(settings):
    await log_task("task a", user_id=1, settings=settings)
    await log_task("task b", user_id=1, settings=settings)
    await complete_task("task a", user_id=1, settings=settings)
    result = await query_tasks("open", user_id=1, settings=settings)
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["description"] == "task b"


async def test_query_tasks_today_returns_due_and_overdue(settings):
    # task due today (no due = always shown in today scope based on implementation)
    await log_task("overdue task", due="2020-01-01", user_id=1, settings=settings)
    await log_task("no due task", user_id=1, settings=settings)
    result = await query_tasks("today", user_id=1, settings=settings)
    descriptions = [t["description"] for t in result["tasks"]]
    assert "overdue task" in descriptions
    assert "no due task" in descriptions
