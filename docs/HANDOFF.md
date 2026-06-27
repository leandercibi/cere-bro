# Cerebro — Agent Handoff Document

**Date:** June 25, 2026
**Status:** Functional with test data loaded, Notion dashboards synced

---

## Architecture Overview

Cerebro is a **Telegram polling bot** that acts as a personal life-management assistant. Users send natural language messages via Telegram, and an LLM (DeepSeek v4 Flash via OpenRouter) routes them to the appropriate tool using OpenAI-compatible tool-calling.

```
Telegram → bot_v2.py → router.py → LLM (tool-calling) → tools/*.py
                                                              ↓
                                                    SQLite + Obsidian vault
```

### Core Components

| File | Purpose |
|------|---------|
| `app/main.py` | Entry point — starts Telegram polling |
| `app/bot_v2.py` | Telegram message handlers, connects to router |
| `app/router.py` | LLM tool-calling router with system prompt, dispatches to tools, formats responses |
| `app/llm.py` | OpenRouter client wrapper with retry logic |
| `app/session.py` | In-memory session buffer for multi-turn context |
| `app/tools/registry.py` | Tool registry with auto parameter schema generation from type hints |
| `lib/config.py` | Pydantic-settings `Settings` class, reads `.env` |
| `lib/db.py` | SQLite persistence layer with migration runner |
| `lib/sinks/obsidian.py` | Writes daily notes, food logs, workout summaries to Obsidian vault |
| `lib/integrations/hevy.py` | Hevy API client for workout sync |
| `serve.py` | **NEW** — HTTP wrapper for local testing without Telegram |

### Data Sinks

- **SQLite** (`data/cerebro.sqlite`) — primary storage for food_logs, tasks, workouts, user_profile
- **Obsidian vault** (`vault/`) — daily notes, idea files, food/workout markdown entries
- **No native Notion sink** — Notion sync is done via external scripts (see below)

---

## Tools (registered in `app/tools/`)

| Tool | File | What it does |
|------|------|-------------|
| `log_food` | `food.py` | Log a meal with LLM-estimated macros (calories, protein, fat, carbs) |
| `edit_food` | `food.py` | Edit an existing food log entry |
| `delete_food` | `food.py` | Delete a food log entry |
| `query_macros` | `food.py` | Query daily/period macro totals |
| `log_workout_note` | `workout.py` | Log a workout note + trigger Hevy sync |
| `sync_workouts` | `workout.py` | Manually trigger Hevy API sync |
| `query_workouts` | `workout.py` | Query workout history |
| `capture_idea` | `ideas.py` | Save an idea to `vault/ideas/` as markdown |
| `deepdive_idea` | `ideas.py` | Research an idea using Tavily web search |
| `log_journal` | `journal.py` | Append to today's daily note in `vault/daily/` |
| `log_task` | `tasks.py` | Create a task in SQLite |
| `complete_task` | `tasks.py` | Mark a task as done |
| `query_tasks` | `tasks.py` | List open/completed tasks |
| `update_profile` | `profile.py` | Set weight, height, age, sex |
| `get_profile` | `profile.py` | Retrieve user profile |

---

## Recent Changes (This Session)

### 1. HTTP Server (`serve.py`) — NEW

A thin HTTP wrapper around `route()` for local testing without Telegram infrastructure.

```bash
cd /Users/leander/personal-projects/cere-bro
python serve.py  # Starts on port 8008
```

- `POST /message` — accepts `{"text": "..."}`, returns `{"reply": "...", "tool_called": "..."}`
- `GET /health` — returns `{"status": "ok"}`
- Uses asyncio event loop in a daemon thread for async route() calls

### 2. Notion Dashboard — GAMIFY Page Redesign

The GAMIFY page (`388ac5f672a5812a93bff3e7b540e536`) was rebuilt with themed sections:

- **Hero** banner
- **Command Center** — 2-column: Player Card + Quick Actions
- **Daily Grind** — 2-column: Active Quests (Tasks) + Today's Habits
- **Operations** — 2-column: Ideas Pipeline + Fuel Station (Food Logs)
- **Performance** — 2-column: Battle Log (Workouts) + Weekly Scoreboard
- **Rewards Shop** — link to rewards database
- **Game Guide** — toggle sections with tips

