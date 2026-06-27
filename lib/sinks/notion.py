"""Notion sink — pushes Cerebro data to the user's Cerebro Notion dashboard.

All public coroutines are fire-and-forget safe: they catch all exceptions and
only log warnings on failure, so Notion errors never break the bot's primary
tool response.

Deduplication is handled via the `notion_pages` SQLite table, which maps
(entity_type, entity_id) → Notion page ID. This allows both idempotent
creation and in-place updates (e.g. marking a task done).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx

import app.db as db
from lib.config import Settings

logger = logging.getLogger("cerebro.notion")

_BASE = "https://api.notion.com/v1"
_VERSION = "2022-06-28"

# Shared client — avoids a full TCP+TLS handshake per Notion API call.
_client = httpx.AsyncClient(timeout=15)

# Cerebro Notion dashboard — database IDs (under the "Data" sub-page)
_DB = {
    "food":    "898ac5f6-72a5-8241-8c4c-01302e9a528b",
    "workout": "852ac5f6-72a5-834c-92aa-81bb2cda2621",
    "habits":  "726ac5f6-72a5-8350-b5e2-01d1ff6967fc",
    "task":    "943ac5f6-72a5-8243-bb1b-01be7615e96e",
    "idea":    "16bac5f6-72a5-83ec-a74f-01c115e2c9a7",
    "body":    "534ac5f6-72a5-8366-92a1-01cd5e7e41cd",
    "journal": "1e5ac5f6-72a5-8356-b1c8-01f5546e5c0b",
    "streaks": "48bac5f6-72a5-83e5-a824-81672c4dbea4",
}


# --- low-level helpers ---

def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": _VERSION,
        "Content-Type": "application/json",
    }


def _rt(text: str) -> list[dict]:
    """Wrap plain text as a Notion rich_text array (max 2000 chars)."""
    return [{"type": "text", "text": {"content": str(text)[:2000]}}]


async def _create_page(api_key: str, db_id: str, props: dict) -> str | None:
    try:
        r = await _client.post(
            f"{_BASE}/pages",
            headers=_headers(api_key),
            json={"parent": {"database_id": db_id}, "properties": props},
        )
        if r.status_code not in (200, 201):
            logger.warning("Notion create failed [%s]: %s", r.status_code, r.text[:300])
            return None
        return r.json()["id"]
    except Exception:
        logger.exception("Notion create_page error")
        return None


async def _update_page(api_key: str, page_id: str, props: dict) -> bool:
    """Patch a Notion page's properties. Returns False on 404 (stale page_id)."""
    try:
        r = await _client.patch(
            f"{_BASE}/pages/{page_id}",
            headers=_headers(api_key),
            json={"properties": props},
        )
        if r.status_code == 404:
            logger.warning("Notion page %s not found (deleted externally?)", page_id)
            return False
        if r.status_code != 200:
            logger.warning("Notion update failed [%s]: %s", r.status_code, r.text[:300])
        return r.status_code == 200
    except Exception:
        logger.exception("Notion update_page error")
        return False


async def _append_blocks(api_key: str, page_id: str, text: str) -> None:
    """Append a paragraph block to a Notion page (used for journal entries)."""
    try:
        r = await _client.patch(
            f"{_BASE}/blocks/{page_id}/children",
            headers=_headers(api_key),
            json={"children": [{"object": "block", "type": "paragraph",
                                 "paragraph": {"rich_text": _rt(text)}}]},
        )
        if r.status_code != 200:
            logger.warning("Notion append block failed [%s]: %s", r.status_code, r.text[:300])
    except Exception:
        logger.exception("Notion append_blocks error")


def _get_page_id(settings: Settings, entity_type: str, entity_id: str) -> str | None:
    conn = db.get_conn(settings.db_path)
    try:
        return db.get_notion_page_id(conn, entity_type, entity_id)
    finally:
        conn.close()


def _store_page_id(
    settings: Settings, entity_type: str, entity_id: str, page_id: str
) -> None:
    conn = db.get_conn(settings.db_path)
    try:
        db.upsert_notion_page(conn, entity_type, entity_id, page_id)
    finally:
        conn.close()


# --- public push functions ---

async def push_food(
    settings: Settings,
    *,
    food_log_id: int,
    summary: str,
    logged_at: datetime,
    junk: bool,
    calories: int | None,
    protein_g: float | None,
    fat_g: float | None,
    carbs_g: float | None,
) -> None:
    if not settings.notion_api_key:
        return
    entity_id = str(food_log_id)
    if _get_page_id(settings, "food", entity_id):
        return  # already synced

    props: dict = {
        "Meal":   {"title": _rt(summary)},
        "Date":   {"date": {"start": logged_at.date().isoformat()}},
        "Time":   {"rich_text": _rt(logged_at.strftime("%H:%M"))},
        "Junk":   {"checkbox": junk},
        "Source": {"select": {"name": "Telegram"}},
    }
    if calories is not None:
        props["Calories"] = {"number": calories}
    if protein_g is not None:
        props["Protein_g"] = {"number": round(protein_g, 1)}
    if fat_g is not None:
        props["Fat_g"] = {"number": round(fat_g, 1)}
    if carbs_g is not None:
        props["Carbs_g"] = {"number": round(carbs_g, 1)}

    page_id = await _create_page(settings.notion_api_key, _DB["food"], props)
    if page_id:
        _store_page_id(settings, "food", entity_id, page_id)


