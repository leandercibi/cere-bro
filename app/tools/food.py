from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from zoneinfo import ZoneInfo

from dateutil import parser as dtparser

import app.db as db
from app.llm import estimate_macros
from app.tools.errors import ToolError
from app.tools.registry import ToolDef
from lib.config import Settings
from lib.models import FoodItem
from lib.sinks.obsidian import append_food, remove_food, update_food
from lib.sinks import notion


def _parse_time(time_str: str | None, tz: ZoneInfo) -> datetime:
    now = datetime.now(tz)
    if not time_str:
        return now
    try:
        parsed = dtparser.parse(time_str, default=now)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed
    except Exception:
        return now


def _open_conn(settings: Settings):
    return db.get_conn(settings.db_path)


async def log_food(
    items: list[dict],
    junk: bool = False,
    time: str | None = None,
    notes: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    logged_at = _parse_time(time, settings.tz)
    food_items = [FoodItem(name=i["name"], quantity=i.get("quantity")) for i in items]
    raw_text = ", ".join(
        f"{i.quantity} {i.name}" if i.quantity else i.name for i in food_items
    )
    conn = _open_conn(settings)
    try:
        log = db.insert_food_log(
            conn,
            user_id=user_id,
            raw_text=raw_text,
            items=food_items,
            junk=junk,
            logged_at=logged_at,
            telegram_message_id=None,
        )
        macros = await estimate_macros(items, settings)
        if macros:
            db.set_food_macros(
                conn,
                log.id,
                est_calories_kcal=macros.get("total_kcal"),
                est_protein_g=macros.get("total_protein_g"),
                est_fat_g=macros.get("total_fat_g"),
                est_carbs_g=macros.get("total_carbs_g"),
                est_calories_items_json=None,
            )
            log = db.get_recent_food_logs(conn, user_id, limit=1)[0]
        anchor = append_food(settings.vault_root, log)
        db.set_obsidian_anchor(conn, log.id, anchor)
        db.recompute_daily_totals(conn, logged_at.date())
    finally:
        conn.close()
    await notion.push_food(
        settings,
        food_log_id=log.id,
        summary=raw_text,
        logged_at=logged_at,
        junk=junk,
        calories=macros.get("total_kcal") if macros else None,
        protein_g=macros.get("total_protein_g") if macros else None,
        fat_g=macros.get("total_fat_g") if macros else None,
        carbs_g=macros.get("total_carbs_g") if macros else None,
    )
    return {
        "food_log_id": log.id,
        "summary": raw_text,
        "logged_at": logged_at.isoformat(),
        "estimated_kcal": macros.get("total_kcal") if macros else None,
        "estimated_macros": {
            "protein_g": macros.get("total_protein_g"),
            "fat_g": macros.get("total_fat_g"),
            "carbs_g": macros.get("total_carbs_g"),
        } if macros else None,
    }


async def edit_food(
    food_log_id: int,
    items: list[dict],
    junk: bool = False,
    time: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    conn = _open_conn(settings)
    try:
        existing_row = conn.execute(
            "SELECT * FROM food_logs WHERE id = ?", (food_log_id,)
        ).fetchone()
        if existing_row is None:
            raise ToolError(f"No food entry with id {food_log_id}.")
        food_items = [FoodItem(name=i["name"], quantity=i.get("quantity")) for i in items]
        raw_text = ", ".join(
            f"{i.quantity} {i.name}" if i.quantity else i.name for i in food_items
        )
        logged_at = _parse_time(time, settings.tz) if time else datetime.fromisoformat(existing_row["logged_at"])
        old_date = datetime.fromisoformat(existing_row["logged_at"]).date()
        log = db.update_food_log(conn, food_log_id, raw_text=raw_text, items=food_items, junk=junk, logged_at=logged_at)
        macros = await estimate_macros(items, settings)
        if macros:
            db.set_food_macros(conn, log.id, est_calories_kcal=macros.get("total_kcal"),
                               est_protein_g=macros.get("total_protein_g"), est_fat_g=macros.get("total_fat_g"),
                               est_carbs_g=macros.get("total_carbs_g"), est_calories_items_json=None)
            log = db.get_recent_food_logs(conn, user_id, limit=100)
            log = next(entry for entry in log if entry.id == food_log_id)
        update_food(settings.vault_root, log)
        db.recompute_daily_totals(conn, old_date)
        if logged_at.date() != old_date:
            db.recompute_daily_totals(conn, logged_at.date())
    finally:
        conn.close()
    return {"food_log_id": food_log_id, "summary": raw_text, "logged_at": logged_at.isoformat()}


async def delete_food(
    target: str,
    food_log_id: int | None = None,
    item_hint: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    conn = _open_conn(settings)
    try:
        if target == "last":
            log = db.get_last_food_log(conn, user_id)
            if log is None:
                raise ToolError("No food entries found.")
        elif target == "by_id":
            if food_log_id is None:
                raise ToolError("food_log_id required for by_id target.")
            logs = db.get_recent_food_logs(conn, user_id, limit=200)
            log = next((entry for entry in logs if entry.id == food_log_id), None)
            if log is None:
                raise ToolError(f"No food entry with id {food_log_id}.")
        elif target == "matching":
            if not item_hint:
                raise ToolError("item_hint required for matching target.")
            log = db.find_recent_food_log_by_item(conn, user_id, item_hint)
            if log is None:
                raise ToolError(f"No recent entry matching '{item_hint}'.")
        else:
            raise ToolError(f"Unknown target '{target}'.")
        deleted_date = log.logged_at.date()
        remove_food(settings.vault_root, log)
        db.delete_food_log(conn, log.id)
        db.recompute_daily_totals(conn, deleted_date)
    finally:
        conn.close()
    return {"deleted_food_log_id": log.id, "summary": log.raw_text}


async def query_macros(
    scope: str,
    date: str | None = None,
    item_hint: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    conn = _open_conn(settings)
    try:
        now = datetime.now(settings.tz)
        if scope == "today":
            day = now.date()
            logs = db.get_food_logs_for_day(conn, user_id, day)
        elif scope == "yesterday":
            from datetime import timedelta
            day = (now - timedelta(days=1)).date()
            logs = db.get_food_logs_for_day(conn, user_id, day)
        elif scope == "last":
            log = db.get_last_food_log(conn, user_id)
            logs = [log] if log else []
            day = log.logged_at.date() if log else now.date()
        elif scope == "by_date":
            if not date:
                raise ToolError("date required for by_date scope.")
            day = date_type.fromisoformat(date)
            logs = db.get_food_logs_for_day(conn, user_id, day)
        elif scope == "matching":
            if not item_hint:
                raise ToolError("item_hint required for matching scope.")
            log = db.find_recent_food_log_by_item(conn, user_id, item_hint)
            logs = [log] if log else []
            day = log.logged_at.date() if log else now.date()
        else:
            raise ToolError(f"Unknown scope '{scope}'.")

        if not logs:
            raise ToolError("No entries found for that scope.")

        totals = db.get_daily_totals(conn, day) if scope not in ("last", "matching") else None
        total_kcal = sum((entry.est_calories_kcal or 0) for entry in logs)
        total_protein = sum((entry.est_protein_g or 0) for entry in logs)
        total_fat = sum((entry.est_fat_g or 0) for entry in logs)
        total_carbs = sum((entry.est_carbs_g or 0) for entry in logs)

        entries = [
            {
                "id": entry.id,
                "summary": entry.raw_text,
                "logged_at": entry.logged_at.isoformat(),
                "kcal": entry.est_calories_kcal,
                "protein_g": entry.est_protein_g,
                "fat_g": entry.est_fat_g,
                "carbs_g": entry.est_carbs_g,
            }
            for entry in logs
        ]
    finally:
        conn.close()

    return {
        "scope": scope,
        "entries": entries,
        "total_kcal": totals.total_kcal if totals else total_kcal,
        "total_protein_g": totals.total_protein_g if totals else total_protein,
        "total_fat_g": totals.total_fat_g if totals else total_fat,
        "total_carbs_g": totals.total_carbs_g if totals else total_carbs,
    }


TOOLS: list[ToolDef] = [
    ToolDef(
        name="log_food",
        description="Log food the user ate. Use when they describe eating something.",
        parameters={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"name": {"type": "string"}, "quantity": {"type": "string"}}, "required": ["name"]},
                    "description": "Food items eaten",
                },
                "junk": {"type": "boolean", "description": "True if user tagged with #junk"},
                "time": {"type": "string", "description": "When they ate, e.g. '1pm', 'lunch'"},
                "notes": {"type": "string", "description": "Any remarks"},
            },
            "required": ["items"],
        },
        handler=log_food,
    ),
    ToolDef(
        name="edit_food",
        description="Edit a previously logged food entry.",
        parameters={
            "type": "object",
            "properties": {
                "food_log_id": {"type": "integer"},
                "items": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "quantity": {"type": "string"}}, "required": ["name"]}},
                "junk": {"type": "boolean"},
                "time": {"type": "string"},
            },
            "required": ["food_log_id", "items"],
        },
        handler=edit_food,
    ),
    ToolDef(
        name="delete_food",
        description="Delete or remove a food log entry. Use when user says 'delete', 'remove', 'undo', 'cancel that'.",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": ["last", "by_id", "matching"]},
                "food_log_id": {"type": "integer"},
                "item_hint": {"type": "string"},
            },
            "required": ["target"],
        },
        handler=delete_food,
    ),
    ToolDef(
        name="query_macros",
        description="Get calorie and macro breakdown.",
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["today", "yesterday", "last", "by_date", "matching"]},
                "date": {"type": "string"},
                "item_hint": {"type": "string"},
            },
            "required": ["scope"],
        },
        handler=query_macros,
    ),
]
