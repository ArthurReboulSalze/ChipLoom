"""Live co-composition inside the window: session lifecycle, agent edits, proposals and requests.

`LiveBridge` owns the `LiveSession` and its `LiveServer`; `AgentPanel` is the "Agent" tab with
pending proposals and takes (its COMMENTS column is `desktop_comments.CommentPanel`). The session never touches Qt: this module is the adapter. Every
session call from the window and every call from the server's threads runs on the GUI thread
(`GuiDispatcher`), so the document is only ever edited there.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
import time

from PySide6.QtCore import QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget)

from .desktop_widgets import ElidedLabel, media_call
from .document import Document
from . import live as live_module
from .live import LiveConflict, LiveServer, LiveSession
from .model import ValidationError

# Authors that are the owner (the window, and browsers that joined the studio); older sessions only know "human".
HUMAN_AUTHORS = tuple(getattr(live_module, "HUMAN_AUTHORS", ("human",)))

CONTEXT_DELAY_MS = 150
ACTIVE_SECONDS = 120          # an agent counts as connected this long after its last sign of life
MODAL_RETRY_MS = 250          # an agent's request waits this long between looks at the owner's open dialog


class GuiDispatcher(QObject):
    """Run a callable on the thread that owns this object (the GUI thread) and return its result.

    Inline when already on that thread, otherwise queued and waited for, so the HTTP server's
    threads never touch the document."""

    _call = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.closed = False
        self._call.connect(self._run, Qt.ConnectionType.QueuedConnection)

    def _run(self, job):
        function, box = job
        try:
            box["result"] = function()
        except BaseException as exc:  # handed back to the waiting thread
            box["error"] = exc
        finally:
            box["done"].set()

    def __call__(self, function):
        if QThread.currentThread() is self.thread():
            return function()
        if self.closed:
            raise ValidationError("The ChipLoom window is closing.", "LIVE_NOT_RUNNING")
        box = {"done": threading.Event()}
        self._call.emit((function, box))
        while not box["done"].wait(0.05):
            if self.closed:
                raise ValidationError("The ChipLoom window is closing.", "LIVE_NOT_RUNNING")
        if "error" in box:
            raise box["error"]
        return box["result"]


class LiveBridge(QObject):
    """Connects the window to a `LiveSession` (journal, proposals, takes) and its loopback server."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.dispatcher = GuiDispatcher(self)
        self.session: LiveSession | None = None
        self.server: LiveServer | None = None
        self.enabled = True
        self.quiet = False            # inside a change the window already presented itself
        self._agent_seen = 0.0        # latest agent write, proposal, take or request seen in session events
        self._agent_name: str | None = None
        self._pending_open: dict | None = None   # an `open` request waiting for the owner's save/discard answer
        self._open_counter = 0
        self.context_timer = QTimer(self)
        self.context_timer.setSingleShot(True)
        self.context_timer.setInterval(CONTEXT_DELAY_MS)
        self.context_timer.timeout.connect(self.push_context)
        self.panel_timer = QTimer(self)
        self.panel_timer.setSingleShot(True)
        self.panel_timer.setInterval(0)
        self.panel_timer.timeout.connect(self._refresh_panel)
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(1000)   # the indicator and the connected-browser count follow the session's own clocks
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start()

    # --- lifecycle -----------------------------------------------------------------
    def attach(self, document):
        """A document was opened or reloaded in the window."""
        if self.session is None:
            self.session = LiveSession(document, dispatcher=self.dispatcher, on_event=self._event)
            for kind, handler in (("play", self._play), ("stop", self._stop), ("seek", self._seek),
                                  ("select", self._select), ("open", self._open)):
                self.session.set_handler(kind, handler)
            self._serve()
        else:
            same = self.session.document.path is not None and self.session.document.path == document.path
            with self.silent():
                # A file reread from disk is not the owner's own edit; a different file is the owner's choice.
                self.session.reset(document, "file" if same else "human", "Reload" if same else "Open")
            if self.server is not None and self.server.running:
                self.server.refresh_discovery()
        self.context_changed()
        self.update_status()
        self.refresh_panel()

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        self._serve()
        self.update_status()

    def _serve(self):
        if self.session is None:
            return
        if self.enabled:
            if self.server is None:
                self.server = LiveServer(self.session, kind="desktop")
            try:
                self.server.start()
            except OSError as exc:
                self.window.message("Live collaboration unavailable: {detail}", True, detail=exc)
            else:
                if self.window.state.values.get("web_lan") is True:   # the owner opened the studio to the network before
                    try:
                        self.server.enable_lan(True)
                    except ValidationError as exc:
                        self.window.state.values["web_lan"] = False
                        self.window.message("The local network could not be opened: {detail}", True, detail=exc)
        elif self.server is not None:
            self.server.stop()

    def shutdown(self):
        self.dispatcher.closed = True
        self._pending_open = None
        self.context_timer.stop()
        self.status_timer.stop()
        if self.server is not None:
            self.server.stop()

    @contextmanager
    def silent(self):
        """Session events caused by the window itself must not be presented twice."""
        previous, self.quiet = self.quiet, True
        try:
            yield
        finally:
            self.quiet = previous

    # --- window -> session ---------------------------------------------------------
    def human_edit(self, label: str):
        """Journal an edit, undo or redo made in the window."""
        if self.session is not None:
            self.session.sync("human", label)
        self.context_changed()

    def external_edit(self, label: str):
        """The open file was rewritten by someone else (an agent, a script): journal it as "file"."""
        if self.session is not None:
            with self.silent():
                self.session.sync("file", label)
        self.context_changed()

    def context_changed(self, *_):
        if self.session is not None:
            self.context_timer.start()

    def push_context(self):
        window, session = self.window, self.session
        if session is None or not window.document:
            return
        index = window.table.currentIndex()
        block = window.table.selection_block()
        pattern = window.pattern_model.pattern
        values = {"path": str(window.document.path) if window.document.path else None,
                  "order": window.current_order, "pattern": pattern,
                  "row": index.row() if index.isValid() else None,
                  "channel": window.pattern_model.channel_of(index.column()) if index.isValid() else None,
                  "selection": {"pattern": pattern, "row": block[0], "rows": block[1], "channel": block[2],
                                "channels": block[3]} if block else None,
                  "playing": window.is_playing(), "audible": list(window.audible()),
                  "position_seconds": round(window.playback_ms() / 1000, 3),
                  "dirty": window.document.dirty, "language": window.language}
        try:
            session.update_context(**values)
        except ValidationError:
            pass

    # --- session -> window ---------------------------------------------------------
    def _event(self, kind: str, payload: dict):
        """Called on the GUI thread by the session."""
        if kind == "change":
            # A comment entry changes no cell: the comment panel presents it (below), the score needs no reload.
            if payload["author"] != "human" and not self.quiet and payload.get("kind") != "comment":
                if payload["author"] not in HUMAN_AUTHORS:
                    self._saw_agent(payload["author"])
                self.window.agent_changed(payload)
            self.refresh_panel()  # stale flags and the preview follow every change
        elif kind == "proposal":
            if payload["action"] == "created":
                proposal = payload["proposal"]
                self._saw_agent(proposal["author"])
                self.window.message("Agent proposal: {label} ({author}) · see the Agent tab",
                                    label=proposal["label"], author=proposal["author"])
            self.refresh_panel()
        elif kind == "take":
            self._saw_agent(payload.get("author"))
            self.window.message("New take: {label}", label=payload["label"])
            self.refresh_panel()
        elif kind == "reset":
            self.refresh_panel()
        elif kind == "comment":
            self.window.comment_panel.on_event(payload)
        elif kind == "request":
            self._saw_agent()
        self.update_status()

    def _saw_agent(self, name: str | None = None):
        self._agent_seen = time.monotonic()
        if isinstance(name, str) and name not in (*HUMAN_AUTHORS, "file"):
            self._agent_name = name

    def refresh_panel(self):
        self.panel_timer.start()

    def _refresh_panel(self):
        self.window.agent_panel.refresh()

    def last_agent_activity(self) -> float | None:
        """`time.monotonic()` of the latest sign of an agent, or None. `session.last_agent_activity` is set on
        every authenticated agent API call, reads included; agent writes, proposals, takes and requests seen
        in session events count too (they also name the agent)."""
        now = time.monotonic()
        marks = [self._agent_seen]
        reported = getattr(self.session, "last_agent_activity", None)
        if isinstance(reported, (int, float)) and not isinstance(reported, bool) and 0 < reported <= now:
            marks.append(float(reported))
        latest = max(marks)
        return latest if latest > 0 else None

    def agent_connected(self) -> bool:
        latest = self.last_agent_activity()
        running = self.server is not None and self.server.running
        return bool(running and latest is not None and time.monotonic() - latest < ACTIVE_SECONDS)

    def update_status(self):
        window = self.window
        running = self.server is not None and self.server.running
        if not running:
            text, tip = "Live: off", "Live collaboration is off (Agent menu)."
        elif self.agent_connected():
            text, tip = "Live: agent connected", "An agent worked on this window in the last two minutes."
        else:
            text, tip = "Live: listening", "Waiting for an agent: it finds this window with `chiploom live`."
        tip = window.t(tip)
        latest = self.last_agent_activity()
        if running and latest is not None:
            seconds = round(time.monotonic() - latest)
            tip += "\n" + window.t("Last agent activity: {seconds} s ago", seconds=seconds)
            if self._agent_name:
                tip += " · " + self._agent_name
        window.live_status.setText(window.t(text))
        extra = f"\n{self.server.url}" if running else ""
        window.live_status.setToolTip(tip + extra)
        devices = len(self.session.web_devices()) if running and self.session is not None else 0
        window.web_status.setVisible(devices > 0)
        window.web_status.setText(window.t("Browsers: {count}", count=devices))
        window.web_status.setToolTip(window.t("Browsers connected to this song (Agent menu, Open in a browser…)"))

    # --- requests from the agent (all on the GUI thread) ---------------------------
    def _play(self, payload: dict) -> dict:
        window = self.window
        if "order" in payload:
            order = payload["order"]
            if window.orders.currentIndex() == order:
                window.select_order(order)
            else:
                window.orders.setCurrentIndex(order)
        window.start_playback()
        return {"playing": True, "order": window.current_order}

    def _stop(self, payload: dict) -> dict:
        self.window.stop()
        return {"playing": False}

    def _seek(self, payload: dict) -> dict:
        self.window.seek_to(round(payload["seconds"] * 1000))
        return {"seconds": payload["seconds"]}

    def _select(self, payload: dict) -> dict:
        window = self.window
        pattern = payload["pattern"]
        orders = window.document.module.orders
        if window.pattern_model.pattern != pattern:
            if pattern not in orders:
                return {"handled": False, "reason": f"pattern {pattern} is not in the order list"}
            window.show_order(orders.index(pattern))
        window.table.select_block(payload["row"], payload["rows"], payload["channel"], payload["channels"])
        return {"selected": payload}

    def _open(self, payload: dict) -> dict:
        """Open a file or take for the agent. Unsaved changes need the owner's answer to a save/discard
        prompt, which can take minutes: the agent gets `{"handled": "pending", "prompt": true}` at once and
        the outcome is journaled when the owner has answered (see `_resolve_open`)."""
        window = self.window
        if self._pending_open is not None:
            return {"handled": False, "reason": "another open request is waiting for the owner's answer"}
        if window.document is None or not window.document.dirty:
            if window.open_document(Path(payload["path"]), ask=False):
                return {"opened": payload["path"]}
            return {"handled": False, "reason": "the file could not be opened"}
        self._open_counter += 1
        self._pending_open = {"id": f"o{self._open_counter}", "path": payload["path"], "take": payload.get("take"),
                              "label": payload.get("label")}
        self._publish_pending()
        window.message("The agent asks to open {name}: answer the save prompt", name=Path(payload["path"]).name)
        QTimer.singleShot(0, self._resolve_open)   # outside the agent's request: the prompt blocks
        return {"handled": "pending", "prompt": True, "request_id": self._pending_open["id"]}

    def _resolve_open(self):
        request = self._pending_open
        if request is None or self.dispatcher.closed:
            return
        if QApplication.activeModalWidget() is not None:   # the owner is answering another dialog first
            QTimer.singleShot(MODAL_RETRY_MS, self._resolve_open)
            return
        window = self.window
        try:
            if not window._discard_or_save():
                outcome = "declined"
            elif window.open_document(Path(request["path"]), ask=False):
                outcome = "opened"
            else:
                outcome = "failed"
        finally:
            self._pending_open = None
            self._publish_pending()
        self._note_outcome(request, outcome)

    def _publish_pending(self):
        """Let the agent see a waiting request in `status` (when the session accepts that context key)."""
        if self.session is None:
            return
        pending = self._pending_open
        try:
            self.session.update_context(pending_request=None if pending is None else
                                        {"request_id": pending["id"], "kind": "open", "path": pending["path"],
                                         "take": pending["take"], "waiting_for": "the owner's save or discard answer"})
        except ValidationError:
            pass   # an older session without that key: the immediate reply and the journal note still tell

    OUTCOMES = {"opened": "Open request: the file was opened", "declined": "Open request: the owner declined",
                "failed": "Open request: the file could not be opened"}

    def _note_outcome(self, request: dict, outcome: str):
        """Journal how an asynchronous request ended, so the agent finds it in `changes` (author "human",
        empty diff, kind "request")."""
        if self.session is None:
            return
        extra = {"request": "open", "request_id": request["id"], "outcome": outcome, "path": request["path"],
                 "take": request["take"]}
        with self.silent():
            self.session.record_note(self.OUTCOMES[outcome], "human", **extra)


