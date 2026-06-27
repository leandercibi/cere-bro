# Cerebro v2 — Tool-Calling Router Architecture

> Technical plan with TDD task breakdown  
> Replaces: rigid `MessageParse` intent schema  
> Keeps: all domain logic, DB layer, Obsidian sink, integrations  
> Model: DeepSeek v4 Flash via OpenRouter (tool-calling capable)

---

## 1. Architecture overview

### What changes

```
v1 (current):
  telegram msg → LLM call #1 (intent classification via structured output)
               → Python dispatcher (if/elif on intent string)
               → domain handler (may call LLM #2 for calorie estimation)
               → response

v2 (target):
  telegram msg → session buffer (last N messages, 15-min TTL)
               → single LLM call with tools[] defined
               → model returns tool_call(name, args)
               → execute matching Python function
               → format response → send to Telegram
```

### What stays the same

- SQLite as source of truth (`data/cerebro.sqlite`)
- All DB schema + migrations
- Obsidian vault writes (daily notes, ideas)
- Hevy, Tavily, Open Food Facts integrations
- Telegram as primary interface
- `python-telegram-bot` for the bot layer
- `apscheduler` for cron jobs (Hevy sync, prompts)
- `openai` SDK for LLM calls (OpenRouter compatible)
- Single-user, single-process on OCI

### What gets deleted

- `app/models.py`: `MessageParse`, all `*Payload` classes (7 intent payloads)
- `app/llm.py`: `parse_message()` function + its ~100-line system prompt
- `app/domains/food.py`: the `handle_message()` dispatcher + all intent routing
- `app/bot.py`: `_ReplyMap`, intent-specific routing in `on_message()`

### What gets created

| New file | Purpose |
|---|---|
| `app/tools/food.py` | Tool functions: `log_food`, `delete_food`, `query_macros` |
| `app/tools/workout.py` | Tool functions: `log_workout_note`, `sync_workouts`, `query_workouts` |
| `app/tools/ideas.py` | Tool functions: `capture_idea`, `deepdive_idea` |
| `app/tools/journal.py` | Tool function: `log_journal` |
| `app/tools/tasks.py` | Tool functions: `log_task`, `complete_task`, `query_tasks` |
| `app/tools/profile.py` | Tool functions: `update_profile`, `get_profile` |
| `app/tools/registry.py` | Tool registry: collects all tools, generates OpenAI tool schemas |
| `app/router.py` | Single LLM call with tools, session buffer, response formatting |
| `app/session.py` | Per-user session buffer with TTL |
| `app/bot_v2.py` | Slim Telegram bot: receives message → router → reply |

### Dependency tree

```
bot_v2.py
  └── router.py
        ├── session.py (conversation buffer)
        ├── tools/registry.py
        │     ├── tools/food.py      → db.py, sinks/obsidian.py
        │     ├── tools/workout.py   → db.py, sinks/obsidian.py, integrations/hevy.py
        │     ├── tools/ideas.py     → sinks/obsidian.py, integrations/tavily.py
        │     ├── tools/journal.py   → sinks/obsidian.py
        │     ├── tools/tasks.py     → db.py
        │     └── tools/profile.py   → db.py
        └── openai SDK (tool-calling)
```

---

## 2. Core contracts

### 2.1 Tool function contract

Every tool is a plain async Python function with typed arguments and a typed
return. No framework dependency. No Telegram objects. No LLM objects.

```python
# Example: tools/food.py

@dataclass
class LogFoodResult:
    food_log_id: int
    summary: str        # human-readable one-liner for Telegram
    logged_at: str      # ISO timestamp
    estimated_kcal: int | None
    estimated_macros: dict | None  # {protein_g, fat_g, carbs_g}

async def log_food(
    items: list[dict],      # [{name: str, quantity: str | None}]
    junk: bool = False,
    time: str | None = None,  # "1pm", "13:00", "lunch" — parsed by tool
    notes: str | None = None,
    *,
    user_id: int,           # injected by router, not from LLM
    settings: Settings,     # injected by router
) -> LogFoodResult:
    ...
```

