from __future__ import annotations

import json
from datetime import datetime, timedelta

import app.db as db
from app.tools.errors import ToolError
from app.tools.registry import ToolDef
from lib.config import Settings
from lib.integrations.hevy import list_workouts
from lib.sinks.obsidian import append_workout_note, append_workout_summary
from lib.sinks import notion


async def log_workout_note(
    note: str,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    now = datetime.now(settings.tz)
    append_workout_note(settings.vault_root, now.date(), note)
    new, _ = await _do_sync(settings)
    return {"note_logged": True, "synced_workouts": new}


async def sync_workouts(
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    new, _ = await _do_sync(settings)
    return {
        "synced_workouts": new,
        "message": f"Synced {new} new workout(s) from Hevy.",
    }


async def query_workouts(
    scope: str,
    date: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    conn = db.get_conn(settings.db_path)
    try:
        now = datetime.now(settings.tz)
        if scope == "today":
            rows = db.get_workouts_for_day(conn, now.date())
        elif scope == "this_week":
            start = now - timedelta(days=now.weekday())
            rows = db.get_workouts_after(conn, start)
        elif scope == "by_date":
            if not date:
                raise ToolError("date required for by_date scope.")
            from datetime import date as date_type
            rows = db.get_workouts_for_day(conn, date_type.fromisoformat(date))
        elif scope == "last":
            rows = db.get_workouts_after(conn, now - timedelta(days=365))
            rows = rows[:1]
        else:
            raise ToolError(f"Unknown scope '{scope}'.")
    finally:
        conn.close()

    if not rows:
        raise ToolError("No workouts found for that scope.")

    return {
        "workouts": [
            {
                "hevy_id": w.hevy_id,
                "title": w.title,
                "started_at": w.started_at.isoformat(),
                "duration_s": w.duration_s,
                "total_volume_kg": w.total_volume_kg,
                "est_calories_kcal": w.est_calories_kcal,
            }
            for w in rows
        ]
    }


async def _do_sync(settings: Settings) -> tuple[int, int]:
    """Pull all Hevy workouts. Returns (new_count, repaired_count).

    For new workouts: insert into DB and write Obsidian summary.
    For known workouts: repair title and exercises_json from latest Hevy data,
    backfilling entries that were stored before exercise names were captured.
    """
    conn = db.get_conn(settings.db_path)
    try:
        known = db.get_known_workout_ids(conn)
        profile = db.get_profile(conn)  # fetch once — doesn't change between workouts
        new_count = 0
        page = 1
        while True:
            workouts = await list_workouts(settings.hevy_api_key, page=page, page_size=10)
            if not workouts:
                break
            for w in workouts:
                if w.id in known:
                    continue  # already stored; Notion is up-to-date from initial sync
                duration_s = int((w.end_time - w.start_time).total_seconds())
                volume_kg = _total_volume(w)
                exercises_json = json.dumps([e.model_dump() for e in w.exercises])
                est_kcal = _estimate_workout_calories(w, profile) if profile else None
                stored = db.insert_workout(
                    conn,
                    hevy_id=w.id,
                    title=w.title,
                    description=w.description,
                    started_at=w.start_time,
                    ended_at=w.end_time,
                    duration_s=duration_s,
                    total_volume_kg=volume_kg,
                    est_calories_kcal=est_kcal,
                    exercises=w.exercises,
                )
                append_workout_summary(settings.vault_root, stored)
                known.add(w.id)
                new_count += 1
                await notion.push_workout(
                    settings,
                    hevy_id=w.id,
                    title=w.title,
                    started_at=w.start_time,
                    duration_s=duration_s,
                    volume_kg=volume_kg,
                    calories_kcal=est_kcal,
                    exercises_json=exercises_json,
                )
            page += 1
    finally:
        conn.close()
    return new_count, 0


def _total_volume(w) -> float:
    total = 0.0
    for ex in w.exercises:
        for s in ex.sets:
            if s.weight_kg and s.reps:
                total += s.weight_kg * s.reps
    return total


def _estimate_workout_calories(w, profile) -> int | None:
    """MET-based estimate: ~5 kcal/min for strength training."""
    duration_min = int((w.end_time - w.start_time).total_seconds()) / 60
    return int(duration_min * 5)


TOOLS: list[ToolDef] = [
    ToolDef(
        name="log_workout_note",
        description="Log a workout narrative and trigger Hevy sync.",
        parameters={
            "type": "object",
            "properties": {"note": {"type": "string", "description": "Workout narrative"}},
            "required": ["note"],
        },
        handler=log_workout_note,
    ),
    ToolDef(
        name="sync_workouts",
        description="Manually sync workouts from Hevy.",
        parameters={"type": "object", "properties": {}},
        handler=sync_workouts,
    ),
    ToolDef(
        name="query_workouts",
        description="Query workout history.",
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["today", "this_week", "by_date", "last"]},
                "date": {"type": "string"},
            },
            "required": ["scope"],
        },
        handler=query_workouts,
    ),
]
