from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime

import app.db as db
from app.llm import get_client, _call_with_retry
from app.session import SessionBuffer
from app.tools.errors import ToolError
from app.tools.registry import get_all_tools, get_openai_tools
from lib.config import Settings

logger = logging.getLogger("cerebro.router")

_session_buffer = SessionBuffer()

_SYSTEM_PROMPT = """\
You are Cerebro, a personal assistant. You help the user log food, workouts, \
ideas, tasks, and journal entries. You also answer questions about their logged data.

## CRITICAL RULE — NEVER mimic tool output
The response strings starting with ✅, 💡, 📓, 💪, 📊, ✔️ are ONLY produced by the \
tool execution framework — never by you. If you generate such text without calling a tool \
you are hallucinating a logged entry that was never actually saved. This is a serious error. \
ALWAYS call the appropriate tool. NEVER write "✅ Logged:", "💡 Idea captured:", \
"📓 Journal entry logged", "✅ Task:", "✔️ Done:" or similar strings yourself.

You MUST use tools to fulfill requests. Only respond with plain text for greetings \
or questions you cannot answer with any tool. When in doubt, use a tool.
You may call multiple tools in a single response when the message warrants it.

## Tool trigger rules

**Tasks** — call log_task whenever the message implies creating a to-do, reminder, or action item:
- Explicit: "#task", "task:", "todo", "reminder:", "action item"
- Casual English: "remind me to", "don't forget to", "I need to", "I should", \
"make sure to", "I have to", "I must", "don't let me forget", "add to my list", \
"can you add", "I want to remember to", "note to", "schedule", "book", "buy", "submit"
- Examples:
  - "remind me to buy groceries" → log_task(description="buy groceries")
  - "don't forget to call mom" → log_task(description="call mom")
  - "I need to renew my gym membership" → log_task(description="renew gym membership")
  - "can you add buy whey protein to my list" → log_task(description="buy whey protein")

**Food** — call log_food for any eating or drinking description:
- "ate", "had", "eating", "drinking", "consumed", "finished", "grabbed", \
"just had", "for lunch", "for dinner", "for breakfast", "as a snack", "meal"
- Examples:
  - "just had a bowl of pasta" → log_food(...)
  - "lunch was rice and dal" → log_food(...)

**Journal** — call log_journal for feelings, reflections, or daily notes:
- "feeling", "today was", "I feel", "mood", "journal:", "note to self", "daily note", \
"today I", "had a good/bad day", "been thinking", "rough day", "solid day", "low energy"
- Example: "feeling tired today" → log_journal(entry="feeling tired today")

**Ideas** — call capture_idea for any novel thought or concept:
- "#idea", "idea:", "what if", "I was thinking", "thought about building", "concept:", \
"had this idea", "podcast idea", "startup idea", "been thinking about starting"
- Example: "what if I built a habit tracker" → capture_idea(...)

**Macros / calories** — call query_macros:
- "how many calories", "what did I eat", "my macros", "calorie count", "nutrition today", \
"calories so far", "total protein"

**Food deletion** — call delete_food:
- "delete", "remove", "undo", "scratch that", "cancel that food", "wrong entry"

**Workouts** — call log_workout_note for workout descriptions; sync_workouts to pull from Hevy.

Current datetime: {now_iso}
User timezone: {timezone}

User profile:
{profile_yaml}\
"""


@dataclass
class RouterResult:
    reply_text: str
    tool_called: str | None  # first tool called (backward compat)
    tools_called: list[str] = field(default_factory=list)


def _get_tool_handler(name: str):
    for tool in get_all_tools():
        if tool.name == name:
            return tool.handler
    return None


def _build_system_prompt(settings: Settings) -> str:
    now_iso = datetime.now(settings.tz).isoformat()
    conn = db.get_conn(settings.db_path)
    try:
        profile = db.get_profile(conn)
    finally:
        conn.close()
    if profile:
        profile_yaml = (
            f"weight_kg: {profile.weight_kg}\n"
            f"height_cm: {profile.height_cm}\n"
            f"age: {profile.age}\n"
            f"sex: {profile.sex}"
        )
    else:
        profile_yaml = "not set"
    return _SYSTEM_PROMPT.format(
        now_iso=now_iso,
        timezone=settings.timezone,
        profile_yaml=profile_yaml,
    )