Script: `/tmp/redesign_gamify2.py`

### 3. Notion Data Sync (`/tmp/sync_to_notion.py`)

Since Cerebro has no native Notion sink, a sync script was created to push SQLite/vault data into Notion databases:

- Syncs food logs, workouts, ideas, tasks from SQLite and vault
- Generates fake habit scores (7 days) and scoreboard entries (4 weeks)
- Created 60+ Notion pages across all databases

### 4. Test Data Population (`/tmp/populate_cerebro.py`)

A script that sends natural language messages to the HTTP server to test the LLM router:

- 37 messages across categories: food, tasks, journal, ideas, workouts, profile
- Tests varied message styles (structured vs. casual)
- Logs all responses to `/tmp/cerebro_test_data.json`
- **Finding:** The router struggles with some task/journal messages — only 3 out of 8 task messages triggered `log_task`. The rest were handled conversationally.

### 5. HOST — Solo Leveling Dashboard Integration

The existing HOST page (`649ac5f672a58399ab190172499fb143`) was integrated with Cerebro data:

- **CEREBRO STATS** section added to Player column with computed Level, Rank, XP, Gold
- **CEREBRO FEED** section added to System column with notifications
- 10 HOST Tasks created (linked to My Character) to feed the formula chain
- Script: `/tmp/sync_cerebro_to_host.py`

**XP System (computed by sync script, not Notion formulas):**

| Activity | XP per unit |
|----------|------------|
| Workout | 150 XP |
| Task | 75 XP |
| Habit day | 50 XP |
| Idea | 30 XP |
| Food log | 25 XP |

Current stats: Level 5 "Rising Shadow", D-Rank Hunter, 5,635 XP, 56 Gold

**Known Issue:** The HOST page's native My Character formulas still show -5100 XP (login penalty debt). The CEREBRO STATS section bypasses this with directly computed values. The native formula chain depends on Notion button automations that cannot be triggered via API.

---

## Notion Database IDs

### Cerebro Databases (under GAMIFY page)

| Database | ID |
|----------|-----|
| Food Logs | `388ac5f6-72a5-81cf-9f44-d01a7452a542` |
| Daily Habits | `388ac5f6-72a5-8114-af84-d415efc37bac` |
| Tasks | `388ac5f6-72a5-81ee-a041-cf474ccae715` |
| Rewards Shop | `388ac5f6-72a5-8148-bd9d-e9e33de8ddcb` |
| Scoreboard | `388ac5f6-72a5-81c0-ac63-cd5a0f5da57c` |
| Ideas | `388ac5f6-72a5-81c6-822b-f10cc99c786d` |
| Workouts | `388ac5f6-72a5-81a4-97f5-cc8dd4ed604b` |

### HOST Solo Leveling Databases

| Database | ID |
|----------|-----|
| My Character | `9caac5f6-72a5-839a-bc1e-011aee654cff` |
| My Character Entry | `592ac5f6-72a5-82fe-a3b6-81905a6aa5e2` (page) |
| HOST Tasks | `07fac5f6-72a5-83eb-9f1d-012f6209f7c9` |
| System | `594ac5f6-72a5-8343-a07c-01534346a2de` |
| Habit Tracker | `383ac5f6-72a5-82ff-8853-81dc5702fc67` |
| Activities | `3f8ac5f6-72a5-837a-937a-81e346cc515d` |

### Key Page IDs

| Page | ID |
|------|-----|
| GAMIFY | `388ac5f672a5812a93bff3e7b540e536` |
| HOST - Solo Leveling | `649ac5f6-72a5-8399-ab19-0172499fb143` |

### Notion Integration

- Integration name: **Manager**
- API key env var: `NOTION_API_KEY`
- API version: `2022-06-28`

---

## Fake/Test Data (Pending Cleanup)

The user has asked to be able to delete all fake entries on their go-ahead. Here's what's fake:

