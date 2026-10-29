"""Pattern grid: model, and a view with tracker keyboard entry and block editing.

Every musical change is a `Document.patch` transaction issued through
`TrackerWindow.apply_patch`; the model only displays (change highlights, proposal overlay, comment markers
and tooltips from `window.comment_panel`, see desktop_comments).
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import (QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, QRect, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QPushButton, QTableView, QWidget

from .desktop_comments import COMMENTS_ROLE
from .desktop_input import effect_letter, format_block, hex_digit, is_key_off, note_name, parse_block, semitone
from .model import XM_KEY_OFF_NAME, Cell, Module, ValidationError
from .patch import cell_text

FLASH_MS = 4000
# The columns of one channel: a MOD cell is note, sample, effect; an XM cell adds the volume column.
PARTS = {"mod": ("note", "sample", "effect"), "xm": ("note", "sample", "volume", "effect")}
HEADERS = {"mod": ("Note", "Smp", "Effect"), "xm": ("Note", "Ins", "Vol", "Effect")}
MIN_WIDTH = {"note": 58, "sample": 42, "volume": 42, "effect": 64}   # px; wider when the viewport has room
WEIGHT = {"note": 1.25, "sample": 1.0, "volume": 1.0, "effect": 1.25}
DRAG_SCROLL_MS = 45      # auto-scroll step while a dragged block waits near the top or bottom edge
DRAG_EDGE = 24           # px from the viewport edge where that scrolling starts
# Ctrl+wheel zooms the track columns sideways: a factor on the fitted widths, ZOOM_STEP per wheel notch,
# from ZOOM_NOTCHES[0] to ZOOM_NOTCHES[1] notches (about 0.5x to 2.4x).
ZOOM_STEP, ZOOM_NOTCHES = 1.1, (-7, 9)
ZOOM_MIN, ZOOM_MAX = ZOOM_STEP ** ZOOM_NOTCHES[0], ZOOM_STEP ** ZOOM_NOTCHES[1]
ZOOM_FLOOR = 0.75        # a zoomed-out column keeps this share of its natural width, so its text stays readable


def snap_zoom(zoom: float) -> float:
    """The nearest whole number of notches within the range: a way back always lands on exactly 1.0."""
    notches = round(math.log(zoom, ZOOM_STEP)) if zoom > 0 else ZOOM_NOTCHES[0]
    return ZOOM_STEP ** max(ZOOM_NOTCHES[0], min(ZOOM_NOTCHES[1], notches))


def valid_zoom(value) -> float:
    """A remembered column zoom, or 1.0 when the session holds something else."""
    return snap_zoom(value) if type(value) in (int, float) and math.isfinite(value) else 1.0


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
        self._laid_out = (0, 12)         # (rows, columns) the views were last told about
        self._flashes: dict[tuple[int, int, int], tuple[str, float]] = {}
        self._overlay: Module | None = None
        self._typing: tuple[int, int, str] | None = None

    # --- Qt model protocol ---------------------------------------------------------
    # --- the shape of what is shown: the module's format and channels, the pattern's rows ---------
    @property
    def module(self) -> Module | None:
        document = self.window.document
        return document.module if document else None

    @property
    def fmt(self) -> str:
        module = self.module
        return module.format if module else "mod"

    @property
    def channels(self) -> int:
        module = self.module
        return module.channels if module else 4

    @property
    def parts(self) -> tuple[str, ...]:
        return PARTS[self.fmt]

    @property
    def row_total(self) -> int:
        """Rows of the shown pattern (64 in a MOD, 1-256 in an XM)."""
        module = self.module
        return module.patterns[self.pattern].rows if module and self.pattern < len(module.patterns) else 0

    def channel_of(self, column: int) -> int:
        return column // len(self.parts)

    def part_of(self, column: int) -> str:
        return self.parts[column % len(self.parts)]

    def column_of(self, channel: int, part: str = "note") -> int:
        return channel * len(self.parts) + self.parts.index(part)

    def _shape(self) -> tuple[int, int]:
        return self.row_total, len(self.parts) * self.channels

    @staticmethod
    def field(value: Cell, part: str) -> str:
        """The text of one cell column."""
        if part == "note":
            return value.note or "---"
        if part == "sample":
            return f"{value.sample:02X}" if value.sample else "--"
        if part == "volume":
            return f"{value.volume:02X}" if value.volume else "--"
        return value.effect

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or not self.window.document else self.row_total

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.parts) * self.channels

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Vertical:
                return f"{section:02X}"
            return self.window.t(HEADERS[self.fmt][section % len(self.parts)])
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
        row, channel, part = index.row(), self.channel_of(index.column()), self.part_of(index.column())
        value = self._cell(row, channel)
        if value is None:
            return None
        colors = self.window.palette_colors
        if role == Qt.ItemDataRole.EditRole:
            return self.field(value, part)
        if role == Qt.ItemDataRole.DisplayRole:
            if self._typing and self._typing[:2] == (row, index.column()):
                return self._typing[2]
            return self.field(self.proposed(row, channel) or value, part)
        if role == Qt.ItemDataRole.ForegroundRole:
            audible = self.window.audible()
            return QColor(self.window.channel_color(channel) if channel < len(audible) and audible[channel]
                          else colors["disabled"])
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
        comments = getattr(self.window, "comment_panel", None)   # desktop_comments: markers and their text
        if role == COMMENTS_ROLE:
            return comments.covering(self.pattern, row, channel) if comments else []
        if role == Qt.ItemDataRole.ToolTipRole:
            if self.fmt == "xm":
                hint = self.window.t("Double-click to edit. Notes C-0..B-7, === is key off; instrument, volume and "
                                     "effect in hexadecimal (effect letters 0-9 then A-Z).")
            else:
                hint = self.window.t("Double-click to edit. Notes C-1..B-3; sample and effect in hexadecimal.")
            note = comments.tooltip(self.pattern, row, channel) if comments else ""
            return f"{note}\n\n{hint}" if note else hint
        return None

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        """Inline (double-click) editing of one field, as a single undoable patch."""
        if role != Qt.ItemDataRole.EditRole or not self.window.document:
            return False
        text = str(value).strip().upper()
        op = {"op": "set", "pattern": self.pattern, "row": index.row(), "channel": self.channel_of(index.column())}
        try:
            part = self.part_of(index.column())
            if part == "note":
                op["note"] = "---" if text in ("", "---") else XM_KEY_OFF_NAME if text in ("OFF", "KEY OFF") else text
            elif part == "sample":
                op["sample"] = int(text, 16) if text not in ("", "--") else 0
            elif part == "volume":
                op["volume"] = int(text, 16) if text not in ("", "--") else 0
            else:
                op["effect"] = text or "000"
            return self.window.apply_patch([op], "Edit cell")
        except (ValueError, TypeError) as exc:
            self.window.message(str(exc), error=True)
            return False

    # --- refresh and highlights ----------------------------------------------------
    def refresh_colors(self):
        """The mutes or the theme changed: repaint every cell's text and background."""
        rows, columns = self.rowCount(), self.columnCount()
        if self.window.document and rows and columns:
            self.dataChanged.emit(self.index(0, 0), self.index(rows - 1, columns - 1),
                                  [Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole])

    def _emit_all(self):
        rows, columns = self.rowCount(), self.columnCount()
        if self.window.document and rows and columns:
            self.dataChanged.emit(self.index(0, 0), self.index(rows - 1, columns - 1))

    def refresh(self, pattern: int | None = None):
        """Redraw. The selection and scroll position survive unless the document appears or vanishes."""
        if pattern is not None:
            if pattern != self.pattern:
                self._typing = None
            self.pattern = pattern
        shown, shape = bool(self.window.document), self._shape()
        if shown != self._shown or shape != self._laid_out:
            # A document appeared or vanished, or the grid changed shape (another pattern length, another
            # channel count or format): the views start over, as for any model with a new size.
            self.beginResetModel()
            self._shown, self._laid_out = shown, shape
            self._typing = None
            self.endResetModel()
        else:
            self._emit_all()

    def highlight(self, row: int):
        previous, self.playing_row = self.playing_row, row
        for changed in {previous, row}:
            if 0 <= changed < self.rowCount():
                self.dataChanged.emit(self.index(changed, 0), self.index(changed, self.columnCount() - 1),
                                      [Qt.ItemDataRole.BackgroundRole])

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
    """The tracker grid. Typing notes needs the window's Edit mode; block shortcuts always work.

    Any channel count and both cell shapes (MOD, XM) are shown: the columns keep their natural width and the
    grid scrolls sideways when the channels do not fit; `columnsChanged` tells the track headers above it
    where the channels are. Ctrl+wheel widens or narrows the columns (`column_zoom`, announced by `zoomChanged`)."""

    columnsChanged = Signal()
    zoomChanged = Signal(float)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.clipboard: tuple[str, list[list], str] | None = None   # grid text, the cells, their format
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setMinimumSectionSize(30)
        self.horizontalScrollBar().valueChanged.connect(lambda *_: self.columnsChanged.emit())
        self.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.setProperty("editMode", False)
        self._drag: dict | None = None   # a press on a selected block, until the button is released
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(DRAG_SCROLL_MS)
        self._drag_timer.timeout.connect(self._drag_autoscroll)
        self.column_zoom = 1.0
        self._wheel_rest = 0   # wheel delta below one notch, from touchpads that scroll in small steps

    def setModel(self, model):
        super().setModel(model)
        model.modelReset.connect(self.fit_columns)

    # --- columns ---------------------------------------------------------------------
    def fit_columns(self):
        """Columns at their natural width, widened to fill the viewport when the channels fit, then zoomed."""
        widths = self.column_widths(self.column_zoom)
        if not widths:
            return
        header = self.horizontalHeader()
        for column, width in enumerate(widths):
            if header.sectionSize(column) != width:
                header.resizeSection(column, max(1, width))
        self.columnsChanged.emit()

    def column_widths(self, zoom: float) -> list[int]:
        model = self.model()
        parts = model.parts if model else ()
        count = model.columnCount() if model else 0
        if not count:
            return []
        natural = sum(MIN_WIDTH[part] for part in parts) * model.channels
        available = self.viewport().width()
        equal, extra = divmod(available, count)
        if equal >= max(MIN_WIDTH.values()):
            # Room for every column at its widest: share the width evenly (the first columns take the remainder).
            widths = [equal + (1 if column < extra else 0) for column in range(count)]
        else:
            # Natural widths, widened in proportion when the channels fit, otherwise the grid scrolls sideways.
            scale = max(1.0, available / natural) if natural else 1.0
            widths = [round(MIN_WIDTH[parts[column % len(parts)]] * scale) for column in range(count)]
            if scale > 1.0:   # the last column takes the rounding error: the channels end at the viewport's edge
                widths[-1] += available - sum(widths)
        if zoom != 1.0:
            widths = [max(round(width * zoom), round(MIN_WIDTH[parts[column % len(parts)]] * ZOOM_FLOOR))
                      for column, width in enumerate(widths)]
        return widths

    def set_column_zoom(self, zoom: float, anchor: int | None = None) -> bool:
        """Zoom the columns, keeping the grid point under `anchor` (a viewport x) in place. False if nothing changed."""
        zoom = snap_zoom(zoom)
        if zoom == self.column_zoom:
            return False
        if zoom < self.column_zoom and self.column_widths(zoom) == self.column_widths(self.column_zoom):
            return False   # every column is at its floor: zooming out further would only store dead notches
        bar, header = self.horizontalScrollBar(), self.horizontalHeader()
        anchor = self.viewport().width() // 2 if anchor is None else anchor
        point, before = bar.value() + anchor, max(1, header.length())
        self.column_zoom = zoom
        self.fit_columns()
        self.updateGeometries()   # the scroll range follows the new widths before the grid is moved back
        bar.setValue(round(point * header.length() / before) - anchor)
        self.zoomChanged.emit(zoom)
        return True

    def wheelEvent(self, event):
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        delta = event.angleDelta()
        self._wheel_rest += delta.y() or delta.x()
        steps = int(self._wheel_rest / 120)
        if steps:
            self._wheel_rest -= steps * 120
            self.set_column_zoom(self.column_zoom * ZOOM_STEP ** steps, round(event.position().x()))
        event.accept()

    def scroll_to_row(self, row: int):
        """Bring a row into view without moving the grid sideways (the follow-playback scroll)."""
        model = self.model()
        if model is None or not 0 <= row < model.rowCount():
            return
        column = max(0, self.columnAt(self.viewport().width() // 2))   # a column that is on screen
        self.scrollTo(model.index(row, column), QAbstractItemView.ScrollHint.EnsureVisible)

    def channel_span(self, channel: int) -> tuple[int, int]:
        """(x, width) of one channel's columns in viewport coordinates (x may be negative when scrolled)."""
        model = self.model()
        width = len(model.parts)
        first, last = channel * width, (channel + 1) * width - 1
        x = self.columnViewportPosition(first)
        return x, self.columnViewportPosition(last) + self.columnWidth(last) - x

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_columns()

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_columns()

    # --- selection helpers ---------------------------------------------------------
    def selection_block(self) -> tuple[int, int, int, int] | None:
        """(row, rows, channel, channels) covered by the selection, or the current cell."""
        indexes = self.selectionModel().selectedIndexes() or [self.currentIndex()]
        indexes = [index for index in indexes if index.isValid()]
        if not indexes:
            return None
        model = self.model()
        rows, columns = [index.row() for index in indexes], [index.column() for index in indexes]
        first, last = model.channel_of(min(columns)), model.channel_of(max(columns))
        return min(rows), max(rows) - min(rows) + 1, first, last - first + 1

    def select_range(self, row: int, rows: int, first_column: int, last_column: int):
        model = self.model()
        top, bottom = model.index(row, first_column), model.index(row + rows - 1, last_column)
        self.selectionModel().setCurrentIndex(top, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selectionModel().select(QItemSelection(top, bottom), QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.scrollTo(top)

    def select_block(self, row: int, rows: int, channel: int, channels: int):
        width = len(self.model().parts)
        self.select_range(row, rows, channel * width, (channel + channels) * width - 1)

    def move_cursor_rows(self, delta: int):
        index = self.currentIndex()
        if index.isValid() and delta:
            last = self.model().row_total - 1
            self.setCurrentIndex(self.model().index(max(0, min(last, index.row() + delta)), index.column()))

    def focusOutEvent(self, event):
        self.window.jam.release_all()   # a key released elsewhere must not leave a note hanging
        super().focusOutEvent(event)

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
        fmt = self.model().fmt
        text = format_block(cells, fmt)
        self.clipboard = (text, cells, fmt)
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
        model = self.model()
        fmt, channels, total = model.fmt, model.channels, model.row_total
        try:
            if self.clipboard and (text == self.clipboard[0] or not text.strip()):
                if self.clipboard[2] != fmt:   # a MOD note and an XM note are not the same pitch
                    self.window.message("Cells copied from a {copied} module cannot be pasted into a {open} module.",
                                        error=True, copied=self.clipboard[2].upper(), open=fmt.upper())
                    return False
                cells = self.clipboard[1]
            elif text.strip():
                cells = parse_block(text, fmt, total, channels)
            else:
                self.window.message("Nothing to paste.")
                return False
        except ValidationError as exc:
            self.window.message(str(exc), error=True)
            return False
        row, channel = block[0], min(block[2], channels - len(cells[0]))
        cells = cells[:total - row]
        ops = [{"op": "write", "pattern": self._pattern, "row": row, "channel": channel + offset,
                "cells": [cell_text(line[offset], fmt) for line in cells]} for offset in range(len(cells[0]))]
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
        model = self.model()
        if not (0 <= target_row and target_row + rows <= model.row_total and 0 <= target_channel
                and target_channel + channels <= model.channels):
            self.window.message("The block is already at the edge of the pattern.")
            return False
        indexes = self.selectionModel().selectedIndexes() or [self.currentIndex()]
        first_column, last_column = min(i.column() for i in indexes), max(i.column() for i in indexes)
        ok = self.window.apply_patch([{"op": "move", "pattern": self._pattern, "row": row, "rows": rows,
                                       "channel": channel, "channels": channels, "to_row": target_row,
                                       "to_channel": target_channel}], "Move block")
        if ok:
            shift = len(model.parts) * delta_channels
            self.select_range(target_row, rows, first_column + shift, last_column + shift)
        return ok

    def transpose_block(self, semitones: int) -> bool:
        block = self.selection_block()
        if not block or not self.window.document:
            return False
        row, rows, channel, channels = block
        return self.window.apply_patch([{"op": "transpose", "pattern": self._pattern, "row": row, "rows": rows,
                                         "channel": channel, "channels": channels, "semitones": semitones}],
                                       "Transpose block")

    # --- dragging a block with the mouse -------------------------------------------
    # A press on a selected cell does not start a new selection: past the system drag distance the
    # selected block follows the pointer (a drop indicator shows where it lands) and is moved on
    # release, or copied when Ctrl is held. Below that distance it is an ordinary click. Presses on
    # unselected cells, Shift-clicks, double-clicks and row-number seeks keep their usual meaning.
    def block_dragging(self) -> bool:
        """True while a dragged block is being placed (a drop indicator is shown)."""
        drag = self._drag
        return bool(drag and drag["active"] and not drag["cancelled"])

    def drop_target(self) -> tuple[int, int] | None:
        """(row, channel) the dragged block would land on, or None."""
        return self._drag["target"] if self.block_dragging() else None

    def drop_rect(self) -> QRect | None:
        """Viewport rectangle of the drop indicator (the block at its target), or None."""
        target = self.drop_target()
        if target is None:
            return None
        _, rows, _, channels = self._drag["block"]
        model = self.model()
        width = len(model.parts)
        top = self.visualRect(model.index(target[0], target[1] * width))
        bottom = self.visualRect(model.index(target[0] + rows - 1, (target[1] + channels) * width - 1))
        return top.united(bottom)

    def mousePressEvent(self, event):
        self._drag_end()
        if (event.button() == Qt.MouseButton.LeftButton and self.window.document
                and event.modifiers() in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ControlModifier)):
            position = event.position().toPoint()
            index = self.indexAt(position)
            block = self.selection_block() if index.isValid() and self.selectionModel().isSelected(index) else None
            if block:
                selected = self.selectionModel().selection()
                columns = [i.column() for i in self.selectionModel().selectedIndexes()]
                super().mousePressEvent(event)   # focus and current cell, as for any click...
                self.selectionModel().select(selected, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self._drag = {"block": block, "columns": (min(columns), max(columns)), "start": position,
                              "selection": selected,
                              "pos": position, "pressed": index, "active": False, "cancelled": False,
                              "grab": (index.row() - block[0], self.model().channel_of(index.column()) - block[2]),
                              "target": None, "copy": False}   # ...but the block stays selected
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        drag = self._drag
        if drag is None:
            return super().mouseMoveEvent(event)
        event.accept()
        if drag["cancelled"]:
            return
        if not event.buttons() & Qt.MouseButton.LeftButton:
            return self._drag_end()
        drag["pos"] = event.position().toPoint()
        if not drag["active"]:
            if (drag["pos"] - drag["start"]).manhattanLength() < QApplication.startDragDistance():
                return
            drag["active"] = True
            self._drag_timer.start()
        self._drag_follow(bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier))

    def mouseReleaseEvent(self, event):
        drag = self._drag
        if drag is None:
            return super().mouseReleaseEvent(event)
        copy = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        dropping = drag["active"] and not drag["cancelled"] and event.button() == Qt.MouseButton.LeftButton
        self._drag_end()
        super().mouseReleaseEvent(event)
        if drag["active"]:   # releasing over the pressed cell would make it the selection: the block stays
            self.selectionModel().select(drag["selection"], QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if dropping:
            self._drop(drag, copy)
        elif not drag["active"] and not drag["cancelled"] and not copy:
            # A plain click on the block: it becomes the selection (what the press alone would have done).
            self.selectionModel().select(drag["pressed"], QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def _drag_follow(self, copy: bool):
        drag = self._drag
        drag["copy"] = copy
        index = self.indexAt(drag["pos"])
        if index.isValid():   # over the empty area the last target stays
            _, rows, _, channels = drag["block"]
            model = self.model()
            row = min(max(index.row() - drag["grab"][0], 0), model.row_total - rows)
            channel = min(max(model.channel_of(index.column()) - drag["grab"][1], 0), model.channels - channels)
            drag["target"] = (row, channel)
        self.viewport().setCursor(Qt.CursorShape.DragCopyCursor if copy else Qt.CursorShape.DragMoveCursor)
        self.viewport().update()

    def _drag_autoscroll(self):
        drag = self._drag
        if not self.block_dragging():
            return self._drag_timer.stop()
        bar, y = self.verticalScrollBar(), drag["pos"].y()
        if y < DRAG_EDGE:
            bar.setValue(bar.value() - 1)
        elif y > self.viewport().height() - DRAG_EDGE:
            bar.setValue(bar.value() + 1)
        else:
            return
        self._drag_follow(drag["copy"])

    def _drag_end(self, cancel: bool = False):
        """Leave dragging. With `cancel` the rest of the gesture is ignored until the button is released."""
        drag = self._drag
        self._drag_timer.stop()
        self.viewport().unsetCursor()
        if drag is not None:
            if cancel and drag["active"]:
                drag["cancelled"] = True
            else:
                self._drag = None
        self.viewport().update()

    def _drop(self, drag: dict, copy: bool) -> bool:
        target = drag["target"]
        row, rows, channel, channels = drag["block"]
        if target is None or target == (row, channel):
            return False   # dropped where it was: nothing moves, and a copy onto itself changes nothing
        op = {"op": "copy" if copy else "move", "pattern": self._pattern, "row": row, "rows": rows,
              "channel": channel, "channels": channels, "to_row": target[0], "to_channel": target[1]}
        if not self.window.apply_patch([op], "Copy block" if copy else "Move block"):
            return False
        shift = len(self.model().parts) * (target[1] - channel)
        self.select_range(target[0], rows, drag["columns"][0] + shift, drag["columns"][1] + shift)
        return True

    def _paint_channel_lines(self):
        """A line before every channel; the groups of four channels get a heavier one, as in the web studio."""
        model = self.model()
        if not model or model.channels < 2:
            return
        colors = self.window.palette_colors
        painter = QPainter(self.viewport())
        for channel in range(1, model.channels):
            x = self.columnViewportPosition(channel * len(model.parts))
            heavy = channel % 4 == 0
            painter.setPen(QPen(QColor(colors["muted" if heavy else "border"]), 2 if heavy else 1))
            painter.drawLine(x, 0, x, self.viewport().height())
        painter.end()

    def paintEvent(self, event):
        super().paintEvent(event)
        self._paint_channel_lines()
        comments = getattr(self.window, "comment_panel", None)
        if comments is not None:
            comments.paint_markers(self)   # corner marks on cells covered by an open comment
        rect = self.drop_rect()
        if rect is None:
            return
        copy, colors = self._drag["copy"], self.window.palette_colors
        color = QColor(colors["human_change"] if copy else colors["accent"])
        painter = QPainter(self.viewport())
        fill = QColor(color)
        fill.setAlpha(70)
        painter.fillRect(rect, fill)
        painter.setPen(QPen(color, 3, Qt.PenStyle.DashLine if copy else Qt.PenStyle.SolidLine))
        painter.drawRect(rect.adjusted(1, 1, -2, -2))
        # A small badge on the rectangle's edge names the gesture without hiding the cells under it.
        text = self.window.t("+ Copy" if copy else "Move")
        metrics = painter.fontMetrics()
        width, height = metrics.horizontalAdvance(text) + 12, metrics.height() + 2
        top = rect.top() - height if rect.top() >= height else rect.bottom() + 1
        badge = QRect(rect.left(), top, width, height)
        painter.fillRect(badge, color)
        painter.setPen(QColor(colors["bg"]))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

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
            if self._drag is not None and self._drag["active"]:
                self._drag_end(cancel=True)   # Esc abandons a drag in progress
                return self._done(event, True)
            self.model().clear_typing()
        if modifiers in (Qt.KeyboardModifier.NoModifier, shift):
            if self.window.edit_mode and not event.isAutoRepeat() and self._type(event):
                event.accept()
                return
            if not self.window.edit_mode and not event.isAutoRepeat() and self._jam(event):
                event.accept()
                return
            if event.text().isprintable() and event.text() and key != Qt.Key.Key_Space:
                # Outside Edit mode (or for unmapped keys) letters must not trigger the item
                # view's type-ahead search, which would move the cursor.
                event.accept()
                return
        super().keyPressEvent(event)

    def _jam(self, event) -> bool:
        """Edit mode off: a piano key plays the current instrument at that pitch and writes nothing."""
        window = self.window
        note = window.jam.note_for(event.text())
        if note is None or not window.document:
            return False
        index = self.currentIndex()
        under_cursor = window.document.module.patterns[self._pattern].get(
            index.row(), self.model().channel_of(index.column())).sample if index.isValid() else 0
        window.jam.press_pattern(event.key(), note, window.instrument_slot(), under_cursor)
        return True

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
        channel, part, fmt = model.channel_of(column), model.part_of(column), model.fmt
        base = {"op": "set", "pattern": model.pattern, "row": row, "channel": channel}
        key, text = event.key(), event.text()
        if key == Qt.Key.Key_Backspace:
            model.clear_typing()
            empty = {"note": {"note": "---"}, "sample": {"sample": 0}, "volume": {"volume": 0},
                     "effect": {"effect": "000"}}[part]
            if window.apply_patch([{**base, **empty}], "Clear field"):
                self.move_cursor_rows(-max(1, window.edit_step.value()))
            return True
        layout = window.keyboard_layout()
        if part == "note":
            if fmt == "xm" and is_key_off(layout, text):
                if window.apply_patch([{**base, "note": XM_KEY_OFF_NAME}], "Enter key off"):
                    self.move_cursor_rows(window.edit_step.value())
                return True
            offset = semitone(layout, text)
            if offset is None:
                return False
            note = note_name(window.edit_octave.value(), offset, fmt)
            if note is None:
                window.message("That key is outside the C-0..B-7 range at this octave." if fmt == "xm"
                               else "That key is outside the C-1..B-3 range at this octave.", error=True)
                return True
            slot = window.instrument_slot()
            under_cursor = window.document.module.patterns[self._pattern].get(row, channel).sample
            if window.apply_patch([{**base, "note": note, **({"sample": slot} if slot else {})}], "Enter note"):
                window.jam.press_pattern(event.key(), note, slot, under_cursor)   # and hear what was just written
                self.move_cursor_rows(window.edit_step.value())
            return True
        typing = model._typing and model._typing[:2] == (row, column)
        previous = model._typing[2].replace("_", "") if typing else ""
        digit = hex_digit(layout, text)
        if digit is None and part == "effect" and fmt == "xm" and not previous:
            digit = effect_letter(text)   # an XM effect starts with 0-9 or A-Z (G-Z: global volume, key off, ...)
        if digit is None:
            return False
        typed = previous + digit
        width = 3 if part == "effect" else 2
        if part == "sample" and len(typed) == 1 and typed not in ("012345678" if fmt == "xm" else "01"):
            typed = "0" + typed  # 2-F cannot start a MOD sample number (up to 1F), 9-F an instrument (up to 80)
        if len(typed) < width:
            model.set_typing(row, column, typed.ljust(width, "_"))
            return True
        model.clear_typing()
        operation = {"effect": typed} if part == "effect" else {part: int(typed, 16)}
        label = {"sample": "Enter instrument" if fmt == "xm" else "Enter sample", "volume": "Enter volume",
                 "effect": "Enter effect"}[part]
        if window.apply_patch([{**base, **operation}], label):
            self.move_cursor_rows(window.edit_step.value())
        return True


class TrackButton(QPushButton):
    """A Mute or Solo button. Ctrl+click does not toggle it: it emits `clearAll` (every track audible again)."""

    clearAll = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.accept()
            self.clearAll.emit()
            return
        super().mousePressEvent(event)


class ChannelStrip(QWidget):
    """The track headers above the grid: a Mute and a Solo button per channel, lined up with the channel's columns.

    Channels beyond the width of the window scroll with the grid. The buttons live in a child widget that covers
    the grid's viewport (not the row numbers), so a scrolled channel is clipped where the grid is."""

    HEIGHT = 32
    SOLO_WIDTH = 50

    def __init__(self, table: PatternView):
        super().__init__()
        self.table = table
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("channelStrip")
        self.clip = QWidget(self)
        self.groups: list[QWidget] = []
        table.columnsChanged.connect(self.relayout)

    def rebuild(self, count: int, states: list[tuple[bool, bool]], callback,
                clear_all=None) -> tuple[list[QPushButton], list[QPushButton]]:
        """Replace the buttons by `count` pairs, restoring `states` (muted, soloed) of the channels kept.
        `clear_all` is called on a Ctrl+click on any of them."""
        for group in self.groups:
            group.setParent(None)
            group.deleteLater()
        self.groups, mutes, solos = [], [], []
        for channel in range(count):
            group = QWidget(self.clip)
            row = QHBoxLayout(group)
            row.setContentsMargins(1, 2, 1, 2)   # the group is exactly as wide as the channel's columns
            row.setSpacing(2)
            mute, solo = TrackButton(), TrackButton()
            mute.setObjectName(f"muteTrack{channel + 1}")
            solo.setObjectName(f"soloTrack{channel + 1}")
            solo.setFixedWidth(self.SOLO_WIDTH)
            solo.setProperty("compact", True)   # the narrower padding of the compact buttons
            solo.setProperty("solo", True)      # a soloed track lights up in the warning colour
            for control in (mute, solo):
                control.setCheckable(True)
                control.setFocusPolicy(Qt.FocusPolicy.TabFocus)
                row.addWidget(control, 1 if control is mute else 0)
            if channel < len(states):
                mute.setChecked(states[channel][0])
                solo.setChecked(states[channel][1])
            for control in (mute, solo):
                control.toggled.connect(callback)
                if clear_all is not None:
                    control.clearAll.connect(clear_all)
            group.show()
            self.groups.append(group)
            mutes.append(mute)
            solos.append(solo)
        self.relayout()
        return mutes, solos

    def relayout(self):
        table = self.table
        viewport = table.viewport()
        self.clip.setGeometry(viewport.geometry().x(), 0, viewport.width(), self.HEIGHT)
        model = table.model()
        if model is None or model.channels != len(self.groups):
            return   # the grid still shows the previous module: the next layout of the columns follows
        for channel, group in enumerate(self.groups):
            x, width = table.channel_span(channel)
            group.setGeometry(x, 0, max(1, width), self.HEIGHT)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()
