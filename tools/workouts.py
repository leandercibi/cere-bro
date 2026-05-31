"""Workout tools — Hevy sync, profile management, workout queries.

Wraps existing business logic from app/domains/workout.py.
"""
from datetime import datetime, timedelta

from hermes.tools import tool

from tools._shared import get_conn, get_settings

# Import existing workout domain logic
from lib.domains.workout import (
    sync_workouts,
    handle_workout_note as _handle_workout_note,
    handle_profile_command as _handle_profile_command,
    get_profile_text,
    _format_sync_line,
    _format_summary_inline,
)
from lib.db import get_workouts_after


@tool(
    name="hevy_sync",
    description=(
        "Pull new workouts from Hevy and save them to the database and vault. "
        "Call when the user mentions finishing a workout, sends '/sync', or on nightly cron."
    ),
)
async def hevy_sync() -> str:
    """Sync workouts from Hevy API, store in DB and write to Obsidian vault.
    
    Returns:
        Confirmation message with sync summary (markdown formatted for Telegram).
    """
    settings = get_settings()
    try:
        result = await sync_workouts(settings)
        return f"🏋️ {_format_sync_line(result)}"
    except Exception as e:
        return f"⚠️ Sync failed: {e}"


@tool(
    name="log_workout_note",
    description=(
        "Append a user narrative note to today's Obsidian daily note for the workout section. "
        "Also triggers a Hevy sync. Use when the user describes how a workout felt — "
        "e.g. 'felt strong today, hit a PR on bench'."
    ),
)
async def log_workout_note(note: str) -> str:
    """Sync workouts and append a narrative note to today's daily note.
    
    Args:
        note: User's narrative about the workout (e.g., "felt strong, fasted").
    
    Returns:
        Confirmation message with sync summary and note confirmation (markdown formatted).
    """
    settings = get_settings()
    try:
        return await _handle_workout_note("", note, settings)
    except Exception as e:
        return f"⚠️ Failed to log workout note: {e}"


@tool(
    name="update_profile",
    description=(
        "Update the user's physical profile (height, weight, age, sex). "
        "Use for '/profile weight=73' or 'I weigh 73 kg now'. "
        "Recalculates BMR and retroactively updates calories for all stored workouts."
    ),
)
async def update_profile(
    weight_kg: float | None = None,
    height_cm: float | None = None,
    age: int | None = None,
    sex: str | None = None,
) -> str:
    """Update user profile and recompute workout calories.
    
    Args:
        weight_kg: Weight in kilograms (optional).
        height_cm: Height in centimeters (optional).
        age: Age in years (optional).
        sex: Biological sex, 'M' or 'F' (optional).
    
    Returns:
        Confirmation message with updated profile and BMR (markdown formatted).
    """
    settings = get_settings()
    
    # Build args string in the format expected by handle_profile_command
    args_parts = []
    if weight_kg is not None:
        args_parts.append(f"weight={weight_kg}")
    if height_cm is not None:
        args_parts.append(f"height={height_cm}")
    if age is not None:
        args_parts.append(f"age={age}")
    if sex is not None:
        args_parts.append(f"sex={sex}")
    
    args_text = " ".join(args_parts)
    
    # If no args provided, return current profile
    if not args_text:
        return await get_profile_text(settings)
    
    try:
        return await _handle_profile_command(args_text, settings)
    except Exception as e:
        return f"⚠️ Failed to update profile: {e}"


@tool(
    name="query_workouts",
    description=(
        "Show recent workout history from the local SQLite database. "
        "Use for 'show my workouts', 'what did I do last week', etc."
    ),
)
async def query_workouts(days: int = 7) -> str:
    """Query recent workouts from the database.
    
    Args:
        days: Number of days to look back (default: 7).
    
    Returns:
        Formatted list of recent workouts (markdown formatted for Telegram).
    """
    settings = get_settings()
    conn = get_conn()
    
    try:
        cutoff = datetime.now(settings.tz) - timedelta(days=days)
        workouts = get_workouts_after(conn, cutoff)
        
        if not workouts:
            return f"📊 No workouts found in the last {days} day{'s' if days != 1 else ''}."
        
        lines = [f"🏋️ **Workouts (last {days} day{'s' if days != 1 else ''})**\n"]
        for w in workouts:
            date_str = w.started_at.strftime("%b %d")
            summary = _format_summary_inline(w)
            lines.append(f"• {date_str} — {summary}")
        
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Failed to query workouts: {e}"
    finally:
        conn.close()
