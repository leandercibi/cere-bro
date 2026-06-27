from __future__ import annotations

import inspect
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import get_args, get_origin, get_type_hints


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    handler: Callable


_INJECTED = {"user_id", "settings"}

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
}


def _py_type_to_json(tp) -> tuple[str, bool]:
    """Return (json_type, is_required). Optional[X] → not required."""
    origin = get_origin(tp)
    # Optional[X] == Union[X, None]
    if origin is types.UnionType or str(origin) == "typing.Union":
        args = [a for a in get_args(tp) if a is not type(None)]
        if args:
            json_type = _TYPE_MAP.get(get_origin(args[0]) or args[0], "string")
            return json_type, False
    if origin is list:
        return "array", True
    return _TYPE_MAP.get(tp, "string"), True


def build_parameters(fn: Callable) -> dict:
    """Build a JSON Schema parameters object from a function's type hints."""
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    properties: dict = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in _INJECTED:
            continue
        tp = hints.get(name, str)
        json_type, is_req = _py_type_to_json(tp)
        prop: dict = {"type": json_type}
        if json_type == "array":
            prop["items"] = {"type": "object"}
        properties[name] = prop
        has_default = param.default is not inspect.Parameter.empty
        if is_req and not has_default:
            required.append(name)

    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def get_all_tools() -> list[ToolDef]:
    from app.tools import food, ideas, journal, profile, tasks, workout

    return (
        food.TOOLS
        + workout.TOOLS
        + ideas.TOOLS
        + journal.TOOLS
        + tasks.TOOLS
        + profile.TOOLS
    )


def get_openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in get_all_tools()
    ]
