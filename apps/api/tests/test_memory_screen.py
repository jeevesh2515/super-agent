"""The memory screen: owner-side store functions and the typed messages on the voice socket."""
import asyncio
import json
import re
import sqlite3
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect
from test_voice_api import ScriptedAdapter, authenticate, connect, make_client

from super_agent_voice import memory
from super_agent_voice.adapter import Transcript

LINE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4} (\w+) (ok|error)$")
SRC = Path(memory.__file__).parent


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem" / "memory.db")
    monkeypatch.setenv("SUPER_AGENT_MEMORY", "on")
    yield
    memory.reset_pause()


def texts(query: str = "") -> list[str]:
    return [item["text"] for item in memory.view(query)["items"]]


def the_fact() -> int:
    memory.remember_fact("my sister Asha lives in Leeds")
    return memory.view()["items"][0]["id"]


def row_count() -> int:
    con = sqlite3.connect(memory.DB_PATH)
    try:
        return con.execute("SELECT (SELECT count(*) FROM facts) + (SELECT count(*) FROM reminders)").fetchone()[0]
    finally:
        con.close()


# --- the owner-side store functions ---------------------------------------------

def test_each_item_records_whether_it_came_from_the_users_words():
    memory.run("remember_fact", {"text": "from the user"}, from_user=True)
    memory.run("remember_fact", {"text": "model only"})
    memory.run("add_reminder", {"text": "call home", "when": "in 20 minutes"}, from_user=True)
    items = {i["text"]: i for i in memory.view()["items"]}
    assert items["from the user"]["fromUser"] is True
    assert items["model only"]["fromUser"] is False
    assert items["call home"]["fromUser"] is True and items["call home"]["kind"] == "reminder"
    assert set(items["call home"]) == {"kind", "id", "text", "createdAt", "fromUser", "dueAt", "repeat"}
    assert set(items["model only"]) == {"kind", "id", "text", "createdAt", "fromUser"}


def test_a_write_through_the_adapter_gate_is_recorded_as_from_the_users_words():
    from super_agent_voice import local_adapter

    async def go() -> str:
        local_adapter._HEARD.set("please remember that Bob likes coffee")
        return await local_adapter.call_tool("remember_fact", {"text": "Bob likes coffee"})

    assert asyncio.run(go()).startswith("Remembered")
    assert memory.view()["items"][0]["fromUser"] is True


def test_a_store_made_before_the_origin_column_is_migrated_and_kept():
    memory.DB_PATH.parent.mkdir(parents=True)
    con = sqlite3.connect(memory.DB_PATH)
    con.execute("CREATE TABLE facts(id INTEGER PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL, deleted_at TEXT)")
    con.execute("INSERT INTO facts(text, created_at) VALUES ('old fact', '2026-01-01T00:00:00.000000+00:00')")
    con.commit()
    con.close()
    assert [(i["text"], i["fromUser"]) for i in memory.view()["items"]] == [("old fact", False)]
    assert memory.remember_fact("new fact") == "Remembered: new fact"


def test_pause_refuses_every_model_write_but_not_reads():
    memory.run("remember_fact", {"text": "kept"})
    memory.set_paused(True)
    assert memory.is_paused()
    for name, args in (("remember_fact", {"text": "x"}), ("add_reminder", {"text": "x", "when": "in 5 minutes"}),
                       ("forget", {"match": "kept"}), ("undo_forget", {}), ("complete_reminder", {"match": "kept"})):
        assert memory.run(name, args) == memory.PAUSED
    assert "kept" in memory.run("list_memory", {})
    memory.reset_pause()
    assert memory.run("remember_fact", {"text": "after"}).startswith("Remembered")
    assert texts() == ["after", "kept"]


def test_view_lists_facts_then_reminders_and_filters_with_the_same_recall():
    memory.remember_fact("my sister Asha lives in Leeds")
    memory.remember_fact("Bob likes coffee")
    memory.add_reminder("call the dentist", "in 20 minutes")
    assert texts() == ["Bob likes coffee", "my sister Asha lives in Leeds", "call the dentist"]
    assert texts("sister") == ["my sister Asha lives in Leeds"]
    assert texts("dentist") == ["call the dentist"]
    assert texts("zzzzz") == []


def test_view_does_not_create_the_store():
    assert memory.view() == {"items": [], "undoable": 0}
    assert not memory.DB_PATH.exists()


