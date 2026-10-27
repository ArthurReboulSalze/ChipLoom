"""Pattern grid: model, and a view with tracker keyboard entry and block editing.

Every musical change is a `Document.patch` transaction issued through
`TrackerWindow.apply_patch`; the model only displays (change highlights, proposal overlay).
"""

from __future__ import annotations

import time

from PySide6.QtCore import (QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, Qt,
                            QTimer)
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QTableView

from .desktop_input import format_block, hex_digit, note_name, parse_block, semitone
from .model import Module, ValidationError
from .patch import cell_text

FLASH_MS = 4000
ROWS, CHANNELS = 64, 4


def input_locale_name() -> str:
    """Locale of the active keyboard layout, used by the Auto keyboard setting."""
    try:
        return QGuiApplication.inputMethod().locale().name()
    except Exception:  # no input method in minimal or headless environments
        return ""


class PatternModel(QAbstractTableModel):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.pattern, self.playing_row = window, 0, -1
        self._shown = False
        self._flashes: dict[tuple[int, int, int], tuple[str, float]] = {}
        self._overlay: Module | None = None
        self._typing: tuple[int, int, str] | None = None

    # --- Qt model protocol ---------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or not self.window.document else ROWS

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 3 * CHANNELS

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Vertical:
                return f"{section:02X}"
            return self.window.t(("Note", "Smp", "Effect")[section % 3])
        return None

    def _cell(self, row: int, channel: int):
        patterns = self.window.document.module.patterns
        return patterns[self.pattern].get(row, channel) if self.pattern < len(patterns) else None

    def proposed(self, row: int, channel: int):
        """The overlay's cell when it differs from the document, otherwise None."""
        overlay = self._overlay
        if overlay is None or self.pattern >= len(overlay.patterns):
            return None
        current, other = self._cell(row, channel), overlay.patterns[self.pattern].get(row, channel)
        return other if other != current else None

    def _flash_kind(self, row: int, channel: int) -> str | None:
        entry = self._flashes.get((self.pattern, row, channel))
        return entry[0] if entry and entry[1] > time.monotonic() else None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not self.window.document:
            return None
        row, channel, part = index.row(), index.column() // 3, index.column() % 3
        value = self._cell(row, channel)
        if value is None:
            return None
        colors = self.window.palette_colors
        if role == Qt.ItemDataRole.EditRole:
            return (value.note or "---", f"{value.sample:02X}" if value.sample else "--", value.effect)[part]
        if role == Qt.ItemDataRole.DisplayRole:
            if self._typing and self._typing[:2] == (row, index.column()):
                return self._typing[2]
            shown = self.proposed(row, channel) or value
            return (shown.note or "---", f"{shown.sample:02X}" if shown.sample else "--", shown.effect)[part]
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor(colors["channels"][channel] if self.window.audible()[channel] else colors["disabled"])
        if role == Qt.ItemDataRole.BackgroundRole:
            kind = self._flash_kind(row, channel)
            if kind:
                return QColor(colors.get(kind, colors["accent"]))
            if self.proposed(row, channel) is not None:
                return QColor(colors.get("proposal", colors["accent"]))
            if row == self.playing_row:
                return QColor(colors["playing"])
            if row % 4 == 0:
                return QColor(colors["beat"])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.window.t("Double-click to edit. Notes C-1..B-3; sample and effect in hexadecimal.")
        return None

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """Inline (double-click) editing of one field, as a single undoable patch."""
        if role != Qt.ItemDataRole.EditRole or not self.window.document:
            return False
        text = str(value).strip().upper()
        op = {"op": "set", "pattern": self.pattern, "row": index.row(), "channel": index.column() // 3}
        try:
            part = index.column() % 3
            if part == 0:
                op["note"] = "---" if text in ("", "---") else text
            elif part == 1:
                op["sample"] = int(text, 16) if text not in ("", "--") else 0
            else:
                op["effect"] = text or "000"
            return self.window.apply_patch([op], "Edit cell")
        except (ValueError, TypeError) as exc:
            self.window.message(str(exc), error=True)
            return False

    # --- refresh and highlights ----------------------------------------------------
    def _emit_all(self):
        if self.window.document:
            self.dataChanged.emit(self.index(0, 0), self.index(ROWS - 1, 3 * CHANNELS - 1))

    def refresh(self, pattern: int | None = None):
        """Redraw. The selection and scroll position survive unless the document appears or vanishes."""
        if pattern is not None:
            if pattern != self.pattern:
                self._typing = None
            self.pattern = pattern
        shown = bool(self.window.document)
        if shown != self._shown:
            self.beginResetModel()
            self._shown = shown
            self._typing = None
            self.endResetModel()
        else:
            self._emit_all()

    def highlight(self, row: int):
        previous, self.playing_row = self.playing_row, row
        for changed in {previous, row}:
            if 0 <= changed < ROWS:
                self.dataChanged.emit(self.index(changed, 0), self.index(changed, 11), [Qt.ItemDataRole.BackgroundRole])

    def set_typing(self, row: int, column: int, text: str):
        self._typing = (row, column, text)
        self.dataChanged.emit(self.index(row, column), self.index(row, column))

    def clear_typing(self):
        if self._typing:
            row, column, _ = self._typing
            self._typing = None
            self.dataChanged.emit(self.index(row, column), self.index(row, column))

    # --- hooks for agent changes and proposals -------------------------------------
    def flash(self, cells, kind: str = "agent_change", duration_ms: int = FLASH_MS):
        """Highlight cells for a few seconds. Cells are `(pattern, row, channel)` tuples,
        `(row, channel)` of the shown pattern, or the dicts of `diff_modules()["cells"]`.
        `kind` is a theme color: agent_change, human_change or proposal."""
        deadline = time.monotonic() + duration_ms / 1000
        count = 0
        for item in cells:
            if isinstance(item, dict):
                key = (item["pattern"], item["row"], item["channel"])
            else:
                key = tuple(item) if len(item) == 3 else (self.pattern, *item)
            self._flashes[key] = (kind, deadline)
            count += 1
        if count:
            self._emit_all()
            QTimer.singleShot(duration_ms + 30, self._expire)

    def _expire(self):
        now = time.monotonic()
        stale = [key for key, (_, deadline) in self._flashes.items() if deadline <= now]
        for key in stale:
            del self._flashes[key]
        if stale:
            self._emit_all()

    def clear_flashes(self):
        if self._flashes:
            self._flashes.clear()
            self._emit_all()

    def flashed(self) -> dict[tuple[int, int, int], str]:
        """Cells currently highlighted, with their kind."""
        now = time.monotonic()
        return {key: kind for key, (kind, deadline) in self._flashes.items() if deadline > now}

    def set_overlay(self, module: Module | None):
        """Show a proposed module: differing cells display its text on the `proposal` color.
        Display only; the document is never touched."""
        self._overlay = module
        self._emit_all()

    @property
    def overlay(self) -> Module | None:
        return self._overlay


class PatternView(QTableView):
    """The tracker grid. Typing notes needs the window's Edit mode; block shortcuts always work."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.clipboard: tuple[str, list[list]] | None = None
        self.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.setProperty("editMode", False)

    # --- selection helpers ---------------------------------------------------------
    def selection_block(self) -> tuple[int, int, int, int] | None:
        """(row, rows, channel, channels) covered by the selection, or the current cell."""
        indexes = self.selectionModel().selectedIndexes() or [self.currentIndex()]
        indexes = [index for index in indexes if index.isValid()]
        if not indexes:
            return None
        rows, columns = [index.row() for index in indexes], [index.column() for index in indexes]
        first, last = min(columns) // 3, max(columns) // 3
        return min(rows), max(rows) - min(rows) + 1, first, last - first + 1

    def select_range(self, row: int, rows: int, first_column: int, last_column: int):
        model = self.model()
        top, bottom = model.index(row, first_column), model.index(row + rows - 1, last_column)
        self.selectionModel().setCurrentIndex(top, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selectionModel().select(QItemSelection(top, bottom), QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.scrollTo(top)

    def select_block(self, row: int, rows: int, channel: int, channels: int):
        self.select_range(row, rows, channel * 3, (channel + channels) * 3 - 1)

    def move_cursor_rows(self, delta: int):
        index = self.currentIndex()
        if index.isValid() and delta:
            self.setCurrentIndex(self.model().index(max(0, min(ROWS - 1, index.row() + delta)), index.column()))

    def currentChanged(self, current, previous):
        self.model().clear_typing()
        super().currentChanged(current, previous)

    def set_edit_mode(self, on: bool):
        self.setProperty("editMode", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)
        self.model().clear_typing()

    # --- block operations (each one patch transaction) -----------------------------
    @property
    def _pattern(self) -> int:
        return self.model().pattern

    def clear_block(self, label: str = "Clear cells") -> bool:
        block = self.selection_block()
        if not block or not self.window.document:
            return False
        row, rows, channel, channels = block
        return self.window.apply_patch([{"op": "clear", "pattern": self._pattern, "row": row, "rows": rows,
                                         "channel": channel, "channels": channels}], label)

    def _block_cells(self, block):
        row, rows, channel, channels = block
        pattern = self.window.document.module.patterns[self._pattern]
        return [[pattern.get(row + r, channel + c) for c in range(channels)] for r in range(rows)]

    def copy_block(self) -> bool:
        block = self.selection_block()
        if not block or not self.window.document:
            return False
        cells = self._block_cells(block)
        text = format_block(cells)
        self.clipboard = (text, cells)
        QGuiApplication.clipboard().setText(text)
        self.window.message("Copied {rows} × {channels} cells", rows=block[1], channels=block[3])
        return True

    def cut_block(self) -> bool:
        return self.copy_block() and self.clear_block("Cut cells")

    def paste_block(self) -> bool:
        """Paste the internal clipboard, or grid text from the system clipboard (what an agent printed)."""
        block = self.selection_block()
        if not block or not self.window.document:
            return False
        text = QGuiApplication.clipboard().text()
        try:
            if self.clipboard and text == self.clipboard[0]:
                cells = self.clipboard[1]
            elif text.strip():
                cells = parse_block(text)
            elif self.clipboard:
                cells = self.clipboard[1]
            else:
                self.window.message("Nothing to paste.")
                return False
        except ValidationError as exc:
            self.window.message(str(exc), error=True)
            return False
        row, channel = block[0], min(block[2], CHANNELS - len(cells[0]))
        cells = cells[:ROWS - row]
        ops = [{"op": "write", "pattern": self._pattern, "row": row, "channel": channel + offset,
                "cells": [cell_text(line[offset]) for line in cells]} for offset in range(len(cells[0]))]
        if not self.window.apply_patch(ops, "Paste cells"):
            return False
        self.select_block(row, len(cells), channel, len(cells[0]))
        return True

    def move_block(self, delta_rows: int, delta_channels: int) -> bool:
        """Move the selected block (patch `move`), keeping the selection on it."""
        block = self.selection_block()
        if not block or not self.window.document:
            return False
        row, rows, channel, channels = block
        target_row, target_channel = row + delta_rows, channel + delta_channels
        if not (0 <= target_row and target_row + rows <= ROWS and 0 <= target_channel
                and target_channel + channels <= CHANNELS):
            self.window.message("The block is already at the edge of the pattern.")
            return False
        indexes = self.selectionModel().selectedIndexes() or [self.currentIndex()]
        first_column, last_column = min(i.column() for i in indexes), max(i.column() for i in indexes)
        ok = self.window.apply_patch([{"op": "move", "pattern": self._pattern, "row": row, "rows": rows,
                                       "channel": channel, "channels": channels, "to_row": target_row,
                                       "to_channel": target_channel}], "Move block")
        if ok:
            self.select_range(target_row, rows, first_column + 3 * delta_channels, last_column + 3 * delta_channels)
        return ok

    def transpose_block(self, semitones: int) -> bool:
        block = self.selection_block()
        if not block or not self.window.document:
            return False
        row, rows, channel, channels = block
        return self.window.apply_patch([{"op": "transpose", "pattern": self._pattern, "row": row, "rows": rows,
                                         "channel": channel, "channels": channels, "semitones": semitones}],
                                       "Transpose block")

    # --- keyboard ------------------------------------------------------------------
    def keyPressEvent(self, event):
        key, modifiers = event.key(), event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        control, shift, alt = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.AltModifier
        if event.matches(QKeySequence.StandardKey.Copy):
            return self._done(event, self.copy_block())
        if event.matches(QKeySequence.StandardKey.Cut):
            return self._done(event, self.cut_block())
        if event.matches(QKeySequence.StandardKey.Paste):
            return self._done(event, self.paste_block())
        if key == Qt.Key.Key_Delete and modifiers == Qt.KeyboardModifier.NoModifier:
            return self._done(event, self.clear_block())
        if modifiers == alt and key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right):
            deltas = {Qt.Key.Key_Up: (-1, 0), Qt.Key.Key_Down: (1, 0), Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1)}
            return self._done(event, self.move_block(*deltas[key]))
        if modifiers in (control, control | shift) and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            amount = 12 if modifiers == control | shift else 1
            return self._done(event, self.transpose_block(amount if key == Qt.Key.Key_Up else -amount))
        if key in (Qt.Key.Key_F1, Qt.Key.Key_F2, Qt.Key.Key_F3) and modifiers == Qt.KeyboardModifier.NoModifier:
            self.window.edit_octave.setValue(key - Qt.Key.Key_F1 + 1)
            return self._done(event, True)
        if event.modifiers() & Qt.KeyboardModifier.KeypadModifier and key in (Qt.Key.Key_Plus, Qt.Key.Key_Minus):
            self.window.edit_octave.setValue(self.window.edit_octave.value() + (1 if key == Qt.Key.Key_Plus else -1))
            return self._done(event, True)
        if key == Qt.Key.Key_Escape:
            self.model().clear_typing()
        if modifiers in (Qt.KeyboardModifier.NoModifier, shift):
            if self.window.edit_mode and not event.isAutoRepeat() and self._type(event):
                event.accept()
                return
            if event.text().isprintable() and event.text() and key != Qt.Key.Key_Space:
                # Outside Edit mode (or for unmapped keys) letters must not trigger the item
                # view's type-ahead search, which would move the cursor.
                event.accept()
                return
        super().keyPressEvent(event)

    @staticmethod
    def _done(event, handled: bool):
        event.accept()
        return handled

    def _type(self, event) -> bool:
        """Edit-mode entry on the current cell. Returns True when the key was consumed."""
        window, model, index = self.window, self.model(), self.currentIndex()
        if not index.isValid() or not window.document:
            return False
        row, column = index.row(), index.column()
        channel, part = column // 3, column % 3
        base = {"op": "set", "pattern": model.pattern, "row": row, "channel": channel}
        key, text = event.key(), event.text()
        if key == Qt.Key.Key_Backspace:
            model.clear_typing()
            empty = ({"note": "---"}, {"sample": 0}, {"effect": "000"})[part]
            if window.apply_patch([{**base, **empty}], "Clear field"):
                self.move_cursor_rows(-max(1, window.edit_step.value()))
            return True
        layout = window.keyboard_layout()
        if part == 0:
            offset = semitone(layout, text)
            if offset is None:
                return False
            note = note_name(window.edit_octave.value(), offset)
            if note is None:
                window.message("That key is outside the C-1..B-3 range at this octave.", error=True)
                return True
            slot = window.instrument_slot()
            if window.apply_patch([{**base, "note": note, **({"sample": slot} if slot else {})}], "Enter note"):
                self.move_cursor_rows(window.edit_step.value())
            return True
        digit = hex_digit(layout, text)
        if digit is None:
            return False
        typed = (model._typing[2].replace("_", "") if model._typing and model._typing[:2] == (row, column) else "") + digit
        width = 2 if part == 1 else 3
        if part == 1 and len(typed) == 1 and typed not in "01":
            typed = "0" + typed  # 2-F cannot start a sample number up to 1F
        if len(typed) < width:
            model.set_typing(row, column, typed.ljust(width, "_"))
            return True
        model.clear_typing()
        operation = {"sample": int(typed, 16)} if part == 1 else {"effect": typed}
        if window.apply_patch([{**base, **operation}], "Enter sample" if part == 1 else "Enter effect"):
            self.move_cursor_rows(window.edit_step.value())
        return True