**Rules:**
- Arguments from the LLM are the function's public parameters (the tool schema)
- `user_id` and `settings` are injected by the router (not exposed to the LLM)
- Return a dataclass/dict with structured data — the router formats it for Telegram
- Raise `ToolError(user_message)` for user-facing errors ("no entries found")
- Let unexpected exceptions bubble — the router catches and replies with a generic error

### 2.2 Tool registry contract

```python
# tools/registry.py

@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict        # JSON Schema for the LLM
    handler: Callable       # the async function to call

def get_all_tools() -> list[ToolDef]:
    """Collect all registered tools. Called once at startup."""

def get_openai_tools() -> list[dict]:
    """Return the tools in OpenAI API format for the tool-calling request."""
```

Tool registration is explicit (no magic decorators, no scanning). Each
`tools/*.py` module exports a `TOOLS` list. `registry.py` concatenates them.

### 2.3 Session buffer contract

```python
# session.py

class SessionBuffer:
    """Per-user sliding window of recent messages for conversational context."""

    def __init__(self, max_messages: int = 20, ttl_seconds: int = 900):
        ...

    def add(self, user_id: int, role: str, content: str) -> None:
        """Append a message. Evicts oldest if over max_messages or TTL."""

    def get(self, user_id: int) -> list[dict]:
        """Return [{"role": ..., "content": ...}, ...] for the user."""

    def clear(self, user_id: int) -> None:
        """Wipe a user's buffer."""
```

In-memory only. Single-user system — no persistence needed. Restart clears
context, which is fine (v1 has no context at all).

### 2.4 Router contract

```python
# router.py

@dataclass
class RouterResult:
    reply_text: str
    tool_called: str | None  # which tool was invoked, for logging

async def route(
    message_text: str,
    user_id: int,
    settings: Settings,
) -> RouterResult:
    """
    1. Retrieve session buffer for user_id
    2. Build messages = system_prompt + buffer + current message
    3. Call LLM with tools=get_openai_tools()
    4. If tool_call returned: execute handler, format result, return
    5. If no tool_call (plain text): return the LLM's text response
    6. Append user message + assistant response to buffer
    """
```

### 2.5 System prompt

```
You are Cerebro, a personal assistant. You help the user log food, workouts,
ideas, tasks, and journal entries. You also answer questions about their
logged data.

Use the available tools to fulfill requests. If a message doesn't match any
tool, respond conversationally in 1-2 sentences.

Current datetime: {now_iso}
User timezone: {timezone}

User profile:
{profile_yaml}
```

**Token budget estimate:**
- System prompt: ~150 tokens
- Tool definitions (10-12 tools): ~400 tokens
- Session buffer (10 messages avg): ~500 tokens
- User message: ~50 tokens
- **Total input: ~1100 tokens per request**
- Output (tool call or text): ~100-200 tokens
- **Total per interaction: ~1300 tokens**

At DeepSeek v4 Flash pricing ($0.10/M input, $0.30/M output via OpenRouter):
~$0.0002 per interaction. 50 interactions/day = $0.01/day = **$0.30/month**.

---

## 3. Task breakdown (TDD order)

Each task follows red-green-refactor: write failing tests first, then
implement until green, then clean up.

### Phase 0: Infrastructure scaffolding

#### T0.1 — Project restructure

**What:** Create `app/tools/` package, `app/router.py`, `app/session.py`,
`app/bot_v2.py` as empty files. Add `app/tools/__init__.py` and
`app/tools/registry.py`.

**Tests:** None (structural only).

**Success criteria:** `from app.tools.registry import get_all_tools` imports
without error. `from app.session import SessionBuffer` imports.

**Expected outcome:** Clean package structure ready for TDD.

---

#### T0.2 — ToolError exception class

**What:** Define `app/tools/errors.py` with `ToolError(user_message: str)`.

**Tests:**
```
test_tool_error_carries_message
test_tool_error_is_exception
```

**Success criteria:** `raise ToolError("no entries")` is catchable and
`.user_message` is accessible.

---

#### T0.3 — SessionBuffer

**What:** Implement `app/session.py`.

**Tests (write first):**
```
test_add_and_get_returns_messages_in_order
test_max_messages_evicts_oldest
test_ttl_evicts_expired_messages
test_get_empty_user_returns_empty_list
test_clear_wipes_user_buffer
test_independent_users_dont_leak
```