def test_edit_fact_cleans_refuses_and_keeps_the_original_on_error():
    memory.remember_fact("first fact")
    memory.remember_fact("second fact")
    first, second = (i["id"] for i in sorted(memory.view()["items"], key=lambda i: i["text"]))
    assert memory.edit_fact(first, "  a  new\u200b  one (draft) ") == ""
    assert texts("draft") == ["a new one [draft]"]
    assert memory.edit_fact(first, "x" * 241) == "bad-text"
    assert memory.edit_fact(first, "   ") == "bad-text"
    assert memory.edit_fact(first, "my password is hunter2") == "secret"
    assert memory.edit_fact(first, "SECOND FACT") == "duplicate"
    assert memory.edit_fact(first, "a new one [draft]") == ""  # the same text on itself is not a duplicate
    assert memory.edit_fact(9999, "anything") == "not-found"
    assert "hunter2" not in " ".join(texts())


def test_edit_fact_cannot_touch_a_forgotten_fact_or_a_reminder():
    fact = the_fact()
    memory.add_reminder("call home", "in 20 minutes")
    reminder = next(i["id"] for i in memory.view()["items"] if i["kind"] == "reminder")
    assert memory.forget_item("fact", fact) == ""
    assert memory.edit_fact(fact, "back from the dead") == "not-found"
    assert texts() == ["call home"]
    assert memory.edit_fact(reminder + 1000, "x") == "not-found"


def test_forget_item_and_restore_use_the_same_24_hour_undo_window():
    memory.remember_fact("keep me")
    memory.add_reminder("call home", "in 20 minutes")
    fact, reminder = (next(i for i in memory.view()["items"] if i["kind"] == kind) for kind in ("fact", "reminder"))
    assert memory.forget_item("fact", fact["id"]) == ""
    assert memory.forget_item("fact", fact["id"]) == "not-found"  # already forgotten
    assert memory.forget_item("reminder", reminder["id"] + 100) == "not-found"
    assert memory.view()["undoable"] == 1
    assert [i["kind"] for i in memory.view()["items"]] == ["reminder"]
    assert memory.restore() == ""
    assert memory.view()["undoable"] == 0
    assert memory.restore() == "nothing-to-restore"
    assert memory.forget_item("reminder", reminder["id"]) == ""
    assert memory.restore() == ""
    assert {i["kind"] for i in memory.view()["items"]} == {"fact", "reminder"}


def test_restore_will_not_exceed_the_fact_cap():
    for i in range(memory.MAX_FACTS):
        memory.remember_fact(f"fact {i}")
    memory.forget_item("fact", memory.view()["items"][0]["id"])
    memory.remember_fact("replacement")
    assert memory.restore() == "full"


def test_the_owner_functions_are_not_reachable_as_model_tools():
    for name in ("edit_fact", "forget_item", "restore", "view", "set_paused", "reset_pause", "screen_edit"):
        assert name not in memory.NAMES and name not in memory._CALLS
        assert memory.run(name, {"text": "x"}) == memory.NO_TOOL
    assert not any(word in schema["function"]["name"] for schema in memory.TOOLS for word in ("edit", "pause"))


def test_screen_audit_lines_hold_only_time_operation_and_outcome():
    memory.remember_fact("my dentist is Dr Zebediah Quill")
    fact = memory.view()["items"][0]["id"]
    memory.edit_fact(fact, "my dentist is Dr Marlow")
    memory.edit_fact(fact, "my password is hunter2")
    memory.forget_item("fact", fact)
    memory.restore()
    memory.set_paused(True)
    memory.reset_pause()
    log = memory.AUDIT_LOG.read_text()
    parsed = [LINE.match(line) for line in log.splitlines()]
    assert all(parsed)
    assert [(m[1], m[2]) for m in parsed] == [
        ("screen_list", "ok"), ("screen_edit", "ok"), ("screen_edit", "error"), ("screen_forget", "ok"),
        ("screen_undo", "ok"), ("screen_pause", "ok")]
    for text in ("Zebediah", "Quill", "Marlow", "hunter2", "password", "dentist"):
        assert text not in log


# --- the messages on the voice socket -------------------------------------------

def session(adapter=None):
    client = make_client(adapter or ScriptedAdapter([]))
    return client, connect(client)


def ask(websocket, **message) -> dict:
    websocket.send_json(message)
    return websocket.receive_json()


