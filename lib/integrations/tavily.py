"""Thin async client over the Tavily Search API.

Tavily returns LLM-ready search results: each hit carries a clean text
snippet, the source URL, and a relevance score. We only need the search
endpoint for divedeep.

Auth: POST /search with an `api_key` field in the JSON body (NOT a header).
Docs: https://docs.tavily.com/

This module is intentionally narrow — just `search`. Synthesis lives in
`app.llm.synthesize_brief`; orchestration lives in `app.domains.ideas`.
"""
from __future__ import annotations

import httpx

_BASE_URL = "https://api.tavily.com"
_TIMEOUT = 20.0
_client: httpx.AsyncClient | None = None


class TavilyAPIError(Exception):
    """Non-2xx response from Tavily."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Tavily API {status_code}: {body[:200]}")


def _get_client() -> httpx.AsyncClient:
    """Lazy module-level client. Reused across calls for connection pooling."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT)
    return _client


async def search(
    api_key: str,
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
) -> list[dict]:
    """POST /search → list of dicts with keys {title, url, content, score}.

    `search_depth='basic'` is the cheap path (free tier); 'advanced' is
    paid. Free tier: 1k searches/month — enough for personal divedeep.

    Returns [] when Tavily returns an empty result set. Raises TavilyAPIError
    on non-2xx so the caller can surface a useful diagnostic.
    """
    client = _get_client()
    resp = await client.post(
        "/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_answer": False,  # we synthesize ourselves with DeepSeek
            "include_raw_content": False,  # `content` snippet is enough
        },
    )
    if resp.status_code >= 400:
        raise TavilyAPIError(resp.status_code, resp.text)

    data = resp.json()
    return data.get("results", [])
