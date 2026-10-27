"""Live co-composition: a session around a `Document`, a loopback JSON server and a client.

Everything here is standard library only (no Qt, no agent provider). The desktop window
embeds a `LiveSession` and a `LiveServer`; an agent talks to the server through
`LiveClient` (or `chiploom live ...`). Headless, `chiploom live serve SOURCE` hosts the
same session without a window.

The session keeps a journal of who changed what (`human` edits made in the window, agent
patches), detects overlapping edits through `base_revision`, offers proposals the owner
reviews, lists takes (saved versions) and relays UI requests (play, stop, open, select).
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import hashlib
import hmac
import http.server
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import mod, project
from .document import Document
from .errors import error_payload
from .model import Module, Pattern, ValidationError, playback_plan, require_int, validate
from .patch import apply_ops, cell_text, diff_modules, pattern_grid, summarize, touched

API_VERSION = 1
MAX_BODY = 2 * 1024 * 1024
JOURNAL_LIMIT = 500
CELL_LIMIT = 1000          # cells kept in a journal diff; the full key set is always kept privately
CLOSED_PROPOSAL_LIMIT = 50
TAKE_LIMIT = 100
AUTHOR = re.compile(r"^[A-Za-z0-9_.\- ]{1,32}$")
CONTEXT_KEYS = {"path", "order", "pattern", "row", "channel", "selection", "playing",
                "position_seconds", "dirty", "language"}
REQUEST_KINDS = {"play", "stop", "open", "select", "seek"}
NEEDS_WINDOW = {"play", "stop", "seek"}


class LiveConflict(ValidationError):
    """A patch overlaps edits made by someone else since its `base_revision`."""

    def __init__(self, message: str, conflicts: list[dict], revision: int | None = None):
        super().__init__(message, "LIVE_CONFLICT")
        self.conflicts = conflicts
        self.revision = revision


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clone_module(module: Module) -> Module:
    """Cheap independent copy: PCM tuples are immutable and shared, cells are frozen."""
    return Module(module.title,
                  [dataclasses.replace(sample, recipe=copy.deepcopy(sample.recipe)) for sample in module.samples],
                  [Pattern(pattern.name, dict(pattern.cells)) for pattern in module.patterns],
                  list(module.orders), copy.deepcopy(module.metadata))


def _author(value: object) -> str:
    if not isinstance(value, str) or not AUTHOR.match(value):
        raise ValidationError("author: 1-32 characters among letters, digits, space, '_', '.', '-'.", "LIVE_AUTHOR")
    return value.strip() or "agent"


def _label(value: object, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip() or len(value) > 80:
        raise ValidationError("label: text of 1-80 characters expected.", "LIVE_LABEL")
    return value.strip()


def _empty(diff: dict) -> bool:
    return not diff.get("cells") and len(diff) == 1


def _trim(diff: dict) -> dict:
    cells = diff.get("cells", [])
    if len(cells) <= CELL_LIMIT:
        return diff
    return {**diff, "cells": cells[:CELL_LIMIT], "cells_total": len(cells), "cells_truncated": True}


def _split_ops(ops: object, base_revision: int | None, label: str | None) -> tuple[Any, int | None, str | None]:
    """Accept `{"ops": [...], "base_revision": N, "label": "..."}` as well as a bare list."""
    if isinstance(ops, dict) and "ops" in ops and set(ops) <= {"ops", "base_revision", "label"}:
        return ops["ops"], ops.get("base_revision") if base_revision is None else base_revision, \
            ops.get("label") if label is None else label
    return ops, base_revision, label


def _public(item: dict) -> dict:
    return {key: value for key, value in item.items() if not key.startswith("_")}


def _dry_run(module: Module, ops: object) -> tuple[Module, list[dict], dict]:
    """Apply `ops` to a copy exactly as `Document.apply` would validate them."""
    candidate = clone_module(module)
    results = apply_ops(candidate, ops)
    validate(candidate)
    playback_plan(candidate)
    return candidate, results, diff_modules(module, candidate)


def _sample_digest(sample) -> str:
    return hashlib.sha256(bytes(value & 255 for value in sample.pcm)).hexdigest()


def _guarded(method):
    """Run a public method through the session dispatcher, under the session lock."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if getattr(self._local, "inside", False):
            return method(self, *args, **kwargs)

        def run():
            self._local.inside = True
            try:
                with self._lock:
                    return method(self, *args, **kwargs)
            finally:
                self._local.inside = False

        return self._dispatcher(run)
    return wrapper


