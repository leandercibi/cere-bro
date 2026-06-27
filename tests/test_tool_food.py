from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import app.db as db
from app.tools.errors import ToolError
from app.tools.food import delete_food, edit_food, log_food, query_macros
from lib.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    s = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="x",
        TELEGRAM_ALLOWED_USER_ID=1,
        OPENROUTER_API_KEY="x",
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=vault,
        TIMEZONE="UTC",
    )
    db.init_db(s.db_path)
    return s


MOCK_MACROS = {
    "total_kcal": 400,
    "total_protein_g": 15.0,
    "total_fat_g": 10.0,
    "total_carbs_g": 50.0,
}


# --- log_food ---

async def test_log_food_inserts_row_in_db(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        result = await log_food([{"name": "rice", "quantity": "1 cup"}], user_id=1, settings=settings)
    assert result["food_log_id"] is not None
    conn = db.get_conn(settings.db_path)
    logs = db.get_recent_food_logs(conn, 1)
    conn.close()
    assert len(logs) == 1
    assert logs[0].items[0].name == "rice"


async def test_log_food_with_junk_flag(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "samosa"}], junk=True, user_id=1, settings=settings)
    conn = db.get_conn(settings.db_path)
    log = db.get_last_food_log(conn, 1)
    conn.close()
    assert log.junk is True


async def test_log_food_with_explicit_time_parses_correctly(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        result = await log_food([{"name": "oats"}], time="8am", user_id=1, settings=settings)
    assert "08:00" in result["logged_at"] or "T08:" in result["logged_at"]


async def test_log_food_without_time_defaults_to_now(settings):
    before = datetime.now(settings.tz).isoformat()[:16]
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        result = await log_food([{"name": "banana"}], user_id=1, settings=settings)
    assert result["logged_at"][:16] >= before


async def test_log_food_writes_obsidian_daily_note(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "dal"}], user_id=1, settings=settings)
    daily_notes = list((settings.vault_root / "daily").glob("*.md")) if (settings.vault_root / "daily").exists() else list(settings.vault_root.glob("**/*.md"))
    assert len(daily_notes) > 0


async def test_log_food_estimates_macros(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        result = await log_food([{"name": "dal"}], user_id=1, settings=settings)
    assert result["estimated_kcal"] == 400
    assert result["estimated_macros"]["protein_g"] == 15.0


async def test_log_food_macro_estimate_failure_still_logs(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        result = await log_food([{"name": "chapati"}], user_id=1, settings=settings)
    assert result["food_log_id"] is not None
    assert result["estimated_kcal"] is None


async def test_log_food_returns_structured_result(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        result = await log_food([{"name": "rice"}], user_id=1, settings=settings)
    assert "food_log_id" in result
    assert "summary" in result
    assert "logged_at" in result
    assert "estimated_kcal" in result


async def test_log_food_recomputes_daily_totals(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "rice"}], user_id=1, settings=settings)
    conn = db.get_conn(settings.db_path)
    totals = db.get_daily_totals(conn, date.today())
    conn.close()
    assert totals is not None
    assert totals.total_kcal == 400


# --- edit_food ---

async def test_edit_food_updates_items_and_junk(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        created = await log_food([{"name": "rice"}], user_id=1, settings=settings)
    fid = created["food_log_id"]
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await edit_food(fid, [{"name": "biryani"}], junk=True, user_id=1, settings=settings)
    conn = db.get_conn(settings.db_path)
    logs = db.get_recent_food_logs(conn, 1)
    conn.close()
    assert logs[0].items[0].name == "biryani"
    assert logs[0].junk is True


async def test_edit_food_nonexistent_id_raises_tool_error(settings):
    with pytest.raises(ToolError):
        await edit_food(9999, [{"name": "x"}], user_id=1, settings=settings)


async def test_edit_food_recomputes_daily_totals_for_both_days(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        created = await log_food([{"name": "rice"}], user_id=1, settings=settings)
    fid = created["food_log_id"]
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await edit_food(fid, [{"name": "dal"}], user_id=1, settings=settings)
    conn = db.get_conn(settings.db_path)
    totals = db.get_daily_totals(conn, date.today())
    conn.close()
    assert totals is not None


# --- delete_food ---

async def test_delete_food_by_id_removes_row(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        created = await log_food([{"name": "samosa"}], user_id=1, settings=settings)
    fid = created["food_log_id"]
    result = await delete_food("by_id", food_log_id=fid, user_id=1, settings=settings)
    assert result["deleted_food_log_id"] == fid
    conn = db.get_conn(settings.db_path)
    logs = db.get_recent_food_logs(conn, 1)
    conn.close()
    assert len(logs) == 0


async def test_delete_food_last_entry(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        await log_food([{"name": "chai"}], user_id=1, settings=settings)
    result = await delete_food("last", user_id=1, settings=settings)
    assert "deleted_food_log_id" in result


async def test_delete_food_by_hint_finds_matching_item(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        await log_food([{"name": "paneer tikka"}], user_id=1, settings=settings)
    result = await delete_food("matching", item_hint="paneer", user_id=1, settings=settings)
    assert "deleted_food_log_id" in result


async def test_delete_food_not_found_raises_tool_error(settings):
    with pytest.raises(ToolError):
        await delete_food("last", user_id=1, settings=settings)


async def test_delete_food_recomputes_daily_totals(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "rice"}], user_id=1, settings=settings)
    await delete_food("last", user_id=1, settings=settings)
    conn = db.get_conn(settings.db_path)
    totals = db.get_daily_totals(conn, date.today())
    conn.close()
    assert totals is not None and totals.total_kcal == 0


# --- query_macros ---

async def test_query_macros_today_sums_all_entries(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "rice"}], user_id=1, settings=settings)
        await log_food([{"name": "dal"}], user_id=1, settings=settings)
    result = await query_macros("today", user_id=1, settings=settings)
    assert result["total_kcal"] == 800
    assert len(result["entries"]) == 2


async def test_query_macros_last_returns_most_recent(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "rice"}], user_id=1, settings=settings)
        await log_food([{"name": "dal"}], user_id=1, settings=settings)
    result = await query_macros("last", user_id=1, settings=settings)
    assert len(result["entries"]) == 1
    assert result["entries"][0]["summary"] == "dal"


