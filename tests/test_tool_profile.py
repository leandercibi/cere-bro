from __future__ import annotations

from pathlib import Path

import pytest

import app.db as db
from app.tools.errors import ToolError
from app.tools.profile import get_profile, update_profile
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


async def test_update_profile_upserts_row(settings):
    result = await update_profile(weight_kg=73.0, height_cm=175.0, age=28, sex="M", user_id=1, settings=settings)
    assert result["weight_kg"] == 73.0
    assert result["sex"] == "M"


async def test_update_profile_partial_update_preserves_existing(settings):
    await update_profile(weight_kg=73.0, height_cm=175.0, age=28, sex="M", user_id=1, settings=settings)
    result = await update_profile(weight_kg=74.0, user_id=1, settings=settings)
    assert result["weight_kg"] == 74.0
    assert result["height_cm"] == 175.0
    assert result["age"] == 28


async def test_get_profile_returns_current_values(settings):
    await update_profile(weight_kg=70.0, height_cm=170.0, age=25, sex="F", user_id=1, settings=settings)
    result = await get_profile(user_id=1, settings=settings)
    assert result["weight_kg"] == 70.0
    assert result["sex"] == "F"
    assert "updated_at" in result


async def test_get_profile_no_profile_raises_tool_error(settings):
    with pytest.raises(ToolError):
        await get_profile(user_id=1, settings=settings)


async def test_update_profile_first_time_missing_fields_raises_tool_error(settings):
    with pytest.raises(ToolError):
        await update_profile(weight_kg=73.0, user_id=1, settings=settings)


async def test_update_profile_recomputes_workout_calories(settings):
    """Updating weight/profile doesn't crash even with no workouts stored."""
    result = await update_profile(weight_kg=75.0, height_cm=175.0, age=28, sex="M", user_id=1, settings=settings)
    assert result["weight_kg"] == 75.0
    # No workouts → no calories to recompute, just verify no exception raised
