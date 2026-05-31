-- Macro storage on food_logs + daily totals cache.
-- Per-row: protein/fat/carbs floats, nullable (failed estimate -> NULL).
-- daily_totals: denormalized cache, source of truth is food_logs. Rebuilt
-- from SUM(food_logs) on every food-log insert/edit/delete. Key is ISO date
-- in the user's local TZ (food_logs.logged_at is stored in user TZ already,
-- so substr(logged_at, 1, 10) gives the right key).

ALTER TABLE food_logs ADD COLUMN est_protein_g REAL;
ALTER TABLE food_logs ADD COLUMN est_fat_g REAL;
ALTER TABLE food_logs ADD COLUMN est_carbs_g REAL;

CREATE TABLE IF NOT EXISTS daily_totals (
    date            TEXT PRIMARY KEY,         -- 'YYYY-MM-DD' in user TZ
    total_kcal      INTEGER NOT NULL DEFAULT 0,
    total_protein_g REAL    NOT NULL DEFAULT 0,
    total_fat_g     REAL    NOT NULL DEFAULT 0,
    total_carbs_g   REAL    NOT NULL DEFAULT 0,
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