async def test_query_macros_by_date(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "roti"}], user_id=1, settings=settings)
    today = date.today().isoformat()
    result = await query_macros("by_date", date=today, user_id=1, settings=settings)
    assert len(result["entries"]) >= 1


async def test_query_macros_matching_item(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "chole bhature"}], user_id=1, settings=settings)
    result = await query_macros("matching", item_hint="chole", user_id=1, settings=settings)
    assert len(result["entries"]) == 1


async def test_query_macros_empty_day_raises_tool_error(settings):
    with pytest.raises(ToolError):
        await query_macros("today", user_id=1, settings=settings)


async def test_edit_food_updates_obsidian_line(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        created = await log_food([{"name": "rice"}], user_id=1, settings=settings)
    fid = created["food_log_id"]
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        with patch("app.tools.food.update_food") as mock_update:
            await edit_food(fid, [{"name": "biryani"}], user_id=1, settings=settings)
    mock_update.assert_called_once()


async def test_edit_food_re_estimates_macros(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        created = await log_food([{"name": "rice"}], user_id=1, settings=settings)
    fid = created["food_log_id"]
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)) as mock_est:
        with patch("app.tools.food.update_food"):
            await edit_food(fid, [{"name": "biryani"}], user_id=1, settings=settings)
    mock_est.assert_called_once()


async def test_delete_food_removes_obsidian_line(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        await log_food([{"name": "samosa"}], user_id=1, settings=settings)
    with patch("app.tools.food.remove_food") as mock_remove:
        await delete_food("last", user_id=1, settings=settings)
    mock_remove.assert_called_once()


async def test_query_macros_yesterday(settings):
    from datetime import timedelta
    yesterday = (datetime.now(settings.tz) - timedelta(days=1)).date().isoformat()
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "roti"}], time=f"{yesterday}T12:00:00", user_id=1, settings=settings)
    result = await query_macros("yesterday", user_id=1, settings=settings)
    assert len(result["entries"]) >= 1


async def test_query_macros_includes_daily_totals(settings):
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=MOCK_MACROS)):
        await log_food([{"name": "dal"}], user_id=1, settings=settings)
    result = await query_macros("today", user_id=1, settings=settings)
    assert "total_kcal" in result
    assert result["total_kcal"] >= 0


async def test_query_macros_fallback_live_estimate_when_stored_is_null(settings):
    """When est_calories_kcal is null on all rows, totals sum to 0 (no crash)."""
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        await log_food([{"name": "dal"}], user_id=1, settings=settings)
    result = await query_macros("today", user_id=1, settings=settings)
    assert result["total_kcal"] == 0
    assert len(result["entries"]) == 1
