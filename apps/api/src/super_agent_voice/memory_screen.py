"""The console's memory screen: typed messages from the browser socket to the owner's own store.

These come only from the browser: app.py's receive loop is the one caller, and adapter events
(model output, tool output, transcripts) never pass through here. Shapes are checked in code, an
unknown field or a wrong type is refused as a bad control (the session fails closed), and replies
hold stored text only for the browser, never the log (REQ-14).
"""
from __future__ import annotations

import asyncio

from . import memory
from .local_adapter import memory_enabled

MAX_QUERY, MAX_EDIT_TEXT = 100, 1000  # characters on the wire; the store then limits a fact to 240
_MAX_ID = 2**31

# One check per field, and every listed field is required: nothing else is accepted.
_SHAPES = {
    "memory.list": {"query": lambda v: isinstance(v, str) and len(v) <= MAX_QUERY},
    "memory.edit": {"id": lambda v: type(v) is int and 0 < v < _MAX_ID,
                    "text": lambda v: isinstance(v, str) and 0 < len(v) <= MAX_EDIT_TEXT},
    "memory.forget": {"kind": lambda v: v in ("fact", "reminder"),
                      "id": lambda v: type(v) is int and 0 < v < _MAX_ID},
    "memory.undo": {},
    "memory.pause": {"paused": lambda v: type(v) is bool},
}


async def handle(control: dict) -> dict | None:
    """The reply for one memory message, or None if the message is malformed."""
    kind = control.get("type")
    shape = _SHAPES.get(kind) if isinstance(kind, str) else None
    if shape is None or control.keys() != {"type", *shape} or not all(ok(control[name]) for name, ok in shape.items()):
        return None
    return await asyncio.to_thread(_apply, kind.removeprefix("memory."), control)


def _enabled() -> bool:
    try:
        return memory_enabled()
    except RuntimeError:  # a bad SUPER_AGENT_MEMORY value means off here as it does for the tools
        return False


def _apply(op: str, control: dict) -> dict:
    if not _enabled():
        if op == "list":
            return {"type": "memory.items", "enabled": False, "paused": False, "undoable": 0, "items": []}
        return {"type": "memory.result", "op": op, "ok": False, "error": "memory-off"}
    if op == "list":
        try:
            return {"type": "memory.items", "enabled": True, "paused": memory.is_paused(), **memory.view(control["query"])}
        except Exception:  # never the exception text, which could hold stored content
            return {"type": "memory.result", "op": op, "ok": False, "error": "failed"}
    if op == "pause":
        memory.set_paused(control["paused"])
        error = ""
    elif op == "edit":
        error = memory.edit_fact(control["id"], control["text"])
    elif op == "forget":
        error = memory.forget_item(control["kind"], control["id"])
    else:
        error = memory.restore()
    return {"type": "memory.result", "op": op, "ok": not error, **({"error": error} if error else {})}
