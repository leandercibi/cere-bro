"""Obsidian sink — writes food logs into the vault as markdown daily notes.

Vault layout (managed by ensure_vault_structure):
    vault/
    ├── README.md
    ├── daily/        ← one daily note per day, edited by this module
    ├── ideas/
    ├── projects/
    ├── journal/
    ├── dashboards/
    └── .backups/

Daily note layout (managed by ensure_daily_note + append_food/update_food):
    # YYYY-MM-DD
    ## Workout
    ## Food
    ## Tasks
    ## Journal

(Ideas live OUTSIDE the daily folder — each idea has its own file at
 vault/ideas/<slug>.md with its own stage-tracked structure.)
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from lib.models import FoodLog, StoredWorkout


# ---------- vault scaffold ----------

VAULT_SUBDIRS = ("daily", "ideas", "projects", "journal", "dashboards", ".backups")
VAULT_README = "cerebro vault — auto-managed daily notes and free-form ideas\n"

DAILY_TEMPLATE = """# {day}

## Workout

## Food

## Tasks

## Journal
"""


def ensure_vault_structure(vault_root: Path) -> None:
    """Create the vault directory tree if missing. Idempotent."""
    vault_root.mkdir(parents=True, exist_ok=True)
    readme = vault_root / "README.md"
    if not readme.exists():
        readme.write_text(VAULT_README)
    for sub in VAULT_SUBDIRS:
        d = vault_root / sub
        d.mkdir(parents=True, exist_ok=True)
        keep = d / ".gitkeep"
        if not keep.exists():
            keep.touch()


# ---------- daily notes ----------

def daily_note_path(vault_root: Path, day: date) -> Path:
    """Return path: vault_root/daily/YYYY-MM-DD.md"""
    return vault_root / "daily" / f"{day.isoformat()}.md"


def ensure_daily_note(vault_root: Path, day: date) -> Path:
    """Create the daily note from template if missing. Idempotent. Returns path."""
    path = daily_note_path(vault_root, day)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DAILY_TEMPLATE.format(day=day.isoformat()))
    return path


# ---------- food rendering ----------

def _anchor_for(food_log_id: int) -> str:
    return f"<!-- cerebro:food:{food_log_id} -->"


def _render_food_line(food_log: FoodLog, anchor: str) -> str:
    items_str = ", ".join(
        f"{item.name} ({item.quantity})" if item.quantity else item.name
        for item in food_log.items
    )
    junk_marker = " #junk" if food_log.junk else ""
    kcal_marker = (
        f" · ~{food_log.est_calories_kcal} kcal"
        if food_log.est_calories_kcal is not None
        else ""
    )
    # Macros segment: only render when ALL THREE are present (a partial split
    # would mislead at a glance). Compact form: '14p 6f 65c'.
    macros_marker = ""
    if (
        food_log.est_protein_g is not None
        and food_log.est_fat_g is not None
        and food_log.est_carbs_g is not None
    ):
        macros_marker = (
            f" · {round(food_log.est_protein_g)}p"
            f" {round(food_log.est_fat_g)}f"
            f" {round(food_log.est_carbs_g)}c"
        )
    time_str = food_log.logged_at.strftime("%H:%M")
    return f"- {time_str} — {items_str}{junk_marker}{kcal_marker}{macros_marker} {anchor}"


# ---------- section helpers ----------

def _is_h2(line: str) -> bool:
    """True for level-2 headings only (## Foo); excludes ### and beyond."""
    return line.startswith("## ") and not line.startswith("### ")


def _find_h2(lines: list[str], heading: str) -> int | None:
    """Return index of the line equal to `heading` (e.g. '## Food'), or None."""
    for i, line in enumerate(lines):
        if line.strip() == heading:
            return i
    return None


def _find_next_h2(lines: list[str], start: int) -> int:
    """Return index of the next level-2 heading at/after `start`, or len(lines)."""
    for i in range(start, len(lines)):
        if _is_h2(lines[i]):
            return i
    return len(lines)


# ---------- food append / update ----------

def append_food(vault_root: Path, food_log: FoodLog) -> str:
    """Append a food line under '## Food' of the daily note for food_log.logged_at.date().

    If '## Food' section is missing, insert it before '## Tasks' (or append at EOF).
    Returns the anchor string used to locate this line later.
    """
    day = food_log.logged_at.date()
    path = ensure_daily_note(vault_root, day)
    text = path.read_text()
    lines = text.splitlines()

    anchor = _anchor_for(food_log.id)
    new_line = _render_food_line(food_log, anchor)

    food_idx = _find_h2(lines, "## Food")
    if food_idx is None:
        _insert_new_food_section(lines, new_line)
    else:
        _append_into_food_section(lines, food_idx, new_line)

    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text)
    return anchor


