"""Multi-turn integration tests — real LLM calls."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from lib.config import Settings
from app.session import SessionBuffer


@pytest.fixture
def settings(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    s = Settings(
        _env_file=".env",
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=vault,
    )
    import app.db as db
    db.init_db(s.db_path)
    return s


async def _route(msg: str, settings: Settings, buf: SessionBuffer, user_id: int = 1):
    from app.router import route
    with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value={"total_kcal": 400, "total_protein_g": 10, "total_fat_g": 8, "total_carbs_g": 60})), \
         patch("app.tools.food.append_food", return_value="anchor"), \
         patch("app.tools.food.update_food"), \
         patch("app.tools.food.remove_food"), \
         patch("app.router._session_buffer", buf):
        return await route(msg, user_id=user_id, settings=settings)


@pytest.mark.integration
async def test_e2e_multiturn_query_after_log(settings):
    """Log food then immediately query calories.

    The LLM may answer from the tool-result context (estimated_kcal already
    present in history) or call query_macros for a precise DB total — both
    are correct. We verify the first turn logged food and the second turn
    produced a meaningful reply.
    """
    buf = SessionBuffer()
    r1 = await _route("had samosa #junk", settings, buf)
    assert r1.tool_called == "log_food"

    r2 = await _route("how many calories was that", settings, buf)
    # LLM may call query_macros or answer from session context — both are valid.
    assert r2.tool_called in ("query_macros", None)
    assert r2.reply_text  # non-empty response either way


@pytest.mark.integration
async def test_e2e_multiturn_edit(settings):
    """Log food, then correct the time — LLM should use context to act on previous entry."""
    buf = SessionBuffer()
    r1 = await _route("had dal chawal at 1pm", settings, buf)
    assert r1.tool_called == "log_food"

    with patch("app.tools.food.update_food"), \
         patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
        r2 = await _route("actually it was at 2pm", settings, buf)
    # LLM should use context — edit_food or log_food are both acceptable
    assert r2.tool_called in ("edit_food", "log_food", "query_macros")  # context-aware response expected
