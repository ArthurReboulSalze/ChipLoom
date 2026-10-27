"""Follow the open file on disk, so an agent's saves appear without pressing F5.

`reconcile` is Qt-free: given the module as last loaded/saved (`base`), the module in the
window (`mine`) and the one now on disk (`theirs`), it decides between nothing, a plain
reload and a three-way merge. `DiskSync` watches the file and feeds `TrackerWindow.apply_external`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from .document import Document, fingerprint
from .model import Module
from .patch import diff_modules, merge_modules


@dataclass
class External:
    kind: str                    # "none", "reload" or "merge"
    module: Module | None = None
    conflicts: list[dict] = field(default_factory=list)


def reconcile(base: Module, mine: Module, theirs: Module) -> External:
    """Nothing to do, a plain reload (no local edits), or the merge of local edits into the file."""
    theirs_fp = fingerprint(theirs)
    if theirs_fp == fingerprint(base):
        return External("none")
    if fingerprint(mine) == fingerprint(base):
        return External("reload", theirs)
    merged, conflicts = merge_modules(base, mine, theirs)
    if fingerprint(merged) == theirs_fp:
        return External("reload", theirs, conflicts)
    return External("merge", merged, conflicts)


def changed_cells(before: Module, after: Module) -> list[dict]:
    return diff_modules(before, after)["cells"]


def mark_clean(document: Document):
    """The document now matches the file on disk."""
    document.mark_saved()


class DiskSync(QObject):
    """Follow the document's file through its folder.

    Only the folder is watched, never the file itself: on Windows a watched file stays open
    inside Qt, which made the agent's atomic replace fail with "access denied" (about 3% of
    saves in a stress test). Folder events plus a cheap stat poll catch every kind of write."""

    DEBOUNCE_MS = 300
    POLL_MS = 500
    applied = Signal(str, list)   # kind ("reload" / "merge"), conflicts

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.path: Path | None = None
        self.base: Module | None = None      # the module as last loaded or saved
        self._signature = None
        self._failed = None
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self._schedule)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(self.DEBOUNCE_MS)
        self.debounce.timeout.connect(self._fire)
        # In-place writes do not always raise a folder event (network drives too): a stat poll is the safety net.
        self.poll = QTimer(self)
        self.poll.setInterval(self.POLL_MS)
        self.poll.timeout.connect(self._poll)

    # --- lifecycle -----------------------------------------------------------------
    def watch(self, path: Path | None, module: Module | None = None):
        """Start following `path`; `module` is the content just loaded or saved there."""
        self.stop()
        if path is None or module is None:
            return
        self.path, self.base = Path(path), copy.deepcopy(module)
        self._signature, self._failed = self._stat(), None
        self._arm()
        self.poll.start()

    def stop(self):
        self.debounce.stop()
        self.poll.stop()
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.path = self.base = self._signature = self._failed = None

    def _stat(self):
        try:
            info = self.path.stat()
            return info.st_mtime_ns, info.st_size
        except OSError:
            return None

    def _arm(self):
        """(Re-)add the folder, which can vanish and come back (removable drives, renamed folders)."""
        folder = str(self.path.parent)
        if self.path.parent.is_dir() and folder not in self.watcher.directories():
            self.watcher.addPath(folder)

    # --- detection -----------------------------------------------------------------
    def _schedule(self, *_):
        self.debounce.start()

    def _poll(self):
        if self.path is not None and self._stat() != self._signature and not self.debounce.isActive():
            self.debounce.start()

    def _fire(self):
        if self.path is not None:
            self._arm()
            self.check()

    def check(self) -> str:
        """Compare the file with the last known state and apply the difference now.
        Returns "unchanged", "missing", "error", "reload" or "merge" (handy for tests)."""
        window, document = self.window, self.window.document
        if self.path is None or document is None or document.path != self.path:
            return "unchanged"
        signature = self._stat()
        if signature is None:
            return "missing"
        if signature == self._signature:
            return "unchanged"
        try:
            theirs = Document.open(self.path)
        except (OSError, ValueError, RuntimeError) as exc:
            # A half-written file: say so once per version of the file and retry when it changes.
            if signature != self._failed:
                self._failed = signature
                window.message("Cannot reload the changed file: {detail}", True, detail=exc)
            return "error"
        self._signature, self._failed = signature, None
        outcome = reconcile(self.base, document.module, theirs.module)
        self.base = copy.deepcopy(theirs.module)
        if outcome.kind == "none":
            return "unchanged"
        window.apply_external(outcome.module, outcome.kind, outcome.conflicts)
        self.applied.emit(outcome.kind, outcome.conflicts)
        return outcome.kind

    def saved(self):
        """Our own save: the file now holds the window's module, so it is not an external change."""
        document = self.window.document
        if document is not None and document.path is not None:
            self.watch(document.path, document.module)