### SQLite (`data/cerebro.sqlite`)

| Table | Fake IDs | Description |
|-------|----------|-------------|
| food_logs | 12–19 | Test food entries from Jun 24 (poha, chole bhature, chips, dosa, paneer, etc.) |
| tasks | 1–3 | "Submit quarterly report", "Buy whey protein", "Renew gym membership" |

Real food data: IDs 1, 5–11 (from actual user messages, May 30 – Jun 16)

### Obsidian Vault

| Path | Fake? |
|------|-------|
| `vault/ideas/chrome-extension-*` | Yes — generated by populate script |
| `vault/ideas/cli-tool-*` | Yes |
| `vault/ideas/sleep-tracking-*` | Yes |
| `vault/ideas/spaced-repetition-*` | Yes |
| `vault/ideas/automate-weekly-*` | Yes |
| `vault/ideas/stock-swing-*` | Yes |
| `vault/ideas/app-to-save-instagram-*` | Possibly real — has 953B (more content) |
| `vault/daily/2026-06-24.md` | Contains fake entries mixed with real |

### Notion (created by sync scripts)

- All pages in Cerebro databases (Food Logs, Tasks, Daily Habits, Ideas, Scoreboard, Workouts) were created by `/tmp/sync_to_notion.py`
- Daily Habits entries (7 days of fake scores/moods) are entirely synthetic
- Scoreboard entries (4 weeks) are entirely synthetic
- HOST Tasks (10 entries) created by `/tmp/sync_cerebro_to_host.py` — IDs in `/tmp/host_sync_cleanup.json`

### Cleanup Script Locations

| File | What it tracks |
|------|---------------|
| `/tmp/cerebro_test_data.json` | All 37 test messages sent + responses |
| `/tmp/host_sync_cleanup.json` | 10 HOST Task page IDs to delete |

### Cleanup Procedure

```python
# SQLite cleanup
DELETE FROM food_logs WHERE id BETWEEN 12 AND 19;
DELETE FROM tasks WHERE id BETWEEN 1 AND 3;

# Obsidian cleanup — delete fake idea files
# (verify app-to-save-instagram one with user first)

# Notion cleanup — delete all pages created by sync scripts
# Use Notion API: DELETE /v1/blocks/{page_id} for each

# HOST Tasks cleanup — use IDs from /tmp/host_sync_cleanup.json
```

---

## Known Bugs and Issues

### 1. LLM Router Misses (High Priority)
The LLM (DeepSeek v4 Flash) doesn't always call the right tool for natural language input:
- Task messages like "remind me to buy groceries" sometimes get conversational responses instead of calling `log_task`
- Journal entries sometimes don't trigger `log_journal`
- Only ~40% of casual-style task messages correctly trigger tools
- **Root cause:** The system prompt instructs tool use, but the model's tool-calling behavior is inconsistent with informal phrasing
- **Potential fix:** Add few-shot examples to the system prompt, or switch to a stronger model for routing

### 2. HOST My Character XP Formula Chain (Medium)
- My Character shows -5100 XP due to accumulated login penalty (XP Loss system)
- HOST Tasks created via API show 0 XP — the formulas depend on Notion button automations (`Completed 🟢` button) that can't be triggered via API
- The CEREBRO STATS text blocks bypass this but aren't truly dynamic (need re-run of sync script)

### 3. Notion Free Plan Block Limit (Medium)
- Workspace shows "Running out of free blocks" (near 1,000 limit)
- Every Notion page/entry = 1 block
- The sync scripts created ~80+ pages, significantly eating into the limit
- Future syncs need to be block-conscious or the user needs to upgrade

### 4. Hevy Workout Names Missing
- Workout entries in Notion show "Unknown" for workout names
- The sync script couldn't extract workout names from the Notion database (property name mismatch)
- The 28 workouts are real (from Hevy API) but their titles aren't displaying correctly in the sync

### 5. No Notion Sink in Core App
- The app only sinks to SQLite + Obsidian
- Notion sync is done via separate scripts, not integrated into the tool pipeline
- If Notion becomes the primary dashboard, a native Notion sink should be built