def test_list_edit_forget_undo_and_pause_on_the_open_socket():
    fact = the_fact()
    memory.add_reminder("call home", "in 20 minutes")
    client, ws = session()
    with client, ws as websocket:
        authenticate(websocket)
        listed = ask(websocket, type="memory.list", query="")
        assert listed["type"] == "memory.items" and listed["enabled"] is True and listed["paused"] is False
        assert [(i["kind"], i["text"]) for i in listed["items"]] == [
            ("fact", "my sister Asha lives in Leeds"), ("reminder", "call home")]
        assert ask(websocket, type="memory.list", query="sister")["items"][0]["id"] == fact

        assert ask(websocket, type="memory.edit", id=fact, text="my sister Asha lives in York") == {
            "type": "memory.result", "op": "edit", "ok": True}
        assert texts("york") == ["my sister Asha lives in York"]

        assert ask(websocket, type="memory.forget", kind="fact", id=fact) == {
            "type": "memory.result", "op": "forget", "ok": True}
        after = ask(websocket, type="memory.list", query="")
        assert [i["kind"] for i in after["items"]] == ["reminder"] and after["undoable"] == 1

        assert ask(websocket, type="memory.undo") == {"type": "memory.result", "op": "undo", "ok": True}
        assert ask(websocket, type="memory.undo") == {
            "type": "memory.result", "op": "undo", "ok": False, "error": "nothing-to-restore"}

        assert ask(websocket, type="memory.pause", paused=True) == {"type": "memory.result", "op": "pause", "ok": True}
        assert memory.run("remember_fact", {"text": "x"}) == memory.PAUSED
        assert ask(websocket, type="memory.list", query="")["paused"] is True
        assert ask(websocket, type="memory.edit", id=fact, text="owner edits still work")["ok"] is True
        assert ask(websocket, type="memory.pause", paused=False)["ok"] is True
        assert memory.run("remember_fact", {"text": "after resume"}).startswith("Remembered")


def test_a_pause_does_not_outlive_the_session():
    client, ws = session()
    with client, ws as websocket:
        authenticate(websocket)
        ask(websocket, type="memory.pause", paused=True)
        assert memory.is_paused()
        websocket.send_json({"type": "session.stop"})
        assert websocket.receive_json() == {"type": "session.state", "state": "stopping"}
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()
    assert not memory.is_paused()


def test_unknown_ids_and_bad_text_are_refused_with_fixed_codes():
    fact = the_fact()
    client, ws = session()
    with client, ws as websocket:
        authenticate(websocket)
        assert ask(websocket, type="memory.edit", id=999, text="x")["error"] == "not-found"
        assert ask(websocket, type="memory.forget", kind="reminder", id=fact)["error"] == "not-found"
        assert ask(websocket, type="memory.edit", id=fact, text="y" * 300)["error"] == "bad-text"
        assert ask(websocket, type="memory.edit", id=fact, text="my password is hunter2")["error"] == "secret"
    assert texts() == ["my sister Asha lives in Leeds"]


@pytest.mark.parametrize("value", ["off", "", "maybe"])
def test_memory_off_refuses_every_message_and_the_list_says_so(monkeypatch, value):
    fact = the_fact()
    monkeypatch.setenv("SUPER_AGENT_MEMORY", value)
    client, ws = session()
    with client, ws as websocket:
        authenticate(websocket)
        assert ask(websocket, type="memory.list", query="") == {
            "type": "memory.items", "enabled": False, "paused": False, "undoable": 0, "items": []}
        for message in ({"type": "memory.edit", "id": fact, "text": "changed"},
                        {"type": "memory.forget", "kind": "fact", "id": fact}, {"type": "memory.undo"},
                        {"type": "memory.pause", "paused": True}):
            reply = ask(websocket, **message)
            assert reply == {"type": "memory.result", "op": message["type"].removeprefix("memory."),
                             "ok": False, "error": "memory-off"}
    assert not memory.is_paused()
    monkeypatch.setenv("SUPER_AGENT_MEMORY", "on")
    assert texts() == ["my sister Asha lives in Leeds"]


