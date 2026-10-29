"""The methods a joined browser may call under `/web/api/<method>`.

A deliberately small subset of the agent API: no saving, no file paths, no opening files, no
sample or library operations. Every edit is journaled as `human-web` and must carry the
`base_revision` the page last read, so it conflicts with newer agent or window edits exactly
like an agent patch does.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Callable

from ..model import (
    EFFECT_DIGITS, NOTES, SIMPLE_COMMANDS, XM_KEY_OFF_NAME, XM_NOTES, Module, ValidationError, playback_plan,
)
from ..xm import XM_COMMANDS
from . import render as renderer

WEB_AUTHOR = "human-web"
WEB_OPS = ("set", "write", "clear", "move", "copy", "transpose")
MAX_WEB_OPS = 200
MAX_DIFF_CELLS = 200


@dataclasses.dataclass
class Binary:
    """A non-JSON answer (the rendered WAV)."""
    data: bytes
    content_type: str
    headers: dict


@dataclasses.dataclass
class Call:
    session: Any
    server: Any
    device: dict
    listener: str


def _params(params: dict, required: tuple = (), optional: tuple = ()) -> dict:
    unknown = set(params) - set(required) - set(optional)
    if unknown:
        raise ValidationError(f"Unknown parameters {sorted(unknown)}.", "LIVE_PARAMS")
    missing = [name for name in required if name not in params]
    if missing:
        raise ValidationError(f"Missing parameters {missing}.", "LIVE_PARAMS")
    return params


def _text(value: object, name: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError(f"{name}: text of at most {limit} characters expected.", "LIVE_PARAMS")
    return value


def profile(module: Module) -> dict:
    """What the page needs to draw and edit this module: grid shape and the cell vocabulary of its format.

    MOD: notes C-1..B-3, effects 0-7 9-F (E is extended), no volume column, up to 31 samples.
    XM: notes C-0..B-7 and key off (===), effects 0-9 A-H K L P R T X, a volume column, up to 128 instruments."""
    xm = module.format == "xm"
    commands = XM_COMMANDS if xm else SIMPLE_COMMANDS | {14}
    return {"format": module.format, "channels": module.channels,
            "notes": list(XM_NOTES if xm else NOTES), "key_off": XM_KEY_OFF_NAME if xm else None,
            "effects": [EFFECT_DIGITS[command] for command in sorted(commands)],
            "volume_column": xm, "sample_slots": len(module.samples),
            "sample_label": "instrument" if xm else "sample", "max_transpose": 95 if xm else 35}


def _header(c: Call) -> dict:
    snapshot = c.session.snapshot()
    plan = playback_plan(snapshot)
    first = plan["timeline"][0]
    return {"duration_seconds": plan["duration_seconds"], "bpm": first["bpm"], "speed": first["speed"],
            "format": snapshot.format, "channels": snapshot.channels}


def _status(c: Call, p: dict) -> dict:
    _params(p)
    context = c.session.context()
    path = context.pop("path", None)
    context.pop("last_change", None)
    return {**context, "file": os.path.basename(path) if path else None, **_header(c),
            "device": c.session.web.view(c.device), "lan": c.server.lan_enabled,
            "render": {"engine": renderer.engine_name(), "max_seconds": renderer.MAX_SECONDS,
                       "default_seconds": renderer.DEFAULT_SECONDS}}


def _hello(c: Call, p: dict) -> dict:
    _params(p)
    return {"api": 1, "author": WEB_AUTHOR, "csrf": c.device["csrf"], **_status(c, {})}


def _score(c: Call, p: dict) -> dict:
    result = c.session.score(**_params(p, (), ("pattern", "start", "rows")))
    for sample in result.get("samples", []):
        sample.pop("sha256", None)
        sample.pop("library_id", None)
    if "patterns" in result:  # the overview: shape of the grid (rows per pattern, channels) and the cell vocabulary
        module = c.session.snapshot()
        result["profile"] = profile(module)
        for item in result["patterns"]:
            item["rows"] = module.patterns[item["index"]].rows
    return result


def _changes(c: Call, p: dict) -> dict:
    result = c.session.changes(**_params(p, (), ("since",)))
    entries = []
    for entry in result["entries"]:
        diff = entry["diff"]
        entries.append({
            "revision": entry["revision"], "author": entry["author"], "label": entry["label"], "at": entry["at"],
            "kind": entry["kind"], "summary": entry["summary"][:3],
            "patterns": sorted({item["pattern"] for item in diff.get("cells", [])}),
            "structure": bool(entry.get("replaced") or set(diff) - {"cells"}),
            "own": entry["author"] == WEB_AUTHOR})
    out = {"revision": result["revision"], "since": result["since"], "entries": entries}
    if "gap" in result:
        out["gap"] = True
    return out


def _patch(c: Call, p: dict) -> dict:
    _params(p, ("ops", "base_revision"), ("label",))
    ops = p["ops"]
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_WEB_OPS:
        raise ValidationError(f"ops: a list of 1-{MAX_WEB_OPS} operations expected.", "LIVE_PARAMS")
    for index, op in enumerate(ops):
        if not isinstance(op, dict) or op.get("op") not in WEB_OPS:
            raise ValidationError(f"ops[{index}]: the browser may use {', '.join(WEB_OPS)}.", "LIVE_PARAMS")
    label = _text(p.get("label"), "label", 80)
    return c.session.apply_patch(ops, WEB_AUTHOR, label or "Edit in browser", p["base_revision"])


def _proposal(item: dict) -> dict:
    diff = item["diff"]
    cells = diff.get("cells", [])
    return {"id": item["id"], "author": item["author"], "label": item["label"], "at": item["at"],
            "status": item["status"], "stale": item.get("stale", False), "summary": item["summary"],
            "cells": cells[:MAX_DIFF_CELLS], "cells_total": diff.get("cells_total", len(cells)),
            "other": sorted(set(diff) - {"cells", "cells_total", "cells_truncated"})}


def _proposals(c: Call, p: dict) -> dict:
    _params(p)
    return {"proposals": [_proposal(item) for item in c.session.proposals()]}


def _accept(c: Call, p: dict) -> dict:
    _params(p, ("id",), ("force",))
    if "force" in p and type(p["force"]) is not bool:
        raise ValidationError("force: true or false expected.", "LIVE_PARAMS")
    result = c.session.accept(p["id"], WEB_AUTHOR, bool(p.get("force")))
    return {"changed": result["changed"], "revision": result["revision"], "summary": result["summary"]}


def _reject(c: Call, p: dict) -> dict:
    _params(p, ("id",), ("reason",))
    item = c.session.reject(p["id"], WEB_AUTHOR, _text(p.get("reason"), "reason", 200))
    return {"proposal": {"id": item["id"], "status": item["status"]}}


def _takes_view(c: Call) -> list[dict]:
    return [{"id": item["id"], "label": item["label"], "author": item["author"], "at": item["at"],
             "title": item["title"], "duration_seconds": item["duration_seconds"],
             "file": os.path.basename(item["path"])} for item in c.session.takes()]


def _takes(c: Call, p: dict) -> dict:
    _params(p)
    return {"takes": _takes_view(c)}


def _request(kind: str, names: tuple = ()) -> Callable[[Call, dict], dict]:
    def call(c: Call, p: dict) -> dict:
        return c.session.request(kind, _params(p, (), names))
    return call


def _comments(c: Call, p: dict) -> dict:
    return {"comments": c.session.comments(**_params(p, (), ("status",)))}


def _comment(c: Call, p: dict) -> dict:
    _params(p, ("text",), ("place",))
    return {"comment": c.session.add_comment(p["text"], p.get("place"), WEB_AUTHOR)}


def _reply(c: Call, p: dict) -> dict:
    _params(p, ("id", "text"))
    return {"comment": c.session.reply_comment(p["id"], p["text"], WEB_AUTHOR)}


def _resolve(c: Call, p: dict) -> dict:
    _params(p, ("id",), ("text", "reopen"))
    if "reopen" in p and type(p["reopen"]) is not bool:
        raise ValidationError("reopen: true or false expected.", "LIVE_PARAMS")
    return {"comment": c.session.resolve_comment(p["id"], WEB_AUTHOR, p.get("text"), bool(p.get("reopen")))}


def _render(c: Call, p: dict) -> Binary:
    _params(p, (), ("order", "row", "seconds", "audible", "proposal", "take"))
    if "proposal" in p and "take" in p:
        raise ValidationError("Give a proposal or a take, not both.", "LIVE_PARAMS")
    if "proposal" in p:
        module = c.session.proposal_preview(p["proposal"])
    elif "take" in p:
        module = c.session.take_module(p["take"])
    else:
        module = c.session.snapshot()
    audible = p.get("audible", c.session.context().get("audible"))
    if audible is not None and isinstance(audible, (list, tuple)) and len(audible) != module.channels and "audible" not in p:
        audible = None  # the window's mutes describe another file (or channel count): hear everything
    revision = c.session.revision
    slot = c.server.render_slot
    if not slot.acquire(blocking=False):
        raise ValidationError("Another section is still rendering; try again in a moment.", "LIVE_BUSY")
    try:
        data, info = renderer.render_wav(module, p.get("order", 0), p.get("row", 0),
                                         p.get("seconds", renderer.DEFAULT_SECONDS), audible)
    finally:
        slot.release()
    info["revision"] = revision
    return Binary(data, "audio/wav", {"X-ChipLoom-Render": _ascii_json(info)})


def _ascii_json(value: dict) -> str:
    import json
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _devices(c: Call, p: dict) -> dict:
    _params(p)
    return {"devices": [{**item, "current": item["id"] == c.device["id"]} for item in c.session.web_devices()]}


WEB_API: dict[str, Callable[[Call, dict], Any]] = {
    "hello": _hello, "status": _status, "score": _score, "changes": _changes, "patch": _patch,
    "proposals": _proposals, "accept": _accept, "reject": _reject, "takes": _takes,
    "play": _request("play", ("order",)), "stop": _request("stop"),
    "select": _request("select", ("pattern", "row", "rows", "channel", "channels")),
    "render": _render, "devices": _devices,
    "comments": _comments, "comment": _comment, "reply": _reply, "resolve": _resolve,
}