class LiveSession:
    """The shared state of one open document: journal, context, proposals, takes, UI requests.

    `dispatcher(fn)` must run `fn()` and return its result. The desktop passes a dispatcher
    that executes `fn` on the Qt GUI thread (and runs it inline when already on that thread,
    otherwise a GUI-thread call would wait for itself). The default runs `fn` in the caller's
    thread; an internal re-entrant lock always serializes sessions calls.

    `on_event(kind, payload)` receives: "change" (journal entry), "proposal"
    ({"action", "proposal"}), "take", "request" ({"kind","payload","handled"}), "reset",
    "saved". It runs inside the dispatcher; exceptions it raises are ignored.
    """

    def __init__(self, document: Document, *, dispatcher: Callable[[Callable[[], Any]], Any] | None = None,
                 on_event: Callable[[str, dict], None] | None = None):
        self._dispatcher = dispatcher or (lambda fn: fn())
        self._listeners: list[Callable[[str, dict], None]] = [on_event] if on_event else []
        self._lock = threading.RLock()
        self._local = threading.local()
        self.document = document
        self._snapshot = clone_module(document.module)
        self._seen = document.revision
        self._revision = 0
        self._journal: list[dict] = []
        self._context: dict[str, Any] = {}
        self._proposals: list[dict] = []
        self._proposal_counter = 0
        self._takes: list[dict] = []
        self._take_counter = 0
        self._handlers: dict[str, Callable[[dict], Any]] = {}

    # --- plumbing ---------------------------------------------------------------------

    @property
    def revision(self) -> int:
        """Journal revision: grows by one for every journaled change (not `Document.revision`)."""
        return self._revision

    def add_listener(self, listener: Callable[[str, dict], None]) -> None:
        self._listeners.append(listener)

    def _emit(self, kind: str, payload: dict) -> None:
        for listener in list(self._listeners):
            try:
                listener(kind, payload)
            except Exception:  # a broken UI callback must never break an edit
                pass

    def _record(self, author: str, label: str, diff: dict, kind: str, extra: dict | None = None,
                replaced: bool = False) -> dict:
        self._revision += 1
        entry = {"revision": self._revision, "author": author, "label": label, "at": now(), "kind": kind,
                 "diff": _trim(diff), "summary": summarize(diff), **(extra or {}),
                 "_keys": {("document",)} if replaced else touched(diff)}
        if replaced:
            entry["replaced"] = True
        self._journal.append(entry)
        del self._journal[:-JOURNAL_LIMIT]
        return entry

    def _oldest(self) -> int:
        return self._journal[0]["revision"] if self._journal else self._revision + 1

    def _absorb(self) -> None:
        """Journal direct `Document` edits nobody reported with `sync()`."""
        if self.document.revision != self._seen:
            self._sync("human", "Edit")

    def _sync(self, author: str, label: str) -> dict | None:
        diff = diff_modules(self._snapshot, self.document.module)
        self._seen = self.document.revision
        if _empty(diff):
            self._snapshot = clone_module(self.document.module)
            return None
        entry = self._record(author, label, diff, "edit")
        self._snapshot = clone_module(self.document.module)
        self._emit("change", _public(entry))
        return _public(entry)

    # --- journal ----------------------------------------------------------------------

    @_guarded
    def sync(self, author: str = "human", label: str = "Edit") -> dict | None:
        """Call after any direct `Document` edit, undo or redo. Returns the journal entry or None."""
        return self._sync(_author(author), _label(label, "Edit"))

    @_guarded
    def reset(self, document: Document, author: str = "human", label: str | None = None) -> dict | None:
        """The window opened or reloaded a file. Same path: journal the net diff as a "reload".
        Another file: journal an "open" that conflicts with every older `base_revision`."""
        author = _author(author)
        old, previous = self.document, self._snapshot
        same = old.path is not None and document.path is not None and old.path == document.path
        self.document = document
        self._seen = document.revision
        if same:
            diff = diff_modules(previous, document.module)
            entry = None if _empty(diff) else self._record(author, _label(label, "Reload"), diff, "reload")
        else:
            entry = self._record(author, _label(label, "Open"), {"cells": []}, "open", replaced=True,
                                 extra={"path": str(document.path) if document.path else None,
                                        "title": document.module.title})
            for proposal in self._proposals:
                if proposal["status"] == "pending":
                    self._close(proposal, "withdrawn", author, "the document was replaced")
        self._snapshot = clone_module(document.module)
        self._emit("reset", {"revision": self._revision, "same_path": same,
                             "path": str(document.path) if document.path else None,
                             "title": document.module.title})
        if entry:
            self._emit("change", _public(entry))
        return _public(entry) if entry else None

    @_guarded
    def changes(self, since: int = 0, author: str | None = None) -> dict:
        self._absorb()
        require_int(since, "since", 0, 2 ** 31)
        entries = [_public(entry) for entry in self._journal
                   if entry["revision"] > since and (author is None or entry["author"] == author)]
        summary = {"human": {"entries": 0, "cells": 0, "lines": []},
                   "agent": {"entries": 0, "cells": 0, "lines": [], "authors": []}}
        for entry in entries:
            group = summary["human" if entry["author"] == "human" else "agent"]
            group["entries"] += 1
            group["cells"] += entry["diff"].get("cells_total", len(entry["diff"].get("cells", [])))
            if len(group["lines"]) < 12:
                group["lines"].extend(f"r{entry['revision']} {entry['label']}: {line}" for line in entry["summary"][:3])
            if group is summary["agent"] and entry["author"] not in group["authors"]:
                group["authors"].append(entry["author"])
        result = {"revision": self._revision, "since": since, "entries": entries, "summary": summary}
        if since + 1 < self._oldest() and since < self._revision:
            result["gap"] = f"The journal only keeps revisions from {self._oldest()}; earlier changes are not listed."
        return result

    def _check_conflicts(self, author: str, base: object, keys: set, diff: dict) -> None:
        if type(base) is not int or not 0 <= base <= self._revision:
            raise ValidationError(f"base_revision: integer between 0 and {self._revision} expected.", "LIVE_BASE")
        if base == self._revision:
            return
        if base + 1 < self._oldest():
            raise LiveConflict("The journal no longer covers base_revision; read the score again and resubmit.",
                               [{"unit": "history", "oldest_revision": self._oldest()}], self._revision)
        later = [entry for entry in self._journal if entry["revision"] > base and entry["author"] != author]
        module, conflicts = self.document.module, []
        for entry in later:
            if ("document",) in entry["_keys"]:
                conflicts.append({"unit": "document", "author": entry["author"], "revision": entry["revision"],
                                  "label": entry["label"], "message": "Another file was opened in the window."})
        if conflicts:
            raise LiveConflict("A different file was opened since base_revision; read the score again.",
                               conflicts, self._revision)
        after = {(c["pattern"], c["row"], c["channel"]): c["after"] for c in diff.get("cells", [])}
        for key in sorted(keys, key=repr):
            owner = next((entry for entry in reversed(later) if key in entry["_keys"]), None)
            if owner is None:
                continue
            item = {"unit": key[0], "author": owner["author"], "revision": owner["revision"], "label": owner["label"]}
            if key[0] == "cell":
                _, pattern, row, channel = key
                item.update(pattern=pattern, row=row, channel=channel,
                            current=cell_text(module.patterns[pattern].get(row, channel))
                            if pattern < len(module.patterns) else None,
                            yours=after.get((pattern, row, channel)))
            elif key[0] == "structure":
                item.update(current={"orders": list(module.orders), "patterns": len(module.patterns)})
            elif key[0] == "sample":
                sample = module.samples[key[1] - 1] if key[1] <= len(module.samples) else None
                item.update(slot=key[1], current=sample and {"name": sample.name, "volume": sample.volume,
                                                              "finetune": sample.finetune})
            elif key[0] == "pattern_name":
                item.update(pattern=key[1], current=module.patterns[key[1]].name if key[1] < len(module.patterns) else None)
            elif key[0] == "title":
                item.update(current=module.title)
            conflicts.append(item)
        if conflicts:
            who = sorted({item["author"] for item in conflicts})
            raise LiveConflict(f"{len(conflicts)} unit(s) were changed by {', '.join(who)} since revision {base}; "
                               "read the changes, adapt the patch and resubmit with the new revision.",
                               conflicts, self._revision)

    def _apply(self, ops: object, author: str, label: str, base_revision: int | None, kind: str,
               extra: dict | None = None) -> dict:
        self._absorb()
        _, _, diff = _dry_run(self.document.module, ops)
        if _empty(diff):
            return {"changed": False, "results": [], "revision": self._revision,
                    "document_revision": self.document.revision, "diff": diff, "summary": []}
        if base_revision is not None:
            self._check_conflicts(author, base_revision, touched(diff), diff)
        outcome = self.document.patch(ops, label)
        self._seen = self.document.revision
        entry = self._record(author, label, outcome["diff"], kind, extra)
        self._snapshot = clone_module(self.document.module)
        self._emit("change", _public(entry))
        return {"changed": outcome["changed"], "results": outcome["results"], "revision": self._revision,
                "document_revision": self.document.revision, "diff": entry["diff"], "summary": entry["summary"]}

    @_guarded
    def apply_patch(self, ops: object, author: str = "agent", label: str | None = None,
                    base_revision: int | None = None) -> dict:
        """Apply patch operations as one undoable transaction.

        With `base_revision` (the `revision` you last read), a patch that touches a unit another
        author changed afterwards raises `LiveConflict` and nothing is applied.
        """
        ops, base_revision, label = _split_ops(ops, base_revision, label)
        return self._apply(ops, _author(author), _label(label, "Patch"), base_revision, "patch")

    # --- context and score --------------------------------------------------------------

    @_guarded
    def update_context(self, **values) -> None:
        """The window reports its state: path, order, pattern, row, channel, selection, playing,
        position_seconds, dirty, language. `None` removes a key."""
        unknown = set(values) - CONTEXT_KEYS
        if unknown:
            raise ValidationError(f"Unknown context keys {sorted(unknown)}; use {sorted(CONTEXT_KEYS)}.", "LIVE_CONTEXT")
        for key, value in values.items():
            if value is None:
                self._context.pop(key, None)
            else:
                self._context[key] = value

    @_guarded
    def context(self) -> dict:
        self._absorb()
        module, document = self.document.module, self.document
        last = self._journal[-1] if self._journal else None
        result = {**self._context,
                  "path": str(document.path) if document.path else self._context.get("path"),
                  "title": module.title, "revision": self._revision, "document_revision": document.revision,
                  "dirty": self._context["dirty"] if "dirty" in self._context else document.dirty,
                  "orders": list(module.orders), "pattern_count": len(module.patterns),
                  "pending_proposals": sum(item["status"] == "pending" for item in self._proposals),
                  "takes": len(self._takes), "window": bool(self._handlers),
                  "last_change": last and {"revision": last["revision"], "author": last["author"],
                                           "label": last["label"], "at": last["at"]}}
        return result

    @_guarded
    def score(self, pattern: int | None = None, start: int = 0, rows: int = 64) -> dict:
        """One pattern as grid lines, or an overview (orders, patterns, samples) when `pattern` is None."""
        self._absorb()
        module = self.document.module
        if pattern is not None:
            lines = pattern_grid(module, pattern, start, rows if start + rows <= 64 else 64 - start)
            return {"revision": self._revision, "pattern": pattern, "name": module.patterns[pattern].name,
                    "start": start, "rows": len(lines),
                    "used_in_orders": [i for i, value in enumerate(module.orders) if value == pattern],
                    "header": "ROW | channel 1 | channel 2 | channel 3 | channel 4 (cells: NOTE SS EEE)",
                    "lines": lines}
        sources = module.metadata.get("sample_sources", {}) if isinstance(module.metadata, dict) else {}
        samples = []
        for slot, sample in enumerate(module.samples, 1):
            if sample.pcm or sample.name:
                source = sources.get(str(slot)) if isinstance(sources, dict) else None
                samples.append({"slot": slot, "name": sample.name, "volume": sample.volume,
                                "finetune": sample.finetune, "length": len(sample.pcm),
                                "loop_start": sample.loop_start, "loop_length": sample.loop_length,
                                "sha256": _sample_digest(sample) if sample.pcm else None,
                                "library_id": source.get("library_id") if isinstance(source, dict) else None})
        plan = playback_plan(module)
        return {"revision": self._revision, "title": module.title, "orders": list(module.orders),
                "duration_seconds": plan["duration_seconds"],
                "patterns": [{"index": index, "name": item.name, "cells": len(item.cells),
                              "used_in_orders": [i for i, value in enumerate(module.orders) if value == index]}
                             for index, item in enumerate(module.patterns)],
                "samples": samples}

    # --- proposals ----------------------------------------------------------------------

    def _proposal_view(self, proposal: dict) -> dict:
        view = _public(proposal)
        if proposal["status"] == "pending":
            others = [entry for entry in self._journal
                      if entry["revision"] > proposal["base_revision"] and entry["author"] != proposal["author"]]
            overlap = proposal["_keys"] & set().union(*(entry["_keys"] for entry in others)) if others else set()
            view["stale"] = bool(overlap)
        return view

    def _find(self, proposal_id: object, pending: bool = True) -> dict:
        for proposal in self._proposals:
            if proposal["id"] == proposal_id:
                if pending and proposal["status"] != "pending":
                    raise ValidationError(f"Proposal {proposal_id} is already {proposal['status']}.", "LIVE_PROPOSAL")
                return proposal
        raise ValidationError(f"Unknown proposal {proposal_id!r}.", "LIVE_PROPOSAL")

    def _close(self, proposal: dict, status: str, by: str, reason: str | None = None) -> None:
        proposal.update(status=status, closed_by=by, closed_at=now(), reason=reason)
        closed = [item for item in self._proposals if item["status"] != "pending"]
        for item in closed[:-CLOSED_PROPOSAL_LIMIT]:
            self._proposals.remove(item)

    @_guarded
    def propose(self, ops: object, author: str = "agent", label: str | None = None) -> dict:
        """Store a validated patch for the owner to preview, accept or reject. Nothing changes yet."""
        ops, _, label = _split_ops(ops, None, label)
        author, label = _author(author), _label(label, "Proposal")
        self._absorb()
        _, _, diff = _dry_run(self.document.module, ops)
        if _empty(diff):
            raise ValidationError("The proposal would not change anything.", "LIVE_PROPOSAL")
        self._proposal_counter += 1
        proposal = {"id": f"p{self._proposal_counter}", "author": author, "label": label, "at": now(),
                    "status": "pending", "base_revision": self._revision, "ops": copy.deepcopy(ops),
                    "diff": _trim(diff), "summary": summarize(diff), "_keys": touched(diff)}
        self._proposals.append(proposal)
        view = self._proposal_view(proposal)
        self._emit("proposal", {"action": "created", "proposal": view})
        return view

    @_guarded
    def proposals(self, status: str | None = "pending") -> list[dict]:
        """Proposals with the given status ("pending" by default; None or "all" for every one kept)."""
        self._absorb()
        return [self._proposal_view(item) for item in self._proposals
                if status in (None, "all") or item["status"] == status]

    @_guarded
    def proposal_preview(self, proposal_id: str) -> Module:
        """A copy of the current module with the proposal applied, for an overlay or an audition."""
        self._absorb()
        proposal = self._find(proposal_id)
        return _dry_run(self.document.module, proposal["ops"])[0]

    @_guarded
    def accept(self, proposal_id: str, author: str = "human", force: bool = False) -> dict:
        """Apply a pending proposal. The change is journaled as the proposer's work (kind
        "accept", with `accepted_by` and `proposal`), so conflicts are judged against every other
        author since the proposal's base revision. `force=True` skips that check (overwrite)."""
        author = _author(author)
        self._absorb()
        proposal = self._find(proposal_id)
        result = self._apply(proposal["ops"], proposal["author"], proposal["label"],
                             None if force else proposal["base_revision"], "accept",
                             {"proposal": proposal["id"], "accepted_by": author})
        self._close(proposal, "accepted", author)
        view = self._proposal_view(proposal)
        self._emit("proposal", {"action": "accepted", "proposal": view})
        return {**result, "proposal": view}

    @_guarded
    def reject(self, proposal_id: str, author: str = "human", reason: str | None = None) -> dict:
        proposal = self._find(proposal_id)
        self._close(proposal, "rejected", _author(author), reason if isinstance(reason, str) else None)
        view = self._proposal_view(proposal)
        self._emit("proposal", {"action": "rejected", "proposal": view})
        return view

    @_guarded
    def withdraw(self, proposal_id: str, author: str = "agent") -> dict:
        proposal = self._find(proposal_id)
        self._close(proposal, "withdrawn", _author(author))
        view = self._proposal_view(proposal)
        self._emit("proposal", {"action": "withdrawn", "proposal": view})
        return view

    # --- takes --------------------------------------------------------------------------

    @_guarded
    def add_take(self, path: str | Path, label: str | None = None, author: str = "agent") -> dict:
        """Register a saved version (project .json or .mod) for the owner to open and compare."""
        file = Path(path).expanduser().resolve()
        if file.suffix.lower() not in (".json", ".mod") or not file.is_file():
            raise ValidationError("A take is an existing .json project or .mod file.", "LIVE_TAKE")
        module = project.load(file) if file.suffix.lower() == ".json" else mod.read(file)
        data = file.read_bytes()
        self._take_counter += 1
        take = {"id": f"t{self._take_counter}", "path": str(file), "label": _label(label, file.stem),
                "author": _author(author), "at": now(), "title": module.title,
                "duration_seconds": playback_plan(module)["duration_seconds"],
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        self._takes.append(take)
        del self._takes[:-TAKE_LIMIT]
        self._emit("take", dict(take))
        return dict(take)

    @_guarded
    def takes(self) -> list[dict]:
        return [dict(take) for take in self._takes]

    @_guarded
    def request_open(self, take: str | None = None, path: str | Path | None = None) -> dict:
        """Ask the window to open a take (by id) or a file. Headless: `{"handled": False}`."""
        if (take is None) == (path is None):
            raise ValidationError("Give exactly one of a take id or a path.", "LIVE_OPEN")
        if take is not None:
            found = next((item for item in self._takes if item["id"] == take), None)
            if found is None:
                raise ValidationError(f"Unknown take {take!r}.", "LIVE_TAKE")
            payload = {"path": found["path"], "take": found["id"], "label": found["label"]}
        else:
            file = Path(path).expanduser().resolve()
            if file.suffix.lower() not in (".json", ".mod") or not file.is_file():
                raise ValidationError("Open an existing .json project or .mod file.", "LIVE_OPEN")
            payload = {"path": str(file), "take": None, "label": file.stem}
        return self.request("open", payload)

    # --- window requests ----------------------------------------------------------------

    @_guarded
    def set_handler(self, kind: str, handler: Callable[[dict], Any] | None) -> None:
        """The window registers what it can do: "play", "stop", "open", "select", "seek".
        `handler(payload)` runs inside the dispatcher (GUI thread) and may return a dict."""
        if kind not in REQUEST_KINDS:
            raise ValidationError(f"Unknown request kind {kind!r}; use {sorted(REQUEST_KINDS)}.", "LIVE_REQUEST")
        if handler is None:
            self._handlers.pop(kind, None)
        else:
            self._handlers[kind] = handler

    def _check_request(self, kind: str, payload: dict) -> dict:
        module = self.document.module
        if kind == "play" and "order" in payload:
            require_int(payload["order"], "order", 0, len(module.orders) - 1)
        elif kind == "seek":
            seconds = payload.get("seconds")
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                raise ValidationError("seconds: a number >= 0 expected.", "LIVE_REQUEST")
        elif kind == "select":
            pattern = require_int(payload.get("pattern", 0), "pattern", 0, len(module.patterns) - 1)
            row = require_int(payload.get("row", 0), "row", 0, 63)
            channel = require_int(payload.get("channel", 0), "channel", 0, 3)
            require_int(payload.get("rows", 1), "rows", 1, 64 - row)
            require_int(payload.get("channels", 1), "channels", 1, 4 - channel)
            payload = {"pattern": pattern, "row": row, "channel": channel, "rows": payload.get("rows", 1),
                       "channels": payload.get("channels", 1)}
        return payload

    @_guarded
    def request(self, kind: str, payload: dict | None = None) -> dict:
        """Ask the window to do something. With no registered handler: play/stop/seek raise
        `LIVE_NO_WINDOW`, select only records the selection in the context, open returns
        `{"handled": False}`."""
        if kind not in REQUEST_KINDS:
            raise ValidationError(f"Unknown request kind {kind!r}; use {sorted(REQUEST_KINDS)}.", "LIVE_REQUEST")
        payload = self._check_request(kind, dict(payload or {}))
        handler = self._handlers.get(kind)
        self._emit("request", {"kind": kind, "payload": payload, "handled": handler is not None})
        if handler is None:
            if kind in NEEDS_WINDOW:
                raise ValidationError(f"No ChipLoom window is attached to this session, so '{kind}' cannot run. "
                                      "Open the window (chiploom gui) to listen.", "LIVE_NO_WINDOW")
            if kind == "select":
                self._context["selection"] = dict(payload)
            return {"handled": False}
        outcome = handler(payload)
        return {"handled": True, **(outcome if isinstance(outcome, dict) else {})}

    # --- saving -------------------------------------------------------------------------

    @_guarded
    def save(self, path: str | Path | None = None) -> dict:
        """Save the project JSON through the document (atomic). Defaults to the document's own .json.

        Another path writes a copy: the session (and the owner's window) keeps its own file.
        """
        own = self.document.path
        target = Path(path).expanduser().resolve() if path is not None else own
        if target is None or target.suffix.lower() != ".json":
            raise ValidationError("Give a .json path to save the project (a .mod source cannot be overwritten).",
                                  "LIVE_SAVE_PATH")
        self._absorb()
        if own is not None and target == own:
            self.document.save_project(target)
            self._emit("saved", {"path": str(target)})
            return {"path": str(target), "copy": False, "dirty": self.document.dirty, "revision": self._revision}
        project.write_json(target, project.to_dict(self.document.module))
        return {"path": str(target), "copy": True, "session_path": str(own) if own else None,
                "dirty": self.document.dirty, "revision": self._revision}


# --- discovery --------------------------------------------------------------------------

def live_home() -> Path:
    override = os.environ.get("CHIPLOOM_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ChipLoom"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "chiploom"


def pid_alive(pid: int) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _reachable(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        with socket.create_connection((parsed.hostname, parsed.port), timeout=0.3):
            return True
    except (OSError, ValueError):
        return False


def discover(home: Path | None = None) -> list[dict]:
    """Live sessions of this user, newest first. Entries of dead processes are removed."""
    directory = (Path(home) if home else live_home()) / "live"
    found = []
    for file in directory.glob("*.json") if directory.is_dir() else []:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not all(key in data for key in ("pid", "url", "token")):
                raise ValueError("incomplete")
            alive = pid_alive(data["pid"]) and _reachable(data["url"])
        except (OSError, ValueError, TypeError):
            alive = False
            data = None
        if not alive:
            try:
                file.unlink()
            except OSError:
                pass
            continue
        found.append(data)
    found.sort(key=lambda item: str(item.get("started", "")), reverse=True)
    return found


# --- server -----------------------------------------------------------------------------

def _params(params: dict, required: tuple = (), optional: tuple = ()) -> dict:
    unknown = set(params) - set(required) - set(optional)
    if unknown:
        raise ValidationError(f"Unknown parameters {sorted(unknown)}.", "LIVE_PARAMS")
    missing = [name for name in required if name not in params]
    if missing:
        raise ValidationError(f"Missing parameters {missing}.", "LIVE_PARAMS")
    return params


def _agent_author(params: dict) -> str:
    author = _author(params.get("author", "agent"))
    if author.lower() == "human":
        raise ValidationError("The author 'human' is reserved for edits made in the window.", "LIVE_AUTHOR")
    return author


def _api_patch(session: LiveSession, params: dict) -> dict:
    _params(params, ("ops",), ("base_revision", "label", "author", "propose"))
    author = _agent_author(params)
    if params.get("propose"):
        if params.get("base_revision") is not None:
            raise ValidationError("A proposal is judged against the revision it is accepted from; "
                                  "omit base_revision.", "LIVE_PARAMS")
        return {"proposal": session.propose(params["ops"], author, params.get("label"))}
    return session.apply_patch(params["ops"], author, params.get("label"), params.get("base_revision"))


def _api_request(kind: str, names: tuple = ()) -> Callable[[LiveSession, dict], dict]:
    def call(session: LiveSession, params: dict) -> dict:
        _params(params, (), names)
        return session.request(kind, params)
    return call


API: dict[str, Callable[[LiveSession, dict], dict]] = {
    "ping": lambda s, p: {"api": API_VERSION, "pid": os.getpid(), "revision": s.revision} if _params(p) == {} else {},
    "status": lambda s, p: s.context() if _params(p) == {} else {},
    "score": lambda s, p: s.score(**_params(p, (), ("pattern", "start", "rows"))),
    "patch": _api_patch,
    "changes": lambda s, p: s.changes(**_params(p, (), ("since", "author"))),
    "proposals": lambda s, p: {"proposals": s.proposals(**_params(p, (), ("status",)))},
    "withdraw": lambda s, p: {"proposal": s.withdraw(_params(p, ("id",), ("author",))["id"], _agent_author(p))},
    "take": lambda s, p: {"take": s.add_take(_params(p, ("path",), ("label", "author"))["path"],
                                              p.get("label"), _agent_author(p))},
    "takes": lambda s, p: {"takes": s.takes()} if _params(p) == {} else {},
    "open": lambda s, p: s.request_open(**_params(p, (), ("take", "path"))),
    "play": _api_request("play", ("order",)),
    "stop": _api_request("stop"),
    "seek": _api_request("seek", ("seconds",)),
    "select": _api_request("select", ("pattern", "row", "rows", "channel", "channels")),
    "save": lambda s, p: s.save(**_params(p, (), ("path",))),
}
HTTP_STATUS = {"LIVE_AUTH": 401, "LIVE_CONFLICT": 409, "LIVE_NO_WINDOW": 503, "LIVE_UNKNOWN_METHOD": 404,
               "LIVE_TOO_LARGE": 413, "LIVE_BAD_REQUEST": 400, "LIVE_METHOD": 405, "LIVE_FORBIDDEN": 403}
DRAIN_LIMIT = 64 * 1024 * 1024


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ChipLoomLive/1"
    protocol_version = "HTTP/1.0"
    timeout = 30

    def log_message(self, *args):  # nothing on stderr
        pass

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, status: int, code: str, message: str, **extra) -> None:
        self._send(status, {"ok": False, "error": "ValidationError", "code": code, "message": message, **extra})

    def _drain(self, length: int) -> None:
        remaining = min(length, DRAIN_LIMIT)
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass

    def _reject_verb(self) -> None:
        self._fail(405, "LIVE_METHOD", "Use POST /v1/<method> with a JSON body.")

    do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = _reject_verb

    def do_POST(self) -> None:
        owner: LiveServer = self.server.owner  # type: ignore[attr-defined]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        consumed = False
        try:
            if self.headers.get("Origin") is not None:
                return self._fail(403, "LIVE_FORBIDDEN", "Browser requests are not accepted.")
            header = self.headers.get("Authorization") or ""
            if not hmac.compare_digest(header.encode("utf-8"), f"Bearer {owner.token}".encode("utf-8")):
                return self._fail(401, "LIVE_AUTH", "Missing or wrong token; read it from the discovery file.")
            match = re.fullmatch(r"/v1/([a-z_]+)", self.path.split("?", 1)[0])
            if not match or match.group(1) not in API:
                return self._fail(404, "LIVE_UNKNOWN_METHOD", f"Unknown method; use one of {sorted(API)}.")
            if length < 0:
                return self._fail(400, "LIVE_BAD_REQUEST", "Invalid Content-Length.")
            if length > MAX_BODY:
                return self._fail(413, "LIVE_TOO_LARGE", f"The request body is limited to {MAX_BODY} bytes.")
            raw = self.rfile.read(length) if length else b"{}"
            consumed = True
            try:
                params = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return self._fail(400, "LIVE_BAD_REQUEST", "The body must be a JSON object.")
            if not isinstance(params, dict):
                return self._fail(400, "LIVE_BAD_REQUEST", "The body must be a JSON object.")
            try:
                result = API[match.group(1)](owner.session, params)
                self._send(200, {"ok": True, **result})
            except LiveConflict as exc:
                payload = error_payload(exc)
                self._send(409, {**payload, "conflicts": exc.conflicts, "revision": exc.revision})
            except Exception as exc:  # structured failure instead of a dropped connection
                payload = error_payload(exc)
                status = HTTP_STATUS.get(payload["code"], 422 if isinstance(exc, ValueError) else 500)
                self._send(status, payload)
        finally:
            if not consumed and length > 0:
                self._drain(length)


class _Httpd(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class _Httpd6(_Httpd):
    address_family = socket.AF_INET6


class LiveServer:
    """Loopback-only JSON server: `POST /v1/<method>` with `Authorization: Bearer <token>`."""

    def __init__(self, session: LiveSession, host: str = "127.0.0.1", port: int = 0, token: str | None = None,
                 kind: str = "headless", home: Path | None = None):
        address = "127.0.0.1" if host == "localhost" else host
        try:
            loopback = ipaddress.ip_address(address).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ValidationError("The live server only binds to loopback (127.0.0.1 or ::1).", "LIVE_HOST")
        require_int(port, "port", 0, 65535)
        if kind not in ("desktop", "headless"):
            raise ValidationError("kind: 'desktop' or 'headless' expected.", "LIVE_PARAMS")
        if token is not None and (not isinstance(token, str) or len(token) < 16):
            raise ValidationError("token: text of at least 16 characters expected.", "LIVE_PARAMS")
        self.session, self.kind, self._address, self._port = session, kind, address, port
        self.token = token or secrets.token_hex(32)
        self._home = Path(home) if home else None
        self._httpd: _Httpd | None = None
        self._thread: threading.Thread | None = None
        self._file: Path | None = None
        self._lock = threading.Lock()
        self._started = ""

    @property
    def url(self) -> str:
        if self._httpd is None:
            raise ValidationError("The live server is not running.", "LIVE_NOT_RUNNING")
        host, port = self._httpd.server_address[:2]
        return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def info(self, secret: bool = True) -> dict:
        """The discovery record (without the token when `secret=False`)."""
        document = self.session.document
        data = {"pid": os.getpid(), "url": self.url, "token": self.token,
                "path": str(document.path) if document.path else None, "title": document.module.title,
                "started": self._started, "kind": self.kind, "api": API_VERSION}
        if not secret:
            del data["token"]
        return data

    def _discovery_file(self) -> Path:
        directory = (self._home or live_home()) / "live"
        name = f"{os.getpid()}.json"
        if name in _OWNED:
            name = f"{os.getpid()}-{self._httpd.server_address[1]}.json"
        return directory / name

    def start(self) -> LiveServer:
        with self._lock:
            if self._httpd is not None:
                return self
            self._httpd = (_Httpd6 if ":" in self._address else _Httpd)((self._address, self._port), _Handler)
            self._httpd.owner = self  # type: ignore[attr-defined]
            self._started = now()
            self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.1},
                                            name="chiploom-live", daemon=True)
            self._thread.start()
            self.session.add_listener(self._on_event)
            self._file = self._discovery_file()
            _OWNED.add(self._file.name)
            self._write_discovery()
        return self

    def _write_discovery(self) -> None:
        if self._file is None:
            return
        payload = (json.dumps(self.info(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        project.atomic_bytes(self._file, payload)
        if os.name != "nt":
            os.chmod(self._file, 0o600)

    def _on_event(self, kind: str, payload: dict) -> None:
        if kind == "reset" and self._file is not None:
            try:
                self._write_discovery()
            except OSError:
                pass

    def refresh_discovery(self) -> None:
        """Rewrite the discovery file (title and path changed)."""
        with self._lock:
            if self._httpd is not None:
                self._write_discovery()

    def stop(self) -> None:
        with self._lock:
            httpd, self._httpd = self._httpd, None
            if httpd is None:
                return
            if self._on_event in self.session._listeners:
                self.session._listeners.remove(self._on_event)
            httpd.shutdown()
            httpd.server_close()
            if self._thread is not None:
                self._thread.join(timeout=5)
            if self._file is not None:
                _OWNED.discard(self._file.name)
                try:
                    self._file.unlink()
                except OSError:
                    pass
                self._file = None

    def __enter__(self) -> LiveServer:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


_OWNED: set[str] = set()


# --- client -----------------------------------------------------------------------------

class LiveClient:
    """Talks to a `LiveServer`. Failures raise `ValidationError` carrying the server's `code`."""

    def __init__(self, url: str, token: str, timeout: float = 30):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def discover(cls, session: str | int | None = None, home: Path | None = None) -> LiveClient:
        """Pick a running session: newest by default, or by pid / url."""
        entries = discover(home)
        if session is not None:
            wanted = str(session).rstrip("/")
            entries = [item for item in entries if str(item["pid"]) == wanted or item["url"].rstrip("/") == wanted]
        if not entries:
            raise ValidationError(
                "No ChipLoom live session is running" + (f" matching {session!r}" if session is not None else "")
                + ". Open the ChipLoom window, or run `chiploom live serve SOURCE` for a headless session.",
                "LIVE_NOT_RUNNING")
        return cls(entries[0]["url"], entries[0]["token"])

    def call(self, method: str, **params) -> dict:
        body = json.dumps({key: value for key, value in params.items() if value is not None},
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(f"{self.url}/v1/{method}", data=body, method="POST", headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            with exc:
                raw = exc.read()
        except (socket.timeout, TimeoutError) as exc:
            raise ValidationError(f"The live session at {self.url} did not answer in time.", "LIVE_TIMEOUT") from exc
        except OSError as exc:
            raise ValidationError(f"No ChipLoom live session answers at {self.url} ({exc}).",
                                  "LIVE_NOT_RUNNING") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ValidationError("The live session sent an unreadable answer.", "LIVE_BAD_RESPONSE") from exc
        if isinstance(payload, dict) and payload.get("ok") is True:
            return payload
        payload = payload if isinstance(payload, dict) else {}
        code, message = payload.get("code") or "LIVE_ERROR", payload.get("message") or "The live session refused the request."
        if code == "LIVE_CONFLICT":
            raise LiveConflict(message, payload.get("conflicts") or [], payload.get("revision"))
        raise ValidationError(message, code)