class AgentPanel(QWidget):
    """Pending proposals (preview, accept, reject, listen) and takes (saved versions)."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("agentPanel")
        self.previewing: str | None = None
        self._proposals: list[dict] = []
        self.compare: dict | None = None   # A/B listening: {"take", "label", "module", "side": "A" | "B"}
        # The columns scroll inside the tab, so a small window does not clip the buttons under them.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        area.setWidget(content)
        outer.addWidget(area)
        layout = QHBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(14)   # room between the proposals, details and takes columns
        self.columns = layout   # desktop_comments adds its COMMENTS column here

        left = QVBoxLayout()
        left.addWidget(window._label("PROPOSALS", "section"))
        self.proposal_list = QListWidget()
        self.proposal_list.setObjectName("proposals")
        self.proposal_list.setMinimumHeight(45)
        self.proposal_list.currentItemChanged.connect(self._selected)
        left.addWidget(self.proposal_list, 1)
        # One elided line (full text in the tooltip): a wrapping label would make the columns ask for their preferred
        # height, which pushes the buttons below the fold of the Agent tab.
        self.empty_hint = ElidedLabel("", "muted")
        window._bind(self.empty_hint, "Proposals from the agent appear here. Select one to preview it on the pattern.")
        window._bind(self.empty_hint, "Proposals from the agent appear here. Select one to preview it on the pattern.",
                     "setToolTip")
        left.addWidget(self.empty_hint)
        buttons = QHBoxLayout()
        self.accept_button = window._button("Accept", self.accept_selected, "acceptProposal")
        self.reject_button = window._button("Reject", self.reject_selected, "rejectProposal")
        self.listen_button = window._button("Listen to proposal", self.listen, "listenProposal")
        self.clear_button = window._button("Clear preview", self.clear_preview, "clearPreview")
        for control in (self.accept_button, self.reject_button, self.listen_button, self.clear_button):
            buttons.addWidget(control)
        buttons.addStretch()
        left.addLayout(buttons)
        layout.addLayout(left, 3)

        middle = QVBoxLayout()
        middle.addWidget(window._label("DETAILS", "section"))
        self.details = QPlainTextEdit()
        self.details.setObjectName("proposalDetails")
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(45)
        middle.addWidget(self.details, 1)
        layout.addLayout(middle, 2)

        right = QVBoxLayout()
        right.addWidget(window._label("TAKES", "section"))
        self.take_list = QListWidget()
        self.take_list.setObjectName("takes")
        self.take_list.setMinimumHeight(45)
        self.take_list.itemDoubleClicked.connect(lambda item: self.open_take())
        right.addWidget(self.take_list, 1)
        self.take_hint = ElidedLabel("", "muted")   # one line: the Agent tab must stay usable in a short window
        window._bind(self.take_hint, "Takes the agent saves appear here.")
        window._bind(self.take_hint, "Takes the agent saves appear here. Open one to work from it, or compare it with the current song.",
                     "setToolTip")
        right.addWidget(self.take_hint)
        take_buttons = QHBoxLayout()
        self.open_button = window._button("Open take", self.open_take, "openTake")
        take_buttons.addWidget(self.open_button)
        self.compare_button = window._button("Compare with current", self.toggle_compare, "compareTake")
        window._bind(self.compare_button, "Ctrl+B: hear the take, then switch between it and the current song at the same position",
                     "setToolTip")
        take_buttons.addWidget(self.compare_button)
        take_buttons.addStretch()
        right.addLayout(take_buttons)
        compare_row = QHBoxLayout()
        self.compare_label = QLabel()
        self.compare_label.setObjectName("compareState")
        self.compare_label.setWordWrap(True)
        self.compare_label.setTextFormat(Qt.TextFormat.PlainText)
        compare_row.addWidget(self.compare_label, 1)
        self.compare_stop_button = window._button("End comparison", self.end_compare, "endCompare")
        compare_row.addWidget(self.compare_stop_button)
        right.addLayout(compare_row)
        layout.addLayout(right, 3)

        self.accept_action = QAction(self)
        self.accept_action.setShortcuts([QKeySequence("Ctrl+Return"), QKeySequence("Ctrl+Enter")])
        self.accept_action.triggered.connect(self.accept_selected)
        window.addAction(self.accept_action)
        self._buttons_state()

    # --- content -------------------------------------------------------------------
    @property
    def session(self) -> LiveSession | None:
        return self.window.live.session

    def selected_id(self) -> str | None:
        item = self.proposal_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def proposal_text(self, proposal: dict) -> str:
        cells = proposal["diff"].get("cells_total", len(proposal["diff"].get("cells", [])))
        text = self.window.t("{id} · {label} · {author} · {cells} cells", id=proposal["id"], label=proposal["label"],
                             author=proposal["author"], cells=cells)
        return text + (" · " + self.window.t("outdated") if proposal.get("stale") else "")

    def refresh(self):
        """Rebuild both lists from the session, keeping the selection and refreshing the overlay."""
        window, session = self.window, self.session
        wanted = self.selected_id()
        self._proposals = session.proposals() if session else []
        self.proposal_list.blockSignals(True)
        self.proposal_list.clear()
        for proposal in self._proposals:
            item = QListWidgetItem(self.proposal_text(proposal))
            item.setData(Qt.ItemDataRole.UserRole, proposal["id"])
            self.proposal_list.addItem(item)
            if proposal["id"] == wanted:
                self.proposal_list.setCurrentItem(item)
        self.proposal_list.blockSignals(False)
        wanted_take = self.take_list.currentItem().data(Qt.ItemDataRole.UserRole) if self.take_list.currentItem() else None
        self.take_list.clear()
        for take in (session.takes() if session else []):
            item = QListWidgetItem(window.t("{id} · {label} · {author} · {seconds:.1f} s", id=take["id"], label=take["label"],
                                            author=take["author"], seconds=take["duration_seconds"]))
            item.setToolTip(take["path"])
            item.setData(Qt.ItemDataRole.UserRole, take["id"])
            self.take_list.addItem(item)
            if take["id"] == wanted_take:
                self.take_list.setCurrentItem(item)
        self.empty_hint.setVisible(not self._proposals)
        self.take_hint.setVisible(self.take_list.count() == 0)
        if self.previewing is not None and self.selected_id() != self.previewing:
            self.previewing = None
            window.pattern_model.set_overlay(None)
        if self.selected_id():
            self._preview(self.selected_id(), jump=False)
        else:
            self.details.clear()
        window.sample_tabs.setTabText(window.sample_tabs.indexOf(self), window.t("Agent") + (f" ({len(self._proposals)})" if self._proposals else ""))
        self._buttons_state()

    def retranslate(self):
        self.refresh()

    def _buttons_state(self):
        has = self.selected_id() is not None
        for control in (self.accept_button, self.reject_button, self.listen_button):
            control.setEnabled(has)
        self.clear_button.setEnabled(self.previewing is not None)
        has_take = self.take_list.currentItem() is not None or self.take_list.count() > 0
        self.open_button.setEnabled(has_take)
        self.compare_button.setEnabled(has_take or self.compare is not None)
        self.compare_stop_button.setEnabled(self.compare is not None)
        self.accept_action.setEnabled(has)
        self._compare_ui()

    # --- preview -------------------------------------------------------------------
    def _selected(self, current, previous):
        if current is None:
            self.clear_preview()
        else:
            self._preview(current.data(Qt.ItemDataRole.UserRole), jump=True)
        self._buttons_state()

    def _preview(self, proposal_id: str, jump: bool):
        window, session = self.window, self.session
        proposal = next((item for item in self._proposals if item["id"] == proposal_id), None)
        if session is None or proposal is None:
            return
        try:
            module = session.proposal_preview(proposal_id)
        except ValidationError as exc:
            window.pattern_model.set_overlay(None)
            self.previewing = None
            self.details.setPlainText(window.t("This proposal can no longer be applied: {detail}", detail=exc))
            return
        self.previewing = proposal_id
        window.pattern_model.set_overlay(module)
        lines = list(proposal["summary"])
        stale = self.window.t("The score changed in these cells since the proposal: accepting may ask to overwrite.")
        self.details.setPlainText("\n".join([proposal["label"], f"{proposal['author']} · {proposal['id']}", ""]
                                            + lines + (["", stale] if proposal.get("stale") else [])))
        cells = proposal["diff"].get("cells", [])
        if jump and cells:
            window.show_pattern(cells[0]["pattern"])
            window.table.scrollTo(window.pattern_model.index(cells[0]["row"], window.pattern_model.column_of(cells[0]["channel"])))

    def clear_preview(self):
        self.previewing = None
        self.window.pattern_model.set_overlay(None)
        self.proposal_list.blockSignals(True)
        self.proposal_list.setCurrentRow(-1)
        self.proposal_list.blockSignals(False)
        self.details.clear()
        self._buttons_state()

    # --- decisions -----------------------------------------------------------------
    def accept_selected(self, *_):
        proposal_id, session, window = self.selected_id(), self.session, self.window
        if not proposal_id or session is None:
            return False
        proposal = next((item for item in self._proposals if item["id"] == proposal_id), None)
        try:
            session.accept(proposal_id, "human")
        except LiveConflict as exc:
            lines = []
            for item in exc.conflicts[:8]:
                if item.get("unit") == "cell":
                    lines.append(f"P{item['pattern']:02X} r{item['row']:02X} ch{item['channel'] + 1}: "
                                 f"{item.get('current')} → {item.get('yours')} ({item['author']}: {item['label']})")
                else:
                    lines.append(f"{item.get('unit')} ({item.get('author')}: {item.get('label')})")
            answer = QMessageBox.question(
                window, window.t("Conflicting edits"),
                window.t("These parts changed since the agent proposed this:") + "\n\n" + "\n".join(lines)
                + "\n\n" + window.t("Accept anyway and overwrite them?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return False
            return self._accept_forced(proposal_id)
        except ValidationError as exc:
            window.message("Proposal cannot be applied: {detail}", True, detail=exc)
            return False
        self.previewing = None
        window.pattern_model.set_overlay(None)
        self.refresh()
        window.message("Accepted: {label} · Ctrl+Z to undo", label=proposal["label"] if proposal else proposal_id)
        return True

    def _accept_forced(self, proposal_id: str) -> bool:
        try:
            self.session.accept(proposal_id, "human", force=True)
        except ValidationError as exc:
            self.window.message("Proposal cannot be applied: {detail}", True, detail=exc)
            return False
        self.previewing = None
        self.window.pattern_model.set_overlay(None)
        self.refresh()
        self.window.message("Accepted: {label} · Ctrl+Z to undo", label=proposal_id)
        return True

    def reject_selected(self, *_):
        proposal_id = self.selected_id()
        if not proposal_id or self.session is None:
            return False
        try:
            self.session.reject(proposal_id, "human")
        except ValidationError as exc:
            self.window.message("Proposal cannot be applied: {detail}", True, detail=exc)
            return False
        self.previewing = None
        self.window.pattern_model.set_overlay(None)
        self.refresh()
        self.window.message("Rejected: {label}", label=proposal_id)
        return True

    def listen(self, *_):
        """Render the proposal through the usual audio cache and play it; the document is untouched."""
        window, session, proposal_id = self.window, self.session, self.selected_id()
        if not proposal_id or session is None:
            return
        try:
            module = session.proposal_preview(proposal_id)
        except ValidationError as exc:
            window.message("Proposal cannot be applied: {detail}", True, detail=exc)
            return
        audible = window.audible()
        window.message("Rendering the proposal…")

        def play(path):
            window.meter.reset()
            window.pause_playback()
            media_call(window.sample_player, "setSource", QUrl.fromLocalFile(str(path)))
            window.sample_player.play()
            window.message("Listening to proposal {id}", id=proposal_id)

        window.submit(lambda: window.cache.prepare(module, audible), play,
                      lambda text: window.message("Audio unavailable: {detail}", True, detail=text))

    # --- takes ---------------------------------------------------------------------
    def chosen_take(self) -> dict | None:
        """The selected take (the first one when none is selected), as the session describes it."""
        item = self.take_list.currentItem() or (self.take_list.item(0) if self.take_list.count() else None)
        if item is None or self.session is None:
            return None
        return next((entry for entry in self.session.takes() if entry["id"] == item.data(Qt.ItemDataRole.UserRole)), None)

    def open_take(self, *_):
        take = self.chosen_take()
        return bool(take) and self.window.open_document(Path(take["path"]))

    # --- A/B comparison -------------------------------------------------------------
    # The take replaces the document only in what the transport plays (`TrackerWindow.listen_to`), at the
    # same song position; the document, its undo history and the journal are never touched.
    def toggle_compare(self, *_) -> bool:
        """Start comparing the chosen take (hearing it first), or switch between current song and take."""
        window = self.window
        if self.compare is None:
            take = self.chosen_take()
            if take is None or not window.document:
                window.message("Select a take to compare with the current song.")
                return False
            try:
                module = Document.open(Path(take["path"])).module
            except (OSError, ValueError, RuntimeError) as exc:
                window.message("Cannot open: {detail}", True, detail=exc)
                return False
            self.compare = {"take": take["id"], "label": take["label"], "module": module, "side": "B"}
        else:
            self.compare["side"] = "A" if self.compare["side"] == "B" else "B"
        compare = self.compare
        window.listen_to(compare["module"] if compare["side"] == "B" else None)
        if not window.is_playing():
            window.start_playback()
        self._buttons_state()
        window.message("Comparing: {listening}", listening=self.compare_text())
        return True

    def end_compare(self, *_, restore: bool = True):
        """Stop comparing. The current song is heard again (not with `restore=False`: the transport was reset)."""
        if self.compare is None:
            return
        self.compare = None
        if restore:
            self.window.listen_to(None)
        else:
            self.window.monitor_module = None
        self._buttons_state()

    def compare_edited(self):
        """The owner edited the current song while hearing the take: switch back to hear the edit."""
        if self.compare is not None and self.compare["side"] == "B":
            self.compare["side"] = "A"
            self.window.monitor_module = None   # the edit's own reload plays the document
            self.window._update_title()
            self._buttons_state()

    def compare_text(self) -> str:
        compare, window = self.compare, self.window
        if compare is None:
            return ""
        if compare["side"] == "B":
            return window.t("take {id} · {label} (B)", id=compare["take"], label=compare["label"])
        return window.t("current song (A)")

    def _compare_ui(self):
        window, compare = self.window, self.compare
        if compare is None:
            self.compare_label.clear()
            self.compare_label.setProperty("side", "")
            self.compare_button.setText(window.t("Compare with current"))
        else:
            self.compare_label.setText(window.t("Listening to {listening}", listening=self.compare_text()))
            self.compare_label.setProperty("side", compare["side"])
            self.compare_button.setText(window.t("Listen to current song (A)" if compare["side"] == "B"
                                                 else "Listen to take (B)"))
        self.compare_label.style().unpolish(self.compare_label)
        self.compare_label.style().polish(self.compare_label)


def status_label() -> QLabel:
    label = QLabel()
    label.setObjectName("liveStatus")
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label
