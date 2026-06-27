"""Integration tests — real LLM calls via OpenRouter.

Run with: pytest tests/integration/ -m integration -v
Cost: ~$0.002 total for the full suite.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from lib.config import Settings


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("integration")
    vault = tmp / "vault"
    vault.mkdir()
    s = Settings(
        _env_file=".env",
        DB_PATH=tmp / "test.sqlite",
        VAULT_ROOT=vault,
    )
    import app.db as db
    db.init_db(s.db_path)
    return s


@pytest.fixture(autouse=True)
def clear_session():
    """Clear session buffer before each test to avoid context bleed."""
    from app.router import _session_buffer
    yield
    # clear all users
    for uid in list(_session_buffer._store.keys()):
        _session_buffer.clear(uid)


async def _route(msg: str, settings: Settings, user_id: int = 1):
    """Helper: route a message, mock all side-effectful tool internals."""
    from app.router import route
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)), \
         patch("app.tools.food.append_food", return_value="anchor"), \
         patch("app.tools.food.update_food"), \
         patch("app.tools.food.remove_food"), \
         patch("app.tools.workout.list_workouts", new=AsyncMock(return_value=[])), \
         patch("app.tools.workout.append_workout_note"), \
         patch("app.tools.workout.append_workout_summary"), \
         patch("app.tools.journal.ensure_daily_note") as mock_note:
        mock_note.return_value = Path("/tmp/daily.md")
        Path("/tmp/daily.md").write_text("## Journal\n")
        return await route(msg, user_id=user_id, settings=settings)


@pytest.mark.integration
async def test_e2e_food_log_natural_language(settings):
    result = await _route("had dal chawal and bhindi for lunch", settings)
    assert result.tool_called == "log_food"


@pytest.mark.integration
async def test_e2e_food_log_with_junk(settings):
    result = await _route("samosa #junk", settings)
    assert result.tool_called == "log_food"


@pytest.mark.integration
async def test_e2e_food_log_with_time(settings):
    result = await _route("oats and banana at 8am", settings)
    assert result.tool_called == "log_food"


@pytest.mark.integration
async def test_e2e_delete_last(settings):
    # Use isolated user_id so buffer has the food log in context
    buf_user = 99
    from app.session import SessionBuffer
    from app.router import _session_buffer
    # log then delete in same session so LLM sees context
    await _route("had rice", settings, user_id=buf_user)
    result = await _route("delete the last entry", settings, user_id=buf_user)
    assert result.tool_called == "delete_food"


@pytest.mark.integration
async def test_e2e_calorie_query(settings):
    result = await _route("how many calories today", settings)
    assert result.tool_called == "query_macros"


@pytest.mark.integration
async def test_e2e_macro_query(settings):
    result = await _route("macros for lunch", settings)
    assert result.tool_called == "query_macros"


@pytest.mark.integration
async def test_e2e_workout_note(settings):
    result = await _route("workout done, felt strong, fasted", settings)
    assert result.tool_called == "log_workout_note"


@pytest.mark.integration
async def test_e2e_idea_capture(settings):
    result = await _route("#idea build a sleep tracker using Oura API", settings)
    assert result.tool_called == "capture_idea"


@pytest.mark.integration
async def test_e2e_task(settings):
    result = await _route("#task submit invoice by Friday", settings)
    assert result.tool_called == "log_task"


@pytest.mark.integration
async def test_e2e_greeting(settings):
    result = await _route("hey", settings)
    assert result.tool_called is None


@pytest.mark.integration
async def test_e2e_ambiguous_defaults_to_no_tool(settings):
    result = await _route("thanks", settings)
    assert result.tool_called is None
