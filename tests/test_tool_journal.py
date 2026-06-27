from __future__ import annotations

from pathlib import Path

import pytest

from app.tools.journal import log_journal
from lib.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    vault = tmp_path / "vault"
    vault.mkdir()
    return Settings(
        _env_file=None,
        TELEGRAM_BOT_TOKEN="x",
        TELEGRAM_ALLOWED_USER_ID=1,
        OPENROUTER_API_KEY="x",
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=vault,
        TIMEZONE="UTC",
    )


async def test_log_journal_appends_to_daily_note(settings):
    result = await log_journal("tired today", user_id=1, settings=settings)
    assert result["logged"] is True
    notes = list(settings.vault_root.glob("**/*.md"))
    assert any("tired today" in p.read_text() for p in notes)


async def test_log_journal_creates_daily_note_if_missing(settings):
    notes_before = list(settings.vault_root.glob("**/*.md"))
    await log_journal("fresh entry", user_id=1, settings=settings)
    notes_after = list(settings.vault_root.glob("**/*.md"))
    assert len(notes_after) > len(notes_before)


async def test_log_journal_multiple_entries_append_sequentially(settings):
    await log_journal("entry one", user_id=1, settings=settings)
    await log_journal("entry two", user_id=1, settings=settings)
    notes = list(settings.vault_root.glob("**/*.md"))
    combined = " ".join(p.read_text() for p in notes)
    assert "entry one" in combined
    assert "entry two" in combined