def update_food(vault_root: Path, food_log: FoodLog) -> None:
    """Replace the line tagged with food_log.obsidian_anchor with the rendered version.

    Searches the daily note for food_log.logged_at.date(). Raises ValueError if
    the daily note or anchor is not found.
    """
    if not food_log.obsidian_anchor:
        raise ValueError("food_log.obsidian_anchor is required for update_food")
    day = food_log.logged_at.date()
    path = daily_note_path(vault_root, day)
    if not path.exists():
        raise ValueError(f"Daily note not found: {path}")

    text = path.read_text()
    lines = text.splitlines()
    anchor = food_log.obsidian_anchor
    new_line = _render_food_line(food_log, anchor)

    for i, line in enumerate(lines):
        if line.endswith(anchor):
            lines[i] = new_line
            break
    else:
        raise ValueError(f"Anchor not found in {path}: {anchor}")

    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text)


def remove_food(vault_root: Path, food_log: FoodLog) -> None:
    """Remove the food line tagged with food_log.obsidian_anchor from the daily note.

    Searches the daily note for food_log.logged_at.date(). Idempotent and tolerant:
    silently no-ops if obsidian_anchor is missing, the daily note doesn't exist,
    or the anchor isn't present in the file.
    """
    anchor = food_log.obsidian_anchor
    if not anchor:
        return
    path = daily_note_path(vault_root, food_log.logged_at.date())
    if not path.exists():
        return

    text = path.read_text()
    lines = text.splitlines()

    new_lines = [line for line in lines if not line.endswith(anchor)]
    if len(new_lines) == len(lines):
        # Anchor not found in this daily note; nothing to do.
        return

    new_text = "\n".join(new_lines)
    if text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text)


# ---------- internal: section mutations ----------

def _append_into_food_section(lines: list[str], food_idx: int, new_line: str) -> None:
    """Mutate `lines` in place: append `new_line` at the end of the ## Food section.

    Strategy: rebuild the section content (lines between '## Food' and the next ## heading
    or EOF), trim leading/trailing blanks, append the new line, wrap with single blanks.
    """
    next_idx = _find_next_h2(lines, food_idx + 1)
    section = lines[food_idx + 1 : next_idx]

    while section and section[-1] == "":
        section.pop()
    while section and section[0] == "":
        section.pop(0)

    section.append(new_line)
    new_section = [""] + section + [""]
    lines[food_idx + 1 : next_idx] = new_section


def _insert_new_food_section(lines: list[str], new_line: str) -> None:
    """Mutate `lines` in place: create a fresh ## Food section.

    Inserted before '## Tasks' if present, else appended at EOF.
    """
    tasks_idx = _find_h2(lines, "## Tasks")
    block = ["## Food", "", new_line, ""]

    if tasks_idx is not None:
        # Ensure blank line before the new section if there isn't one already.
        if tasks_idx > 0 and lines[tasks_idx - 1] != "":
            block = [""] + block
        lines[tasks_idx:tasks_idx] = block
    else:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(["## Food", "", new_line])


# ---------- workout rendering ----------

def _workout_anchor_for(hevy_id: str) -> str:
    return f"<!-- cerebro:workout:{hevy_id} -->"


def _fmt_volume_kg(kg: float) -> str:
    """'12.4k kg' for >=1000, '640 kg' otherwise."""
    if kg >= 1000:
        return f"{kg / 1000:.1f}k kg"
    return f"{kg:.0f} kg"


def _fmt_duration_s(seconds: int) -> str:
    """'1h 23m', '2h', or '45m'. Rounds to nearest minute."""
    minutes = round(seconds / 60)
    if minutes >= 60:
        h, m = divmod(minutes, 60)
        return f"{h}h {m}m" if m else f"{h}h"
    return f"{minutes}m"


def _render_workout_line(workout: StoredWorkout, anchor: str) -> str:
    """`- {title} · {n} exercises[ · {vol}][ · {dur}][ · ~{kcal} kcal] {anchor}`"""
    try:
        n_exercises = len(json.loads(workout.exercises_json))
    except (ValueError, TypeError):
        n_exercises = 0

    parts = [f"{workout.title}", f"{n_exercises} exercises"]
    if workout.total_volume_kg > 0:
        parts.append(_fmt_volume_kg(workout.total_volume_kg))
    parts.append(_fmt_duration_s(workout.duration_s))
    if workout.est_calories_kcal is not None:
        parts.append(f"~{workout.est_calories_kcal} kcal")

    return f"- {' · '.join(parts)} {anchor}"


