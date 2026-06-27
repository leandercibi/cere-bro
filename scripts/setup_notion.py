"""Cerebro Notion Dashboard Builder.

Creates the full database structure, gamification system, and dashboard page.
Run once to set up, idempotent on re-run (checks for existing databases).
"""
from __future__ import annotations

import json
import sys
import time

import httpx

NOTION_VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"


def headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    h = headers(token)
    if method == "POST":
        r = httpx.post(url, headers=h, json=body, timeout=30)
    elif method == "PATCH":
        r = httpx.patch(url, headers=h, json=body, timeout=30)
    else:
        r = httpx.get(url, headers=h, timeout=30)
    if r.status_code >= 400:
        print(f"ERROR {r.status_code}: {r.text[:500]}")
        sys.exit(1)
    return r.json()


def create_page(token: str, title: str, icon: str, children: list | None = None) -> str:
    body = {
        "parent": {"type": "page_id", "page_id": ""},
        "properties": {"title": [{"text": {"content": title}}]},
        "icon": {"type": "emoji", "emoji": icon},
    }
    # Top-level page — use workspace parent
    # Notion API requires creating under an existing page the integration has access to.
    # We'll create a page first, then use it as parent.
    # Actually for top-level, we search for pages and use workspace.
    # The integration needs a page shared with it. Let's create inline DB approach.
    pass


def create_database(token: str, parent_page_id: str, title: str, icon: str, properties: dict) -> str:
    body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"text": {"content": title}}],
        "icon": {"type": "emoji", "emoji": icon},
        "properties": properties,
    }
    result = api("POST", "/databases", token, body)
    db_id = result["id"]
    print(f"  Created database: {title} ({db_id})")
    return db_id


def create_page_with_content(token: str, parent_id: str, title: str, icon: str, children: list) -> str:
    body = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {"title": [{"text": {"content": title}}]},
        "icon": {"type": "emoji", "emoji": icon},
        "children": children,
    }
    result = api("POST", "/pages", token, body)
    page_id = result["id"]
    print(f"  Created page: {title} ({page_id})")
    return page_id


def append_blocks(token: str, page_id: str, children: list) -> None:
    api("PATCH", f"/blocks/{page_id}/children", token, {"children": children})


def heading(level: int, text: str, color: str = "default") -> dict:
    key = f"heading_{level}"
    return {
        "object": "block",
        "type": key,
        key: {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "color": color,
        },
    }


def paragraph(text: str, bold: bool = False, color: str = "default") -> dict:
    rt = {"type": "text", "text": {"content": text}}
    if bold:
        rt["annotations"] = {"bold": True}
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [rt],
            "color": color,
        },
    }


def callout(text: str, icon: str, color: str = "blue_background") -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "icon": {"type": "emoji", "emoji": icon},
            "color": color,
        },
    }


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def linked_db(database_id: str) -> dict:
    return {
        "object": "block",
        "type": "link_to_page",
        "link_to_page": {"type": "database_id", "database_id": database_id},
    }