---

## Environment Setup

```bash
cd /Users/leander/personal-projects/cere-bro

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Required env vars in .env:
TELEGRAM_BOT_TOKEN=       # Telegram bot token
TELEGRAM_ALLOWED_USER_ID= # Single-user whitelist
OPENROUTER_API_KEY=       # For DeepSeek v4 Flash
LLM_MODEL=deepseek/deepseek-v4-flash
TAVILY_API_KEY=           # For idea deep-dive research
DB_PATH=./data/cerebro.sqlite
VAULT_ROOT=./vault
TIMEZONE=Asia/Kolkata
HEVY_API_KEY=             # For workout sync
NOTION_API_KEY=           # For Notion dashboard sync

# Run the bot
python -m app.main        # Telegram polling mode
python serve.py           # HTTP mode on port 8008

# Run tests
pytest
```

---

## Future Development / Improvement Ideas

### High Priority
1. **Native Notion sink** — Add a Notion writer to `lib/sinks/` so food logs, tasks, workouts auto-sync to Notion databases on every tool call
2. **Fix router reliability** — Improve tool-calling accuracy with few-shot examples, system prompt tuning, or switching to a stronger model (Claude, GPT-4o)
3. **Cleanup script** — Build a single `cleanup.py` that removes all fake/test data from SQLite, Obsidian, and Notion in one go

### Medium Priority
4. **Standalone web dashboard** — A local HTML/JS dashboard served from Cerebro that renders real charts/gauges from SQLite (bypasses Notion limitations entirely)
5. **Cron-based Notion sync** — Automate the sync scripts on a schedule so the HOST page always shows fresh stats
6. **HOST formula chain fix** — Either fix the XP Loss debt or restructure the My Character formulas to read from Cerebro data directly
7. **Workout name mapping** — Fix the Hevy sync to correctly map workout titles into the Notion Workouts database
8. **Sleep/habit tracking** — Add tools for logging sleep, mood, water intake

### Low Priority
9. **Multi-turn tool calling** — Currently only the first tool call is handled per message; support chained tool calls
10. **Notion search/query** — Allow querying Notion databases from Telegram ("what did I eat last week?")
11. **Reward system** — Implement the Rewards Shop (spend Gold on self-defined rewards)
12. **ChartBase radar chart sync** — Update the Statistics radar chart values programmatically (requires ChartBase API or embed URL manipulation)

---

## File Reference — Temp Scripts

These are in `/tmp/` and will be lost on reboot. Copy to the project if needed.

| Script | Purpose |
|--------|---------|
| `/tmp/redesign_gamify2.py` | Rebuilds the GAMIFY Notion page layout |
| `/tmp/sync_to_notion.py` | Syncs SQLite/vault data → Cerebro Notion databases |
| `/tmp/populate_cerebro.py` | Sends test messages to HTTP server for NLP testing |
| `/tmp/sync_cerebro_to_host.py` | Syncs Cerebro stats → HOST Solo Leveling page |

---

## Quick Reference — API Endpoints

### Cerebro HTTP Server (serve.py)
```bash
# Log food
curl -X POST localhost:8008/message -H 'Content-Type: application/json' \
  -d '{"text": "had dal chawal for lunch"}'

# Log a task
curl -X POST localhost:8008/message -H 'Content-Type: application/json' \
  -d '{"text": "#task buy groceries by friday"}'

# Health check
curl localhost:8008/health
```

### Notion API
```bash
NOTION_KEY="<from .env>"

# Query a database
curl -s "https://api.notion.com/v1/databases/{DB_ID}/query" \
  -H "Authorization: Bearer $NOTION_KEY" \
  -H "Notion-Version: 2022-06-28" \
  -H "Content-Type: application/json" -d '{}'

# Get page blocks
curl -s "https://api.notion.com/v1/blocks/{PAGE_ID}/children" \
  -H "Authorization: Bearer $NOTION_KEY" \
  -H "Notion-Version: 2022-06-28"
```