# ---------- workout section helpers ----------

def _append_into_workout_section(
    lines: list[str], workout_idx: int, new_line: str
) -> None:
    """Mutate `lines` in place: append `new_line` at the end of '## Workout'.

    Mirrors _append_into_food_section: rebuild the section content, trim blanks,
    append the new line, re-wrap with single blank lines.
    """
    next_idx = _find_next_h2(lines, workout_idx + 1)
    section = lines[workout_idx + 1 : next_idx]

    while section and section[-1] == "":
        section.pop()
    while section and section[0] == "":
        section.pop(0)

    section.append(new_line)
    new_section = [""] + section + [""]
    lines[workout_idx + 1 : next_idx] = new_section


def _insert_new_workout_section(lines: list[str], new_line: str) -> None:
    """Mutate `lines` in place: create a fresh '## Workout' section.

    Insertion target, in order of preference:
      1. before '## Food'
      2. before the first '## ' heading
      3. at end of file
    """
    food_idx = _find_h2(lines, "## Food")
    insert_at: int | None = food_idx

    if insert_at is None:
        # No Food heading; find the first level-2 heading.
        for i, line in enumerate(lines):
            if _is_h2(line):
                insert_at = i
                break

    block = ["## Workout", "", new_line, ""]

    if insert_at is not None:
        if insert_at > 0 and lines[insert_at - 1] != "":
            block = [""] + block
        lines[insert_at:insert_at] = block
    else:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(["## Workout", "", new_line])


# ---------- workout append (public API) ----------

def append_workout_summary(vault_root: Path, workout: StoredWorkout) -> str:
    """Append a workout summary line under '## Workout' of the daily note for
    workout.started_at.date(). Creates the daily note from template if missing
    and the '## Workout' section if missing (inserted before '## Food').
    Returns the anchor string used to identify this line later.
    """
    day = workout.started_at.date()
    path = ensure_daily_note(vault_root, day)
    text = path.read_text()
    lines = text.splitlines()

    anchor = _workout_anchor_for(workout.hevy_id)
    new_line = _render_workout_line(workout, anchor)

    workout_idx = _find_h2(lines, "## Workout")
    if workout_idx is None:
        _insert_new_workout_section(lines, new_line)
    else:
        _append_into_workout_section(lines, workout_idx, new_line)

    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text)
    return anchor


def append_workout_note(vault_root: Path, day: date, note: str) -> None:
    """Append a `> {note}` blockquote line under '## Workout' in the daily note
    for `day`. Multiple notes per day are allowed (each becomes its own line).
    No anchor — notes are append-only narrative; no edit/delete via reply.
    """
    cleaned = note.strip()
    if cleaned.startswith(">"):
        cleaned = cleaned[1:].lstrip()
    if not cleaned:
        return

    path = ensure_daily_note(vault_root, day)
    text = path.read_text()
    lines = text.splitlines()

    new_line = f"> {cleaned}"
    workout_idx = _find_h2(lines, "## Workout")
    if workout_idx is None:
        _insert_new_workout_section(lines, new_line)
    else:
        _append_into_workout_section(lines, workout_idx, new_line)

    new_text = "\n".join(lines)
    if text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text)


def update_workout_summary(vault_root: Path, workout: StoredWorkout) -> None:
    """Re-render the workout summary line in the daily note for
    workout.started_at.date(). Locates the line by its anchor and replaces it
    with the current rendering of `workout` (picks up new est_calories_kcal,
    revised volume, etc).

    Idempotent: silently no-ops if the daily note doesn't exist OR if no line
    in it ends with this workout's anchor. Used after `/profile` updates to
    sync vault display with the DB-side recompute.
    """
    day = workout.started_at.date()
    path = daily_note_path(vault_root, day)
    if not path.exists():
        return

    anchor = _workout_anchor_for(workout.hevy_id)
    new_line = _render_workout_line(workout, anchor)

    text = path.read_text()
    lines = text.splitlines(keepends=True)

    replaced = False
    for i, line in enumerate(lines):
        # Anchor lives inside the line; preserve trailing newline of the
        # original line if present.
        if anchor in line:
            trailing = "\n" if line.endswith("\n") else ""
            lines[i] = new_line + trailing
            replaced = True
            break

    if not replaced:
        return

    path.write_text("".join(lines))
