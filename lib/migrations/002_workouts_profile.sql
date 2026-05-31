-- Workouts (synced from Hevy) and single-row user profile.
-- Profile is required to compute per-workout calories (BMR + MET formula).

CREATE TABLE IF NOT EXISTS workouts (
    hevy_id           TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    description       TEXT,
    started_at        TEXT NOT NULL,                    -- ISO-8601
    ended_at          TEXT NOT NULL,                    -- ISO-8601
    duration_s        INTEGER NOT NULL,
    total_volume_kg   REAL NOT NULL DEFAULT 0,
    est_calories_kcal INTEGER,                          -- null when profile is missing
    exercises_json    TEXT NOT NULL,                    -- JSON list of HevyExercise
    fetched_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_workouts_started_at ON workouts(started_at DESC);

-- Single-row table; the CHECK pins it to id=1 so upsert is unambiguous.
CREATE TABLE IF NOT EXISTS user_profile (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    height_cm   REAL NOT NULL,
    age         INTEGER NOT NULL,
    sex         TEXT NOT NULL CHECK (sex IN ('M', 'F')),
    weight_kg   REAL NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
