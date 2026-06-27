-- Track Notion page IDs so we can update instead of duplicate-create.
CREATE TABLE IF NOT EXISTS notion_pages (
    entity_type    TEXT NOT NULL,   -- 'food' | 'workout' | 'task' | 'idea' | 'journal'
    entity_id      TEXT NOT NULL,   -- local id (food_log_id, hevy_id, task_id, slug, date)
    notion_page_id TEXT NOT NULL,
    synced_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (entity_type, entity_id)
);
