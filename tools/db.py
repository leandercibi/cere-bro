"""Database query tools for Hermes agent."""
from datetime import date, datetime, timedelta

from hermes.tools import tool
from tools._shared import get_conn, get_settings

from lib.db import (
    get_food_logs_for_day,
    get_daily_totals,
    get_workouts_after,
    get_profile,
)


@tool(
    name="db_query_food",
    description="Query food logs for a date range. Returns structured summary with items and macros.",
)
async def db_query_food(
    start_date: str,  # ISO date YYYY-MM-DD
    end_date: str | None = None,  # ISO date YYYY-MM-DD; None = same as start_date
) -> str:
    """Query food logs between start_date and end_date (inclusive)."""
    conn = get_conn()
    settings = get_settings()
    user_id = settings.telegram_allowed_user_id
    
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else start
    
    if end < start:
        return "⚠️ end_date must be >= start_date"
    
    lines = [f"🍽️ **Food logs: {start_date} to {end.isoformat()}**\n"]
    
    current = start
    while current <= end:
        logs = get_food_logs_for_day(conn, user_id, current)
        if logs:
            lines.append(f"**{current.isoformat()}**")
            for log in logs:
                time_str = log.logged_at.strftime("%H:%M")
                items_str = ", ".join(
                    f"{item.name} ({item.quantity})" if item.quantity else item.name
                    for item in log.items
                )
                junk = " #junk" if log.junk else ""
                kcal = f" · {log.est_calories_kcal} kcal" if log.est_calories_kcal else ""
                macros = ""
                if log.est_protein_g and log.est_fat_g and log.est_carbs_g:
                    macros = f" · {int(log.est_protein_g)}p {int(log.est_fat_g)}f {int(log.est_carbs_g)}c"
                lines.append(f"  {time_str} — {items_str}{junk}{kcal}{macros}")
            
            # Add daily totals (if table exists)
            try:
                totals = get_daily_totals(conn, current)
                if totals:
                    lines.append(
                        f"  **Total:** {totals.total_kcal} kcal · "
                        f"{int(totals.total_protein_g)}p {int(totals.total_fat_g)}f {int(totals.total_carbs_g)}c\n"
                    )
            except Exception:
                pass  # daily_totals table may not exist yet
        else:
            lines.append(f"**{current.isoformat()}** — no logs\n")
        
        current += timedelta(days=1)
    
    conn.close()
    return "\n".join(lines)


@tool(
    name="db_query_workouts",
    description="Query workout history for the last N days. Returns structured summary with exercises and calories.",
)
async def db_query_workouts(days: int = 14) -> str:
    """Query workouts from the last N days."""
    conn = get_conn()
    
    since = datetime.now() - timedelta(days=days)
    workouts = get_workouts_after(conn, since)
    
    if not workouts:
        conn.close()
        return f"🏋️ No workouts in the last {days} days"
    
    lines = [f"🏋️ **Workouts (last {days} days):**\n"]
    
    for w in workouts:
        day = w.started_at.date().isoformat()
        time_str = w.started_at.strftime("%H:%M")
        duration_min = w.duration_s // 60
        volume_kg = int(w.total_volume_kg)
        kcal = f" · {w.est_calories_kcal} kcal" if w.est_calories_kcal else ""
        
        lines.append(
            f"**{day}** {time_str} — {w.title} · "
            f"{duration_min}min · {volume_kg}kg{kcal}"
        )
    
    conn.close()
    return "\n".join(lines)


@tool(
    name="db_daily_totals",
    description="Get calorie and macro totals for a specific date. Returns summary of total intake.",
)
async def db_daily_totals(date_str: str) -> str:  # ISO date YYYY-MM-DD
    """Get daily totals for a specific date."""
    conn = get_conn()
    
    try:
        day = date.fromisoformat(date_str)
        totals = get_daily_totals(conn, day)
        
        conn.close()
        
        if not totals:
            return f"📊 No food logs for {date_str}"
        
        return (
            f"📊 **Daily totals for {date_str}:**\n"
            f"- **Calories:** {totals.total_kcal} kcal\n"
            f"- **Protein:** {int(totals.total_protein_g)}g\n"
            f"- **Fat:** {int(totals.total_fat_g)}g\n"
            f"- **Carbs:** {int(totals.total_carbs_g)}g\n"
            f"_Updated: {totals.updated_at.strftime('%H:%M')}_"
        )
    except Exception as e:
        conn.close()
        return f"⚠️ Unable to query daily totals: {str(e)}\n(The daily_totals table may not exist yet - run migration 004)"
