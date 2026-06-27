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
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=tmp_path / "vault",
        TIMEZONE="UTC",
    )
    import app.db as db
    db.init_db(s.db_path)
    (tmp_path / "vault").mkdir(exist_ok=True)
    return s


def _make_update(text: str, user_id: int = 42, reply_to_text: str | None = None):
    """Build a minimal fake telegram Update."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_message.text = text
    update.effective_message.message_id = 1
    update.effective_message.reply_to_message = None
    if reply_to_text is not None:
        reply_msg = MagicMock()
        reply_msg.text = reply_to_text
        reply_msg.message_id = 99
        update.effective_message.reply_to_message = reply_msg
    update.effective_message.reply_text = AsyncMock()
    return update


def _make_context(settings: Settings):
    ctx = MagicMock()
    ctx.bot_data = {"settings": settings}
    return ctx


# --- T3.1 message handling ---

async def test_bot_rejects_unauthorized_user(settings):
    from app.bot_v2 import on_message
    update = _make_update("hello", user_id=999)
    ctx = _make_context(settings)
    await on_message(update, ctx)
    update.effective_message.reply_text.assert_not_called()


async def test_bot_passes_message_to_router(settings):
    from app.bot_v2 import on_message
    from app.router import RouterResult
    update = _make_update("had rice", user_id=42)
    ctx = _make_context(settings)
    with patch("app.bot_v2.route", new=AsyncMock(return_value=RouterResult("✅ Logged: rice", "log_food"))) as mock_route:
        await on_message(update, ctx)
    mock_route.assert_called_once_with("had rice", user_id=42, settings=settings)


async def test_bot_sends_router_reply_to_telegram(settings):
    from app.bot_v2 import on_message
    from app.router import RouterResult
    update = _make_update("hey", user_id=42)
    ctx = _make_context(settings)
    with patch("app.bot_v2.route", new=AsyncMock(return_value=RouterResult("Hello!", None))):
        await on_message(update, ctx)
    update.effective_message.reply_text.assert_called_once_with("Hello!")


async def test_bot_start_command_replies_help_text(settings):
    from app.bot_v2 import on_start
    update = _make_update("/start", user_id=42)
    ctx = _make_context(settings)
    await on_start(update, ctx)
    update.effective_message.reply_text.assert_called_once()
    args = update.effective_message.reply_text.call_args[0]
    assert len(args[0]) > 0  # non-empty help text


async def test_bot_handles_router_exception_gracefully(settings):
    from app.bot_v2 import on_message
    update = _make_update("had rice", user_id=42)
    ctx = _make_context(settings)
    with patch("app.bot_v2.route", new=AsyncMock(side_effect=Exception("boom"))):
        await on_message(update, ctx)
    update.effective_message.reply_text.assert_called_once()
    reply = update.effective_message.reply_text.call_args[0][0]
    assert reply  # some error message sent


# --- T3.2 reply-to context ---

async def test_reply_to_adds_context_to_session(settings):
    """Replying to a bot message adds that message to session buffer before routing."""
    from app.bot_v2 import on_message
    from app.router import RouterResult
    from app.session import SessionBuffer
    buf = SessionBuffer()
    update = _make_update("delete it", user_id=42, reply_to_text="✅ Logged: samosa")
    ctx = _make_context(settings)
    with patch("app.bot_v2.route", new=AsyncMock(return_value=RouterResult("🗑️ Deleted", "delete_food"))) as mock_route:
        with patch("app.bot_v2._session_buffer", buf):
            await on_message(update, ctx)
    # The reply-to text should have been added to the buffer before route() was called
    mock_route.assert_called_once()


async def test_reply_to_unknown_message_works_as_fresh_request(settings):
    """Reply-to with no recognisable context still routes normally."""
    from app.bot_v2 import on_message
    from app.router import RouterResult
    update = _make_update("what was that?", user_id=42, reply_to_text="some random text")
    ctx = _make_context(settings)
    with patch("app.bot_v2.route", new=AsyncMock(return_value=RouterResult("ok", None))):
        await on_message(update, ctx)
    update.effective_message.reply_text.assert_called_once_with("ok")


async def test_reply_to_with_delete_removes_that_entry(settings):
    """LLM context includes the original bot message so it can act on it."""
    from app.bot_v2 import on_message
    from app.router import RouterResult
    from app.session import SessionBuffer
    buf = SessionBuffer()
    update = _make_update("undo", user_id=42, reply_to_text="✅ Logged: dal chawal (id=5)")
    ctx = _make_context(settings)
    with patch("app.bot_v2.route", new=AsyncMock(return_value=RouterResult("🗑️ Deleted", "delete_food"))):
        with patch("app.bot_v2._session_buffer", buf):
            await on_message(update, ctx)
    # verify the original message was injected into buffer before routing
    msgs = buf.get(42)
    assert any("dal chawal" in m["content"] for m in msgs)
