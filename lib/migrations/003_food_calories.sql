-- Add stored calorie estimate columns to food_logs.
-- est_calories_kcal: total kcal estimate from estimate_calories() at insert/edit time.
-- est_calories_items_json: per-item breakdown (list of {name, quantity, kcal}) so
-- the calorie_query path can render details without a fresh LLM call.
-- Both nullable: rows persisted before this migration, OR rows where the
-- estimate call failed at insert time, will have NULL.

ALTER TABLE food_logs ADD COLUMN est_calories_kcal INTEGER;
ALTER TABLE food_logs ADD COLUMN est_calories_items_json TEXT;
