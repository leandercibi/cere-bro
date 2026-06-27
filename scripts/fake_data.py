"""Fake data population script for Cerebro.

Usage:
  python scripts/fake_data.py            # send fake messages, record created IDs
  python scripts/fake_data.py --cleanup  # delete everything that was created
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

SERVER = "http://localhost:8008"
CLEANUP_FILE = Path(__file__).parent / "fake_data_ids.json"

DB_PATH = os.environ.get("DB_PATH", "data/cerebro.sqlite")
VAULT = Path(os.environ.get("VAULT_ROOT", "vault"))
NOTION_KEY = os.environ.get("NOTION_API_KEY", "")

# ---------------------------------------------------------------------------
# Message bank — varied, casual, how a real user texts throughout the day
# ---------------------------------------------------------------------------

MESSAGES = [
    # --- Food: breakfast (different levels of structure) ---
    ("food", "had oats with almond milk and banana this morning, feeling healthy lol"),
    ("food", "breakfast - 2 scrambled eggs + brown toast + black coffee"),
    ("food", "poha for breakfast, pretty light"),
    ("food", "skipped breakfast again, just had black coffee"),
    ("food", "idli sambar for breakfast! mom made it, 3 idlis"),

    # --- Food: lunch ---
    ("food", "dal chawal for lunch, simple but filling"),
    ("food", "had a chicken rice bowl from the canteen, around 450 cals i think"),
    ("food", "subway veggie wrap for lunch, was pretty okay"),
    ("food", "rajma rice for lunch, solid"),
    ("food", "had a salad and grilled chicken, trying to eat clean this week"),

    # --- Food: dinner ---
    ("food", "dinner was rotis with sabzi and dal"),
    ("food", "grilled salmon with roasted broccoli and rice for dinner"),
    ("food", "paneer tikka masala with 2 chapatis for dinner"),
    ("food", "pasta tonight, made it at home with tomato sauce and chicken"),
    ("food", "just had khichdi for dinner, lazy cooking day"),

    # --- Food: snacks & misc ---
    ("food", "post workout - whey protein shake with almond milk"),
    ("food", "handful of almonds and some dates around 4pm"),
    ("food", "green tea and a banana as a snack"),
    ("food", "had masala chai and some mathri at a colleague's desk"),

    # --- Food: junk confessions ---
    ("food", "okay i caved. chips and diet coke while watching series, junk obviously"),
    ("food", "samosa at 4pm from the office canteen, not great"),
    ("food", "ordered pizza tonight. pepperoni. entire thing. no regrets"),
    ("food", "had a double scoop ice cream after dinner, it was a rough day okay"),
    ("food", "burger and fries for lunch, definitely junk but it was worth it"),

    # --- Tasks: varied urgency and phrasings ---
    ("task", "remind me to call the bank tomorrow about my savings account"),
    ("task", "need to submit expense report by friday eod"),
    ("task", "I should finish reading Atomic Habits this week"),
    ("task", "don't forget - dentist appointment needs to be scheduled"),
    ("task", "buy groceries this weekend - eggs, milk, spinach, veggies"),
    ("task", "gotta renew my gym membership before it expires"),
    ("task", "I have to review the job offer letter tonight"),
    ("task", "make sure to back up laptop before the OS update"),
    ("task", "submit leave application for next friday"),
    ("task", "need to call the ISP about slow speeds"),

    # --- Ideas: startup / tech / lifestyle ---
    ("idea", "had this idea - app that tracks sleep quality using phone microphone without any wearable"),
    ("idea", "habit tracker with spotify wrapped style monthly stats, that would be so satisfying"),
    ("idea", "thinking about starting a food journal blog for people who track macros seriously"),
    ("idea", "chrome extension that auto-blocks social media after 10pm, would literally save me"),
    ("idea", "AI personal trainer that watches your form via front camera and gives real time corrections"),
    ("idea", "what if there was a service that meal preps and delivers based on your macro targets"),
    ("idea", "podcast idea - interviewing people who changed careers after 30"),

    # --- Journal: good days, bad days, neutral ---
    ("journal", "today was actually really good. hit the gym early and stayed focused all day"),
    ("journal", "feeling pretty drained. too many meetings, barely ate properly"),
    ("journal", "had a great catch up with an old college friend over coffee, needed that"),
    ("journal", "rough night, barely slept and it showed the whole day"),
    ("journal", "solid workout session in the evening, legs day done"),
    ("journal", "low energy day but managed to get through the important stuff"),
    ("journal", "feeling motivated lately, think the sleep routine change is helping"),
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _snapshot() -> dict:
    """Capture current max IDs and vault idea files."""
    conn = _conn()
    food_max = conn.execute("SELECT COALESCE(MAX(id), 0) FROM food_logs").fetchone()[0]
    task_max = conn.execute("SELECT COALESCE(MAX(id), 0) FROM tasks").fetchone()[0]
    conn.close()

    idea_files = set(glob.glob(str(VAULT / "ideas" / "*.md")))
    journal_files = set(glob.glob(str(VAULT / "daily" / "*.md")))

    return {
        "food_max": food_max,
        "task_max": task_max,
        "idea_files": list(idea_files),
        "journal_files": list(journal_files),
    }


def _diff(before: dict, after: dict) -> dict:
    """Return IDs/files created between before and after snapshots."""
    conn = _conn()

    new_food = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM food_logs WHERE id > ?", (before["food_max"],)
        ).fetchall()
    ]
    new_tasks = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM tasks WHERE id > ?", (before["task_max"],)
        ).fetchall()
    ]
    conn.close()

    before_ideas = set(before["idea_files"])
    after_ideas = set(glob.glob(str(VAULT / "ideas" / "*.md")))
    new_ideas = list(after_ideas - before_ideas)

    before_journals = set(before["journal_files"])
    after_journals = set(glob.glob(str(VAULT / "daily" / "*.md")))
    new_journals = list(after_journals - before_journals)

    return {
        "food_ids": new_food,
        "task_ids": new_tasks,
        "idea_files": new_ideas,
        "journal_files": new_journals,
    }


def send_message(text: str) -> dict:
    r = httpx.post(f"{SERVER}/message", json={"text": text}, timeout=60)
    return r.json()


def populate():
    print(f"Checking server at {SERVER}...")
    try:
        httpx.get(f"{SERVER}/health", timeout=5)
    except Exception as e:
        print(f"Server not reachable: {e}\nRun: python serve.py")
        sys.exit(1)

    before = _snapshot()
    print(f"Baseline: food_max={before['food_max']}, task_max={before['task_max']}, ideas={len(before['idea_files'])}\n")

    results = []
    for i, (category, msg) in enumerate(MESSAGES, 1):
        print(f"[{i:02d}/{len(MESSAGES)}] {category.upper()} → \"{msg[:60]}...\"" if len(msg) > 60 else f"[{i:02d}/{len(MESSAGES)}] {category.upper()} → \"{msg}\"")
        try:
            resp = send_message(msg)
            tools = resp.get("tools_called") or ([resp.get("tool_called")] if resp.get("tool_called") else [])
            reply = resp.get("reply", "")[:80]
            status = "✓" if tools else "✗ NO TOOL"
            print(f"         {status}  tools={tools}  reply=\"{reply}\"")
            results.append({"msg": msg, "category": category, "tools": tools, "ok": bool(tools)})
        except Exception as e:
            print(f"         ERROR: {e}")
            results.append({"msg": msg, "category": category, "tools": [], "ok": False})
        time.sleep(0.5)  # be gentle on the LLM API

    after = _snapshot()
    created = _diff(before, after)

    # Fetch notion_pages entries created for these IDs
    conn = _conn()
    notion_pages = []
    for fid in created["food_ids"]:
        row = conn.execute(
            "SELECT notion_page_id FROM notion_pages WHERE entity_type='food' AND entity_id=?",
            (str(fid),),
        ).fetchone()
        if row:
            notion_pages.append({"entity_type": "food", "entity_id": str(fid), "page_id": row[0]})
    for tid in created["task_ids"]:
        row = conn.execute(
            "SELECT notion_page_id FROM notion_pages WHERE entity_type='task' AND entity_id=?",
            (str(tid),),
        ).fetchone()
        if row:
            notion_pages.append({"entity_type": "task", "entity_id": str(tid), "page_id": row[0]})
    conn.close()

    manifest = {
        "created_at": datetime.now().isoformat(),
        "sqlite": created,
        "notion_pages": notion_pages,
        "results": results,
    }
    CLEANUP_FILE.write_text(json.dumps(manifest, indent=2))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    ok = sum(1 for r in results if r["ok"])
    print(f"  Messages sent : {len(MESSAGES)}")
    print(f"  Tools called  : {ok}/{len(MESSAGES)} ({100*ok//len(MESSAGES)}%)")
    by_cat: dict[str, list] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["ok"])
    for cat, vals in sorted(by_cat.items()):
        n = len(vals); h = sum(vals)
        print(f"  {cat:<10}: {h}/{n} picked up")
    print(f"\n  New food logs : {len(created['food_ids'])}")
    print(f"  New tasks     : {len(created['task_ids'])}")
    print(f"  New idea files: {len(created['idea_files'])}")
    print(f"  Notion pages  : {len(notion_pages)}")
    print(f"\n  Cleanup manifest saved → {CLEANUP_FILE}")
    print("  Run `python scripts/fake_data.py --cleanup` to delete everything.")


async def _delete_notion_page(page_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.delete(
            f"https://api.notion.com/v1/blocks/{page_id}",
            headers={
                "Authorization": f"Bearer {NOTION_KEY}",
                "Notion-Version": "2022-06-28",
            },
        )


def cleanup():
    if not CLEANUP_FILE.exists():
        print("No cleanup manifest found. Run populate first.")
        sys.exit(1)

    manifest = json.loads(CLEANUP_FILE.read_text())
    created = manifest["sqlite"]
    notion_pages = manifest.get("notion_pages", [])

    conn = _conn()

    # Delete food logs
    for fid in created.get("food_ids", []):
        conn.execute("DELETE FROM food_logs WHERE id = ?", (fid,))
        conn.execute("DELETE FROM notion_pages WHERE entity_type='food' AND entity_id=?", (str(fid),))
        print(f"  Deleted food_log id={fid}")

    # Delete tasks
    for tid in created.get("task_ids", []):
        conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
        conn.execute("DELETE FROM notion_pages WHERE entity_type='task' AND entity_id=?", (str(tid),))
        print(f"  Deleted task id={tid}")

    conn.commit()
    conn.close()

    # Delete vault idea files
    for f in created.get("idea_files", []):
        p = Path(f)
        if p.exists():
            p.unlink()
            print(f"  Deleted vault file: {p.name}")

    # Soft-delete Notion pages (archive them)
    if notion_pages and NOTION_KEY:
        print(f"\n  Archiving {len(notion_pages)} Notion pages...")
        asyncio.run(_archive_notion_pages(notion_pages))

    CLEANUP_FILE.unlink()
    print(f"\nCleanup done. Manifest removed.")


async def _archive_notion_pages(pages: list[dict]) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        for p in pages:
            r = await client.patch(
                f"https://api.notion.com/v1/pages/{p['page_id']}",
                headers={
                    "Authorization": f"Bearer {NOTION_KEY}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json={"archived": True},
            )
            status = "✓" if r.status_code == 200 else f"✗ {r.status_code}"
            print(f"  {status} archived {p['entity_type']} id={p['entity_id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true", help="Delete all fake entries")
    args = parser.parse_args()

    os.chdir(Path(__file__).parent.parent)  # run from cere-bro root

    if args.cleanup:
        cleanup()
    else:
        populate()
