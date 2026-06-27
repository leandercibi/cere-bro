from __future__ import annotations

from datetime import datetime

from dateutil import parser as dtparser

import app.db as db
from app.tools.errors import ToolError
from app.tools.registry import ToolDef
from lib.config import Settings
from lib.sinks import notion


async def log_task(
    description: str,
    due: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    now = datetime.now(settings.tz)
    due_at: str | None = None
    if due:
        try:
            parsed = dtparser.parse(due, default=now)
            due_at = parsed.isoformat()
        except Exception:
            due_at = None

    conn = db.get_conn(settings.db_path)
    try:
        cur = conn.execute(
            "INSERT INTO tasks (user_id, description, due_at) VALUES (?, ?, ?)",
            (user_id, description, due_at),
        )
        conn.commit()
        task_id = cur.lastrowid
    finally:
        conn.close()
    await notion.push_task(settings, task_id=task_id, description=description, due_at=due_at)
    return {"task_id": task_id, "description": description, "due_at": due_at}


async def complete_task(
    hint: str,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    now = datetime.now(settings.tz).isoformat()
    conn = db.get_conn(settings.db_path)
    try:
        rows = conn.execute(
            "SELECT id, description, due_at FROM tasks WHERE user_id = ? AND completed = 0",
            (user_id,),
        ).fetchall()
        matches = [r for r in rows if hint.lower() in r["description"].lower()]
        if not matches:
            raise ToolError(f"No open task matching '{hint}'.")
        task = matches[0]
        conn.execute(
            "UPDATE tasks SET completed = 1, completed_at = ? WHERE id = ?",
            (now, task["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    completed_dt = datetime.now(settings.tz)
    # Ensure the task exists in Notion (no-op if already there) before marking done.
    # This covers tasks created before Notion integration was added.
    await notion.push_task(settings, task_id=task["id"], description=task["description"], due_at=task["due_at"])
    await notion.update_task_done(settings, task_id=task["id"], completed_at=completed_dt)
    return {"completed_task_id": task["id"], "description": task["description"]}


async def query_tasks(
    scope: str,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    now = datetime.now(settings.tz)
    today = now.date().isoformat()
    conn = db.get_conn(settings.db_path)
    try:
        if scope == "today":
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id = ? AND completed = 0 AND (due_at IS NULL OR substr(due_at,1,10) <= ?)",
                (user_id, today),
            ).fetchall()
        elif scope == "open":
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id = ? AND completed = 0",
                (user_id,),
            ).fetchall()
        elif scope == "all":
            rows = conn.execute(
                "SELECT * FROM tasks WHERE user_id = ?", (user_id,)
            ).fetchall()
        else:
            raise ToolError(f"Unknown scope '{scope}'.")
        tasks = [
            {
                "id": r["id"],
                "description": r["description"],
                "due_at": r["due_at"],
                "completed": bool(r["completed"]),
            }
            for r in rows
        ]
    finally:
        conn.close()
    return {"scope": scope, "tasks": tasks}


TOOLS: list[ToolDef] = [
    ToolDef(
        name="log_task",
        description="Create a new task or reminder. ALWAYS use this when message contains '#task' or 'task:'. Do not respond with plain text.",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "due": {"type": "string", "description": "Due date, e.g. 'tomorrow', 'Friday'"},
            },
            "required": ["description"],
        },
        handler=log_task,
    ),
    ToolDef(
        name="complete_task",
        description="Mark a task as done.",
        parameters={
            "type": "object",
            "properties": {"hint": {"type": "string"}},
            "required": ["hint"],
        },
        handler=complete_task,
    ),
    ToolDef(
        name="query_tasks",
        description="List tasks.",
        parameters={
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["today", "open", "all"]},
            },
            "required": ["scope"],
        },
        handler=query_tasks,
    ),
]