**Success criteria:** All 6 tests pass. No external dependencies.

**Expected outcome:** A working in-memory buffer with TTL. ~40 lines of
implementation.

---

#### T0.4 — Tool registry

**What:** Implement `app/tools/registry.py` — tool collection and OpenAI
schema generation.

**Tests (write first):**
```
test_register_tool_from_function_signature
test_get_openai_tools_format_matches_spec
test_tool_description_included
test_parameter_types_mapped_correctly (str, int, float, bool, list, optional)
test_required_vs_optional_params
test_injected_params_excluded_from_schema (user_id, settings)
```

**Success criteria:** Given a typed async function, produces a valid OpenAI
tool definition with correct JSON Schema for parameters.

**Expected outcome:** ~80 lines. Uses `inspect.signature` + type hints to
build schemas. No LLM calls.

---

### Phase 1: Tool functions (pure logic, no LLM)

Each tool function is tested against a real SQLite DB (in-memory or tmp_path)
and a tmp_path vault. LLM calls within tools (calorie estimation) are mocked.
These tests prove the tools work correctly in isolation.

#### T1.1 — `tools/food.py`: `log_food`

**What:** Extract food-logging logic from `domains/food.py::_handle_food_log`
into a standalone tool function.

**Tests (write first):**
```
test_log_food_inserts_row_in_db
test_log_food_with_junk_flag
test_log_food_with_explicit_time_parses_correctly
test_log_food_without_time_defaults_to_now
test_log_food_writes_obsidian_daily_note
test_log_food_estimates_macros (mock LLM)
test_log_food_macro_estimate_failure_still_logs
test_log_food_returns_structured_result
test_log_food_recomputes_daily_totals
```

**Success criteria:** 9 tests pass. Food row in SQLite matches input.
Obsidian daily note has the food line. Macro estimate stored on row.
`daily_totals` cache updated.

**Expected outcome:** ~80 lines. Reuses `db.insert_food_log`,
`sinks/obsidian.append_food`, `llm.estimate_calories` (mocked in tests).

---

#### T1.2 — `tools/food.py`: `edit_food`

**What:** Edit an existing food log entry by ID.

**Tests (write first):**
```
test_edit_food_updates_items_and_junk
test_edit_food_updates_obsidian_line
test_edit_food_re_estimates_macros (mock LLM)
test_edit_food_recomputes_daily_totals_for_both_days (if date changed)
test_edit_food_nonexistent_id_raises_tool_error
```

**Success criteria:** 5 tests pass.

---

#### T1.3 — `tools/food.py`: `delete_food`

**What:** Delete a food log entry.

**Tests (write first):**
```
test_delete_food_by_id_removes_row
test_delete_food_removes_obsidian_line
test_delete_food_by_hint_finds_matching_item
test_delete_food_last_entry
test_delete_food_recomputes_daily_totals
test_delete_food_not_found_raises_tool_error
```

**Success criteria:** 6 tests pass.

---

#### T1.4 — `tools/food.py`: `query_macros`

**What:** Query calorie/macro breakdown for a scope (today, yesterday,
last, by_date, matching item).

**Tests (write first):**
```
test_query_macros_today_sums_all_entries
test_query_macros_yesterday
test_query_macros_last_returns_most_recent
test_query_macros_by_date
test_query_macros_matching_item
test_query_macros_empty_day_raises_tool_error
test_query_macros_includes_daily_totals
test_query_macros_fallback_live_estimate_when_stored_is_null (mock LLM)
```

**Success criteria:** 8 tests pass. Returns structured data (not formatted
strings).

---

#### T1.5 — `tools/workout.py`: `log_workout_note`

**What:** Log a narrative workout note to Obsidian + trigger Hevy sync.

**Tests (write first):**
```
test_log_workout_note_appends_blockquote_to_daily_note
test_log_workout_note_triggers_hevy_sync (mock Hevy)
test_log_workout_note_sync_stores_new_workouts
test_log_workout_note_sync_skips_known_workouts
```

**Success criteria:** 4 tests pass. Reuses existing `handle_workout_note`
logic from `domains/workout.py`.

---

#### T1.6 — `tools/workout.py`: `sync_workouts`

**What:** Manual Hevy sync command (replaces `/sync`).

