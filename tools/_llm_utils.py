"""LLM utilities for calorie and macro estimation.

Extracted from cere-bro/app/llm.py for use in Hermes tools.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openai import AsyncOpenAI

# Make the existing cere-bro app importable
_CEREBRO_ROOT = Path(__file__).resolve().parent.parent.parent / "cere-bro"
if str(_CEREBRO_ROOT) not in sys.path:
    sys.path.insert(0, str(_CEREBRO_ROOT))

from lib.config import Settings
from lib.models import CalorieEstimate, FoodItem

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_CALORIE_SYSTEM_PROMPT = """You estimate macros for a list of food items, mostly Indian.

Return strict JSON matching the CalorieEstimate schema (a per-item macro estimate).

For each input item, return {name, quantity, kcal, protein_g, fat_g, carbs_g}.
- Echo the input name and quantity exactly.
- kcal is an integer; protein_g, fat_g, carbs_g are floats (grams).
- When quantity is missing or vague, assume a typical single serving (e.g.
  1 roti ≈ 110 kcal / 3p / 3f / 18c, 1 cup dal ≈ 180 kcal / 9p / 5f / 23c,
  1 cup rice ≈ 200 kcal / 4p / 0.5f / 45c, 1 samosa ≈ 130 kcal / 3p / 8f / 13c,
  1 cup yogurt ≈ 100 kcal / 8p / 4f / 5c).

total_kcal       is the sum of items' kcal (integer).
total_protein_g  is the sum of items' protein_g (float).
total_fat_g      is the sum of items' fat_g (float).
total_carbs_g    is the sum of items' carbs_g (float).

notes: short caveat if any (e.g. 'assumed standard portion sizes'). Else null.

Be reasonable, not pessimistic. If a food is genuinely unknown, give a
best-guess macro split typical for that food category and add a note."""

_client: AsyncOpenAI | None = None


def _get_client(settings: Settings) -> AsyncOpenAI:
    """Return a cached AsyncOpenAI client pointed at OpenRouter."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=_OPENROUTER_BASE_URL,
            api_key=settings.openrouter_api_key,
        )
    return _client


async def estimate_calories(
    items: list[FoodItem], settings: Settings
) -> CalorieEstimate:
    """Estimate per-item calories + total. Indian portions assumed when ambiguous.

    Falls back to CalorieEstimate(items=[], total_kcal=0, notes='estimate failed')
    if structured-output returns None. Other API exceptions bubble up.
    """
    client = _get_client(settings)
    user_payload = json.dumps([i.model_dump() for i in items])

    response = await client.beta.chat.completions.parse(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": _CALORIE_SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ],
        response_format=CalorieEstimate,
        temperature=0.2,
    )

    parsed = response.choices[0].message.parsed
    if parsed is None:
        return CalorieEstimate(items=[], total_kcal=0, notes="estimate failed")
    return parsed
