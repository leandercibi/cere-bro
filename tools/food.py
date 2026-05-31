"""Food logging tools for Hermes Agent.

Wraps cere-bro food domain logic as @tool decorated functions.
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

from lib.models import FoodItem
from tools._shared import get_conn, get_settings
from tools._food_helpers import (
    handle_food_log_insert,
    handle_food_log_edit,
    handle_food_delete,
    handle_food_query,
)


@tool(
    name="log_food",
    description=(
        "Log a meal, snack, or drink. Use when the user mentions eating or drinking "
        "anything. Extract items and quantities from natural language. "
        "Returns a confirmation message with estimated calories and macros."
    ),
)
async def log_food(
    raw_text: str,
    items: list[dict],  # [{name: str, quantity: str | None}]
    junk: bool = False,
    logged_at: str | None = None,
) -> str:
    """Insert food log → SQLite + Obsidian daily note. Returns confirmation.
    
    Args:
        raw_text: The original user message text
        items: List of food items, each with 'name' and optional 'quantity'
        junk: True if this is junk food (user mentioned #junk)
        logged_at: ISO timestamp string when food was eaten (None = now)
    
    Returns:
        Markdown-formatted confirmation message for Telegram
    """
    settings = get_settings()
    conn = await asyncio.to_thread(get_conn)
    
    try:
        # Convert dict items to FoodItem models
        food_items = [FoodItem(**item) for item in items]
        
        # Parse logged_at timestamp or use now
        if logged_at:
            logged_at_dt = datetime.fromisoformat(logged_at)
        else:
            logged_at_dt = datetime.now(settings.tz)
        
        # Use a placeholder user_id and telegram_message_id for Hermes context
        # In production, these would come from the Hermes session context
        user_id = settings.telegram_allowed_user_id
        telegram_message_id = 0  # Hermes doesn't use Telegram message IDs
        
        result = await handle_food_log_insert(
            conn=conn,
            user_id=user_id,
            telegram_message_id=telegram_message_id,
            raw_text=raw_text,
            items=food_items,
            junk=junk,
            logged_at=logged_at_dt,
            settings=settings,
        )
        
        return result
    finally:
        conn.close()


@tool(
    name="edit_food",
    description=(
        "Edit a specific food log entry by ID. Use when the user wants to correct "
        "or update a previously logged meal. Returns updated confirmation message."
    ),
)
async def edit_food(
    food_log_id: int,
    raw_text: str,
    items: list[dict],  # [{name: str, quantity: str | None}]
    junk: bool = False,
    logged_at: str | None = None,
) -> str:
    """Edit an existing food log entry. Returns confirmation.
    
    Args:
        food_log_id: The ID of the food log entry to edit
        raw_text: The updated user message text
        items: Updated list of food items
        junk: Updated junk food flag
        logged_at: Updated ISO timestamp (None = keep original time)
    
    Returns:
        Markdown-formatted confirmation message for Telegram
    """
    settings = get_settings()
    conn = await asyncio.to_thread(get_conn)
    
    try:
        # Convert dict items to FoodItem models
        food_items = [FoodItem(**item) for item in items]
        
        # Parse logged_at timestamp or use now
        if logged_at:
            logged_at_dt = datetime.fromisoformat(logged_at)
        else:
            logged_at_dt = datetime.now(settings.tz)
        
        result = await handle_food_log_edit(
            conn=conn,
            food_log_id=food_log_id,
            raw_text=raw_text,
            items=food_items,
            junk=junk,
            logged_at=logged_at_dt,
            settings=settings,
        )
        
        return result
    finally:
        conn.close()


@tool(
    name="delete_food",
    description=(
        "Delete a food log entry. Use when the user says 'undo', 'remove', "
        "'delete that', or refers to a specific logged item to remove. "
        "Can delete by ID, by item name hint, or the most recent entry."
    ),
)
async def delete_food(
    food_log_id: int | None = None,
    item_hint: str | None = None,
) -> str:
    """Delete a food log entry. Returns confirmation.
    
    Args:
        food_log_id: Specific food log ID to delete (takes precedence)
        item_hint: Food item name to search for (e.g., 'samosa')
                   If neither provided, deletes the most recent entry
    
    Returns:
        Markdown-formatted confirmation message for Telegram
    """
    settings = get_settings()
    conn = await asyncio.to_thread(get_conn)
    
    try:
        user_id = settings.telegram_allowed_user_id
        
        result = await handle_food_delete(
            conn=conn,
            user_id=user_id,
            food_log_id=food_log_id,
            item_hint=item_hint,
            settings=settings,
        )
        
        return result
    finally:
        conn.close()


@tool(
    name="query_food",
    description=(
        "Query food logs and macro totals. Use for 'calories today', "
        "'what did I eat yesterday', 'show macros for last week', "
        "'calorie breakdown', 'macro breakdown', etc. "
        "Returns detailed breakdown with calories, protein, fat, and carbs."
    ),
)
async def query_food(
    scope: str = "today",  # today | yesterday | last | by_date | matching
    day: str | None = None,  # ISO date for scope=by_date
    item_hint: str | None = None,  # food name for scope=matching
) -> str:
    """Query food logs and return macro breakdown.
    
    Args:
        scope: Query scope - 'today', 'yesterday', 'last' (most recent),
               'by_date' (specific date), or 'matching' (search by item)
        day: ISO date string (YYYY-MM-DD) when scope='by_date'
        item_hint: Food item name to search for when scope='matching'
    
    Returns:
        Markdown-formatted breakdown with calories and macros for Telegram
    """
    settings = get_settings()
    conn = await asyncio.to_thread(get_conn)
    
    try:
        user_id = settings.telegram_allowed_user_id
        now = datetime.now(settings.tz)
        
        # Parse day if provided
        day_dt = None
        if day:
            day_dt = datetime.fromisoformat(day)
        
        result = await handle_food_query(
            conn=conn,
            user_id=user_id,
            scope=scope,
            day=day_dt,
            item_hint=item_hint,
            now=now,
            settings=settings,
        )
        
        return result
    finally:
        conn.close()
