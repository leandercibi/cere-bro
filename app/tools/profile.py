from __future__ import annotations

import app.db as db
from app.tools.errors import ToolError
from app.tools.registry import ToolDef
from lib.config import Settings


async def update_profile(
    weight_kg: float | None = None,
    height_cm: float | None = None,
    age: int | None = None,
    sex: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    conn = db.get_conn(settings.db_path)
    try:
        existing = db.get_profile(conn)
        if existing:
            new_weight = weight_kg if weight_kg is not None else existing.weight_kg
            new_height = height_cm if height_cm is not None else existing.height_cm
            new_age = age if age is not None else existing.age
            new_sex = sex if sex is not None else existing.sex
        else:
            if any(v is None for v in [weight_kg, height_cm, age, sex]):
                raise ToolError("First-time profile needs weight_kg, height_cm, age, and sex.")
            new_weight, new_height, new_age, new_sex = weight_kg, height_cm, age, sex
        profile = db.upsert_profile(conn, height_cm=new_height, age=new_age, sex=new_sex, weight_kg=new_weight)
    finally:
        conn.close()
    return {
        "weight_kg": profile.weight_kg,
        "height_cm": profile.height_cm,
        "age": profile.age,
        "sex": profile.sex,
    }


async def get_profile(
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    conn = db.get_conn(settings.db_path)
    try:
        profile = db.get_profile(conn)
    finally:
        conn.close()
    if not profile:
        raise ToolError("No profile set yet. Use update_profile to create one.")
    return {
        "weight_kg": profile.weight_kg,
        "height_cm": profile.height_cm,
        "age": profile.age,
        "sex": profile.sex,
        "updated_at": profile.updated_at.isoformat(),
    }


TOOLS: list[ToolDef] = [
    ToolDef(
        name="update_profile",
        description="Update user physical profile.",
        parameters={
            "type": "object",
            "properties": {
                "weight_kg": {"type": "number"},
                "height_cm": {"type": "number"},
                "age": {"type": "integer"},
                "sex": {"type": "string", "enum": ["M", "F"]},
            },
        },
        handler=update_profile,
    ),
    ToolDef(
        name="get_profile",
        description="Show user's current profile.",
        parameters={"type": "object", "properties": {}},
        handler=get_profile,
    ),
]