async def route(
    message_text: str,
    user_id: int,
    settings: Settings,
) -> RouterResult:
    history = _session_buffer.get(user_id)
    system_prompt = _build_system_prompt(settings)
    messages = (
        [{"role": "system", "content": system_prompt}]
        + history
        + [{"role": "user", "content": message_text}]
    )

    client = get_client(settings)
    logger.info("Calling LLM (%s) with %d messages", settings.llm_model, len(messages))
    resp = await _call_with_retry(
        client,
        model=settings.llm_model,
        messages=messages,
        tools=get_openai_tools(),
        tool_choice="auto",
    )

    msg = resp.choices[0].message
    logger.info("LLM response: tool_calls=%s", [tc.function.name for tc in msg.tool_calls] if msg.tool_calls else "none")

    tools_called: list[str] = []
    reply_text: str

    if msg.tool_calls:
        result_parts: list[str] = []
        tool_results: list[dict] = []
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            tools_called.append(tool_name)
            handler = _get_tool_handler(tool_name)
            if handler is None:
                logger.warning("LLM requested unknown tool %r — skipping", tool_name)
                formatted = f"(Unknown tool '{tool_name}' — nothing was saved.)"
                result = {}
                result_parts.append(formatted)
                tool_results.append({"tool_call_id": tc.id, "content": "{}"})
                continue
            try:
                args = json.loads(tc.function.arguments)
                logger.info("Tool call: %s(%s)", tool_name, args)
                result = await handler(**args, user_id=user_id, settings=settings)
                formatted = _format_result(tool_name, result)
            except ToolError as e:
                formatted = e.user_message
                result = {}
            except Exception:
                logger.exception("Tool %s failed", tool_name)
                formatted = "Something went wrong. Please try again."
                result = {}
            result_parts.append(formatted)
            tool_results.append({"tool_call_id": tc.id, "content": json.dumps(result)})
        reply_text = "\n".join(result_parts)

        # Store in proper OpenAI tool-call format so the model knows these
        # responses come from tool execution, not its own generation.
        _session_buffer.add_message(user_id, {"role": "user", "content": message_text})
        _session_buffer.add_message(user_id, {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })
        for tc, tr in zip(msg.tool_calls, tool_results):
            _session_buffer.add_message(user_id, {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tr["content"],
            })
    else:
        reply_text = msg.content or ""
        _session_buffer.add(user_id, "user", message_text)
        _session_buffer.add(user_id, "assistant", reply_text)

    return RouterResult(
        reply_text=reply_text,
        tool_called=tools_called[0] if tools_called else None,
        tools_called=tools_called,
    )


def _format_result(tool_name: str, result: dict) -> str:
    """Turn a tool result dict into a human-readable Telegram reply."""
    if tool_name == "log_food":
        kcal = result.get("estimated_kcal")
        kcal_str = f" (~{kcal} kcal)" if kcal else ""
        return f"✅ Logged: {result['summary']}{kcal_str}"
    if tool_name == "edit_food":
        return f"✏️ Updated: {result['summary']}"
    if tool_name == "delete_food":
        return f"🗑️ Deleted: {result['summary']}"
    if tool_name == "query_macros":
        kcal = result.get("total_kcal", 0)
        p = result.get("total_protein_g", 0)
        f = result.get("total_fat_g", 0)
        c = result.get("total_carbs_g", 0)
        return f"📊 {kcal} kcal | P:{p:.0f}g F:{f:.0f}g C:{c:.0f}g"
    if tool_name == "log_workout_note":
        synced = result.get("synced_workouts", 0)
        return f"💪 Workout logged. {synced} new workout(s) synced from Hevy."
    if tool_name == "sync_workouts":
        return result.get("message", "Sync complete.")
    if tool_name == "query_workouts":
        workouts = result.get("workouts", [])
        if not workouts:
            return "No workouts found."
        lines = [f"- {w['title']} ({w['started_at'][:10]})" for w in workouts]
        return "🏋️ Workouts:\n" + "\n".join(lines)
    if tool_name == "capture_idea":
        return f"💡 Idea captured: *{result['title']}* (`{result['slug']}`)"
    if tool_name == "deepdive_idea":
        action = result.get("action")
        if action == "list":
            return "Recent ideas:\n" + "\n".join(f"- {s}" for s in result.get("ideas", []))
        if action == "disambiguation":
            return "Multiple matches:\n" + "\n".join(f"- {s}" for s in result.get("matches", []))
        if action == "existing_brief":
            return f"📖 Existing research found for `{result['slug']}`."
        return f"🔬 Research complete for `{result['slug']}` ({result.get('sources', 0)} sources)."
    if tool_name == "log_journal":
        return f"📓 Journal entry logged for {result['date']}."
    if tool_name == "log_task":
        due = f" (due: {result['due_at'][:10]})" if result.get("due_at") else ""
        return f"✅ Task: {result['description']}{due}"
    if tool_name == "complete_task":
        return f"✔️ Done: {result['description']}"
    if tool_name == "query_tasks":
        tasks = result.get("tasks", [])
        if not tasks:
            return "No tasks found."
        lines = [f"- {'✓' if t['completed'] else '○'} {t['description']}" for t in tasks]
        return "\n".join(lines)
    if tool_name == "update_profile":
        return f"👤 Profile updated: {result['weight_kg']}kg, {result['height_cm']}cm, age {result['age']}"
    if tool_name == "get_profile":
        return (
            f"👤 Weight: {result['weight_kg']}kg | "
            f"Height: {result['height_cm']}cm | "
            f"Age: {result['age']} | Sex: {result['sex']}"
        )
    return json.dumps(result)