**Tests (write first):**
```
test_sync_workouts_pulls_all_pages (mock Hevy)
test_sync_workouts_idempotent
test_sync_workouts_writes_obsidian_summaries
test_sync_workouts_computes_calories_with_profile (mock profile)
test_sync_workouts_without_profile_skips_calories
test_sync_workouts_returns_count_and_summary
```

**Success criteria:** 6 tests pass.

---

#### T1.7 — `tools/workout.py`: `query_workouts`

**What:** Query workout history (today, this week, by date).

**Tests (write first):**
```
test_query_workouts_today
test_query_workouts_this_week
test_query_workouts_by_date
test_query_workouts_empty_raises_tool_error
```

**Success criteria:** 4 tests pass.

---

#### T1.8 — `tools/ideas.py`: `capture_idea`

**What:** Create a new idea file in the vault.

**Tests (write first):**
```
test_capture_idea_creates_file_with_template
test_capture_idea_with_description_and_tags
test_capture_idea_slug_collision_appends_suffix
test_capture_idea_returns_slug_and_path
```

**Success criteria:** 4 tests pass. Reuses `domains/ideas.py` logic.

---

#### T1.9 — `tools/ideas.py`: `deepdive_idea`

**What:** Research an idea via Tavily + LLM synthesis.

**Tests (write first):**
```
test_deepdive_single_match_runs_research (mock Tavily + LLM)
test_deepdive_no_match_creates_then_researches
test_deepdive_multiple_matches_returns_disambiguation_list
test_deepdive_no_hint_lists_recent_ideas
test_deepdive_already_researched_returns_existing_brief
test_deepdive_appends_brief_to_vault_file
```

**Success criteria:** 6 tests pass.

---

#### T1.10 — `tools/journal.py`: `log_journal`

**What:** Append a journal entry to today's daily note under `## Journal`.

**Tests (write first):**
```
test_log_journal_appends_to_daily_note
test_log_journal_creates_daily_note_if_missing
test_log_journal_multiple_entries_append_sequentially
```

**Success criteria:** 3 tests pass.

---

#### T1.11 — `tools/tasks.py`: `log_task`, `complete_task`, `query_tasks`

**What:** Task CRUD. New DB table `tasks` (migration 005).

**Tests (write first):**
```
test_log_task_inserts_row_with_due_date
test_log_task_without_due_date
test_complete_task_by_fragment_match
test_complete_task_not_found_raises_tool_error
test_query_tasks_today_returns_due_and_overdue
test_query_tasks_open_returns_all_incomplete
```

**Success criteria:** 6 tests pass. New migration applied.

**DB migration (005_tasks.sql):**
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    description TEXT NOT NULL,
    due_at      TEXT,               -- ISO datetime, nullable
    completed   INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
