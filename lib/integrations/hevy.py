"""Thin async client over the Hevy public API.

Base: https://api.hevyapp.com/v1 — Pro-only. Auth via `api-key` header.
Pagination is server-side (newest first, max page_size=10).

This module is intentionally narrow — just `list_workouts` and
`validate_api_key`. Higher-level orchestration (incremental sync, calorie
attribution, write-out to vault) lives in `app.domains.workout`.
"""
from __future__ import annotations

import httpx

from lib.models import HevyWorkout

_BASE_URL = "https://api.hevyapp.com"
_TIMEOUT = 20.0
_client: httpx.AsyncClient | None = None


class HevyAPIError(Exception):
    """Non-2xx response from the Hevy API.

    Carries `status_code` and a snippet of the response body so callers can
    surface useful diagnostics (e.g. show 'Hevy says: rate limited' to the
    user) without re-fetching.
    """

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Hevy API {status_code}: {body[:200]}")


def _get_client() -> httpx.AsyncClient:
    """Lazy module-level client. Reused across calls so connection pooling
    works even though each request authenticates with a header."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT)
    return _client


async def list_workouts(
    api_key: str, page: int = 1, page_size: int = 10
) -> list[HevyWorkout]:
    """GET /v1/workouts. Returns workouts on this page (newest first).

    Returns [] when past the end of the user's history. Raises HevyAPIError
    on any non-2xx (including 401/403 — caller decides how to surface).
    """
    client = _get_client()
    resp = await client.get(
        "/v1/workouts",
        params={"page": page, "pageSize": page_size},
        headers={"api-key": api_key},
    )
    if resp.status_code >= 400:
        raise HevyAPIError(resp.status_code, resp.text)

    data = resp.json()
    raw = data.get("workouts", [])
    return [HevyWorkout.model_validate(w) for w in raw]


async def validate_api_key(api_key: str) -> bool:
    """GET /v1/user/info. True on 2xx, False on 401/403, raises on other 4xx/5xx.

    Used by the bot's `/sync` to give a clean 'invalid key' message instead
    of a stack trace when the user's HEVY_API_KEY is wrong.
    """
    client = _get_client()
    resp = await client.get("/v1/user/info", headers={"api-key": api_key})
    if resp.status_code in (401, 403):
        return False
    if resp.status_code >= 400:
        raise HevyAPIError(resp.status_code, resp.text)
    return True
