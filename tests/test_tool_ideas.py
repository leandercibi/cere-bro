from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.tools.ideas import capture_idea, deepdive_idea
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
        TAVILY_API_KEY="x",
        DB_PATH=tmp_path / "test.sqlite",
        VAULT_ROOT=vault,
        TIMEZONE="UTC",
    )


async def test_capture_idea_creates_file_with_template(settings):
    result = await capture_idea("build a sleep tracker", user_id=1, settings=settings)
    path = Path(result["path"])
    assert path.exists()
    text = path.read_text()
    assert "# build a sleep tracker" in text
    assert "## Spark" in text
    assert "## Brief" in text


async def test_capture_idea_with_description_and_tags(settings):
    result = await capture_idea("oura api project", description="Track sleep stages", tags=["health"], user_id=1, settings=settings)
    text = Path(result["path"]).read_text()
    assert "Track sleep stages" in text
    assert "#health" in text


async def test_capture_idea_slug_collision_appends_suffix(settings):
    await capture_idea("my idea", user_id=1, settings=settings)
    result2 = await capture_idea("my idea", user_id=1, settings=settings)
    assert result2["slug"] != "my-idea"
    assert Path(result2["path"]).exists()


async def test_capture_idea_returns_slug_and_path(settings):
    result = await capture_idea("test idea", user_id=1, settings=settings)
    assert "slug" in result
    assert "path" in result
    assert result["slug"] == "test-idea"


async def test_deepdive_no_hint_lists_recent_ideas(settings):
    await capture_idea("idea one", user_id=1, settings=settings)
    await capture_idea("idea two", user_id=1, settings=settings)
    result = await deepdive_idea(user_id=1, settings=settings)
    assert result["action"] == "list"
    assert len(result["ideas"]) >= 2


async def test_deepdive_multiple_matches_returns_disambiguation_list(settings):
    await capture_idea("predict workout times", user_id=1, settings=settings)
    await capture_idea("predict sleep times", user_id=1, settings=settings)
    result = await deepdive_idea("predict", user_id=1, settings=settings)
    assert result["action"] == "disambiguation"
    assert len(result["matches"]) == 2


async def test_deepdive_single_match_runs_research(settings):
    await capture_idea("sleep tracker oura", user_id=1, settings=settings)
    mock_results = [{"title": "Oura Ring", "url": "https://example.com", "content": "sleep data"}]
    with patch("app.tools.ideas.tavily_search", new=AsyncMock(return_value=mock_results)):
        result = await deepdive_idea("sleep tracker", user_id=1, settings=settings)
    assert result["action"] == "researched"
    assert result["sources"] == 1


async def test_deepdive_no_match_creates_then_researches(settings):
    mock_results = [{"title": "Result", "url": "https://example.com", "content": "info"}]
    with patch("app.tools.ideas.tavily_search", new=AsyncMock(return_value=mock_results)):
        result = await deepdive_idea("brand new concept", user_id=1, settings=settings)
    assert result["action"] == "researched"
    # file was created
    ideas_dir = settings.vault_root / "ideas"
    assert any(ideas_dir.glob("*.md"))


async def test_deepdive_already_researched_returns_existing_brief(settings):
    await capture_idea("existing idea", user_id=1, settings=settings)
    # manually write a brief
    path = settings.vault_root / "ideas" / "existing-idea.md"
    text = path.read_text().replace("_not yet researched_", "Already researched content here.")
    path.write_text(text)
    result = await deepdive_idea("existing idea", user_id=1, settings=settings)
    assert result["action"] == "existing_brief"


async def test_deepdive_appends_brief_to_vault_file(settings):
    await capture_idea("new concept", user_id=1, settings=settings)
    mock_results = [{"title": "R", "url": "https://x.com", "content": "detail"}]
    with patch("app.tools.ideas.tavily_search", new=AsyncMock(return_value=mock_results)):
        await deepdive_idea("new concept", user_id=1, settings=settings)
    path = settings.vault_root / "ideas" / "new-concept.md"
    assert "_not yet researched_" not in path.read_text()