```

---

#### T1.12 — `tools/profile.py`: `update_profile`, `get_profile`

**What:** Wrap existing `db.upsert_profile` / `db.get_profile`.

**Tests (write first):**
```
test_update_profile_upserts_row
test_update_profile_partial_update_preserves_existing
test_get_profile_returns_current_values
test_get_profile_no_profile_raises_tool_error
test_update_profile_recomputes_workout_calories
```

**Success criteria:** 5 tests pass.

---

### Phase 2: Router (LLM integration)

#### T2.1 — Router: tool dispatch (mocked LLM)

**What:** Implement `app/router.py`. Mock the OpenAI client to return
predetermined tool_calls. Verify the router executes the right tool with
the right args.

**Tests (write first):**
```
test_router_dispatches_food_log_tool
test_router_dispatches_delete_food_tool
test_router_dispatches_query_macros_tool
test_router_dispatches_workout_note_tool
test_router_dispatches_capture_idea_tool
test_router_dispatches_journal_tool
test_router_dispatches_task_tool
test_router_plain_text_response_when_no_tool_call
test_router_injects_user_id_and_settings
test_router_tool_error_returns_user_message
test_router_unexpected_error_returns_generic_message
test_router_appends_to_session_buffer
test_router_includes_session_history_in_messages
test_router_system_prompt_includes_profile
test_router_system_prompt_includes_current_time
```

**Success criteria:** 15 tests pass. Router correctly bridges LLM tool
calls to Python functions.

**Expected outcome:** ~100 lines. The router is a thin async function:
build messages, call LLM, match tool name to handler, execute, format.

---

#### T2.2 — Router: multi-turn context

**What:** Verify the session buffer gives the LLM conversational context.

**Tests (write first):**
```
test_router_second_message_sees_first_in_context (mock LLM inspects messages)
test_router_buffer_ttl_clears_stale_context
test_router_buffer_max_messages_evicts_oldest
```

**Success criteria:** 3 tests pass.

---

#### T2.3 — Router: disambiguation flow

**What:** Handle multi-step flows like deepdive disambiguation (multiple
matching ideas → user picks one).

**Tests (write first):**
```
test_disambiguation_list_sent_on_multiple_matches
test_followup_number_resolves_to_correct_idea
test_non_numeric_followup_clears_disambiguation_state
```

**Success criteria:** 3 tests pass. The LLM sees the disambiguation list
in its context and the user's numeric reply; it calls `deepdive_idea` with
the resolved slug.

---

### Phase 3: Bot layer (Telegram integration)

#### T3.1 — `bot_v2.py`: message handling

**What:** Slim Telegram bot that passes messages to the router and sends
replies. Replaces `bot.py`.

**Tests (write first):**
```
test_bot_rejects_unauthorized_user
test_bot_passes_message_to_router (mock router)
test_bot_sends_router_reply_to_telegram (mock telegram)
test_bot_start_command_replies_help_text
test_bot_handles_router_exception_gracefully
```

**Success criteria:** 5 tests pass. Bot is ~60 lines.

---

#### T3.2 — Reply-to context

**What:** When user replies to a bot message, include the original message
in the session buffer so the LLM has context.

**Tests (write first):**
```
test_reply_to_food_confirmation_edits_that_entry
test_reply_to_with_delete_removes_that_entry
test_reply_to_unknown_message_works_as_fresh_request
```

**Success criteria:** 3 tests pass. Uses session buffer — no separate
`_ReplyMap` needed. The LLM sees the confirmation message in context and
decides whether to edit/delete.

---

### Phase 4: Cron jobs

#### T4.1 — Scheduled jobs

**What:** `apscheduler` jobs for Hevy nightly sync, proactive prompts,
daily Obsidian git commit.

**Tests (write first):**
```
test_hevy_nightly_sync_job_calls_sync_workouts
test_morning_tasks_push_sends_telegram_message
test_journal_prompt_sends_at_10pm
test_workout_check_skips_if_hevy_has_today
test_obsidian_git_commit_runs_at_2355
```

**Success criteria:** 5 tests pass. Jobs call tool functions (not
duplicated logic).

---

### Phase 5: Integration tests (LLM in the loop)

These tests make REAL LLM calls to DeepSeek via OpenRouter. They are
expensive (~$0.01 total) and slow (~2s each). Run separately:
`pytest tests/integration/ -m integration`.

#### T5.1 — End-to-end tool routing

**What:** Send natural language messages and verify the correct tool is
called with correct arguments.

**Tests:**
```
test_e2e_food_log_natural_language
  input: "had dal chawal and bhindi for lunch"
  expect: log_food called with items containing "dal chawal" and "bhindi"

test_e2e_food_log_with_junk
  input: "samosa #junk"
  expect: log_food called with junk=True

test_e2e_food_log_with_time
  input: "oats and banana at 8am"
  expect: log_food called with time containing "8"

test_e2e_delete_last
  input: "delete the last entry"
  expect: delete_food called with target="last"

test_e2e_calorie_query
  input: "how many calories today"
  expect: query_macros called with scope="today"

test_e2e_macro_query
  input: "macros for lunch"
  expect: query_macros called with scope="matching"

test_e2e_workout_note
  input: "workout done, felt strong, fasted"
  expect: log_workout_note called

test_e2e_idea_capture
  input: "#idea build a sleep tracker using Oura API"
  expect: capture_idea called with title containing "sleep tracker"

test_e2e_deepdive
  input: "deepdive predict workout times"
  expect: deepdive_idea called with hint containing "predict workout"

test_e2e_journal
  input: "tired today, didn't sleep well"
  (after 10pm prompt context) expect: log_journal called

