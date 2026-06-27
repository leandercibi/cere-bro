from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.tools.registry import ToolDef
from lib.config import Settings
from lib.integrations.tavily import search as tavily_search
from lib.sinks import notion


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def _ideas_dir(settings: Settings) -> Path:
    d = settings.vault_root / "ideas"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _idea_path(settings: Settings, slug: str) -> Path:
    return _ideas_dir(settings) / f"{slug}.md"


async def capture_idea(
    title: str,
    description: str | None = None,
    tags: list | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    slug = _slug(title)
    path = _idea_path(settings, slug)
    # handle slug collision
    if path.exists():
        suffix = 1
        while path.exists():
            path = _idea_path(settings, f"{slug}-{suffix}")
            suffix += 1
        slug = path.stem

    tag_str = " ".join(f"#{t}" for t in (tags or []))
    now = datetime.now(settings.tz).isoformat()
    content = f"# {title}\n\ntags: {tag_str}\ncreated: {now}\n\n## Spark\n\n{description or ''}\n\n## Brief\n\n_not yet researched_\n"
    path.write_text(content, encoding="utf-8")
    await notion.push_idea(
        settings,
        slug=slug,
        title=title,
        description=description,
        tags=tags or [],
        created_at=datetime.now(settings.tz),
    )
    return {"slug": slug, "path": str(path), "title": title}


async def deepdive_idea(
    title_hint: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    ideas_dir = _ideas_dir(settings)
    all_files = sorted(ideas_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not title_hint:
        recent = [p.stem for p in all_files[:5]]
        return {"action": "list", "ideas": recent}

    hint_norm = title_hint.lower().replace(" ", "-")
    matches = [p for p in all_files if hint_norm in p.stem.lower() or title_hint.lower() in p.stem.lower().replace("-", " ")]
    if len(matches) > 1:
        return {"action": "disambiguation", "matches": [p.stem for p in matches]}
    if len(matches) == 0:
        result = await capture_idea(title_hint, user_id=user_id, settings=settings)
        slug = result["slug"]
        path = Path(result["path"])
    else:
        path = matches[0]
        slug = path.stem
        text = path.read_text(encoding="utf-8")
        if "## Brief" in text and "_not yet researched_" not in text:
            return {"action": "existing_brief", "slug": slug}

    results = await tavily_search(settings.tavily_api_key, title_hint or slug, max_results=5)
    brief = _format_brief(results)
    text = path.read_text(encoding="utf-8")
    text = text.replace("_not yet researched_", brief)
    path.write_text(text, encoding="utf-8")
    return {"action": "researched", "slug": slug, "sources": len(results)}


def _format_brief(results: list[dict]) -> str:
    lines = []
    for r in results:
        lines.append(f"- [{r.get('title', r['url'])}]({r['url']}): {r.get('content', '')[:200]}")
    return "\n".join(lines) or "_no results found_"


TOOLS: list[ToolDef] = [
    ToolDef(
        name="capture_idea",
        description="Capture a new idea or project. ALWAYS use this when message contains '#idea' or starts with 'idea:'. Do not respond with plain text.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
        handler=capture_idea,
    ),
    ToolDef(
        name="deepdive_idea",
        description="Research an idea via web search.",
        parameters={
            "type": "object",
            "properties": {"title_hint": {"type": "string"}},
        },
        handler=deepdive_idea,
    ),
]
