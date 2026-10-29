"""Comments with a place in the window: the owner's remarks on a block of cells, for the agent to read.

The data and its rules live in `comments.py` (the core); this module is the window's side:

- `CommentStore`  the same add / reply / resolve / reopen operations whether a live session is attached (the
                  session journals them and tells the agent) or not (they go straight to `document.comments`
                  through the same helpers), so both paths stay identical.
- `CommentPanel`  the "COMMENTS" column of the Agent tab (list, Go to, Reply, Resolve / Reopen, Show resolved),
                  the comment dialog for the grid selection or the whole song, the grid's context menu, the
                  corner markers painted on covered cells and their tooltips (`COMMENTS_ROLE` of the model).

Hooks elsewhere (one or two lines each): desktop_layout creates `window.comment_panel` after the Agent tab and
lists Ctrl+M in the "?" popup; desktop_menus adds `window.comment_action` (Ctrl+M) and
`window.song_comment_action` to the Agent menu; desktop_pattern asks `covering`, `tooltip` and `paint_markers`;
desktop_live forwards the session's "comment" events to `on_event` (and does not reload the score for a comment
journal entry); desktop_song refreshes the panel in `refresh_document` (open, reload, edits) and
desktop_preferences in `retranslate`.

Relies on: window.document (its `comments` list and module), window.live (`session`, `silent`), window.agent_panel
(`columns`, the Agent tab's row of columns), window.table (`selection_block`, `select_block`), window.pattern_model
(`pattern`, `parts`, `channels`), window.palette_colors, window.comment_action / song_comment_action /
cut_action / copy_action / paste_action / clear_action, `show_pattern`, `_update_title`, `message`, `t`, `_bind`,
`_rebind`, `_button` and `_label`.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygon
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidgetItem, QMenu,
                               QVBoxLayout, QWidget)

from . import comments as comment_store
from .desktop_widgets import HintList, ElidedLabel
from .model import ValidationError

AUTHOR = "human"                                  # the window's author name in the session and in comments
COMMENTS_ROLE = Qt.ItemDataRole.UserRole + 1      # PatternModel: ids of the open comments covering a cell
MARKER_PX = 7                                     # side of the corner triangle on a covered cell


class CommentStore:
    """Comment operations on the window's document, through the live session when one is attached."""

    def __init__(self, window):
        self.window = window

    @property
    def session(self):
        live = getattr(self.window, "live", None)
        session = getattr(live, "session", None)
        return session if session is not None and session.document is self.window.document else None

    @property
    def comments(self) -> list[dict]:
        document = self.window.document
        return document.comments if document else []

    def add(self, text: object, place: dict | None) -> dict:
        session = self.session
        if session is not None:
            return session.add_comment(text, place, AUTHOR)
        document = self.window.document
        comment = comment_store.create(document.module, document.comments, text, place, AUTHOR)
        document.comments.append(comment)
        comment_store.trim(document.comments)
        return comment_store.view(comment)

    def reply(self, comment_id: str, text: object) -> dict:
        session = self.session
        if session is not None:
            return session.reply_comment(comment_id, text, AUTHOR)
        comment = comment_store.find(self.comments, comment_id)
        comment_store.reply(comment, text, AUTHOR)
        return comment_store.view(comment)

    def resolve(self, comment_id: str, reopen: bool = False) -> dict:
        session = self.session
        if session is not None:
            return session.resolve_comment(comment_id, AUTHOR, reopen=reopen)
        comment = comment_store.find(self.comments, comment_id)
        wanted = "open" if reopen else "resolved"
        if comment["status"] == wanted:   # the session's own rule, so both paths refuse the same thing
            raise ValidationError(f"Comment {comment['id']} is already {wanted}.", "COMMENT_INVALID")
        comment_store.set_status(comment, wanted, AUTHOR)
        return comment_store.view(comment)


