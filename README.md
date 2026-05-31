# cerebro

Personal assistant Telegram bot — single-user, scoped to me.

This is the food-domain MVP slice. The full vision (workouts, body metrics,
tasks, habits, ideas, journal, divedeep research) is in
[`../personal-assistant/prd-v2.md`](../personal-assistant/prd-v2.md). Layers
land one at a time on top of this skeleton.

## What this slice does

- **Log food.** Telegram message → DeepSeek (via OpenRouter) classifies intent
  and extracts items → SQLite row + appended line in today's Obsidian daily
  note → `✅ logged …` confirmation.
- **Edit a log.** Reply to a confirmation with the corrected text → row
  updated, daily-note line replaced in place → `✏️ updated …`.
- **Delete a log.** Reply to a confirmation saying "delete that", or send
  "remove the samosa" / "undo last" without a reply → row removed, line
  removed from the daily note → `🗑️ removed …`.
- **Calorie breakdown.** Send "calorie breakdown", "cal for today", "calories
  yesterday", or reply to a specific entry → LLM estimates per-item kcal +
  total → `📊 …` reply with a rough estimate.
- **Workouts via Hevy.** `/sync` pulls newest workouts (full history on first
  run, incremental after). Each session lands as a structured row in SQLite
  and a one-line summary under `## Workout` in the daily note —
  `Push Day · 8 exercises · 12.4k kg · 1h 23m · ~340 kcal`.
- **Workout narrative.** Saying "workout done, felt strong" → auto-runs sync,
  appends your narrative as a `> blockquote` under today's `## Workout`,
  replies with both the sync result and a note confirmation. Narratives are
  Obsidian-only by design (lets the LLM read context later for pattern
  questions).
- **Profile / BMR / calories.** `/profile height=170 age=27 sex=M weight=73`
  sets the profile used to compute BMR (Mifflin-St Jeor) and per-workout
  calories (MET×weight×duration). Updating profile retroactively recomputes
  calories on every stored workout.
- `#junk` tag flips a flag on a food entry and surfaces a `⚠️ junk` warning.
- Allowlist: bot only responds to the configured Telegram user id.

## Setup

### 1. Credentials

Create `.env` from the template and fill in:

```bash
cp .env.example .env
```

You need:

| Var | Where to get it |
|---|---|
| `telegram bot token` | Message [@BotFather](https://t.me/BotFather), `/newbot` |
| `telegram user id` | Message [@userinfobot](https://t.me/userinfobot) |
| `open router key` | Sign up at [openrouter.ai](https://openrouter.ai), top up $5, generate key |
| `hevy key` | [hevy.com/settings?developer](https://hevy.com/settings?developer) (Pro account required) |
| `brave search key` | Optional in food MVP (used later by `#divedeep`). Free tier: [brave.com/search/api](https://brave.com/search/api/) |

Other vars (`DB_PATH`, `VAULT_ROOT`, `TIMEZONE`, `LLM_MODEL`) have sane
defaults in `.env.example`.

### 2. Install

Python 3.12 required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Run

```bash
source .venv/bin/activate
python -m app.bot
```

The bot opens long-polling against Telegram. First run creates
`data/cerebro.sqlite` and writes daily notes under `vault/daily/`.

### 4. Verify with the bot

In Telegram:

1. `/start` — should reply with a usage line.
2. `/profile height=170 age=27 sex=M weight=73` — reply shows BMR.
3. `/sync` — first run pulls all your Hevy history; subsequent runs are
   incremental. Reply: `🏋️ synced N new workouts`.
4. `had dal chawal at 1pm` — reply `✅ logged 13:00 — dal, chawal`.
5. Reply to that confirmation with `dal chawal and raita` — reply
   `✏️ updated 13:00 — dal, chawal, raita`.
6. `samosa #junk` — reply contains `⚠️ junk`.
7. `calorie breakdown` — reply starts with `📊` and shows per-item kcal +
   total for the most recent entry.
8. `cal for today` — same shape, summed across today's entries.
9. Reply to your dal-chawal-raita confirmation with `delete that` — reply
   starts with `🗑️ removed`.
10. `workout done, felt strong` — reply starts with `🏋️` (sync result)
    and includes `📝 noted: "…"`.

Check `vault/daily/<today>.md` — entries appear under `## Food` and
`## Workout`.
Check the SQLite row counts:
  `sqlite3 data/cerebro.sqlite 'select count(*) from food_logs'`
  `sqlite3 data/cerebro.sqlite 'select count(*) from workouts'`

## Project layout

```
cere-bro/
├── app/
│   ├── bot.py              # Telegram polling, allowlist, edit-by-reply
│   ├── config.py           # .env-driven Settings
│   ├── models.py           # FoodItem, FoodParse, FoodLog
│   ├── llm.py              # OpenRouter (DeepSeek) structured parsing
│   ├── db.py               # SQLite + tiny migrations runner
│   ├── migrations/
│   │   └── 001_init.sql
│   ├── domains/
│   │   └── food.py         # parse → persist → vault → reply
│   └── sinks/
│       └── obsidian.py     # daily-note writer + vault scaffold
├── tests/
│   └── test_food_domain.py # 4 tests, mocks LLM
├── vault/                   # gitignored; auto-managed by the bot
│   ├── daily/
│   ├── ideas/
│   ├── projects/
│   ├── journal/
│   ├── dashboards/
│   └── .backups/
├── data/                    # gitignored; SQLite lives here
├── pyproject.toml
└── .env.example
```

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

The LLM is mocked. No network calls.

## Known v1 limitations

- **Reply-context is in-memory only.** Restart the bot and the
  bot-reply → food_log map is empty. Edits / deletes / queries via
  reply-to fall back to a fresh request after restart and the bot warns the
  user. Persistent reply-context is a v1.1 task (add `bot_reply_message_id`
  column + migration).
- **Calorie estimates are LLM guesses.** ±25% off typical for Indian
  portions. Reply uses `≈` and a `(rough estimate)` tag. Good enough to
  notice trends; not a tracker replacement.
- **`item_hint` matching is fuzzy.** "samosa" matches stored `samosa` via
  case-insensitive substring on item names within the last 50 entries.
  Won't catch typos. Acceptable for MVP.
- **No Notion sync yet.** PRD calls for 6h batch sync. Layer in next.
- **Macros not extracted.** Items + junk flag only. Calories are computed on
  demand by the LLM, not stored.
- **No Hevy, body metrics, tasks, habits, journal, divedeep.** Per the
  layered roadmap.
- **DeepSeek structured-output verification pending.** First real call will
  confirm OpenRouter forwards `response_format=Pydantic schema` correctly to
  DeepSeek. If parsed comes back `None`, fallback returns `intent='other'`
  (or `notes='estimate failed'` for calories). One-line edit in `app/llm.py`
  to switch to JSON mode + `model_validate_json` if needed.

## Next layers (in order)

1. Notion sink (every-6h batch).
2. Body metrics intent (`/metrics weight=… bodyfat=…`) + Hevy `events` API
   for delete sync.
3. Tasks + habits with streaks + weekly score.
4. Ideas + projects domain (file writes to vault).
5. Daily git commit at 23:55 IST (vault repo, separate origin).
6. Proactive prompts (apscheduler) + nightly auto-sync at 23:30 IST.
7. `#divedeep` (Brave Search → Playwright fetch → trafilatura → DeepSeek synthesis).
8. Weekly digest.
