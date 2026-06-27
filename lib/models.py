"""Shared data models for cerebro.

These are the contracts between modules (llm, db, sinks, domains).
Keep dependency-free — only stdlib + pydantic.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- Food domain primitives ----------

class FoodItem(BaseModel):
    """A single item within a food log entry."""

    name: str = Field(description="Canonical food name, lowercase (e.g. 'dal', 'roti')")
    quantity: Optional[str] = Field(
        default=None,
        description="Free-form quantity if user mentioned one (e.g. '2', '1 cup', 'small bowl')",
    )


# ---------- Persisted row ----------

class FoodLog(BaseModel):
    """A persisted food log row."""

    id: int
    user_id: int
    raw_text: str
    items: list[FoodItem]
    junk: bool
    logged_at: datetime
    created_at: datetime
    telegram_message_id: Optional[int] = None
    obsidian_anchor: Optional[str] = None
    est_calories_kcal: Optional[int] = None  # total kcal estimate (None if not yet computed or failed)
    est_calories_items_json: Optional[str] = None  # JSON list of {name, quantity, kcal, protein_g, fat_g, carbs_g}
    est_protein_g: Optional[float] = None  # total grams protein
    est_fat_g: Optional[float] = None      # total grams fat
    est_carbs_g: Optional[float] = None    # total grams carbs


# ---------- LLM intent + payloads ----------

class FoodLogPayload(BaseModel):
    """Populated when MessageParse.intent == 'food_log'."""

    items: list[FoodItem] = Field(default_factory=list)
    junk: bool = Field(
        default=False,
        description="True if and only if the message contains the hashtag #junk (case-insensitive).",
    )
    logged_at: Optional[datetime] = Field(
        default=None,
        description="Inferred eating time, if user mentioned one. Else null.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Free-form remarks the user added (e.g. 'felt heavy after').",
    )


class DeletePayload(BaseModel):
    """Populated when MessageParse.intent == 'delete'."""

    target: Literal["recent", "matching"] = Field(
        description=(
            "'recent' for 'delete the last entry', 'matching' if the user named a specific food."
        )
    )
    item_hint: Optional[str] = Field(
        default=None,
        description="Lowercase food name (e.g. 'samosa') if the user named one. Else null.",
    )


class CalorieQueryPayload(BaseModel):
    """Populated when MessageParse.intent == 'calorie_query' OR 'macro_query'.

    Both intents share the same payload shape — the difference is just the
    user-facing phrasing ("calorie breakdown" vs "macro breakdown"). Both
    return the full kcal+protein+fat+carbs view; see
    `app.domains.food._handle_macro_query`.
    """

    scope: Literal["last", "today", "yesterday", "by_date", "matching"] = Field(
        description=(
            "'last' = the most recent food entry. "
            "'today' / 'yesterday' = all entries that day. "
            "'by_date' = a specific date the user mentioned. "
            "'matching' = the most recent entry whose items contain `item_hint`."
        )
    )
    day: Optional[date] = Field(
        default=None,
        description="ISO date (YYYY-MM-DD) when scope='by_date'. Else null.",
    )
    item_hint: Optional[str] = Field(
        default=None,
        description="Lowercase food name when scope='matching'. Else null.",
    )


class WorkoutNotePayload(BaseModel):
    """Populated when MessageParse.intent == 'workout_note'.

    The narrative the user wrote about a workout (e.g. 'felt strong, fasted').
    Triggers a Hevy sync as a side-effect when handled.
    """

    note: str = Field(
        description="The narrative text about the workout, lightly cleaned. Echo the user's words."
    )


class IdeaCapturePayload(BaseModel):
    """Populated when MessageParse.intent == 'idea_capture'.

    A new idea / project / thought the user wants tracked separately. Each
    captured idea becomes its own file at `vault/ideas/<slug>.md` with a
    stage-tracked structure. Editing happens in Obsidian, not via Telegram.
    """

    title: str = Field(
        description=(
            "Concise idea title (≤ ~10 words). Lowercase, no trailing punctuation. "
            "This drives the filename slug and the H1 of the idea note."
        )
    )
    description: Optional[str] = Field(
        default=None,
        description=(
            "The 'spark' — context, motivation, or extra detail beyond the title. "
            "Null when the user only stated a title."
        ),
    )
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Optional tags from the message (e.g. #productivity, #ml). Stripped of "
            "the leading '#'. Excludes the '#idea' marker itself."
        ),
    )


class IdeaDeepdivePayload(BaseModel):
    """Populated when MessageParse.intent == 'idea_deepdive'.

    Three modes (resolved by `app.domains.ideas.handle_idea_deepdive`):
      - `title_hint` provided AND a single matching idea -> run dive (or
        return existing brief if one is already on the idea file).
      - `title_hint` provided AND no match -> create a new idea with that
        title, then run dive.
      - `title_hint` empty/null -> list the 5 most-recently-updated ideas
        as a discovery menu.
    Multiple matches are handled by the bot layer (it asks the user to pick).
    """

    title_hint: Optional[str] = Field(
        default=None,
        description=(
            "Substring match against existing idea slugs/titles. Null when the "
            "user just said 'deepdive' with no idea name."
        ),
    )


class MessageParse(BaseModel):
    """Top-level LLM output: classifies the user's intent and carries one payload."""

    intent: Literal[
        "food_log",
        "delete",
        "calorie_query",
        "macro_query",
        "workout_note",
        "idea_capture",
        "idea_deepdive",
        "other",
    ] = Field(
        description=(
            "Pick exactly one intent based on the user's message. "
            "'food_log' = describing food they ate. "
            "'delete' = wants to remove a previous entry. "
            "'calorie_query' = asking for a calorie breakdown. "
            "'macro_query' = asking for protein/fat/carbs/macro breakdown. "
            "'workout_note' = describing a workout they finished "
            "(e.g. 'workout done', 'leg day complete, felt tired'). "
            "'idea_capture' = capturing a new idea/project/thought "
            "(e.g. '#idea ...', 'new idea: ...', 'project idea: ...'). "
            "'idea_deepdive' = asking for research on an idea "
            "(e.g. 'deepdive', 'deepdive predict workout times', "
            "'dive deep into <name>', 'research <name>', '#deepdive <name>'). "
            "'other' = anything else."
        )
    )
    food_log: Optional[FoodLogPayload] = None
    delete: Optional[DeletePayload] = None
    calorie_query: Optional[CalorieQueryPayload] = None
    macro_query: Optional[CalorieQueryPayload] = None  # same payload shape as calorie_query
    workout_note: Optional[WorkoutNotePayload] = None
    idea_capture: Optional[IdeaCapturePayload] = None
    idea_deepdive: Optional[IdeaDeepdivePayload] = None


