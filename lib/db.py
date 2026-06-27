"""SQLite persistence layer for cerebro.

Stdlib-only. Source of truth lives in a single SQLite file. Migrations are
plain .sql files under app/migrations/, applied in lex order, tracked in the
_migrations table so each runs at most once.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from lib.models import FoodItem, FoodLog, HevyExercise, StoredWorkout, UserProfile
from lib.models import DailyTotals
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


# ---------- Connection / migrations ----------

def get_conn(db_path: Path) -> sqlite3.Connection:
    """Open a connection with row_factory=sqlite3.Row and foreign_keys=ON.

    `check_same_thread=False` is safe here because the bot opens a fresh
    connection per handler and never shares it across concurrent tasks; it
    only crosses threads because each `asyncio.to_thread` call may land on a
    different worker thread, which is sequential within a single handler.
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> None:
    """Ensure parent dir exists, open conn, apply pending migrations, close."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn(db_path)
    try:
        _apply_migrations(conn)
    finally:
        conn.close()


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply any *.sql files in MIGRATIONS_DIR not yet recorded in _migrations."""
    # Bootstrap the tracking table so the first lookup below doesn't blow up.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _migrations (
            filename    TEXT PRIMARY KEY,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()

    applied = {row["filename"] for row in conn.execute("SELECT filename FROM _migrations")}

    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    for path in files:
        if path.name in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        # executescript implicitly commits any open transaction; if it raises,
        # the _migrations row below will not be inserted, so a retry re-runs
        # the script. Migrations use CREATE ... IF NOT EXISTS to stay idempotent.
        conn.executescript(sql)
        conn.execute("INSERT INTO _migrations (filename) VALUES (?)", (path.name,))
        conn.commit()


# ---------- Row mapping ----------

