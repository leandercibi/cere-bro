from app.tools.errors import ToolError


def test_tool_error_carries_message():
    err = ToolError("no entries found")
    assert err.user_message == "no entries found"


def test_tool_error_is_exception():
    err = ToolError("oops")
    assert isinstance(err, Exception)
    try:
        raise ToolError("boom")
    except ToolError as e:
        assert e.user_message == "boom"