async def push_workout(
    settings: Settings,
    *,
    hevy_id: str,
    title: str,
    started_at: datetime,
    duration_s: int,
    volume_kg: float,
    calories_kcal: int | None,
    exercises_json: str,
) -> None:
    if not settings.notion_api_key:
        return

    try:
        exercises = json.loads(exercises_json)
        num_exercises = len(exercises)
        num_sets = sum(len(e.get("sets", [])) for e in exercises)
    except Exception:
        num_exercises = 0
        num_sets = 0

    props: dict = {
        "Session":      {"title": _rt(title)},
        "Date":         {"date": {"start": started_at.date().isoformat()}},
        "Duration_min": {"number": round(duration_s / 60)},
        "Volume_kg":    {"number": round(volume_kg, 1)},
        "Exercises":    {"number": num_exercises},
        "Sets":         {"number": num_sets},
        "Category":     {"select": {"name": "Strength"}},
    }
    if calories_kcal is not None:
        props["Calories_kcal"] = {"number": calories_kcal}

    existing = _get_page_id(settings, "workout", hevy_id)
    if existing:
        ok = await _update_page(settings.notion_api_key, existing, props)
        if not ok:
            # Page was deleted externally — clear stale record and recreate.
            _store_page_id(settings, "workout", hevy_id, "")
            existing = None
    if not existing:
        page_id = await _create_page(settings.notion_api_key, _DB["workout"], props)
        if page_id:
            _store_page_id(settings, "workout", hevy_id, page_id)


async def push_task(
    settings: Settings,
    *,
    task_id: int,
    description: str,
    due_at: str | None,
) -> None:
    if not settings.notion_api_key:
        return
    entity_id = str(task_id)
    if _get_page_id(settings, "task", entity_id):
        return

    props: dict = {
        "Task":     {"title": _rt(description)},
        "Status":   {"select": {"name": "Not started"}},
        "Priority": {"select": {"name": "Medium"}},
    }
    if due_at:
        props["Due_date"] = {"date": {"start": due_at[:10]}}

    page_id = await _create_page(settings.notion_api_key, _DB["task"], props)
    if page_id:
        _store_page_id(settings, "task", entity_id, page_id)


async def update_task_done(
    settings: Settings,
    *,
    task_id: int,
    completed_at: datetime,
) -> None:
    if not settings.notion_api_key:
        return
    page_id = _get_page_id(settings, "task", str(task_id))
    if not page_id:
        return
    await _update_page(settings.notion_api_key, page_id, {
        "Status":         {"select": {"name": "Done"}},
        "Completed_date": {"date": {"start": completed_at.date().isoformat()}},
    })


async def push_idea(
    settings: Settings,
    *,
    slug: str,
    title: str,
    description: str | None,
    tags: list[str] | None,
    created_at: datetime,
) -> None:
    if not settings.notion_api_key:
        return
    if _get_page_id(settings, "idea", slug):
        return

    props: dict = {
        "Idea":    {"title": _rt(title)},
        "Created": {"date": {"start": created_at.date().isoformat()}},
        "Stage":   {"select": {"name": "Raw"}},
    }
    if description:
        props["Notes"] = {"rich_text": _rt(description)}
    if tags:
        props["Tags"] = {"multi_select": [{"name": t} for t in tags[:5]]}

    page_id = await _create_page(settings.notion_api_key, _DB["idea"], props)
    if page_id:
        _store_page_id(settings, "idea", slug, page_id)


async def push_journal(
    settings: Settings,
    *,
    date_str: str,
    entry: str,
) -> None:
    """Push a journal entry to Notion.

    Each entry is appended as a paragraph block on the day's page so that
    multiple entries per day are all preserved (unlike replacing a single
    rich_text property which would overwrite earlier entries).
    """
    if not settings.notion_api_key:
        return

    existing = _get_page_id(settings, "journal", date_str)
    if not existing:
        props: dict = {"Date": {"title": _rt(date_str)}}
        page_id = await _create_page(settings.notion_api_key, _DB["journal"], props)
        if page_id:
            _store_page_id(settings, "journal", date_str, page_id)
            existing = page_id

    if existing:
        await _append_blocks(settings.notion_api_key, existing, entry)
