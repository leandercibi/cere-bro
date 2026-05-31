"""Private helper functions for food domain logic.

Extracted from cere-bro/app/domains/food.py. These functions contain the
core business logic for food logging, editing, deleting, and querying.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Make the existing cere-bro app importable
_CEREBRO_ROOT = Path(__file__).resolve().parent.parent.parent / "cere-bro"
if str(_CEREBRO_ROOT) not in sys.path:
    sys.path.insert(0, str(_CEREBRO_ROOT))

from lib.config import Settings
from lib.db import (
    _row_to_food_log,
    delete_food_log,
    find_recent_food_log_by_item,
    get_daily_totals,
    get_food_logs_for_day,
    get_last_food_log,
    insert_food_log,
    recompute_daily_totals,
    set_food_macros,
    set_obsidian_anchor,
    update_food_log,
)
from lib.models import FoodItem, FoodLog
from lib.sinks.obsidian import (
    append_food,
    ensure_daily_note,
    remove_food,
    update_food,
)
from tools._llm_utils import estimate_calories

logger = logging.getLogger("cerebro.food")


def _build_items_str(items: list[FoodItem]) -> str:
    """Render items as a comma-separated 'name (qty)' / 'name' list."""
    parts: list[str] = []
    for it in items:
        if it.quantity:
            parts.append(f"{it.name} ({it.quantity})")
        else:
            parts.append(it.name)
    return ", ".join(parts)


def _format_log_summary(fl: FoodLog) -> str:
    """One-line summary used in confirmation replies."""
    hhmm = fl.logged_at.strftime("%H:%M")
    base = f"{hhmm} — {_build_items_str(fl.items)}"
    if fl.junk:
        base += " ⚠️ junk"
    if fl.est_calories_kcal is not None:
        base += f" · ~{fl.est_calories_kcal} kcal"
    if (
        fl.est_protein_g is not None
        and fl.est_fat_g is not None
        and fl.est_carbs_g is not None
    ):
        base += (
            f" · {round(fl.est_protein_g)}p"
            f" {round(fl.est_fat_g)}f"
            f" {round(fl.est_carbs_g)}c"
        )
    return base


async def _estimate_and_persist_calories(
    conn: sqlite3.Connection,
    fl: FoodLog,
    settings: Settings,
) -> None:
    """Best-effort full-macro estimate for a freshly inserted/updated food_log.

    Mutates `fl` in place (sets est_calories_kcal, est_protein_g, est_fat_g,
    est_carbs_g, est_calories_items_json) so downstream renderers see the
    values. On failure, all four numeric fields go to None and the row's
    columns are cleared — important on edits where stale values from before
    the edit must not be rendered against the new items.
    """
    if not fl.items:
        await asyncio.to_thread(
            set_food_macros,
            conn,
            fl.id,
            est_calories_kcal=None,
            est_protein_g=None,
            est_fat_g=None,
            est_carbs_g=None,
            est_calories_items_json=None,
        )
        fl.est_calories_kcal = None
        fl.est_calories_items_json = None
        fl.est_protein_g = None
        fl.est_fat_g = None
        fl.est_carbs_g = None
        return
    try:
        est = await estimate_calories(fl.items, settings)
    except Exception:
        logger.exception("estimate_macros failed for food_log id=%s", fl.id)
        await asyncio.to_thread(
            set_food_macros,
            conn,
            fl.id,
            est_calories_kcal=None,
            est_protein_g=None,
            est_fat_g=None,
            est_carbs_g=None,
            est_calories_items_json=None,
        )
        fl.est_calories_kcal = None
        fl.est_calories_items_json = None
        fl.est_protein_g = None
        fl.est_fat_g = None
        fl.est_carbs_g = None
        return
    items_json = json.dumps([i.model_dump() for i in est.items])
    await asyncio.to_thread(
        set_food_macros,
        conn,
        fl.id,
        est_calories_kcal=est.total_kcal,
        est_protein_g=est.total_protein_g,
        est_fat_g=est.total_fat_g,
        est_carbs_g=est.total_carbs_g,
        est_calories_items_json=items_json,
    )
    fl.est_calories_kcal = est.total_kcal
    fl.est_calories_items_json = items_json
    fl.est_protein_g = est.total_protein_g
    fl.est_fat_g = est.total_fat_g
    fl.est_carbs_g = est.total_carbs_g


def _fetch_food_log_by_id(
    conn: sqlite3.Connection, food_log_id: int
) -> FoodLog | None:
    """Fetch a food log by ID."""
    row = conn.execute(
        "SELECT * FROM food_logs WHERE id = ?", (food_log_id,)
    ).fetchone()
    return _row_to_food_log(row) if row is not None else None


async def _macros_for_log(
    log: FoodLog, settings: Settings
) -> dict[str, int | float | None]:
    """Return a dict with keys {kcal, protein_g, fat_g, carbs_g}.

    Prefers stored values from the food_log row (cheap, deterministic, matches
    what's rendered in the daily note). When the stored fields are absent
    OR a row predates the macros column AND the items_json has no protein
    breakdown, falls back to a live LLM `estimate_calories` call — only for
    that row.
    """
    if (
        log.est_calories_kcal is not None
        and log.est_protein_g is not None
        and log.est_fat_g is not None
        and log.est_carbs_g is not None
    ):
        return {
            "kcal": log.est_calories_kcal,
            "protein_g": log.est_protein_g,
            "fat_g": log.est_fat_g,
            "carbs_g": log.est_carbs_g,
        }
    # Live fallback (best-effort; missing data must not crash the query).
    try:
        est = await estimate_calories(log.items, settings)
    except Exception:
        logger.exception(
            "live estimate_calories failed during macro_query for log id=%s", log.id
        )
        return {
            "kcal": log.est_calories_kcal,  # may still be set even if macros are NULL
            "protein_g": None,
            "fat_g": None,
            "carbs_g": None,
        }
    return {
        "kcal": est.total_kcal,
        "protein_g": est.total_protein_g,
        "fat_g": est.total_fat_g,
        "carbs_g": est.total_carbs_g,
    }


async def handle_food_log_insert(
    conn: sqlite3.Connection,
    user_id: int,
    telegram_message_id: int,
    raw_text: str,
    items: list[FoodItem],
    junk: bool,
    logged_at: datetime,
    settings: Settings,
) -> str:
    """Insert a new food log entry. Returns confirmation message."""
    await asyncio.to_thread(ensure_daily_note, settings.vault_root, logged_at.date())
    fl = await asyncio.to_thread(
        insert_food_log,
        conn,
        user_id=user_id,
        raw_text=raw_text,
        items=items,
        junk=junk,
        logged_at=logged_at,
        telegram_message_id=telegram_message_id,
    )
    # Estimate before the Obsidian write so the line includes the kcal segment
    # on first render. Failure here is non-fatal — the food row stays valid
    # and the line just lacks the kcal segment.
    await _estimate_and_persist_calories(conn, fl, settings)
    anchor = await asyncio.to_thread(append_food, settings.vault_root, fl)
    await asyncio.to_thread(set_obsidian_anchor, conn, fl.id, anchor)
    fl.obsidian_anchor = anchor
    await asyncio.to_thread(recompute_daily_totals, conn, fl.logged_at.date())

    return "✅ logged " + _format_log_summary(fl)


async def handle_food_log_edit(
    conn: sqlite3.Connection,
    food_log_id: int,
    raw_text: str,
    items: list[FoodItem],
    junk: bool,
    logged_at: datetime,
    settings: Settings,
) -> str:
    """Edit an existing food log entry. Returns confirmation message."""
    # Fetch the original log to get the original day
    original_log = _fetch_food_log_by_id(conn, food_log_id)
    if original_log is None:
        return f"⚠️ food log id={food_log_id} not found"
    
    original_day = original_log.logged_at.date()
    updated = await asyncio.to_thread(
        update_food_log,
        conn,
        food_log_id,
        raw_text=raw_text,
        items=items,
        junk=junk,
        logged_at=logged_at,
    )
    # Items changed — stale macros from the original log must not be reused.
    # _estimate_and_persist_calories rewrites the DB row and mutates
    # `updated` so the Obsidian re-render below picks up the new values.
    await _estimate_and_persist_calories(conn, updated, settings)
    await asyncio.to_thread(update_food, settings.vault_root, updated)
    # Refresh daily_totals: rare but the user may have moved the entry to
    # a different day via reply-edit, so cover both old and new dates.
    await asyncio.to_thread(
        recompute_daily_totals, conn, updated.logged_at.date()
    )
    if original_day != updated.logged_at.date():
        await asyncio.to_thread(recompute_daily_totals, conn, original_day)
    return "✏️ updated " + _format_log_summary(updated)


async def handle_food_delete(
    conn: sqlite3.Connection,
    user_id: int,
    food_log_id: int | None,
    item_hint: str | None,
    settings: Settings,
) -> str:
    """Delete a food log entry. Returns confirmation message."""
    target: FoodLog | None = None
    
    if food_log_id is not None:
        target = _fetch_food_log_by_id(conn, food_log_id)
        if target is None:
            return f"⚠️ food log id={food_log_id} not found"
    elif item_hint:
        target = await asyncio.to_thread(
            find_recent_food_log_by_item, conn, user_id, item_hint
        )
        if target is None:
            return f'⚠️ no recent entry matching "{item_hint}"'
    else:
        target = await asyncio.to_thread(get_last_food_log, conn, user_id)
        if target is None:
            return "⚠️ nothing to delete — no entries yet"

    await asyncio.to_thread(remove_food, settings.vault_root, target)
    await asyncio.to_thread(delete_food_log, conn, target.id)
    await asyncio.to_thread(
        recompute_daily_totals, conn, target.logged_at.date()
    )
    return "🗑️ removed " + _format_log_summary(target)


async def handle_food_query(
    conn: sqlite3.Connection,
    user_id: int,
    scope: str,
    day: datetime | None,
    item_hint: str | None,
    now: datetime,
    settings: Settings,
) -> str:
    """Query food logs and macro totals. Returns formatted breakdown."""
    logs: list[FoodLog]
    header: str

    if scope == "last":
        last = await asyncio.to_thread(get_last_food_log, conn, user_id)
        logs = [last] if last is not None else []
        header = "most recent"
    elif scope == "today":
        logs = await asyncio.to_thread(
            get_food_logs_for_day, conn, user_id, now.date()
        )
        header = "today"
    elif scope == "yesterday":
        yday = (now - timedelta(days=1)).date()
        logs = await asyncio.to_thread(
            get_food_logs_for_day, conn, user_id, yday
        )
        header = "yesterday"
    elif scope == "by_date" and day is not None:
        logs = await asyncio.to_thread(
            get_food_logs_for_day, conn, user_id, day.date()
        )
        header = day.date().isoformat()
    elif scope == "matching" and item_hint:
        match = await asyncio.to_thread(
            find_recent_food_log_by_item, conn, user_id, item_hint
        )
        logs = [match] if match is not None else []
        header = f"most recent {item_hint}"
    else:
        logs = []
        header = "unknown"

    if not logs:
        return "⚠️ no entries found for that query"

    # Header includes the latest entry's HH:MM so the user knows the cutoff.
    last_hhmm = logs[-1].logged_at.strftime("%H:%M")
    reply_lines: list[str] = [f"📊 {header} (up to {last_hhmm})"]

    for log in logs:
        macros = await _macros_for_log(log, settings)
        hhmm = log.logged_at.strftime("%H:%M")
        items_summary = _build_items_str(log.items)
        junk_marker = " #junk" if log.junk else ""
        kcal_seg = (
            f" · {macros['kcal']} kcal" if macros["kcal"] is not None else ""
        )
        reply_lines.append(
            f"\n{hhmm} — {items_summary}{junk_marker}{kcal_seg}"
        )
        if macros["protein_g"] is not None:
            reply_lines.append(
                f"  · {round(macros['protein_g'])}g protein "
                f"· {round(macros['fat_g'])}g fat "
                f"· {round(macros['carbs_g'])}g carbs"
            )

    # Daily total line. We pick the day of the latest entry shown; for
    # multi-day scopes (rare) we sum what we displayed instead of relying on
    # the cache, since the cache is per-day.
    days_shown = {log.logged_at.date() for log in logs}
    if len(days_shown) == 1:
        only_day = next(iter(days_shown))
        totals = await asyncio.to_thread(get_daily_totals, conn, only_day)
        if totals is not None:
            reply_lines.append(
                f"\n─────\ntotal · {totals.total_kcal} kcal · "
                f"{round(totals.total_protein_g)}p "
                f"· {round(totals.total_fat_g)}f "
                f"· {round(totals.total_carbs_g)}c"
            )
    elif len(days_shown) > 1:
        # Fall back to summing rendered values when the query straddles days.
        sum_kcal = sum(log.est_calories_kcal or 0 for log in logs)
        sum_p = sum(log.est_protein_g or 0 for log in logs)
        sum_f = sum(log.est_fat_g or 0 for log in logs)
        sum_c = sum(log.est_carbs_g or 0 for log in logs)
        reply_lines.append(
            f"\n─────\ntotal · {sum_kcal} kcal · "
            f"{round(sum_p)}p · {round(sum_f)}f · {round(sum_c)}c"
        )

    reply_lines.append("(rough estimate)")
    return "\n".join(reply_lines)
