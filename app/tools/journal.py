from __future__ import annotations

from datetime import datetime

from app.tools.registry import ToolDef
from lib.config import Settings
from lib.sinks.obsidian import ensure_daily_note
from lib.sinks import notion


async def log_journal(
    entry: str,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    now = datetime.now(settings.tz)
    path = ensure_daily_note(settings.vault_root, now.date())
    text = path.read_text(encoding="utf-8")
    journal_line = f"\n> {entry}\n"
    text = (
        text + journal_line
        if "## Journal" in text
        else text + f"\n## Journal\n{journal_line}"
    )
    path.write_text(text, encoding="utf-8")
    await notion.push_journal(settings, date_str=now.date().isoformat(), entry=entry)
    return {"logged": True, "date": now.date().isoformat()}


TOOLS: list[ToolDef] = [
    ToolDef(
        name="log_journal",
        description="Log a journal entry for today.",
        parameters={
            "type": "object",
            "properties": {"entry": {"type": "string"}},
            "required": ["entry"],
        },
        handler=log_journal,
    ),
]