def local_time(value: object) -> str:
    """The stored UTC time in the computer's time zone: "11:05" today, "2026-10-28 11:05" before ("" when unknown)."""
    if not isinstance(value, str):
        return ""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return value
    return moment.strftime("%H:%M" if moment.date() == datetime.now().astimezone().date() else "%Y-%m-%d %H:%M")


def covers(place: dict | None, pattern: int, row: int, channel: int) -> bool:
    return (place is not None and place["pattern"] == pattern and place["row"] <= row < place["row"] + place["rows"]
            and place["channel"] <= channel < place["channel"] + place["channels"])


class CommentPanel(QWidget):
    """The COMMENTS column of the Agent tab, the comment dialog, and the grid's markers (see the module docstring)."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.store = CommentStore(window)
        self.setObjectName("commentPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.header = QLabel()
        self.header.setObjectName("section")
        header.addWidget(self.header, 1)
        self.show_resolved = window._bind(QCheckBox(), "Show resolved")
        self.show_resolved.setObjectName("showResolved")
        self.show_resolved.toggled.connect(lambda *_: self.refresh())
        header.addWidget(self.show_resolved)
        layout.addLayout(header)
        self.list = HintList()
        self.list.setObjectName("comments")
        window._bind(self.list, "No message yet. Write to your agent in the box below: select cells in the grid "
                                "first to point at a place, or leave the box unticked for the whole song. Its "
                                "answers appear here under your message.", "set_hint")
        self.list.setMinimumHeight(45)
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(lambda *_: self._buttons_state())
        self.list.itemDoubleClicked.connect(lambda item: self.go_to())
        window._bind(self.list, "Ctrl+M in the grid: comment on the selected cells · double-click: go to the place",
                     "setToolTip")
        layout.addWidget(self.list, 1)
        # New comments start from the grid (Ctrl+M, right-click, Agent menu): the Agent tab has no height to spare.
        self.hint = ElidedLabel("", "muted")   # one line, as in the other Agent tab columns (see AgentPanel.empty_hint)
        for setter in ("setText", "setToolTip"):
            window._bind(self.hint, "Select cells in the grid and press Ctrl+M (or right-click, Comment on the "
                                    "selection…): your agent sees exactly where.", setter)
        layout.addWidget(self.hint)
        self.hint.setVisible(False)   # the list says it in its own box; the tooltip stays
        # The one place to write to the agent from the Agent tab (Ctrl+M in the grid does the same).
        compose = QHBoxLayout()
        self.compose = QLineEdit()
        self.compose.setObjectName("composeComment")
        window._bind(self.compose, "Write to your agent here, then press Enter…", "setPlaceholderText")
        self.compose.returnPressed.connect(self.send_compose)
        compose.addWidget(self.compose, 1)
        self.send_button = window._button("Send", self.send_compose, "sendComment")
        compose.addWidget(self.send_button)
        layout.addLayout(compose)
        target = QHBoxLayout()
        self.at_selection = window._bind(QCheckBox(), "About the selected cells")
        self.at_selection.setObjectName("commentAtSelection")
        self.at_selection.setChecked(True)
        self.at_selection.toggled.connect(lambda *_: self.update_target())
        target.addWidget(self.at_selection)
        self.target = ElidedLabel("", "muted")
        target.addWidget(self.target, 1)
        layout.addLayout(target)
        actions = QHBoxLayout()
        self.go_button = window._button("Go to", self.go_to, "gotoComment")
        self.reply_button = window._button("Reply", self.reply_selected, "replyComment")
        self.resolve_button = window._button("Resolve", self.resolve_selected, "resolveComment")
        for control in (self.go_button, self.reply_button, self.resolve_button):
            actions.addWidget(control)
        actions.addStretch()
        layout.addLayout(actions)
        window.agent_panel.columns.addWidget(self, 3)
        window.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        window.table.customContextMenuRequested.connect(self._grid_menu)
        self.refresh()

    # --- reading ---------------------------------------------------------------------
    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected(self) -> dict | None:
        wanted = self.selected_id()
        return next((item for item in self.store.comments if item["id"] == wanted), None)

    def open_count(self) -> int:
        return sum(item["status"] == "open" for item in self.store.comments)

    def place_text(self, place: dict | None) -> str:
        """"Pattern 01 · rows 00-1F · channels 4-5": pattern and rows in hexadecimal as the grid shows them, tracks from 1."""
        t = self.window.t
        if place is None:
            return t("Whole song")
        first, last = place["row"], place["row"] + place["rows"] - 1
        rows = t("rows {first}-{last}", first=f"{first:02X}", last=f"{last:02X}") if place["rows"] > 1 \
            else t("row {row}", row=f"{first:02X}")
        channel = place["channel"] + 1
        channels = t("channels {first}-{last}", first=channel, last=channel + place["channels"] - 1) \
            if place["channels"] > 1 else t("channel {channel}", channel=channel)
        return " · ".join([t("Pattern {pattern}", pattern=f"{place['pattern']:02X}"), rows, channels])

    def comment_text(self, comment: dict) -> str:
        """The list entry: id, author, time and place, the text, then the replies and the resolution."""
        t = self.window.t
        head = " · ".join(part for part in (comment["id"], comment.get("author") or AUTHOR, local_time(comment.get("at")),
                                            self.place_text(comment.get("place"))) if part)
        lines = [head, comment["text"]]
        for reply in comment.get("replies", []):
            when = local_time(reply.get("at"))
            lines.append(f"  » {reply.get('author', '')}{' · ' + when if when else ''}: {reply.get('text', '')}")
        if comment["status"] == "resolved":
            lines.append(t("Resolved by {author}", author=comment.get("resolved_by") or "—"))
        return "\n".join(lines)

    def open_comments(self, pattern: int) -> list[dict]:
        return [item for item in self.store.comments if item["status"] == "open" and item.get("place")
                and item["place"]["pattern"] == pattern]

    def covering(self, pattern: int, row: int, channel: int) -> list[str]:
        """Ids of the open comments whose block covers this cell (the model's COMMENTS_ROLE)."""
        return [item["id"] for item in self.open_comments(pattern) if covers(item["place"], pattern, row, channel)]

    def tooltip(self, pattern: int, row: int, channel: int) -> str:
        here = [item for item in self.open_comments(pattern) if covers(item["place"], pattern, row, channel)]
        if not here:
            return ""
        lines = [self.window.t("Comments here:")]
        for item in here:
            lines.append(f"{item['id']} · {item.get('author') or AUTHOR}: {item['text']}")
            lines += [f"  » {reply.get('author', '')}: {reply.get('text', '')}" for reply in item.get("replies", [])]
        return "\n".join(lines)

    # --- display ---------------------------------------------------------------------
    def refresh(self):
        """Rebuild the list (open comments first), keep the selection, repaint the grid's markers."""
        window = self.window
        wanted = self.selected_id()
        comments = self.store.comments
        shown = [item for item in comments if item["status"] == "open"]
        if self.show_resolved.isChecked():
            shown += [item for item in comments if item["status"] == "resolved"]
        self.list.blockSignals(True)
        self.list.clear()
        for comment in shown:
            text = self.comment_text(comment)
            item = QListWidgetItem(text)
            item.setToolTip(text)
            item.setData(Qt.ItemDataRole.UserRole, comment["id"])
            self.list.addItem(item)
            if comment["id"] == wanted:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        count = self.open_count()
        self.header.setText(window.t("COMMENTS · {count} open", count=count) if count else window.t("COMMENTS"))
        self.hint.setVisible(False)
        self.update_target()
        self._buttons_state()
        window.table.viewport().update()
        if window.document:
            window._update_title()   # comments make the project unsaved (Document.dirty)
            window.live.context_changed()   # and the session's status says so (live status `dirty`)

    def retranslate(self):
        self.refresh()

    def compose_place(self) -> dict | None:
        """Where a message typed in the box goes: the grid selection when the box is ticked, else the whole song."""
        return self.selection_place() if self.at_selection.isChecked() else None

    def update_target(self):
        place = self.compose_place() if self.window.document else None
        self.target.setText("→ " + self.place_text(place))
        self.target.setToolTip(self.target.text())

    def send_compose(self, *_) -> dict | None:
        """Send the typed message as a comment (with the selection's place, or on the whole song)."""
        window = self.window
        text = self.compose.text().strip()
        if not text:
            return None
        if not window.document:
            window.message("Open a song first.", True)
            return None
        place = self.compose_place()
        result = self._run(lambda: self.store.add(text, place), "Comment added: {place}", place=self.place_text(place))
        if result is not None:
            self.compose.clear()
        return result

    def _buttons_state(self):
        comment = self.selected()
        self.go_button.setEnabled(bool(comment and comment.get("place")))
        self.reply_button.setEnabled(comment is not None)
        self.resolve_button.setEnabled(comment is not None)
        reopen = comment is not None and comment["status"] == "resolved"
        self.window._rebind(self.resolve_button, "Reopen" if reopen else "Resolve")

    def paint_markers(self, view):
        """A small corner triangle (accent colour, outlined in the background colour so it reads on a selected
        or highlighted cell too) on every visible cell covered by an open comment of the shown pattern."""
        model, window = view.model(), self.window
        if model is None or not window.document:
            return
        places = [item["place"] for item in self.open_comments(model.pattern)]
        top = view.rowAt(0)
        if not places or top < 0:
            return
        bottom = view.rowAt(view.viewport().height() - 1)
        bottom = model.rowCount() - 1 if bottom < 0 else bottom
        covered = {(row, channel) for place in places
                   for row in range(max(top, place["row"]), min(bottom, place["row"] + place["rows"] - 1) + 1)
                   for channel in range(place["channel"], min(place["channel"] + place["channels"], model.channels))}
        if not covered:
            return
        colors, width = window.palette_colors, len(model.parts)
        painter = QPainter(view.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(colors["bg"]), 1))
        painter.setBrush(QColor(colors["accent"]))
        for row, channel in covered:
            column = (channel + 1) * width - 1
            x = view.columnViewportPosition(column) + view.columnWidth(column) - 2
            y = view.rowViewportPosition(row) + 1
            painter.drawPolygon(QPolygon([QPoint(x - MARKER_PX, y), QPoint(x, y), QPoint(x, y + MARKER_PX)]))
        painter.end()

    def on_event(self, payload: dict):
        """A "comment" event from the live session: refresh, and name someone else's comment, reply or resolution."""
        self.refresh()
        comment, action = payload.get("comment") or {}, payload.get("action")
        if not comment or self.window.live.quiet:   # the window's own action announces itself
            return
        last = (comment.get("replies") or [{}])[-1]
        author = {"created": comment.get("author"), "replied": last.get("author"),
                  "resolved": comment.get("resolved_by")}.get(action)
        if author == AUTHOR:
            return
        texts = {"created": ("{author} commented: {snippet}", comment.get("text", "")),
                 "replied": ("{author} replied to {id}: {snippet}", last.get("text", "")),
                 "resolved": ("{author} resolved {id}", ""), "reopened": ("Comment {id} reopened", "")}
        if action in texts:
            text, snippet = texts[action]
            self.window.message(text, author=author or "?", id=comment.get("id", ""), snippet=snippet[:80])

    # --- actions ---------------------------------------------------------------------
    def ask_text(self, title: str, prompt: str) -> str | None:
        """The text typed in a small dialog, or None when cancelled (tests replace this method)."""
        text, ok = QInputDialog.getMultiLineText(self.window, title, prompt)
        return text if ok else None

    def _run(self, action, done: str, **values) -> dict | None:
        try:
            with self.window.live.silent():   # the session's event for this action must not announce it again
                result = action()
        except ValidationError as exc:
            self.window.message("Comment not saved: {detail}", True, detail=exc)
            return None
        self.refresh()
        self.window.message(done, **values)
        return result

    def selection_place(self) -> dict | None:
        window = self.window
        block = window.table.selection_block() if window.document else None
        if block is None:
            return None
        row, rows, channel, channels = block
        return {"pattern": window.pattern_model.pattern, "row": row, "rows": rows, "channel": channel,
                "channels": channels}

    def comment_selection(self, *_, text: str | None = None) -> dict | None:
        """Comment on the selection (Ctrl+M): attach a comment to the selected block of the grid, or to the current cell."""
        window = self.window
        if not window.document:
            window.message("Open a song first.", True)
            return None
        place = self.selection_place()
        if place is None:
            window.message("Select a cell or a block first.", True)
            return None
        if text is None:
            text = self.ask_text(window.t("Comment"), window.t("What should your agent look at here?") + "\n"
                                 + self.place_text(place))
        if text is None:
            return None
        return self._run(lambda: self.store.add(text, place), "Comment added: {place}", place=self.place_text(place))

    def comment_song(self, *_, text: str | None = None) -> dict | None:
        """"Comment on the whole song…": a comment without a place."""
        window = self.window
        if not window.document:
            window.message("Open a song first.", True)
            return None
        if text is None:
            text = self.ask_text(window.t("Comment"), window.t("What should your agent know about the whole song?"))
        if text is None:
            return None
        return self._run(lambda: self.store.add(text, None), "Comment added: {place}", place=window.t("Whole song"))

    def go_to(self, *_) -> bool:
        """Show the comment's pattern and select its block (clipped to what the pattern still holds)."""
        window, comment = self.window, self.selected()
        place = comment.get("place") if comment else None
        if place is None:
            return False
        module = window.document.module
        if place["pattern"] >= len(module.patterns):
            window.message("This place is no longer in the song.", True)
            return False
        window.show_pattern(place["pattern"])
        total = module.patterns[place["pattern"]].rows
        row, channel = min(place["row"], total - 1), min(place["channel"], module.channels - 1)
        rows, channels = max(1, min(place["rows"], total - row)), max(1, min(place["channels"], module.channels - channel))
        window.table.select_block(row, rows, channel, channels)
        window.table.setFocus()
        return True

    def reply_selected(self, *_, text: str | None = None) -> dict | None:
        comment = self.selected()
        if comment is None:
            return None
        if text is None:
            text = self.ask_text(self.window.t("Reply to {id}", id=comment["id"]), self.window.t("Your reply"))
        if text is None:
            return None
        return self._run(lambda: self.store.reply(comment["id"], text), "Reply sent to {id}", id=comment["id"])

    def resolve_selected(self, *_) -> dict | None:
        """Resolve the selected comment, or reopen it when it is resolved."""
        comment = self.selected()
        if comment is None:
            return None
        reopen = comment["status"] == "resolved"
        return self._run(lambda: self.store.resolve(comment["id"], reopen=reopen),
                         "Comment {id} reopened" if reopen else "Comment {id} resolved", id=comment["id"])

    def grid_menu(self) -> QMenu:
        """The grid's context menu: comment on the selection or the whole song, then the block edits."""
        window = self.window
        menu = QMenu(window.table)
        menu.addActions([action for action in (getattr(window, "comment_action", None),
                                               getattr(window, "song_comment_action", None)) if action is not None])
        edits = [getattr(window, name, None) for name in ("cut_action", "copy_action", "paste_action", "clear_action")]
        if any(edits):
            menu.addSeparator()
            menu.addActions([action for action in edits if action is not None])
        return menu

    def _grid_menu(self, position):
        menu = self.grid_menu()
        menu.exec(self.window.table.viewport().mapToGlobal(position))
        menu.deleteLater()
