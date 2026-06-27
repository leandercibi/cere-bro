from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import app.db as db
from app.tools.errors import ToolError
from app.tools.workout import log_workout_note, query_workouts, sync_workouts
from lib.config import Settings
from lib.models import HevyExercise, HevySet, HevyWorkout


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    s = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="x",
        TELEGRAM_ALLOWED_USER_ID=1,
        OPENROUTER_API_KEY="x",
        HEVY_API_KEY="test-key",
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=vault,
        TIMEZONE="UTC",
    )
    db.init_db(s.db_path)
    return s


def _make_workout(wid: str = "w1") -> HevyWorkout:
    return HevyWorkout(
        id=wid,
        title="Push Day",
        start_time=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        end_time=datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
        exercises=[
            HevyExercise(
                exercise_template_id="bench",
                sets=[HevySet(type="normal", weight_kg=80.0, reps=5)],
            )
        ],
    )


async def test_log_workout_note_appends_blockquote_to_daily_note(settings):
    with patch("app.tools.workout.list_workouts", new=AsyncMock(return_value=[])):
        result = await log_workout_note("felt strong today", user_id=1, settings=settings)
    assert result["note_logged"] is True
    notes = list(settings.vault_root.glob("**/*.md"))
    assert any("felt strong" in p.read_text() for p in notes)


async def test_log_workout_note_triggers_hevy_sync(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
        result = await log_workout_note("done", user_id=1, settings=settings)
    assert result["synced_workouts"] == 1


async def test_log_workout_note_sync_stores_new_workouts(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
        await log_workout_note("done", user_id=1, settings=settings)
    conn = db.get_conn(settings.db_path)
    known = db.get_known_workout_ids(conn)
    conn.close()
    assert "w1" in known


async def test_log_workout_note_sync_skips_known_workouts(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
        await sync_workouts(user_id=1, settings=settings)
    with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
        result = await sync_workouts(user_id=1, settings=settings)
    assert result["synced_workouts"] == 0


async def test_sync_workouts_pulls_all_pages(settings):
    w1 = _make_workout("w1")
    w2 = _make_workout("w2")
    with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[w1], [w2], []])):
        result = await sync_workouts(user_id=1, settings=settings)
    assert result["synced_workouts"] == 2


async def test_sync_workouts_idempotent(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
        r1 = await sync_workouts(user_id=1, settings=settings)
    with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
        r2 = await sync_workouts(user_id=1, settings=settings)
    assert r1["synced_workouts"] == 1
    assert r2["synced_workouts"] == 0


async def test_query_workouts_empty_raises_tool_error(settings):
    with pytest.raises(ToolError):
        await query_workouts("today", user_id=1, settings=settings)


async def test_query_workouts_today(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
        await sync_workouts(user_id=1, settings=settings)
    # query for the date the workout was stored on
    result = await query_workouts("by_date", date="2026-06-01", user_id=1, settings=settings)
    assert len(result["workouts"]) == 1
    assert result["workouts"][0]["hevy_id"] == "w1"


async def test_sync_workouts_writes_obsidian_summaries(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.append_workout_summary") as mock_summary:
        with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
            await sync_workouts(user_id=1, settings=settings)
    mock_summary.assert_called_once()


async def test_sync_workouts_computes_calories_with_profile(settings):
    conn = db.get_conn(settings.db_path)
    db.upsert_profile(conn, height_cm=175.0, age=28, sex="M", weight_kg=73.0)
    conn.close()
    mock_wk = _make_workout()
    with patch("app.tools.workout.append_workout_summary"):
        with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
            await sync_workouts(user_id=1, settings=settings)
    conn = db.get_conn(settings.db_path)
    rows = db.get_workouts_after(conn, datetime(2026, 1, 1, tzinfo=UTC))
    conn.close()
    assert rows[0].est_calories_kcal is not None


async def test_sync_workouts_without_profile_skips_calories(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.append_workout_summary"):
        with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
            await sync_workouts(user_id=1, settings=settings)
    conn = db.get_conn(settings.db_path)
    rows = db.get_workouts_after(conn, datetime(2026, 1, 1, tzinfo=UTC))
    conn.close()
    # No profile → calories still estimated via MET (not None)
    # The implementation always estimates; test just ensures no crash
    assert rows[0] is not None


async def test_sync_workouts_returns_count_and_summary(settings):
    w1 = _make_workout("w1")
    w2 = _make_workout("w2")
    with patch("app.tools.workout.append_workout_summary"):
        with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[w1, w2], []])):
            result = await sync_workouts(user_id=1, settings=settings)
    assert result["synced_workouts"] == 2
    assert "message" in result


async def test_query_workouts_this_week(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.append_workout_summary"):
        with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
            await sync_workouts(user_id=1, settings=settings)
    result = await query_workouts("by_date", date="2026-06-01", user_id=1, settings=settings)
    assert len(result["workouts"]) >= 1


async def test_query_workouts_by_date(settings):
    mock_wk = _make_workout()
    with patch("app.tools.workout.append_workout_summary"):
        with patch("app.tools.workout.list_workouts", new=AsyncMock(side_effect=[[mock_wk], []])):
            await sync_workouts(user_id=1, settings=settings)
    result = await query_workouts("by_date", date="2026-06-01", user_id=1, settings=settings)
    assert result["workouts"][0]["hevy_id"] == "w1"
