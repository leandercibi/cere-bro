from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI, RateLimitError

from lib.config import Settings

logger = logging.getLogger("cerebro.llm")

_client: AsyncOpenAI | None = None


def get_client(settings: Settings) -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
    return _client


async def _call_with_retry(client: AsyncOpenAI, max_retries: int = 3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await client.chat.completions.create(**kwargs)
        except RateLimitError:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt + 1
            logger.warning("Rate limited, retrying in %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
            await asyncio.sleep(wait)


async def estimate_macros(items: list[dict], settings: Settings) -> dict | None:
    """Call LLM to estimate kcal+macros for items. Returns None on failure."""
    try:
        client = get_client(settings)
        items_text = ", ".join(
            f"{i['quantity']} {i['name']}" if i.get("quantity") else i["name"]
            for i in items
        )
        resp = await _call_with_retry(
            client,
            model=settings.llm_model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a nutrition estimator. Given food items, return JSON with keys: "
                        "total_kcal (int), total_protein_g (float), total_fat_g (float), "
                        "total_carbs_g (float), items (array of {name, kcal, protein_g, fat_g, carbs_g})."
                    ),
                },
                {"role": "user", "content": f"Estimate macros for: {items_text}"},
            ],
            max_tokens=400,
        )
        return json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        logger.exception("estimate_macros failed")
        return None