@pytest.mark.parametrize("message", [
    {"type": "memory.list"},
    {"type": "memory.list", "query": 5},
    {"type": "memory.list", "query": None},
    {"type": "memory.list", "query": "x" * 101},
    {"type": "memory.list", "query": "", "extra": 1},
    {"type": "memory.edit", "id": 1},
    {"type": "memory.edit", "text": "x"},
    {"type": "memory.edit", "id": "1", "text": "x"},
    {"type": "memory.edit", "id": 1.0, "text": "x"},
    {"type": "memory.edit", "id": True, "text": "x"},
    {"type": "memory.edit", "id": 0, "text": "x"},
    {"type": "memory.edit", "id": -1, "text": "x"},
    {"type": "memory.edit", "id": 2**31, "text": "x"},
    {"type": "memory.edit", "id": 1, "text": ""},
    {"type": "memory.edit", "id": 1, "text": 7},
    {"type": "memory.edit", "id": 1, "text": "x" * 1001},
    {"type": "memory.edit", "id": 1, "text": "x", "kind": "fact"},
    {"type": "memory.forget", "id": 1},
    {"type": "memory.forget", "kind": "other", "id": 1},
    {"type": "memory.forget", "kind": ["fact"], "id": 1},
    {"type": "memory.forget", "kind": "fact", "id": None},
    {"type": "memory.forget", "kind": "fact", "id": 1, "all": True},
    {"type": "memory.undo", "id": 1},
    {"type": "memory.pause"},
    {"type": "memory.pause", "paused": 1},
    {"type": "memory.pause", "paused": "true"},
    {"type": "memory.unknown"},
    {"type": "memory."},
    {"type": ["memory.list"], "query": ""},
])
def test_malformed_messages_fail_the_session_closed_and_change_nothing(message):
    the_fact()
    client, ws = session()
    with client, ws as websocket:
        authenticate(websocket)
        websocket.send_text(json.dumps(message))
        assert websocket.receive_json() == {"type": "session.error", "category": "invalid-control"}
    assert texts() == ["my sister Asha lives in Leeds"] and not memory.is_paused()


def test_an_oversized_message_fails_closed():
    client, ws = session()
    with client, ws as websocket:
        authenticate(websocket)
        websocket.send_text(json.dumps({"type": "memory.edit", "id": 1, "text": "x" * 70_000}))
        assert websocket.receive_json() == {"type": "session.error", "category": "invalid-control"}


@pytest.mark.parametrize("message", [
    {"type": "memory.edit", "id": 1, "text": "changed"},
    {"type": "memory.forget", "kind": "fact", "id": 1},
    {"type": "memory.undo"},
    {"type": "memory.pause", "paused": True},
    {"type": "memory.list", "query": ""},
])
def test_a_memory_message_before_authentication_is_refused_and_changes_nothing(message):
    the_fact()
    client = make_client(ScriptedAdapter([]))
    with client, connect(client) as websocket:
        websocket.send_json(message)
        with pytest.raises(WebSocketDisconnect) as refused:
            websocket.receive_json()
        assert refused.value.code == 1008
    assert texts() == ["my sister Asha lives in Leeds"] and not memory.is_paused()


def test_text_from_the_model_cannot_send_memory_messages():
    fact = the_fact()
    hostile = [json.dumps(m) for m in (
        {"type": "memory.forget", "kind": "fact", "id": fact}, {"type": "memory.edit", "id": fact, "text": "owned"},
        {"type": "memory.pause", "paused": True}, {"type": "memory.undo"})]
    events = [Transcript("assistant", text) for text in hostile] + [Transcript("user", hostile[0])]
    client, ws = session(ScriptedAdapter(events))
    with client, ws as websocket:
        authenticate(websocket)
        got = [websocket.receive_json() for _ in events]
        assert [m["type"] for m in got] == ["conversation.text"] * len(events)  # shown as text, nothing more
    assert texts() == ["my sister Asha lives in Leeds"] and not memory.is_paused()


def test_nothing_but_the_receive_loop_can_reach_the_screen_handlers():
    # Model output arrives through adapter events and tool calls; none of those modules may import the screen.
    for name in ("local_adapter.py", "gemini_adapter.py", "tier1.py", "actions.py", "recap.py", "weather.py", "tools.py", "adapter.py"):
        source = (SRC / name).read_text()
        for needle in ("memory_screen", "edit_fact", "forget_item", "set_paused", "memory.restore", "memory.view"):
            assert needle not in source, (name, needle)
    app_source = (SRC / "app.py").read_text()
    assert app_source.count("memory_screen.handle") == 1
    receive = app_source.split("async def _receive(", 1)[1].split("async def _forward(", 1)[0]
    assert "memory_screen.handle" in receive