# ---------- Calorie estimation ----------

class ItemCalorie(BaseModel):
    """Per-item macro estimate (calories + protein + fat + carbs).

    Class name kept as `ItemCalorie` for back-compat with earlier code paths
    that reference it; the shape is the rich macro view.
    """

    name: str
    quantity: Optional[str] = None
    kcal: int = Field(description="Estimated calories for this item, integer.")
    protein_g: float = Field(default=0.0, description="Protein in grams.")
    fat_g: float = Field(default=0.0, description="Fat in grams.")
    carbs_g: float = Field(default=0.0, description="Carbohydrates in grams.")


class CalorieEstimate(BaseModel):
    """LLM output for `estimate_macros(items)`.

    Class name kept as `CalorieEstimate` for back-compat; carries full
    macro totals (kcal + protein + fat + carbs).
    """

    items: list[ItemCalorie]
    total_kcal: int
    total_protein_g: float = Field(default=0.0)
    total_fat_g: float = Field(default=0.0)
    total_carbs_g: float = Field(default=0.0)
    notes: Optional[str] = Field(
        default=None,
        description="Short caveat (e.g. 'assumed standard portion sizes'). Else null.",
    )


# Aliases for forward-looking call sites.
ItemMacros = ItemCalorie
MacroEstimate = CalorieEstimate


# ---------- Workouts (Hevy) ----------

class HevySet(BaseModel):
    """A single set as returned by the Hevy API."""

    type: str  # 'warmup' | 'normal' | 'failure' | 'dropset' | ...
    weight_kg: Optional[float] = None
    reps: Optional[int] = None
    distance_meters: Optional[float] = None
    duration_seconds: Optional[int] = None
    rpe: Optional[float] = None


class HevyExercise(BaseModel):
    """An exercise within a Hevy workout."""

    exercise_template_id: str
    title: Optional[str] = None  # exercise name from Hevy API (e.g. "Barbell Bench Press")
    notes: Optional[str] = None
    sets: list[HevySet] = Field(default_factory=list)


class HevyWorkout(BaseModel):
    """A workout as returned by the Hevy API."""

    id: str
    title: str
    description: Optional[str] = None
    start_time: datetime
    end_time: datetime
    exercises: list[HevyExercise] = Field(default_factory=list)


class StoredWorkout(BaseModel):
    """A workout row persisted in SQLite."""

    hevy_id: str
    title: str
    description: Optional[str] = None
    started_at: datetime
    ended_at: datetime
    duration_s: int
    total_volume_kg: float
    est_calories_kcal: Optional[int] = None  # null when profile is missing
    exercises_json: str  # raw JSON of HevyExercise list
    fetched_at: datetime


# ---------- User profile (for BMR / calorie estimation) ----------

class UserProfile(BaseModel):
    """Single-row profile used to compute BMR and per-workout calories."""

    height_cm: float
    age: int
    sex: Literal["M", "F"]
    weight_kg: float
    updated_at: datetime


# ---------- Daily macro totals (denormalized cache) ----------

class DailyTotals(BaseModel):
    """Per-day rollup of all food_logs for that date in user TZ.

    A denormalized cache: source of truth is `food_logs`. Rebuilt by
    `app.db.recompute_daily_totals(conn, day)` on every food_log
    insert/edit/delete. Read by macro_query.
    """

    date: date
    total_kcal: int
    total_protein_g: float
    total_fat_g: float
    total_carbs_g: float
    updated_at: datetime
