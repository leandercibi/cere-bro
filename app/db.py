from pathlib import Path

import lib.db as _lib_db

_lib_db.MIGRATIONS_DIR = Path(__file__).parent / "migrations"

from lib.db import *  # noqa: E402, F401, F403
from lib.db import (  # noqa: E402, F401
    delete_food_log,
    find_recent_food_log_by_item,
    get_conn,
    get_daily_totals,
    get_food_logs_for_day,
    get_known_workout_ids,
    get_last_food_log,
    get_profile,
    get_recent_food_logs,
    get_workouts_after,
    get_workouts_for_day,
    init_db,
    insert_food_log,
    insert_workout,
    recompute_daily_totals,
    set_food_macros,
    set_obsidian_anchor,
    update_food_log,
    upsert_profile,
)
