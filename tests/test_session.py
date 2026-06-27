import time

from app.session import SessionBuffer


def test_add_and_get_returns_messages_in_order():
    buf = SessionBuffer()
    buf.add(1, "user", "hello")
    buf.add(1, "assistant", "hi")
    msgs = buf.get(1)
    assert msgs == [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]


def test_max_messages_evicts_oldest():
    buf = SessionBuffer(max_messages=2)
    buf.add(1, "user", "a")
    buf.add(1, "user", "b")
    buf.add(1, "user", "c")
    msgs = buf.get(1)
    assert len(msgs) == 2
    assert msgs[0]["content"] == "b"
    assert msgs[1]["content"] == "c"


def test_ttl_evicts_expired_messages(monkeypatch):
    buf = SessionBuffer(ttl_seconds=10)
    t = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: t)
    buf.add(1, "user", "old")
    t = 1015.0  # 15s later — past TTL
    buf.add(1, "user", "new")
    msgs = buf.get(1)
    assert len(msgs) == 1
    assert msgs[0]["content"] == "new"


def test_get_empty_user_returns_empty_list():
    buf = SessionBuffer()
    assert buf.get(99) == []


def test_clear_wipes_user_buffer():
    buf = SessionBuffer()
    buf.add(1, "user", "hello")
    buf.clear(1)
    assert buf.get(1) == []


def test_independent_users_dont_leak():
    buf = SessionBuffer()
    buf.add(1, "user", "user1 msg")
    buf.add(2, "user", "user2 msg")
    assert buf.get(1) == [{"role": "user", "content": "user1 msg"}]
    assert buf.get(2) == [{"role": "user", "content": "user2 msg"}]
