"""Obsidian vault query tools for Hermes agent."""
from pathlib import Path

from hermes.tools import tool
from tools._shared import VAULT_ROOT


@tool(
    name="obsidian_query",
    description=(
        "Read content from the Obsidian vault. Use to look up a daily note, "
        "an idea file, or the journal. Returns markdown text."
    ),
)
async def obsidian_query(
    path: str,  # relative to vault root, e.g. "daily/2026-05-30.md" or "ideas/sleep-tracker.md"
) -> str:
    """Read a file from the Obsidian vault."""
    target = VAULT_ROOT / path
    if not target.exists():
        return f"⚠️ file not found: {path}"
    if not target.is_file():
        return f"⚠️ not a file: {path}"
    return target.read_text(encoding="utf-8")


@tool(
    name="obsidian_list_daily",
    description="List available daily note dates. Returns recent daily notes in reverse chronological order.",
)
async def obsidian_list_daily(last_n: int = 7) -> str:
    """List recent daily notes."""
    daily_dir = VAULT_ROOT / "daily"
    if not daily_dir.exists():
        return "📂 no daily notes directory yet"
    
    files = sorted(daily_dir.glob("*.md"), reverse=True)[:last_n]
    if not files:
        return "📂 no daily notes yet"
    
    return "📅 **Recent daily notes:**\n" + "\n".join(f"- {f.stem}" for f in files)