def _row_to_food_log(row: sqlite3.Row) -> FoodLog:
    items = [FoodItem.model_validate(d) for d in json.loads(row["items_json"])]
    keys = row.keys()
    return FoodLog(
        id=row["id"],
        user_id=row["user_id"],
        raw_text=row["raw_text"],
        items=items,
        junk=bool(row["junk"]),
        logged_at=datetime.fromisoformat(row["logged_at"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        telegram_message_id=row["telegram_message_id"],
        obsidian_anchor=row["obsidian_anchor"],
        est_calories_kcal=row["est_calories_kcal"],
        est_calories_items_json=row["est_calories_items_json"],
        # Macro columns added in migration 004; tolerate older rows that
        # somehow lack them (shouldn't happen post-migration).
        est_protein_g=row["est_protein_g"] if "est_protein_g" in keys else None,
        est_fat_g=row["est_fat_g"] if "est_fat_g" in keys else None,
        est_carbs_g=row["est_carbs_g"] if "est_carbs_g" in keys else None,
    )


def _items_to_json(items: list[FoodItem]) -> str:
    return json.dumps([i.model_dump() for i in items])


# ---------- Food logs ----------

def insert_food_log(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    raw_text: str,
    items: list[FoodItem],
    junk: bool,
    logged_at: datetime,
    telegram_message_id: int | None,
) -> FoodLog:
    """Insert a food log and return the persisted row."""
    cur = conn.execute(
        """
        INSERT INTO food_logs (
            user_id, raw_text, items_json, junk, logged_at, telegram_message_id
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            raw_text,
            _items_to_json(items),
            1 if junk else 0,
            logged_at.isoformat(),
            telegram_message_id,
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
    assert new_id is not None  # AUTOINCREMENT always populates this
    row = conn.execute("SELECT * FROM food_logs WHERE id = ?", (new_id,)).fetchone()
    return _row_to_food_log(row)


def update_food_log(
    conn: sqlite3.Connection,
    food_log_id: int,
    *,
    raw_text: str,
    items: list[FoodItem],
    junk: bool,
    logged_at: datetime,
) -> FoodLog:
    """Update mutable fields. Preserves user_id, telegram_message_id, obsidian_anchor, created_at."""
    existing = conn.execute(
        "SELECT id FROM food_logs WHERE id = ?", (food_log_id,)
    ).fetchone()
    if existing is None:
        raise ValueError(f"food_log id={food_log_id} not found")

    conn.execute(
        """
        UPDATE food_logs
           SET raw_text   = ?,
               items_json = ?,
               junk       = ?,
               logged_at  = ?
         WHERE id = ?
        """,
        (
            raw_text,
            _items_to_json(items),
            1 if junk else 0,
            logged_at.isoformat(),
            food_log_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM food_logs WHERE id = ?", (food_log_id,)).fetchone()
    return _row_to_food_log(row)


def get_food_log_by_message_id(
    conn: sqlite3.Connection,
    telegram_message_id: int,
) -> FoodLog | None:
    """Look up by the user's original Telegram message id."""
    row = conn.execute(
        "SELECT * FROM food_logs WHERE telegram_message_id = ?",
        (telegram_message_id,),
    ).fetchone()
    return _row_to_food_log(row) if row is not None else None


def set_obsidian_anchor(
    conn: sqlite3.Connection, food_log_id: int, anchor: str
) -> None:
    """Persist the Obsidian anchor used to locate the line for edits."""
    conn.execute(
        "UPDATE food_logs SET obsidian_anchor = ? WHERE id = ?",
        (anchor, food_log_id),
    )
    conn.commit()


def set_food_calories(
    conn: sqlite3.Connection,
    food_log_id: int,
    est_calories_kcal: int | None,
    est_calories_items_json: str | None,
) -> None:
    """Back-compat shim around `set_food_macros` (kcal only). Prefer
    `set_food_macros` for new call sites."""
    set_food_macros(
        conn,
        food_log_id,
        est_calories_kcal=est_calories_kcal,
        est_protein_g=None,
        est_fat_g=None,
        est_carbs_g=None,
        est_calories_items_json=est_calories_items_json,
    )


def set_food_macros(
    conn: sqlite3.Connection,
    food_log_id: int,
    *,
    est_calories_kcal: int | None,
    est_protein_g: float | None,
    est_fat_g: float | None,
    est_carbs_g: float | None,
    est_calories_items_json: str | None,
) -> None:
    """Persist the full macro estimate for a food_log row. All fields nullable
    so a failed estimate (caller passes Nones) leaves the row in pre-migration
    shape.
    """
    conn.execute(
        """
        UPDATE food_logs
           SET est_calories_kcal = ?,
               est_protein_g    = ?,
               est_fat_g        = ?,
               est_carbs_g      = ?,
               est_calories_items_json = ?
         WHERE id = ?
        """,
        (
            est_calories_kcal,
            est_protein_g,
            est_fat_g,
            est_carbs_g,
            est_calories_items_json,
            food_log_id,
        ),
    )
    conn.commit()


# ---------- Food log queries / deletes ----------

def get_last_food_log(
    conn: sqlite3.Connection, user_id: int
) -> FoodLog | None:
    """Return the most recent food_log for user_id by logged_at DESC, id DESC.

    None if no rows exist for that user.
    """
    row = conn.execute(
        """
        SELECT * FROM food_logs
         WHERE user_id = ?
         ORDER BY logged_at DESC, id DESC
         LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    return _row_to_food_log(row) if row is not None else None


def get_recent_food_logs(
    conn: sqlite3.Connection, user_id: int, limit: int = 20
) -> list[FoodLog]:
    """Return up to `limit` most recent food_logs for user_id, newest first."""
    rows = conn.execute(
        """
        SELECT * FROM food_logs
         WHERE user_id = ?
         ORDER BY logged_at DESC, id DESC
         LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [_row_to_food_log(r) for r in rows]


def get_food_logs_for_day(
    conn: sqlite3.Connection, user_id: int, day: date
) -> list[FoodLog]:
    """Return all food_logs for user_id whose stored ISO timestamp begins with `day`.

    Comparison is on the date portion of the stored string (first 10 chars), which is
    always YYYY-MM-DD for ISO-8601. Sorted by logged_at ASC.
    """
    rows = conn.execute(
        """
        SELECT * FROM food_logs
         WHERE user_id = ?
           AND substr(logged_at, 1, 10) = ?
         ORDER BY logged_at ASC, id ASC
        """,
        (user_id, day.isoformat()),
    ).fetchall()
    return [_row_to_food_log(r) for r in rows]


def find_recent_food_log_by_item(
    conn: sqlite3.Connection, user_id: int, item_hint: str, lookback: int = 50
) -> FoodLog | None:
    """Scan the last `lookback` entries for user_id; return the most recent log
    whose items contain a name matching item_hint (case-insensitive substring).

    Items are JSON-encoded in the row, so we filter in Python rather than SQL.
    """
    needle = item_hint.strip().lower()
    if not needle:
        return None
    candidates = get_recent_food_logs(conn, user_id, limit=lookback)
    for log in candidates:  # newest first
        for item in log.items:
            if needle in item.name.lower():
                return log
    return None


def delete_food_log(
    conn: sqlite3.Connection, food_log_id: int
) -> FoodLog | None:
    """Delete the row by id. Returns the deleted row, or None if not found."""
    row = conn.execute(
        "SELECT * FROM food_logs WHERE id = ?", (food_log_id,)
    ).fetchone()
    if row is None:
        return None
    deleted = _row_to_food_log(row)
    conn.execute("DELETE FROM food_logs WHERE id = ?", (food_log_id,))
    conn.commit()
    return deleted


# ---------- Workouts ----------

def _row_to_stored_workout(row: sqlite3.Row) -> StoredWorkout:
    return StoredWorkout(
        hevy_id=row["hevy_id"],
        title=row["title"],
        description=row["description"],
        started_at=datetime.fromisoformat(row["started_at"]),
        ended_at=datetime.fromisoformat(row["ended_at"]),
        duration_s=row["duration_s"],
        total_volume_kg=row["total_volume_kg"],
        est_calories_kcal=row["est_calories_kcal"],
        exercises_json=row["exercises_json"],
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
    )


def get_known_workout_ids(conn: sqlite3.Connection) -> set[str]:
    """Return all hevy_ids currently in the workouts table."""
    rows = conn.execute("SELECT hevy_id FROM workouts").fetchall()
    return {r["hevy_id"] for r in rows}


def insert_workout(
    conn: sqlite3.Connection,
    *,
    hevy_id: str,
    title: str,
    description: str | None,
    started_at: datetime,
    ended_at: datetime,
    duration_s: int,
    total_volume_kg: float,
    est_calories_kcal: int | None,
    exercises: list[HevyExercise],
) -> StoredWorkout:
    """Insert a workout. Stores exercises as JSON.

    Idempotent under hevy_id: raises sqlite3.IntegrityError on duplicate.
    Caller pre-checks via get_known_workout_ids() to skip already-synced rows.
    """
    exercises_json = json.dumps([e.model_dump() for e in exercises])
    conn.execute(
        """
        INSERT INTO workouts (
            hevy_id, title, description, started_at, ended_at,
            duration_s, total_volume_kg, est_calories_kcal, exercises_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            hevy_id,
            title,
            description,
            started_at.isoformat(),
            ended_at.isoformat(),
            duration_s,
            total_volume_kg,
            est_calories_kcal,
            exercises_json,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM workouts WHERE hevy_id = ?", (hevy_id,)
    ).fetchone()
    return _row_to_stored_workout(row)


def get_workouts_for_day(
    conn: sqlite3.Connection, day: date
) -> list[StoredWorkout]:
    """Return workouts whose started_at falls on `day`. Sorted started_at ASC.

    Compares the date portion of the stored ISO timestamp (first 10 chars).
    Caller is responsible for tz alignment when constructing `day`.
    """
    rows = conn.execute(
        """
        SELECT * FROM workouts
         WHERE substr(started_at, 1, 10) = ?
         ORDER BY started_at ASC
        """,
        (day.isoformat(),),
    ).fetchall()
    return [_row_to_stored_workout(r) for r in rows]


def get_workouts_after(
    conn: sqlite3.Connection, since: datetime
) -> list[StoredWorkout]:
    """Return workouts with started_at >= since. Sorted started_at ASC."""
    rows = conn.execute(
        "SELECT * FROM workouts WHERE started_at >= ? ORDER BY started_at ASC",
        (since.isoformat(),),
    ).fetchall()
    return [_row_to_stored_workout(r) for r in rows]


def update_workout_calories(
    conn: sqlite3.Connection, hevy_id: str, est_calories_kcal: int | None
) -> None:
    """Update a workout's est_calories_kcal in place.

    Used after a profile change to backfill the estimate across stored workouts.
    """
    conn.execute(
        "UPDATE workouts SET est_calories_kcal = ? WHERE hevy_id = ?",
        (est_calories_kcal, hevy_id),
    )
    conn.commit()


def repair_workout(
    conn: sqlite3.Connection,
    hevy_id: str,
    title: str,
    exercises: list[HevyExercise],
) -> None:
    """Update title and exercises_json for an existing workout entry.

    Called on every sync pass so that entries stored before the title/exercise-name
    fix are backfilled with the current Hevy API data.
    """
    exercises_json = json.dumps([e.model_dump() for e in exercises])
    conn.execute(
        "UPDATE workouts SET title = ?, exercises_json = ? WHERE hevy_id = ?",
        (title, exercises_json, hevy_id),
    )
    conn.commit()


def get_all_workouts(conn: sqlite3.Connection) -> list[StoredWorkout]:
    """Return every workout, sorted started_at ASC.

    Used to recompute calories after a profile update.
    """
    rows = conn.execute(
        "SELECT * FROM workouts ORDER BY started_at ASC"
    ).fetchall()
    return [_row_to_stored_workout(r) for r in rows]


# ---------- User profile ----------

def _row_to_profile(row: sqlite3.Row) -> UserProfile:
    return UserProfile(
        height_cm=row["height_cm"],
        age=row["age"],
        sex=row["sex"],
        weight_kg=row["weight_kg"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def upsert_profile(
    conn: sqlite3.Connection,
    *,
    height_cm: float,
    age: int,
    sex: str,
    weight_kg: float,
) -> UserProfile:
    """Insert or replace the single user_profile row (id=1). Returns the persisted row."""
    if sex not in ("M", "F"):
        raise ValueError(f"sex must be 'M' or 'F', got {sex!r}")
    conn.execute(
        """
        INSERT OR REPLACE INTO user_profile
            (id, height_cm, age, sex, weight_kg, updated_at)
        VALUES (1, ?, ?, ?, ?, datetime('now'))
        """,
        (height_cm, age, sex, weight_kg),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM user_profile WHERE id = 1").fetchone()
    return _row_to_profile(row)


def get_profile(conn: sqlite3.Connection) -> UserProfile | None:
    """Return the user_profile row, or None if not yet set."""
    row = conn.execute("SELECT * FROM user_profile WHERE id = 1").fetchone()
    return _row_to_profile(row) if row is not None else None


# ---------- Daily totals (denormalized cache over food_logs) ----------

def _row_to_daily_totals(row: sqlite3.Row) -> DailyTotals:
    return DailyTotals(
        date=date.fromisoformat(row["date"]),
        total_kcal=int(row["total_kcal"] or 0),
        total_protein_g=float(row["total_protein_g"] or 0),
        total_fat_g=float(row["total_fat_g"] or 0),
        total_carbs_g=float(row["total_carbs_g"] or 0),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def get_daily_totals(conn: sqlite3.Connection, day: date) -> DailyTotals | None:
    """Read the cached row for `day`. None if no entries logged that day."""
    row = conn.execute(
        "SELECT * FROM daily_totals WHERE date = ?", (day.isoformat(),)
    ).fetchone()
    return _row_to_daily_totals(row) if row is not None else None


def recompute_daily_totals(conn: sqlite3.Connection, day: date) -> DailyTotals:
    """Recompute the daily_totals row for `day` from food_logs.

    Idempotent. Source of truth = food_logs; this is a denormalized cache.
    Call after every food_log insert/edit/delete on the affected day(s).
    Rows missing macros (NULL est_protein_g etc) contribute 0 to that field.
    Returns the persisted DailyTotals (zeros if no entries that day).
    """
    day_iso = day.isoformat()
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(est_calories_kcal), 0) AS total_kcal,
            COALESCE(SUM(est_protein_g),   0)  AS total_protein_g,
            COALESCE(SUM(est_fat_g),       0)  AS total_fat_g,
            COALESCE(SUM(est_carbs_g),     0)  AS total_carbs_g
          FROM food_logs
         WHERE substr(logged_at, 1, 10) = ?
        """,
        (day_iso,),
    ).fetchone()

    total_kcal = int(row["total_kcal"] or 0)
    total_protein_g = float(row["total_protein_g"] or 0)
    total_fat_g = float(row["total_fat_g"] or 0)
    total_carbs_g = float(row["total_carbs_g"] or 0)

    conn.execute(
        """
        INSERT INTO daily_totals
            (date, total_kcal, total_protein_g, total_fat_g, total_carbs_g, updated_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(date) DO UPDATE SET
            total_kcal      = excluded.total_kcal,
            total_protein_g = excluded.total_protein_g,
            total_fat_g     = excluded.total_fat_g,
            total_carbs_g   = excluded.total_carbs_g,
            updated_at      = excluded.updated_at
        """,
        (day_iso, total_kcal, total_protein_g, total_fat_g, total_carbs_g),
    )
    conn.commit()

    persisted = conn.execute(
        "SELECT * FROM daily_totals WHERE date = ?", (day_iso,)
    ).fetchone()
    return _row_to_daily_totals(persisted)


# ---------- Notion page tracking ----------

def get_notion_page_id(
    conn: sqlite3.Connection, entity_type: str, entity_id: str
) -> str | None:
    """Return stored Notion page ID for this entity, or None if not yet synced."""
    row = conn.execute(
        "SELECT notion_page_id FROM notion_pages WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    ).fetchone()
    return row["notion_page_id"] if row else None


def upsert_notion_page(
    conn: sqlite3.Connection, entity_type: str, entity_id: str, notion_page_id: str
) -> None:
    """Insert or update the Notion page ID for this entity."""
    conn.execute(
        """INSERT INTO notion_pages (entity_type, entity_id, notion_page_id, synced_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT (entity_type, entity_id) DO UPDATE SET
               notion_page_id = excluded.notion_page_id,
               synced_at = excluded.synced_at""",
        (entity_type, entity_id, notion_page_id, datetime.now().isoformat()),
    )
    conn.commit()
