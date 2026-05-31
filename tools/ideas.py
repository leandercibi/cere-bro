"""Ideas tools for Hermes Agent.

Wraps cere-bro ideas domain logic as @tool decorated functions.
Returns markdown-formatted strings for Telegram display.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from hermes.tools import tool

# Make the existing cere-bro app importable
_CEREBRO_ROOT = Path(__file__).resolve().parent.parent.parent / "cere-bro"
if str(_CEREBRO_ROOT) not in sys.path:
    sys.path.insert(0, str(_CEREBRO_ROOT))

from lib.domains.ideas import (
    handle_idea_capture,
    handle_idea_deepdive,
    find_ideas_by_hint,
    list_latest_ideas,
    _parse_frontmatter,
    _write_frontmatter,
    _bump_updated,
)
from lib.models import IdeaCapturePayload, IdeaDeepdivePayload
from tools._shared import get_settings


@tool(
    name="capture_idea",
    description=(
        "Capture a new idea to the vault. Creates a structured markdown file "
        "with stages (ideation, research, breakdowns, feasibility, decision). "
        "Use when the user mentions a new idea, concept, or project they want to track."
    ),
)
async def capture_idea(
    title: str,
    description: str | None = None,
    tags: list[str] | None = None,
) -> str:
    """Create a new idea file in vault/ideas/.
    
    Args:
        title: The idea title (will be slugified for filename)
        description: Optional description of the idea
        tags: Optional list of tags
    
    Returns:
        Markdown-formatted confirmation message for Telegram
    """
    settings = get_settings()
    
    payload = IdeaCapturePayload(
        title=title,
        description=description,
        tags=tags or [],
    )
    
    result = await handle_idea_capture(payload, settings)
    return result


@tool(
    name="append_idea",
    description=(
        "Append text to an existing idea file. Finds the idea by fuzzy matching "
        "the title hint, then appends the text to the specified stage section. "
        "Use when the user wants to add notes to an existing idea."
    ),
)
async def append_idea(
    title_hint: str,
    text: str,
    stage: str = "ideation",
) -> str:
    """Append text to an existing idea's stage section.
    
    Args:
        title_hint: Partial title or slug to match the idea
        text: Text to append (will be formatted as a bullet point)
        stage: Stage section to append to (ideation, early-stage, research, 
               breakdowns, feasibility, decision)
    
    Returns:
        Markdown-formatted confirmation message for Telegram
    """
    settings = get_settings()
    vault_root = settings.vault_root
    
    # Fuzzy match the idea
    matches = await asyncio.to_thread(find_ideas_by_hint, vault_root, title_hint)
    
    if not matches:
        return f"⚠️ No idea found matching '{title_hint}'"
    
    if len(matches) > 1:
        lines = [f"🤔 Multiple ideas match '{title_hint}':"]
        for i, s in enumerate(matches, start=1):
            lines.append(f"{i}. {s.slug}")
        lines.append("\nPlease be more specific.")
        return "\n".join(lines)
    
    idea = matches[0]
    
    # Map stage name to section heading
    stage_map = {
        "ideation": "## 1. Ideation",
        "early-stage": "## 2. Early stage",
        "research": "## 3. Research",
        "breakdowns": "## 4. Breakdowns",
        "feasibility": "## 5. Feasibility",
        "decision": "## 6. Decision",
    }
    
    stage_heading = stage_map.get(stage.lower())
    if not stage_heading:
        return f"⚠️ Invalid stage '{stage}'. Valid: ideation, early-stage, research, breakdowns, feasibility, decision"
    
    # Read the file
    content = await asyncio.to_thread(idea.path.read_text)
    lines = content.splitlines(keepends=True)
    
    # Find the stage section
    section_start = None
    section_end = len(lines)
    
    for i, line in enumerate(lines):
        if line.strip() == stage_heading:
            section_start = i + 1
        elif section_start is not None and line.startswith("## ") and not line.startswith("### "):
            section_end = i
            break
    
    if section_start is None:
        return f"⚠️ Section '{stage}' not found in {idea.slug}"
    
    # Format the text as a bullet point if not already
    formatted_text = text.strip()
    if not formatted_text.startswith("- "):
        formatted_text = f"- {formatted_text}"
    if not formatted_text.endswith("\n"):
        formatted_text += "\n"
    
    # Insert the text at the end of the section
    lines.insert(section_end, formatted_text)
    
    # Write back
    new_content = "".join(lines)
    await asyncio.to_thread(idea.path.write_text, new_content)
    
    # Bump updated timestamp
    now = datetime.now(settings.tz)
    await asyncio.to_thread(_bump_updated, idea.path, now)
    
    return (
        f"✏️ appended to **{idea.title}**\n"
        f"_section:_ {stage}\n"
        f"📄 vault/ideas/{idea.slug}.md"
    )


@tool(
    name="advance_idea",
    description=(
        "Advance an idea to the next stage. Updates the status field in frontmatter. "
        "Use when the user wants to move an idea forward in the workflow."
    ),
)
async def advance_idea(
    title_hint: str,
    to_stage: str,
) -> str:
    """Advance an idea to a new stage by updating frontmatter status.
    
    Args:
        title_hint: Partial title or slug to match the idea
        to_stage: Target stage (ideation, early-stage, research, breakdowns, 
                  feasibility, decision)
    
    Returns:
        Markdown-formatted confirmation message for Telegram
    """
    settings = get_settings()
    vault_root = settings.vault_root
    
    # Fuzzy match the idea
    matches = await asyncio.to_thread(find_ideas_by_hint, vault_root, title_hint)
    
    if not matches:
        return f"⚠️ No idea found matching '{title_hint}'"
    
    if len(matches) > 1:
        lines = [f"🤔 Multiple ideas match '{title_hint}':"]
        for i, s in enumerate(matches, start=1):
            lines.append(f"{i}. {s.slug}")
        lines.append("\nPlease be more specific.")
        return "\n".join(lines)
    
    idea = matches[0]
    
    # Validate stage
    valid_stages = ["ideation", "early-stage", "research", "breakdowns", "feasibility", "decision"]
    normalized_stage = to_stage.lower()
    if normalized_stage not in valid_stages:
        return f"⚠️ Invalid stage '{to_stage}'. Valid: {', '.join(valid_stages)}"
    
    # Read and parse frontmatter
    content = await asyncio.to_thread(idea.path.read_text)
    fields, body = _parse_frontmatter(content)
    
    if not fields:
        return f"⚠️ No frontmatter found in {idea.slug}"
    
    old_status = fields.get("status", "unknown")
    
    # Update status field
    fields["status"] = normalized_stage
    
    # Write back
    new_content = _write_frontmatter(fields, body)
    await asyncio.to_thread(idea.path.write_text, new_content)
    
    # Bump updated timestamp
    now = datetime.now(settings.tz)
    await asyncio.to_thread(_bump_updated, idea.path, now)
    
    return (
        f"🚀 advanced **{idea.title}**\n"
        f"_{old_status}_ → _{normalized_stage}_\n"
        f"📄 vault/ideas/{idea.slug}.md"
    )


@tool(
    name="deepdive_idea",
    description=(
        "Research an idea using web search and AI synthesis. Spawns a background "
        "subagent to search Tavily and synthesize findings with DeepSeek. "
        "Writes results to the Research section of the idea file. "
        "Use when the user wants to research or explore an idea in depth."
    ),
)
async def deepdive_idea(
    title_hint: str | None = None,
) -> str:
    """Research an idea via Tavily search + DeepSeek synthesis.
    
    Note: This spawns a background subagent for the research pipeline.
    
    Args:
        title_hint: Partial title or slug to match the idea. If None, lists recent ideas.
    
    Returns:
        Markdown-formatted research brief or list of ideas for Telegram
    """
    settings = get_settings()
    
    payload = IdeaDeepdivePayload(title_hint=title_hint) if title_hint else None
    
    result = await handle_idea_deepdive(payload, settings)
    
    # The result has reply_text and optional pending_candidates
    # For Hermes, we'll just return the reply_text and ignore disambiguation
    # (the analyst report suggested simplifying to single-match only for v1)
    return result.reply_text


@tool(
    name="list_ideas",
    description=(
        "List recent ideas from the vault, ordered by most recently updated. "
        "Use when the user wants to see their ideas or browse what they've captured."
    ),
)
async def list_ideas(
    n: int = 5,
) -> str:
    """List the n most recently updated ideas.
    
    Args:
        n: Number of ideas to list (default: 5)
    
    Returns:
        Markdown-formatted list of ideas for Telegram
    """
    settings = get_settings()
    vault_root = settings.vault_root
    
    ideas = await asyncio.to_thread(list_latest_ideas, vault_root, n)
    
    if not ideas:
        return (
            "ℹ️ No ideas yet. Capture one with:\n"
            "'capture an idea about using my logs to predict best workout times'"
        )
    
    lines = [f"💡 **Latest {len(ideas)} ideas** (most recent first):"]
    for i, idea in enumerate(ideas, start=1):
        updated = idea.updated_at.strftime("%Y-%m-%d")
        lines.append(f"{i}. **{idea.title}**")
        lines.append(f"   _{idea.status}_ · updated {updated}")
    
    return "\n".join(lines)
