-- Initial schema: food logs + migrations tracking table.
-- All timestamps are ISO-8601 strings (TEXT). junk is 0/1 (INTEGER).

CREATE TABLE IF NOT EXISTS food_logs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              INTEGER NOT NULL,
    raw_text             TEXT    NOT NULL,
    items_json           TEXT    NOT NULL,
    junk                 INTEGER NOT NULL DEFAULT 0,
    logged_at            TEXT    NOT NULL,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    telegram_message_id  INTEGER UNIQUE,
    obsidian_anchor      TEXT
);

CREATE INDEX IF NOT EXISTS idx_food_logs_logged_at ON food_logs(logged_at);
CREATE INDEX IF NOT EXISTS idx_food_logs_user_id ON food_logs(user_id);

CREATE TABLE IF NOT EXISTS _migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
