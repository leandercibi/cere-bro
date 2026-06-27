

from app.tools.registry import build_parameters, get_openai_tools
from lib.config import Settings


async def _sample_fn(
    name: str,
    count: int,
    score: float,
    active: bool,
    tags: list,
    note: str | None = None,
    *,
    user_id: int,
    settings: Settings,
) -> dict:
    return {}


def test_register_tool_from_function_signature():
    from app.tools.registry import ToolDef
    td = ToolDef(name="foo", description="bar", parameters=build_parameters(_sample_fn), handler=_sample_fn)
    assert td.name == "foo"
    assert "name" in td.parameters["properties"]


def test_tool_description_included():
    tools = get_openai_tools()
    for t in tools:
        assert t["function"]["description"]  # non-empty


def test_get_openai_tools_format_matches_spec():
    tools = get_openai_tools()
    assert len(tools) > 0
    for t in tools:
        assert t["type"] == "function"
        assert "function" in t
        fn = t["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn


def test_parameter_types_mapped_correctly():
    params = build_parameters(_sample_fn)
    props = params["properties"]
    assert props["name"]["type"] == "string"
    assert props["count"]["type"] == "integer"
    assert props["score"]["type"] == "number"
    assert props["active"]["type"] == "boolean"
    assert props["tags"]["type"] == "array"


def test_required_vs_optional_params():
    params = build_parameters(_sample_fn)
    required = params.get("required", [])
    assert "name" in required
    assert "count" in required
    assert "note" not in required  # Optional[str] with default


def test_injected_params_excluded_from_schema():
    params = build_parameters(_sample_fn)
    props = params["properties"]
    assert "user_id" not in props
    assert "settings" not in props