test_e2e_task
  input: "#task submit invoice by Friday"
  expect: log_task called with description and due_date

test_e2e_greeting
  input: "hey"
  expect: no tool called, plain text response

test_e2e_ambiguous_defaults_to_no_tool
  input: "thanks"
  expect: no tool called
```

**Success criteria:** ≥12/13 tests pass (one flaky is acceptable for
LLM-in-the-loop tests). Each test verifies the tool name and key arguments
only — not exact values.

**Cost:** ~13 calls × ~1300 tokens × $0.10/M = ~$0.002 total.

---

#### T5.2 — Multi-turn context test

**What:** Verify conversational context works end-to-end.

**Tests:**
```
test_e2e_multiturn_edit
  msg1: "had dal chawal at 1pm"  → log_food
  msg2: "actually it was 2pm"   → edit_food (LLM uses context to know what to edit)

test_e2e_multiturn_query_after_log
  msg1: "had samosa #junk"      → log_food
  msg2: "how many calories was that" → query_macros with scope="last"
```

**Success criteria:** 2/2 pass.

---

## 4. Migration strategy

### From v1 to v2

1. **No data migration.** SQLite schema is unchanged (except new `tasks` table).
   The vault is unchanged. v2 reads the same DB and vault as v1.

2. **Parallel run.** Both `bot.py` (v1) and `bot_v2.py` can coexist in the
   codebase. Switch by changing the entry point in `pyproject.toml` / systemd.

3. **Cutover.** Once v2 passes all integration tests and 1 week of manual use:
   - Delete `app/domains/food.py`, `app/domains/workout.py`, `app/domains/ideas.py`
   - Delete `app/llm.py::parse_message` and `_PARSE_SYSTEM_PROMPT_TEMPLATE`
   - Delete `MessageParse` and all `*Payload` models
   - Delete old `app/bot.py`
   - Keep `app/llm.py::estimate_calories` and `synthesize_brief` (called by tools)

4. **Rollback.** If v2 has issues, switch entry point back to `bot.py`. No
   data loss possible — both versions write to the same DB/vault.

---

## 5. File-level change map

```
app/
├── tools/                    # NEW — all tool functions
│   ├── __init__.py
│   ├── registry.py           # tool collection + schema generation
│   ├── errors.py             # ToolError exception
│   ├── food.py               # log_food, edit_food, delete_food, query_macros
│   ├── workout.py            # log_workout_note, sync_workouts, query_workouts
│   ├── ideas.py              # capture_idea, deepdive_idea
│   ├── journal.py            # log_journal
│   ├── tasks.py              # log_task, complete_task, query_tasks
│   └── profile.py            # update_profile, get_profile
├── router.py                 # NEW — LLM tool-calling router
├── session.py                # NEW — per-user message buffer
├── bot_v2.py                 # NEW — slim Telegram bot
├── bot.py                    # KEEP (v1 fallback, delete after cutover)
├── llm.py                    # KEEP estimate_calories + synthesize_brief
│                             # DELETE parse_message after cutover
├── models.py                 # KEEP FoodLog, HevyWorkout, etc.
│                             # DELETE MessageParse + Payloads after cutover
├── db.py                     # UNCHANGED
├── config.py                 # UNCHANGED
├── sinks/obsidian.py         # UNCHANGED
├── integrations/hevy.py      # UNCHANGED
├── integrations/tavily.py    # UNCHANGED
└── migrations/
    ├── 001-004               # UNCHANGED
    └── 005_tasks.sql         # NEW