def build_all(token: str):
    print("=" * 60)
    print("CEREBRO NOTION DASHBOARD BUILDER")
    print("=" * 60)

    # --- Step 1: Create root page ---
    print("\n[1/8] Creating root Cerebro page...")

    # Find a regular page (not a database row) to nest under
    search = api("POST", "/search", token, {
        "query": "",
        "filter": {"value": "page", "property": "object"},
        "page_size": 20,
    })
    parent_id = None
    for p in search.get("results", []):
        if p.get("parent", {}).get("type") == "workspace":
            parent_id = p["id"]
            break
    if not parent_id:
        print("  ERROR: No workspace-level page found. Share a page with the integration first.")
        sys.exit(1)

    root_body = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {"title": [{"text": {"content": "Cerebro Command Center"}}]},
        "icon": {"type": "emoji", "emoji": "🧠"},
        "cover": {"type": "external", "external": {"url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1500"}},
        "children": [
            callout(
                "Your personal data OS. Everything logged, scored, and gamified.",
                "🧠",
                "blue_background",
            ),
            divider(),
        ],
    }

    root = api("POST", "/pages", token, root_body)
    root_id = root["id"]
    print(f"  Root page: {root_id}")

    # --- Step 2: Create Food Logs database ---
    print("\n[2/8] Creating Food Logs database...")
    food_db_id = create_database(token, root_id, "Food Logs", "🍛", {
        "Meal": {"title": {}},
        "Date": {"date": {}},
        "Calories": {"number": {"format": "number"}},
        "Protein (g)": {"number": {"format": "number"}},
        "Fat (g)": {"number": {"format": "number"}},
        "Carbs (g)": {"number": {"format": "number"}},
        "Junk": {"checkbox": {}},
        "Time": {"rich_text": {}},
        "XP Earned": {
            "formula": {
                "expression": 'if(prop("Junk"), 5, 10)',
            },
        },
        "Source": {"select": {
            "options": [
                {"name": "Telegram", "color": "blue"},
                {"name": "Manual", "color": "gray"},
            ]
        }},
    })

    # --- Step 3: Create Workouts database ---
    print("\n[3/8] Creating Workouts database...")
    workout_db_id = create_database(token, root_id, "Workouts", "🏋️", {
        "Title": {"title": {}},
        "Date": {"date": {}},
        "Duration (min)": {"number": {"format": "number"}},
        "Volume (kg)": {"number": {"format": "number"}},
        "Calories Burned": {"number": {"format": "number"}},
        "Type": {"select": {
            "options": [
                {"name": "Strength", "color": "blue"},
                {"name": "Cardio", "color": "green"},
                {"name": "HIIT", "color": "red"},
                {"name": "Yoga", "color": "purple"},
                {"name": "Manual", "color": "gray"},
            ]
        }},
        "Exercises": {"number": {"format": "number"}},
        "Notes": {"rich_text": {}},
        "Source": {"select": {
            "options": [
                {"name": "Hevy", "color": "orange"},
                {"name": "Manual", "color": "gray"},
            ]
        }},
        "XP Earned": {
            "formula": {
                "expression": 'if(prop("Duration (min)") > 60, 75, if(prop("Duration (min)") > 30, 50, 25))',
            },
        },
    })

    # --- Step 4: Create Ideas database ---
    print("\n[4/8] Creating Ideas database...")
    ideas_db_id = create_database(token, root_id, "Ideas", "💡", {
        "Idea": {"title": {}},
        "Status": {"select": {
            "options": [
                {"name": "💭 Ideation", "color": "gray"},
                {"name": "🌱 Early Stage", "color": "green"},
                {"name": "🔬 Research", "color": "blue"},
                {"name": "📋 Breakdown", "color": "yellow"},
                {"name": "⚖️ Feasibility", "color": "orange"},
                {"name": "✅ Go", "color": "green"},
                {"name": "📦 Shelved", "color": "gray"},
                {"name": "❌ Killed", "color": "red"},
            ]
        }},
        "Description": {"rich_text": {}},
        "Tags": {"multi_select": {
            "options": [
                {"name": "ml", "color": "blue"},
                {"name": "health", "color": "green"},
                {"name": "productivity", "color": "yellow"},
                {"name": "finance", "color": "orange"},
                {"name": "side-project", "color": "purple"},
            ]
        }},
        "Has Research": {"checkbox": {}},
        "Created": {"date": {}},
        "Updated": {"date": {}},
        "XP Earned": {
            "formula": {
                "expression": 'if(prop("Has Research"), 30, 15)',
            },
        },
    })

    # --- Step 5: Create Tasks database ---
    print("\n[5/8] Creating Tasks database...")
    tasks_db_id = create_database(token, root_id, "Tasks", "✅", {
        "Task": {"title": {}},
        "Due": {"date": {}},
        "Done": {"checkbox": {}},
        "Completed At": {"date": {}},
        "Priority": {"select": {
            "options": [
                {"name": "🔴 High", "color": "red"},
                {"name": "🟡 Medium", "color": "yellow"},
                {"name": "🟢 Low", "color": "green"},
            ]
        }},
        "XP Earned": {
            "formula": {
                "expression": 'if(prop("Done"), if(contains(prop("Priority"), "High"), 25, if(contains(prop("Priority"), "Medium"), 15, 10)), 0)',
            },
        },
    })

    # --- Step 6: Create Habits database ---
    print("\n[6/8] Creating Habits Tracker database...")
    # Create base habits DB without formulas first
    habits_db_id = create_database(token, root_id, "Daily Habits", "🔥", {
        "Date": {"title": {}},
        "Early Sleep": {"checkbox": {}},
        "No Junk Food": {"checkbox": {}},
        "Reading 30m": {"checkbox": {}},
        "Workout Done": {"checkbox": {}},
        "Water 2.5L": {"checkbox": {}},
        "Meditation": {"checkbox": {}},
        "Mood": {"select": {
            "options": [
                {"name": "🔥 Great", "color": "green"},
                {"name": "😊 Good", "color": "blue"},
                {"name": "😐 Neutral", "color": "gray"},
                {"name": "😔 Low", "color": "orange"},
                {"name": "😫 Bad", "color": "red"},
            ]
        }},
        "Journal": {"rich_text": {}},
    })
    # Add formula properties via PATCH (they reference checkbox props that must exist first)
    api("PATCH", f"/databases/{habits_db_id}", token, {
        "properties": {
            "Habits Score": {
                "formula": {
                    "expression": (
                        'round((if(prop("Early Sleep"), 1, 0) + '
                        'if(prop("No Junk Food"), 1, 0) + '
                        'if(prop("Reading 30m"), 1, 0) + '
                        'if(prop("Workout Done"), 1, 0) + '
                        'if(prop("Water 2.5L"), 1, 0) + '
                        'if(prop("Meditation"), 1, 0)) / 6 * 100)'
                    ),
                },
            },
            "XP Earned": {
                "formula": {
                    "expression": (
                        'if(prop("Early Sleep"), 10, 0) + '
                        'if(prop("No Junk Food"), 10, 0) + '
                        'if(prop("Reading 30m"), 10, 0) + '
                        'if(prop("Workout Done"), 10, 0) + '
                        'if(prop("Water 2.5L"), 10, 0) + '
                        'if(prop("Meditation"), 10, 0)'
                    ),
                },
            },
            "Perfect Day": {
                "formula": {
                    "expression": (
                        'and(and(prop("Early Sleep"), prop("No Junk Food")), '
                        'and(and(prop("Reading 30m"), prop("Workout Done")), '
                        'and(prop("Water 2.5L"), prop("Meditation"))))'
                    ),
                },
            },
        },
    })
    print("  Added formula properties to Daily Habits")

    # --- Step 7: Create Scoreboard database ---
    print("\n[7/8] Creating Scoreboard database...")
    score_db_id = create_database(token, root_id, "Scoreboard", "🏆", {
        "Week": {"title": {}},
        "Start Date": {"date": {}},
        "Total XP": {"number": {"format": "number"}},
        "Food Logs": {"number": {"format": "number"}},
        "Workouts": {"number": {"format": "number"}},
        "Ideas Captured": {"number": {"format": "number"}},
        "Tasks Completed": {"number": {"format": "number"}},
        "Avg Habit Score": {"number": {"format": "number"}},
        "Perfect Days": {"number": {"format": "number"}},
        "Level": {
            "formula": {
                "expression": (
                    'if(prop("Total XP") >= 5000, "🏆 Legend", '
                    'if(prop("Total XP") >= 3000, "💎 Diamond", '
                    'if(prop("Total XP") >= 2000, "🥇 Gold", '
                    'if(prop("Total XP") >= 1000, "🥈 Silver", '
                    'if(prop("Total XP") >= 500, "🥉 Bronze", '
                    '"🌱 Rookie")))))'
                ),
            },
        },
        "Weekly Grade": {
            "formula": {
                "expression": (
                    'if(prop("Avg Habit Score") >= 90, "A+", '
                    'if(prop("Avg Habit Score") >= 80, "A", '
                    'if(prop("Avg Habit Score") >= 70, "B", '
                    'if(prop("Avg Habit Score") >= 60, "C", '
                    'if(prop("Avg Habit Score") >= 50, "D", "F")))))'
                ),
            },
        },
        "Streak": {"number": {"format": "number"}},
    })

    # --- Step 8: Build dashboard page with linked views ---
    print("\n[8/8] Building dashboard page...")

    dashboard_blocks = [
        heading(1, "Dashboard"),
        paragraph(""),

        # XP System explanation
        callout(
            "🎮 XP SYSTEM\n"
            "• Log food: 10 XP (5 if junk)\n"
            "• Workout: 25-75 XP (by duration)\n"
            "• Capture idea: 15 XP (30 with research)\n"
            "• Complete task: 10-25 XP (by priority)\n"
            "• Each habit: 10 XP (60 XP for perfect day)\n\n"
            "🌱 Rookie (0) → 🥉 Bronze (500) → 🥈 Silver (1000) → 🥇 Gold (2000) → 💎 Diamond (3000) → 🏆 Legend (5000)",
            "🎮",
            "yellow_background",
        ),
        divider(),

        # Scoreboard
        heading(2, "🏆 Weekly Scoreboard"),
        paragraph("Your weekly XP, level, and grade. Fill in each Sunday."),
        linked_db(score_db_id),
        paragraph(""),

        # Habits
        heading(2, "🔥 Daily Habits"),
        paragraph("Check off habits daily. Score auto-calculates. Aim for 100%."),
        linked_db(habits_db_id),
        paragraph(""),

        # Food
        heading(2, "🍛 Food Log"),
        paragraph("Every meal logged from Telegram lands here."),
        linked_db(food_db_id),
        paragraph(""),

        # Workouts
        heading(2, "🏋️ Workouts"),
        paragraph("Auto-synced from Hevy + manual entries."),
        linked_db(workout_db_id),
        paragraph(""),

        # Tasks
        heading(2, "✅ Tasks"),
        paragraph("Your task queue. Complete for XP."),
        linked_db(tasks_db_id),
        paragraph(""),

        # Ideas
        heading(2, "💡 Ideas"),
        paragraph("Idea pipeline from ideation to decision."),
        linked_db(ideas_db_id),
    ]

    # Notion API limits children to 100 blocks per request
    dashboard_id = create_page_with_content(
        token, root_id, "Dashboard", "📊", dashboard_blocks[:100]
    )
    if len(dashboard_blocks) > 100:
        append_blocks(token, dashboard_id, dashboard_blocks[100:])

    # --- Step 9: Create XP Reference page ---
    print("\n[BONUS] Creating XP reference page...")
    xp_blocks = [
        heading(1, "Gamification Guide"),
        divider(),
        heading(2, "XP Rewards"),
        callout(
            "FOOD LOGGING\n"
            "• Log a meal: +10 XP\n"
            "• Log junk food (honest!): +5 XP\n"
            "• Log all 3 meals in a day: +10 bonus XP",
            "🍛", "green_background",
        ),
        callout(
            "WORKOUTS\n"
            "• < 30 min session: +25 XP\n"
            "• 30-60 min session: +50 XP\n"
            "• 60+ min session: +75 XP",
            "🏋️", "blue_background",
        ),
        callout(
            "IDEAS & RESEARCH\n"
            "• Capture an idea: +15 XP\n"
            "• Deepdive research: +30 XP\n"
            "• Advance idea stage: +20 XP",
            "💡", "yellow_background",
        ),
        callout(
            "TASKS\n"
            "• Complete low priority: +10 XP\n"
            "• Complete medium priority: +15 XP\n"
            "• Complete high priority: +25 XP",
            "✅", "orange_background",
        ),
        callout(
            "DAILY HABITS (10 XP each)\n"
            "• Sleep before 11:30 PM\n"
            "• No junk food\n"
            "• 30 min reading\n"
            "• Workout done\n"
            "• Water 2.5L+\n"
            "• Meditation\n"
            "Perfect day (all 6): 60 XP",
            "🔥", "red_background",
        ),
        divider(),
        heading(2, "Level Thresholds"),
        callout(
            "🌱 Rookie: 0 XP\n"
            "🥉 Bronze: 500 XP (~1 week of solid logging)\n"
            "🥈 Silver: 1,000 XP (~2 weeks)\n"
            "🥇 Gold: 2,000 XP (~1 month)\n"
            "💎 Diamond: 3,000 XP (~6 weeks)\n"
            "🏆 Legend: 5,000 XP (~3 months of consistency)",
            "🏆", "purple_background",
        ),
        divider(),
        heading(2, "Weekly Grade"),
        paragraph("Based on average daily habit score:"),
        callout(
            "A+ = 90-100%  |  A = 80-89%  |  B = 70-79%\n"
            "C = 60-69%  |  D = 50-59%  |  F = below 50%",
            "📊", "gray_background",
        ),
    ]
    create_page_with_content(token, root_id, "Gamification Guide", "🎮", xp_blocks)

    # --- Done ---
    print("\n" + "=" * 60)
    print("DONE! All databases and pages created.")
    print("=" * 60)
    print(f"\nRoot page ID: {root_id}")
    print(f"\nDatabase IDs:")
    print(f"  Food Logs:    {food_db_id}")
    print(f"  Workouts:     {workout_db_id}")
    print(f"  Ideas:        {ideas_db_id}")
    print(f"  Tasks:        {tasks_db_id}")
    print(f"  Daily Habits: {habits_db_id}")
    print(f"  Scoreboard:   {score_db_id}")
    print(f"\nNext steps:")
    print(f"  1. Open Notion — find 'Cerebro Command Center' page")
    print(f"  2. On Dashboard, switch database views:")
    print(f"     - Scoreboard → Gallery view")
    print(f"     - Daily Habits → Calendar view")
    print(f"     - Food Logs → Table (sorted by Date desc)")
    print(f"     - Tasks → Board view (group by Done)")
    print(f"     - Ideas → Board view (group by Status)")
    print(f"  3. Save these DB IDs in your .env for the Cerebro bot sync")

    return {
        "root_page_id": root_id,
        "food_db_id": food_db_id,
        "workout_db_id": workout_db_id,
        "ideas_db_id": ideas_db_id,
        "tasks_db_id": tasks_db_id,
        "habits_db_id": habits_db_id,
        "score_db_id": score_db_id,
    }


if __name__ == "__main__":
    token = sys.argv[1] if len(sys.argv) > 1 else ""
    if not token:
        print("Usage: python setup_notion.py <notion_api_key>")
        sys.exit(1)
    build_all(token)
