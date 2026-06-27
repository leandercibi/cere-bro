from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.router import route
from app.session import SessionBuffer
from lib.config import Settings


@pytest.fixture
def settings(tmp_path):
    s = Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="x",
        TELEGRAM_ALLOWED_USER_ID=1,
        OPENROUTER_API_KEY="x",
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=tmp_path / "vault",
        TIMEZONE="UTC",
    )
    import app.db as db
    db.init_db(s.db_path)
    (tmp_path / "vault").mkdir(exist_ok=True)
    return s


def _mock_tool_call(name: str, args: dict):
    """Build a fake OpenAI response with a tool_call."""
    tool_call = MagicMock()
    tool_call.id = "call_1"
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(args)

    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tool_call]

    choice = MagicMock()
    choice.message = msg

    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _mock_text_response(text: str):
    """Build a fake OpenAI response with plain text."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None

    choice = MagicMock()
    choice.message = msg

    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _patch_llm(return_value):
    """Patch the _call_with_retry function in the router to return a canned response."""
    return patch("app.router._call_with_retry", new=AsyncMock(return_value=return_value))


def _patch_llm_fn(fn):
    """Patch _call_with_retry with a custom async function."""
    return patch("app.router._call_with_retry", new=fn)


# --- Tool dispatch tests ---

async def test_router_dispatches_food_log_tool(settings):
    resp = _mock_tool_call("log_food", {"items": [{"name": "rice"}]})
    with _patch_llm(resp):
        with patch("app.tools.food.estimate_macros", new=AsyncMock(return_value=None)):
            with patch("app.tools.food.append_food", return_value="anchor"):
                result = await route("had rice for lunch", user_id=1, settings=settings)
    assert result.tool_called == "log_food"


async def test_router_dispatches_delete_food_tool(settings):
    resp = _mock_tool_call("delete_food", {"target": "last"})
    with _patch_llm(resp):
        with patch("app.tools.food.ToolError"):
            with patch("app.tools.food.db") as mock_db:
                mock_db.get_conn.return_value.__enter__ = MagicMock()
                mock_db.get_last_food_log.return_value = None
                mock_db.get_conn.return_value = MagicMock()
                result = await route("delete last entry", user_id=1, settings=settings)
    assert result.tool_called == "delete_food"


async def test_router_dispatches_query_macros_tool(settings):
    resp = _mock_tool_call("query_macros", {"scope": "today"})
    with _patch_llm(resp):
        result = await route("how many calories today", user_id=1, settings=settings)
    assert result.tool_called == "query_macros"


async def test_router_dispatches_workout_note_tool(settings):
    resp = _mock_tool_call("log_workout_note", {"note": "felt great"})
    with _patch_llm(resp):
        with patch("app.tools.workout.list_workouts", new=AsyncMock(return_value=[])):
            with patch("app.tools.workout.append_workout_note"):
                result = await route("workout done", user_id=1, settings=settings)
    assert result.tool_called == "log_workout_note"


async def test_router_dispatches_capture_idea_tool(settings):
    resp = _mock_tool_call("capture_idea", {"title": "sleep tracker"})
    with _patch_llm(resp):
        result = await route("#idea sleep tracker", user_id=1, settings=settings)
    assert result.tool_called == "capture_idea"


async def test_router_dispatches_journal_tool(settings):
    resp = _mock_tool_call("log_journal", {"entry": "tired today"})
    with _patch_llm(resp):
        with patch("app.tools.journal.ensure_daily_note") as mock_note:
            mock_note.return_value = MagicMock()
            mock_note.return_value.read_text.return_value = "## Journal\n"
            mock_note.return_value.write_text = MagicMock()
            result = await route("tired today", user_id=1, settings=settings)
    assert result.tool_called == "log_journal"


async def test_router_dispatches_task_tool(settings):
    resp = _mock_tool_call("log_task", {"description": "submit invoice"})
    with _patch_llm(resp):
        result = await route("#task submit invoice", user_id=1, settings=settings)
    assert result.tool_called == "log_task"


async def test_router_plain_text_response_when_no_tool_call(settings):
    resp = _mock_text_response("Hello! How can I help?")
    with _patch_llm(resp):
        result = await route("hey", user_id=1, settings=settings)
    assert result.tool_called is None
    assert result.reply_text == "Hello! How can I help?"


async def test_router_injects_user_id_and_settings(settings):
    """Verify handler is called with user_id and settings injected."""
    called_with = {}

    async def fake_log_food(items, junk=False, time=None, notes=None, *, user_id, settings):
        called_with["user_id"] = user_id
        called_with["settings"] = settings
        return {"food_log_id": 1, "summary": "rice", "logged_at": "2026-01-01", "estimated_kcal": None, "estimated_macros": None}

    resp = _mock_tool_call("log_food", {"items": [{"name": "rice"}]})
    with _patch_llm(resp):
        with patch("app.router._get_tool_handler", return_value=fake_log_food):
            await route("had rice", user_id=42, settings=settings)
    assert called_with["user_id"] == 42
    assert called_with["settings"] is settings


async def test_router_tool_error_returns_user_message(settings):
    from app.tools.errors import ToolError

    async def failing_tool(**kwargs):
        raise ToolError("no entries found")

    resp = _mock_tool_call("query_macros", {"scope": "today"})
    with _patch_llm(resp):
        with patch("app.router._get_tool_handler", return_value=failing_tool):
            result = await route("calories today", user_id=1, settings=settings)
    assert "no entries found" in result.reply_text
    assert result.tool_called == "query_macros"


async def test_router_unexpected_error_returns_generic_message(settings):
    async def exploding_tool(**kwargs):
        raise RuntimeError("db exploded")

    resp = _mock_tool_call("log_food", {"items": [{"name": "rice"}]})
    with _patch_llm(resp):
        with patch("app.router._get_tool_handler", return_value=exploding_tool):
            result = await route("had rice", user_id=1, settings=settings)
    assert result.reply_text
    assert result.tool_called == "log_food"


async def test_router_appends_to_session_buffer(settings):
    resp = _mock_text_response("Hi there!")
    buf = SessionBuffer()
    with _patch_llm(resp):
        with patch("app.router._session_buffer", buf):
            await route("hello", user_id=1, settings=settings)
    msgs = buf.get(1)
    assert any(m["content"] == "hello" for m in msgs)
    assert any(m["content"] == "Hi there!" for m in msgs)


async def test_router_includes_session_history_in_messages(settings):
    buf = SessionBuffer()
    buf.add(1, "user", "previous message")
    buf.add(1, "assistant", "previous reply")

    captured_messages = []

    async def fake_retry(_client, **kwargs):
        captured_messages.extend(kwargs["messages"])
        return _mock_text_response("ok")

    with _patch_llm_fn(fake_retry):
        with patch("app.router._session_buffer", buf):
            await route("new message", user_id=1, settings=settings)

    contents = [m["content"] for m in captured_messages]
    assert "previous message" in contents
    assert "previous reply" in contents


async def test_router_system_prompt_includes_current_time(settings):
    captured = []

    async def fake_retry(_client, **kwargs):
        captured.extend(kwargs["messages"])
        return _mock_text_response("ok")

    with _patch_llm_fn(fake_retry):
        await route("hey", user_id=1, settings=settings)

    system_msg = next(m for m in captured if m["role"] == "system")
    assert "2026" in system_msg["content"]


async def test_router_system_prompt_includes_profile(settings):
    import app.db as db
    conn = db.get_conn(settings.db_path)
    db.upsert_profile(conn, height_cm=175.0, age=28, sex="M", weight_kg=73.0)
    conn.close()

    captured = []

    async def fake_retry(_client, **kwargs):
        captured.extend(kwargs["messages"])
        return _mock_text_response("ok")

    with _patch_llm_fn(fake_retry):
        await route("hey", user_id=1, settings=settings)

    system_msg = next(m for m in captured if m["role"] == "system")
    assert "73" in system_msg["content"]


# --- Multi-turn context tests ---

async def test_router_second_message_sees_first_in_context(settings):
    buf = SessionBuffer()
    messages_per_call = []

    call_count = 0

    async def fake_retry(_client, **kwargs):
        nonlocal call_count
        messages_per_call.append(list(kwargs["messages"]))
        call_count += 1
        return _mock_text_response(f"reply {call_count}")

    with _patch_llm_fn(fake_retry):
        with patch("app.router._session_buffer", buf):
            await route("first message", user_id=1, settings=settings)
            await route("second message", user_id=1, settings=settings)

    second_call_contents = [m["content"] for m in messages_per_call[1]]
    assert "first message" in second_call_contents


async def test_router_buffer_ttl_clears_stale_context(settings):
    import asyncio
    buf = SessionBuffer(ttl_seconds=1)
    buf.add(1, "user", "old message")
    await asyncio.sleep(1.1)

    captured = []

    async def fake_retry(_client, **kwargs):
        captured.extend(kwargs["messages"])
        return _mock_text_response("ok")

    with _patch_llm_fn(fake_retry):
        with patch("app.router._session_buffer", buf):
            await route("new message", user_id=1, settings=settings)

    contents = [m["content"] for m in captured]
    assert "old message" not in contents


async def test_router_buffer_max_messages_evicts_oldest(settings):
    buf = SessionBuffer(max_messages=2)
    buf.add(1, "user", "msg1")
    buf.add(1, "assistant", "reply1")
    buf.add(1, "user", "msg2")

    captured = []

    async def fake_retry(_client, **kwargs):
        captured.extend(kwargs["messages"])
        return _mock_text_response("ok")

    with _patch_llm_fn(fake_retry):
        with patch("app.router._session_buffer", buf):
            await route("msg3", user_id=1, settings=settings)

    contents = [m["content"] for m in captured]
    assert "msg1" not in contents
    assert "reply1" in contents
