"""Comments attached to a place in the score: the owner's (or an agent's) remarks on a block of cells.

A comment is plain data, stored in a project under `metadata.comments` and kept by the `Document`
outside its undo history (undoing a note never removes a comment). The live session adds, replies to,
resolves and reopens them; the window and the browser studio show them; `feedback` and agents read them.

    {"id": "c3", "author": "human", "text": "Track 5 drags here", "at": "2026-10-29T10:00:00Z",
     "place": {"pattern": 1, "row": 0, "rows": 32, "channel": 4, "channels": 1},   # or null: the whole song
     "cells": ["00 | C-5 0A 20 049", ...],    # the block as grid text when the comment was written
     "status": "open", "replies": [{"author": "agent", "text": "...", "at": "..."}],
     "resolved_by": null, "resolved_at": null}
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from .model import Module, ValidationError, require_int
from .patch import pattern_grid

TEXT_LIMIT = 1000
COMMENT_LIMIT = 300        # comments kept; the oldest resolved ones go first
REPLY_LIMIT = 50
CELL_ROWS = 32             # rows of grid text kept with a comment
STATUSES = ("open", "resolved")
_KEYS = {"id", "author", "text", "at", "place", "cells", "status", "replies", "resolved_by", "resolved_at"}
_PLACE_KEYS = ("pattern", "row", "rows", "channel", "channels")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def text(value: object, name: str = "text") -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > TEXT_LIMIT:
        raise ValidationError(f"{name}: a non-empty text of at most {TEXT_LIMIT} characters expected.", "COMMENT_INVALID")
    return value.strip()


def place(module: Module, value: object) -> dict | None:
    """A checked block `{pattern, row, rows, channel, channels}` of `module`, or None for the whole song."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - set(_PLACE_KEYS) or "pattern" not in value:
        raise ValidationError("place: an object with pattern and optional row, rows, channel, channels expected "
                              "(or null for the whole song).", "COMMENT_INVALID")
    pattern = require_int(value["pattern"], "pattern", 0, len(module.patterns) - 1, "COMMENT_INVALID")
    total = module.patterns[pattern].rows
    row = require_int(value.get("row", 0), "row", 0, total - 1, "COMMENT_INVALID")
    rows = require_int(value.get("rows", 1), "rows", 1, total - row, "COMMENT_INVALID")
    channel = require_int(value.get("channel", 0), "channel", 0, module.channels - 1, "COMMENT_INVALID")
    channels = require_int(value.get("channels", 1), "channels", 1, module.channels - channel, "COMMENT_INVALID")
    return {"pattern": pattern, "row": row, "rows": rows, "channel": channel, "channels": channels}


def cells(module: Module, where: dict | None) -> list[str]:
    """The block as grid text (`RR | cell | cell`), at most CELL_ROWS rows; empty for the whole song."""
    if where is None:
        return []
    lines = pattern_grid(module, where["pattern"], where["row"], min(where["rows"], CELL_ROWS))
    first, last = where["channel"], where["channel"] + where["channels"]
    result = []
    for line in lines:
        row, *parts = line.split(" | ")
        result.append(" | ".join([row, *parts[first:last]]))
    return result


def create(module: Module, existing: list[dict], body: object, where: object, author: str) -> dict:
    checked = place(module, where)
    number = 1 + max((int(item["id"][1:]) for item in existing if str(item.get("id", "")).startswith("c")
                      and str(item["id"])[1:].isdigit()), default=0)
    return {"id": f"c{number}", "author": author, "text": text(body), "at": now(), "place": checked,
            "cells": cells(module, checked), "status": "open", "replies": [], "resolved_by": None,
            "resolved_at": None}


def find(comments: list[dict], comment_id: object) -> dict:
    for item in comments:
        if item["id"] == comment_id:
            return item
    raise ValidationError(f"Unknown comment {comment_id!r}.", "COMMENT_UNKNOWN")


def reply(comment: dict, body: object, author: str) -> dict:
    if len(comment["replies"]) >= REPLY_LIMIT:
        raise ValidationError(f"A comment keeps at most {REPLY_LIMIT} replies.", "COMMENT_INVALID")
    entry = {"author": author, "text": text(body, "reply"), "at": now()}
    comment["replies"].append(entry)
    return entry


def set_status(comment: dict, status: str, author: str) -> None:
    comment["status"] = status
    comment["resolved_by"] = author if status == "resolved" else None
    comment["resolved_at"] = now() if status == "resolved" else None


def trim(comments: list[dict]) -> None:
    """Keep at most COMMENT_LIMIT comments, dropping the oldest resolved ones first."""
    while len(comments) > COMMENT_LIMIT:
        resolved = next((item for item in comments if item["status"] == "resolved"), None)
        comments.remove(resolved or comments[0])


def load(metadata: object) -> list[dict]:
    """Comments read from `metadata.comments`, checked loosely (a malformed list is refused with a code)."""
    raw = metadata.get("comments", []) if isinstance(metadata, dict) else []
    if not isinstance(raw, list):
        raise ValidationError("metadata.comments must be a list.", "COMMENT_INVALID")
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) - _KEYS or not {"id", "text", "status"} <= set(item) \
                or item["status"] not in STATUSES:
            raise ValidationError(f"metadata.comments[{index}]: expected a comment object (id, text, status open or "
                                  "resolved).", "COMMENT_INVALID")
        result.append({"author": "human", "at": None, "place": None, "cells": [], "replies": [], "resolved_by": None,
                       "resolved_at": None, **copy.deepcopy(item)})
    return result


def view(comment: dict) -> dict:
    return copy.deepcopy(comment)


def view_all(comments: list[dict]) -> list[dict]:
    return [view(item) for item in comments]


def label(comment: dict, action: str) -> str:
    where = comment["place"]
    spot = (f"pattern {where['pattern']}, rows {where['row']}-{where['row'] + where['rows'] - 1}, "
            f"channel{'s' if where['channels'] > 1 else ''} {where['channel']}"
            + (f"-{where['channel'] + where['channels'] - 1}" if where["channels"] > 1 else "")) if where else "song"
    words = {"created": "Comment", "replied": "Reply", "resolved": "Resolved", "reopened": "Reopened"}[action]
    snippet = comment["text"] if action in ("created", "resolved", "reopened") else comment["replies"][-1]["text"]
    return f"{words} ({spot}): {snippet[:60]}"