tests/
├── test_session.py           # Phase 0
├── test_registry.py          # Phase 0
├── test_tool_food.py         # Phase 1
├── test_tool_workout.py      # Phase 1
├── test_tool_ideas.py        # Phase 1
├── test_tool_journal.py      # Phase 1
├── test_tool_tasks.py        # Phase 1
├── test_tool_profile.py      # Phase 1
├── test_router.py            # Phase 2
├── test_bot_v2.py            # Phase 3
├── test_cron_jobs.py         # Phase 4
├── integration/
│   ├── test_e2e_routing.py   # Phase 5 (real LLM)
│   └── test_e2e_multiturn.py # Phase 5 (real LLM)
└── (existing v1 tests — keep until cutover)
```

---

## 6. Tool definitions for the LLM

These are the OpenAI-format tool definitions sent in each request. Total
token footprint: ~400 tokens.

```json
[
  {
    "type": "function",
    "function": {
      "name": "log_food",
      "description": "Log food the user ate. Use when they describe eating something.",
      "parameters": {
        "type": "object",
        "properties": {
          "items": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "name": {"type": "string"},
                "quantity": {"type": "string"}
              },
              "required": ["name"]
            },
            "description": "Food items eaten"
          },
          "junk": {
            "type": "boolean",
            "description": "True if user tagged with #junk"
          },
          "time": {
            "type": "string",
            "description": "When they ate, e.g. '1pm', 'lunch', '13:00'"
          },
          "notes": {
            "type": "string",
            "description": "Any remarks like 'felt heavy'"
          }
        },
        "required": ["items"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "edit_food",
      "description": "Edit a previously logged food entry. Use when user wants to correct something they logged.",
      "parameters": {
        "type": "object",
        "properties": {
          "food_log_id": {"type": "integer", "description": "ID of the entry to edit (from context)"},
          "items": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "quantity": {"type": "string"}}, "required": ["name"]}},
          "junk": {"type": "boolean"},
          "time": {"type": "string"}
        },
        "required": ["food_log_id", "items"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "delete_food",
      "description": "Delete a food log entry. Use when user says 'delete', 'remove', 'undo'.",
      "parameters": {
        "type": "object",
        "properties": {
          "target": {
            "type": "string",
            "enum": ["last", "by_id", "matching"],
            "description": "'last' for most recent, 'by_id' with food_log_id, 'matching' with item_hint"
          },
          "food_log_id": {"type": "integer"},
          "item_hint": {"type": "string", "description": "Food name to search for"}
        },
        "required": ["target"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "query_macros",
      "description": "Get calorie and macro breakdown. Use for 'calories today', 'macros', 'how much protein'.",
      "parameters": {
        "type": "object",
        "properties": {
          "scope": {
            "type": "string",
            "enum": ["today", "yesterday", "last", "by_date", "matching"],
            "description": "Time scope for the query"
          },
          "date": {"type": "string", "description": "ISO date for by_date scope"},
          "item_hint": {"type": "string", "description": "Food name for matching scope"}
        },
        "required": ["scope"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "log_workout_note",
      "description": "Log a workout narrative and trigger Hevy sync. Use when user describes a workout they did.",
      "parameters": {
        "type": "object",
        "properties": {
          "note": {"type": "string", "description": "The workout narrative"}
        },
        "required": ["note"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "sync_workouts",
      "description": "Manually sync workouts from Hevy. Use when user says 'sync' or asks about recent workouts not yet synced.",
      "parameters": {"type": "object", "properties": {}}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "query_workouts",
      "description": "Query workout history. Use for 'workouts this week', 'last workout', 'training today'.",
      "parameters": {
        "type": "object",
        "properties": {
          "scope": {
            "type": "string",
            "enum": ["today", "this_week", "by_date", "last"],
            "description": "Time scope"
          },
          "date": {"type": "string", "description": "ISO date for by_date"}
        },
        "required": ["scope"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "capture_idea",
      "description": "Capture a new idea or project. Use when user says '#idea', 'new idea', 'project idea'.",
      "parameters": {
        "type": "object",
        "properties": {
          "title": {"type": "string", "description": "Concise idea title, <=10 words"},
          "description": {"type": "string", "description": "Extra context or motivation"},
          "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags without # prefix"}
        },
        "required": ["title"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "deepdive_idea",
      "description": "Research an idea via web search. Use for 'deepdive', 'research', '#divedeep'.",
      "parameters": {
        "type": "object",
        "properties": {
          "title_hint": {"type": "string", "description": "Idea name to search for. Omit to list recent ideas."}
        }
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "log_journal",
      "description": "Log a journal entry for today. Use for free-form reflections, mood, daily notes.",
      "parameters": {
        "type": "object",
        "properties": {
          "entry": {"type": "string", "description": "The journal text"}
        },
        "required": ["entry"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "log_task",
      "description": "Create a new task. Use when user says '#task' or describes something to do.",
      "parameters": {
        "type": "object",
        "properties": {
          "description": {"type": "string", "description": "What needs to be done"},
          "due": {"type": "string", "description": "When it's due, e.g. 'tomorrow', 'Friday', '2026-06-05'"}
        },
        "required": ["description"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "complete_task",
      "description": "Mark a task as done. Use when user says '#done' or 'completed X'.",
      "parameters": {
        "type": "object",
        "properties": {
          "hint": {"type": "string", "description": "Fragment of the task description to match"}
        },
        "required": ["hint"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "query_tasks",
      "description": "List tasks. Use for 'my tasks', 'what's due', 'open tasks'.",
      "parameters": {
        "type": "object",
        "properties": {
          "scope": {
            "type": "string",
            "enum": ["today", "open", "all"],
            "description": "'today' for due today + overdue, 'open' for all incomplete, 'all' for everything"
          }
        },
        "required": ["scope"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "update_profile",
      "description": "Update user physical profile. Use for 'weight is 73', '/profile height=170'.",
      "parameters": {
        "type": "object",
        "properties": {
          "weight_kg": {"type": "number"},
          "height_cm": {"type": "number"},
          "age": {"type": "integer"},
          "sex": {"type": "string", "enum": ["M", "F"]}
        }
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_profile",
      "description": "Show user's current profile (weight, height, BMR). Use for '/profile', 'my stats'.",
      "parameters": {"type": "object", "properties": {}}
    }
  }
]
```

---

## 7. Test execution plan

### Prerequisites

```bash
pip install -e ".[dev]"  # pytest, pytest-asyncio, ruff
```

### Test commands

```bash
# Unit tests only (fast, no LLM, no network)
pytest tests/ -m "not integration" -v

# Integration tests (real LLM calls, requires OPENROUTER_API_KEY)
pytest tests/integration/ -m integration -v

# Full suite
pytest tests/ -v

# Coverage
pytest tests/ -m "not integration" --cov=app --cov-report=term-missing
```

### CI markers

```python
# conftest.py
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: real LLM calls (slow, costs money)")
```

### Coverage target

- Unit tests: ≥90% line coverage on `app/tools/`, `app/router.py`, `app/session.py`
- Integration tests: not measured (they test LLM behavior, not code paths)

---

## 8. Success criteria (overall)

| Criterion | Measurement |
|---|---|
| All unit tests pass | `pytest -m "not integration"` exits 0 |
| ≥90% code coverage | `--cov-report` on tools + router + session |
| Integration tests ≥12/13 pass | `pytest -m integration` |
| Token cost per interaction ≤1500 | Measure via OpenRouter dashboard |
| Monthly cost ≤$1 at 50 interactions/day | OpenRouter billing |
| Response latency ≤3s (p95) | Measured in production logs |
| No regressions in existing features | v1 test suite still passes during parallel run |
| Clean cutover | v1 code deletable without breaking v2 |

---

## 9. Implementation order (recommended)

```
Week 1: Phase 0 (T0.1-T0.4) + Phase 1 food tools (T1.1-T1.4)
Week 2: Phase 1 remaining tools (T1.5-T1.12)
Week 3: Phase 2 router (T2.1-T2.3) + Phase 3 bot (T3.1-T3.2)
Week 4: Phase 4 cron (T4.1) + Phase 5 integration tests (T5.1-T5.2)
Week 5: Manual testing on OCI, parallel run with v1
Week 6: Cutover, delete v1 code
```

---

## 10. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| DeepSeek v4 Flash tool-calling quality | Model picks wrong tool or hallucinates args | Integration tests catch this; tool descriptions tuned iteratively; fallback to DeepSeek v3 or GPT-4o-mini |
| Tool schema token bloat | 15 tools × ~30 tokens each = 450 tokens overhead | Acceptable; still <1500 total. Can prune descriptions if needed |
| Session buffer misleads LLM | Stale context causes wrong tool call | 15-min TTL; max 20 messages; user can `/clear` |
| Reply-to context lost on restart | User replies to old message, no context | Same as v1 — graceful degradation, treat as fresh request |
| `apscheduler` reliability | Missed cron jobs | systemd watchdog restarts process; jobs are idempotent |
| DeepSeek structured output format | Tool call JSON malformed | OpenAI SDK handles parsing; retry once on parse failure |
