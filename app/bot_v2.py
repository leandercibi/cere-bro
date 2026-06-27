from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.router import route, _session_buffer
from lib.config import Settings

logger = logging.getLogger(__name__)

_HELP = (
    "👋 I'm Cerebro. I understand natural language.\n\n"
    "Examples:\n"
    "• had dal chawal for lunch\n"
    "• delete last entry\n"
    "• calories today\n"
    "• workout done, felt strong\n"
    "• #idea build a sleep tracker\n"
    "• #task submit invoice by Friday\n"
    "• tired today (journal)\n"
)


async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(_HELP)


async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = ctx.bot_data["settings"]
    user_id = update.effective_user.id

    if user_id != settings.telegram_allowed_user_id:
        return

    text = update.effective_message.text or ""

    # Inject reply-to context into session buffer before routing
    reply_to = update.effective_message.reply_to_message
    if reply_to and reply_to.text:
        _session_buffer.add(user_id, "assistant", reply_to.text)

    try:
        result = await route(text, user_id=user_id, settings=settings)
        await update.effective_message.reply_text(result.reply_text)
    except Exception:
        logger.exception("Unhandled error in on_message")
        await update.effective_message.reply_text("Something went wrong. Please try again.")


def build_app(settings: Settings) -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app


if __name__ == "__main__":
    from lib.config import get_settings
    s = get_settings()
    build_app(s).run_polling()
