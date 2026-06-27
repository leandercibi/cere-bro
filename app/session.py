from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Entry:
    message: dict[str, Any]  # full OpenAI message dict
    ts: float


class SessionBuffer:
    def __init__(self, max_messages: int = 20, ttl_seconds: int = 900) -> None:
        self._max = max_messages
        self._ttl = ttl_seconds
        self._store: dict[int, list[_Entry]] = {}

    def _sanitize(self, entries: list[_Entry]) -> list[_Entry]:
        """Remove orphaned tool messages left behind after eviction.

        OpenAI requires that every role=tool message is preceded (somewhere
        earlier in the list) by an assistant message whose tool_calls array
        contains the matching tool_call_id.  When the head of the buffer is
        trimmed, an assistant+tool_calls entry can be dropped while its
        paired tool entries remain — producing a malformed sequence that the
        API rejects with a 400.  We detect and remove such orphans here.
        """
        valid_ids: set[str] = set()
        for e in entries:
            tc_list = e.message.get("tool_calls") if e.message.get("role") == "assistant" else None
            if tc_list:
                for tc in tc_list:
                    valid_ids.add(tc["id"])
        return [
            e for e in entries
            if e.message.get("role") != "tool" or e.message.get("tool_call_id") in valid_ids
        ]

    def _evict(self, user_id: int) -> None:
        entries = self._store.get(user_id, [])
        cutoff = time.monotonic() - self._ttl
        entries = [e for e in entries if e.ts >= cutoff]
        if len(entries) > self._max:
            entries = entries[-self._max :]
        self._store[user_id] = self._sanitize(entries)

    def add_message(self, user_id: int, message: dict[str, Any]) -> None:
        if user_id not in self._store:
            self._store[user_id] = []
        self._store[user_id].append(_Entry(message=message, ts=time.monotonic()))
        self._evict(user_id)

    def add(self, user_id: int, role: str, content: str) -> None:
        self.add_message(user_id, {"role": role, "content": content})

    def get(self, user_id: int) -> list[dict]:
        self._evict(user_id)
        return [e.message for e in self._store.get(user_id, [])]

    def clear(self, user_id: int) -> None:
        self._store.pop(user_id, None)
