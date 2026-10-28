"""Sound workshop, part 1: the sample editor and the levels view.

`SampleEditor` is the right half of the "Song samples" tab: a waveform with draggable loop handles and a
trim selection, numeric fields, fades, gain, volume and fine tune. Every change is previewed first (the
`sample_tools` report and an audition of the edited copy, the song untouched) and applied as exactly one
undoable `Document.patch`. Refusals from the core (`SAMPLE_LOOP`, `SAMPLE_CLIP`, `SAMPLE_SOURCE`, ...) are
shown as readable sentences, and the documented flags (`adapt`, `adjust_loop`, `allow_clip`, `allow_loop`)
are offered as explicit choices.

`LevelsPanel` lists each song sample's loudness against its role's target (`loudness.py`) with a Match button.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QSizePolicy, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QDoubleSpinBox,
                               QVBoxLayout, QWidget)

from . import loudness, sample_tools, synth_tools
from .desktop_widgets import XM_REFUSED_TIP, button as make_button, label
from .model import Sample, ValidationError

LEVEL_FLAG_DB = 6.0       # a sample this far from its role's target is flagged
HANDLE_GRAB_PX = 6


def even(value: int) -> int:
    return int(value) & ~1


class WaveEditor(QWidget):
    """Waveform of one sample with a loop (two draggable handles) and a trim selection (drag in the empty area).

    Positions are bytes of the PCM, always even. The widget only reports gestures (`loopChanged`,
    `selectionChanged`); the sample editor decides what they mean."""

    loopChanged = Signal(int, int)        # loop_start, loop_length (0: no loop)
    selectionChanged = Signal(int, int)   # start, end (equal: nothing selected)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.sample: Sample | None = None
        self.ghost: Sample | None = None      # the edited copy being previewed
        self.loop = (0, 0)
        self.selection = (0, 0)
        self._drag: str | None = None
        self._anchor = 0
        self.setMinimumHeight(96)
        self.setMouseTracking(True)
        self.setObjectName("waveEditor")

    # --- model ---------------------------------------------------------------------
    @property
    def count(self) -> int:
        return len(self.sample.pcm) if self.sample else 0

    def set_sample(self, sample: Sample | None):
        self.sample, self.ghost = sample, None
        self.loop = (sample.loop_start, sample.loop_length) if sample else (0, 0)
        self.selection = (0, 0)
        self.update()

    def set_ghost(self, sample: Sample | None):
        self.ghost = sample
        self.update()

    def set_loop(self, start: int, length: int):
        self.loop = (even(start), even(length))
        self.update()

    def set_selection(self, start: int, end: int):
        self.selection = (even(min(start, end)), even(max(start, end)))
        self.update()

    # --- geometry --------------------------------------------------------------------
    def _area(self) -> QRect:
        return self.rect().adjusted(10, 14, -10, -10)

    def x_at(self, position: int) -> int:
        area = self._area()
        return area.left() + round(area.width() * position / max(1, self.count))

    def byte_at(self, x: int) -> int:
        area = self._area()
        fraction = (x - area.left()) / max(1, area.width())
        return even(max(0, min(self.count, round(fraction * self.count))))

    def handle_at(self, x: int) -> str | None:
        """Which draggable edge is under `x`: "loop_start", "loop_end", "sel_start", "sel_end" or None."""
        candidates = []
        if self.loop[1]:
            candidates += [("loop_start", self.loop[0]), ("loop_end", self.loop[0] + self.loop[1])]
        if self.selection[0] != self.selection[1]:
            candidates += [("sel_start", self.selection[0]), ("sel_end", self.selection[1])]
        near = [(abs(self.x_at(position) - x), name) for name, position in candidates
                if abs(self.x_at(position) - x) <= HANDLE_GRAB_PX]
        return min(near)[1] if near else None

    # --- painting --------------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        colors = self.window.palette_colors
        painter.fillRect(self.rect(), QColor(colors["panel"]))
        area = self._area()
        painter.setPen(QPen(QColor(colors["border"]), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.drawLine(area.left(), area.center().y(), area.right(), area.center().y())
        if not self.sample or not self.sample.pcm:
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter,
                             self.window.t("Pick a sample in the list to edit its loop, trim, fades and gain."))
            return
        start, length = self.loop
        if length:
            painter.fillRect(QRect(self.x_at(start), area.top(), max(1, self.x_at(start + length) - self.x_at(start)),
                                   area.height()), QColor(colors["loop"]))
        low, high = self.selection
        if high > low:
            fill = QColor(colors["accent"])
            fill.setAlpha(55)
            painter.fillRect(QRect(self.x_at(low), area.top(), max(1, self.x_at(high) - self.x_at(low)), area.height()), fill)
        self._draw_wave(painter, self.sample, area, QColor(colors["accent"]), 1)
        if self.ghost is not None:
            self._draw_wave(painter, self.ghost, area, QColor(colors["warning"]), 1)
        if length:
            painter.setPen(QPen(QColor(colors["warning"]), 2))
            for position in (start, start + length):
                x = self.x_at(position)
                painter.drawLine(x, area.top() - 8, x, area.bottom())
                painter.fillRect(QRect(x - 3, area.top() - 10, 7, 7), QColor(colors["warning"]))
        if high > low:
            painter.setPen(QPen(QColor(colors["accent"]), 1, Qt.PenStyle.DashLine))
            for position in (low, high):
                painter.drawLine(self.x_at(position), area.top(), self.x_at(position), area.bottom())

    def _draw_wave(self, painter: QPainter, sample: Sample, area: QRect, color: QColor, width: int):
        painter.setPen(QPen(color, width))
        pcm = sample.pcm
        if not pcm:
            return
        scale, base = area.height() * 0.5 / (32768 if sample.bits == 16 else 128), area.center().y()
        buckets = max(1, min(area.width(), len(pcm)))
        span = area.width() * len(pcm) / max(1, self.count)   # a trimmed preview keeps its true share of the width
        for index, (low, high) in enumerate(sample_tools.waveform_summary(pcm, buckets)):
            x = area.left() + round(span * index / buckets)
            painter.drawLine(x, base - round(high * scale), x, base - round(low * scale) + (1 if high == low else 0))

    # --- mouse ---------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.count:
            return
        x = event.position().toPoint().x()
        handle = self.handle_at(x)
        if handle:
            self._drag = handle
            return
        self._drag, self._anchor = "select", self.byte_at(x)
        self.selection = (self._anchor, self._anchor)
        self.update()

    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if self._drag is None:
            near = self.handle_at(x)
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.CrossCursor)
            return
        position = self.byte_at(x)
        if self._drag == "select":
            self.set_selection(self._anchor, position)
            self.selectionChanged.emit(*self.selection)
        elif self._drag in ("loop_start", "loop_end"):
            start, length = self.loop
            end = start + length
            if self._drag == "loop_start":
                start = min(position, end - 4)
            else:
                end = max(position, start + 4)
            self.set_loop(max(0, start), end - max(0, start))
            self.loopChanged.emit(*self.loop)
        else:
            low, high = self.selection
            if self._drag == "sel_start":
                low = position
            else:
                high = position
            self.set_selection(low, high)
            self.selectionChanged.emit(*self.selection)

    def mouseReleaseEvent(self, event):
        self._drag = None

    def mouseDoubleClickEvent(self, event):
        self.set_selection(0, 0)
        self.selectionChanged.emit(0, 0)


def _spin(maximum: int, step: int = 2, name: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(0, max(0, maximum))
    box.setSingleStep(step)
    box.setAccelerated(True)
    if name:
        box.setObjectName(name)
    return box


class SampleEditor(QWidget):
    """Edit the sample selected in the song's sample list. See the module docstring."""

    OPS = {"loop": "sample_loop", "trim": "sample_trim", "gain": "sample_gain", "fade": "sample_fade"}
    LABELS = {"loop": "Set loop", "trim": "Trim sample", "gain": "Change gain", "fade": "Fade sample"}

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("sampleEditor")
        self.last_preview: dict | None = None
        self._loading = False
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        layout = QVBoxLayout()          # the waveform and what it says
        layout.setSpacing(6)
        outer.addLayout(layout, 1)
        self.title = window._label("Select a sample", "itemTitle")
        layout.addWidget(self.title)
        self.info = label("", "muted")
        self.info.setWordWrap(True)
        self.info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.info)
        self.wave = WaveEditor(window)
        layout.addWidget(self.wave, 1)
        selection = QHBoxLayout()
        selection.setSpacing(6)
        self.selection_buttons = []
        for text, callback, name in (("Loop = selection", self.loop_to_selection, "loopSelection"),
                                     ("No loop", self.no_loop, "noLoop"), ("Whole sample", self.reset_trim, "trimAll")):
            control = window._button(text, callback, name)
            control.setProperty("compact", True)
            selection.addWidget(control)
            self.selection_buttons.append(control)
        selection.addStretch()
        layout.addLayout(selection)
        self.report = QLabel()
        self.report.setObjectName("editReport")
        self.report.setWordWrap(True)
        self.report.setTextFormat(Qt.TextFormat.PlainText)
        self.report.setMinimumHeight(34)
        self.report.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.report)

        grid = QGridLayout()            # the numbers
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        outer.addLayout(grid)
        self.loop_start, self.loop_length = _spin(0, name="loopStart"), _spin(0, name="loopLength")
        self.trim_start, self.trim_end = _spin(0, name="trimStart"), _spin(0, name="trimEnd")
        self.gain_db = QDoubleSpinBox()
        self.gain_db.setObjectName("gainDb")
        self.gain_db.setRange(-24, 24)
        self.gain_db.setDecimals(1)
        self.gain_db.setSingleStep(0.5)
        self.gain_db.setSuffix(" dB")
        self.headroom = label("", "muted")
        self.fade_in, self.fade_out = _spin(0, 8, "fadeIn"), _spin(0, 8, "fadeOut")
        for box in (self.loop_start, self.loop_length, self.trim_start, self.trim_end, self.gain_db, self.fade_in,
                    self.fade_out):
            box.setMinimumWidth(104)
        rows = (("Loop", (self.loop_start, self.loop_length), "loop"), ("Trim", (self.trim_start, self.trim_end), "trim"),
                ("Gain", (self.gain_db, self.headroom), "gain"), ("Fade", (self.fade_in, self.fade_out), "fade"))
        self.listen, self.apply = {}, {}
        for row, (name, fields, kind) in enumerate(rows):
            caption = window._label(name, "muted")
            caption.setMinimumWidth(34)
            grid.addWidget(caption, row, 0)
            for column, field in enumerate(fields, 1):
                grid.addWidget(field, row, column)
            self.listen[kind] = window._button("Preview", lambda _=False, kind=kind: self.preview(kind), f"preview{kind.title()}")
            self.apply[kind] = window._button("Apply", lambda _=False, kind=kind: self.apply_edit(kind), f"apply{kind.title()}")
            self.listen[kind].setProperty("compact", True)
            self.apply[kind].setProperty("compact", True)
            self.apply[kind].setProperty("tone", "apply")   # the committing button of the pair: accent outline
            grid.addWidget(self.listen[kind], row, 3)
            grid.addWidget(self.apply[kind], row, 4)
        # volume and fine tune keep their original place (`TrackerWindow.sample_volume`, `.finetune`).
        self.volume = QSpinBox()
        self.volume.setRange(0, 64)
        self.volume.setObjectName("sampleVolume")
        self.finetune = QSpinBox()
        self.finetune.setRange(-8, 7)
        self.finetune.setObjectName("sampleFinetune")
        for box in (self.volume, self.finetune):
            box.setMinimumWidth(104)
        grid.addWidget(window._label("Volume", "muted"), 4, 0)
        grid.addWidget(self.volume, 4, 1)
        grid.addWidget(self.finetune, 4, 2)
        self.play_button = window._button("Play sample", window.play_sample, "playSample")
        self.apply_button = window._button("Apply", window.apply_sample, "applySample")
        self.apply_button.setProperty("compact", True)
        self.apply_button.setProperty("tone", "apply")
        self.play_button.setProperty("compact", True)
        grid.addWidget(self.play_button, 4, 3)
        grid.addWidget(self.apply_button, 4, 4)
        grid.setRowStretch(5, 1)

        self.wave.loopChanged.connect(self._wave_loop)
        self.wave.selectionChanged.connect(self._wave_selection)
        for box in (self.loop_start, self.loop_length):
            box.valueChanged.connect(self._loop_fields)
        for box in (self.trim_start, self.trim_end):
            box.valueChanged.connect(self._trim_fields)
        for box in (self.gain_db, self.fade_in, self.fade_out, self.loop_start, self.loop_length, self.trim_start,
                    self.trim_end):
            box.valueChanged.connect(self._clear_preview)
        self.retranslate()
        self.load()

    @staticmethod
    def _row_buttons(window, *buttons) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for text, callback, name in buttons:
            control = window._button(text, callback, name)
            control.setProperty("compact", True)
            row.addWidget(control)
        row.addStretch()
        return holder

    def retranslate(self):
        t = self.window.t
        self.loop_start.setPrefix(t("start "))
        self.loop_length.setPrefix(t("length "))
        self.trim_start.setPrefix(t("from "))
        self.trim_end.setPrefix(t("to "))
        self.finetune.setPrefix(t("fine tune "))
        self.fade_in.setPrefix(t("in "))
        self.fade_out.setPrefix(t("out "))
        for box, tip in ((self.loop_start, "Loop start in bytes (even). Drag the amber handles on the waveform."),
                         (self.loop_length, "Loop length in bytes (even, at least 4); 0 means no loop."),
                         (self.trim_start, "First byte kept. Drag in the waveform to select a range."),
                         (self.trim_end, "End of the kept range, in bytes (even)."),
                         (self.gain_db, "Gain in decibels. A gain that would clip is refused, with the clean headroom."),
                         (self.fade_in, "Bytes faded in from silence at the start."),
                         (self.fade_out, "Bytes faded out to silence at the end.")):
            box.setToolTip(t(tip))
        for kind in self.OPS:
            self.listen[kind].setToolTip(t("Hear the edited copy and read what would change. The song is not touched."))
            self.apply[kind].setToolTip(t("Apply as one undoable change (Ctrl+Z)."))
        if self.window.module_format == "xm":   # the core refuses these edits on an XM: say why on each control
            for control in self._edit_controls():
                control.setToolTip(t(XM_REFUSED_TIP))
        self.update_headroom()

    def _edit_controls(self) -> list[QWidget]:
        """What edits PCM or loops: refused by the core on an XM module."""
        return [self.wave, self.loop_start, self.loop_length, self.trim_start, self.trim_end, self.gain_db,
                self.fade_in, self.fade_out, *self.listen.values(), *self.apply.values(), *self.selection_buttons]

    def update_format(self):
        """Follow the open module's format: an XM keeps volume, fine tune (-128..127) and Play, and loses the edits."""
        xm = self.window.module_format == "xm"
        self.finetune.setRange(*((-128, 127) if xm else (-8, 7)))
        self.retranslate()
        self._enable()
        self._info(self.current()[1] if self.current() else None)

    def _enable(self):
        found = self.current()
        sample = found[1] if found else None
        editable = sample is not None and self.window.module_format != "xm"
        for control in self._edit_controls():
            control.setEnabled(editable)
        for control in (self.volume, self.finetune, self.play_button, self.apply_button):
            control.setEnabled(sample is not None)

    # --- the selected sample ---------------------------------------------------------
    def current(self) -> tuple[int, Sample] | None:
        window = self.window
        item = window.samples.currentItem()
        if not window.document or item is None:
            return None
        slot = item.data(Qt.ItemDataRole.UserRole) + 1
        return slot, window.document.module.samples[slot - 1]

    def load(self):
        """Show the selected sample: waveform, bytes, fields back to their neutral values."""
        found = self.current()
        self._loading = True
        sample = found[1] if found else None
        self.wave.set_sample(sample)
        count = len(sample.pcm) if sample else 0
        for box, value in ((self.loop_start, sample.loop_start if sample else 0),
                           (self.loop_length, sample.loop_length if sample else 0), (self.trim_start, 0),
                           (self.trim_end, count), (self.fade_in, 0), (self.fade_out, 0)):
            box.setRange(0, count)
            box.setValue(value)
        self.gain_db.setValue(0)
        self._enable()
        self._loading = False
        self.last_preview = None
        self.update_headroom()
        if sample is None:
            self.info.setText(self.window.t("This song has no samples yet: add one from the Sample library or the Create tab."))
            self.show_report("")
        else:
            self.show_report("")
        self._info(sample)

    def _info(self, sample: Sample | None):
        if sample is None:
            return
        looping = (self.window.t("loop {start} → {end}", start=sample.loop_start, end=sample.loop_start + sample.loop_length)
                   if sample.loop_length else self.window.t("no loop"))
        self.info.setText(self.window.sample_summary(sample, looping))

    def update_headroom(self):
        found = self.current()
        room = sample_tools.headroom_db(found[1].pcm) if found and self.window.module_format != "xm" else None
        self.headroom.setText(self.window.t("headroom {db:+.1f} dB", db=room) if room is not None else "")

    def show_report(self, text: str, error: bool = False):
        self.report.setText(text)
        self.report.setProperty("error", error)
        self.report.style().unpolish(self.report)
        self.report.style().polish(self.report)

    def _clear_preview(self, *_):
        if not self._loading:
            self.last_preview = None
            self.wave.set_ghost(None)

    # --- fields <-> waveform -----------------------------------------------------------
    def _wave_loop(self, start: int, length: int):
        self._loading = True
        self.loop_start.setValue(start)
        self.loop_length.setValue(length)
        self._loading = False
        self._clear_preview()

    def _wave_selection(self, start: int, end: int):
        self._loading = True
        self.trim_start.setValue(start if end > start else 0)
        self.trim_end.setValue(end if end > start else self.wave.count)
        self._loading = False
        self._clear_preview()

    def _loop_fields(self, *_):
        if not self._loading:
            self.wave.set_loop(self.loop_start.value(), self.loop_length.value())

    def _trim_fields(self, *_):
        if not self._loading:
            low, high = self.trim_start.value(), self.trim_end.value()
            self.wave.set_selection(low, high if (low, high) != (0, self.wave.count) else low)

    def loop_to_selection(self):
        low, high = self.wave.selection
        if high - low < 4:
            self.show_report(self.window.t("Drag across the waveform to select the part that should loop."))
            return
        self._wave_loop(low, high - low)
        self.wave.set_loop(low, high - low)

    def no_loop(self):
        self._wave_loop(0, 0)
        self.wave.set_loop(0, 0)

    def reset_trim(self):
        self.wave.set_selection(0, 0)
        self._wave_selection(0, 0)

    # --- candidates, previews, applying ---------------------------------------------------
    def operation(self, kind: str, flags: dict) -> dict:
        slot = self.current()[0]
        op = {"op": self.OPS[kind], "slot": slot}
        if kind == "loop":
            op.update(loop_start=even(self.loop_start.value()), loop_length=even(self.loop_length.value()))
        elif kind == "trim":
            op.update(start=even(self.trim_start.value()), end=even(self.trim_end.value()))
        elif kind == "gain":
            op["db"] = self.gain_db.value()
        else:
            op.update(fade_in=self.fade_in.value(), fade_out=self.fade_out.value())
        return {**op, **{key: True for key, on in flags.items() if on}}

    def candidate(self, kind: str, flags: dict) -> tuple[Sample, dict]:
        """The edited copy and its report, exactly as the patch operation would compute them."""
        slot, sample = self.current()
        sample_tools.guard_edit(self.window.document.module, sample, slot)
        op = self.operation(kind, flags)
        if kind == "loop":
            return sample_tools.with_loop(sample, op["loop_start"], op["loop_length"], op.get("adapt", False))
        if kind == "trim":
            return sample_tools.trim(sample, op["start"], op["end"], op.get("adjust_loop", False), op.get("adapt", False))
        if kind == "gain":
            return sample_tools.gain(sample, op["db"], op.get("allow_clip", False))
        return sample_tools.fade(sample, op["fade_in"], op["fade_out"], op.get("allow_loop", False))

    def describe(self, kind: str, report: dict) -> str:
        t = self.window.t
        extra = ""
        if report.get("adaptations"):
            extra = " · " + ", ".join(t(self.ADAPTATIONS.get(item, item)) for item in report["adaptations"])
        if kind == "loop":
            if not report["looped"]:
                return t("No loop afterwards: the sample plays once.") + extra
            return t("Loop {start} → {end} ({length} bytes) · jump at the seam {jump}",
                     start=report["loop_start"], end=report["loop_start"] + report["loop_length"],
                     length=report["loop_length"], jump=report["seam_jump"]) + extra
        if kind == "trim":
            return t("Keeps bytes {start} → {end}: {before} → {after} bytes", start=report["start"], end=report["end"],
                     before=report["bytes_before"], after=report["bytes"]) + extra
        if kind == "gain":
            return t("{db:+.1f} dB · peak {before} → {after} · {changed} bytes change · clipped {clipped}",
                     db=report["db"], before=report["peak_before"], after=report["peak_after"],
                     changed=report["changed_bytes"], clipped=report["clipped"])
        return t("Fade in {fade_in} · out {fade_out} bytes · {changed} bytes change", fade_in=report["fade_in"],
                 fade_out=report["fade_out"], changed=report["changed_bytes"])

    ADAPTATIONS = {"prepend-two-zero-bytes": "two zero bytes added at the start", "loop-shortened": "loop shortened",
                   "loop-removed": "loop removed"}

    # What to offer for a refusal: (flag, sentence about the problem, the choice).
    def refusal(self, kind: str, exc: ValidationError) -> tuple[str | None, str, str]:
        t, message = self.window.t, str(exc)
        if exc.code == "SAMPLE_SOURCE":
            return None, t("This project only allows samples from its declared source, so the sound cannot be edited this "
                           "way.") + " " + message.split(" Change the recipe")[0], ""
        if exc.code == "SAMPLE_CLIP":
            found = self.current()
            room = sample_tools.headroom_db(found[1].pcm) if found else None
            text = t("A gain of {db:+.1f} dB would push loud bytes past the 8-bit limit.", db=self.gain_db.value())
            if room is not None:
                text += " " + t("The largest clean gain is {room:+.1f} dB.", room=room)
            return "allow_clip", text, t("Apply it anyway and flatten (clip) the loudest bytes")
        if exc.code == "SAMPLE_LOOP":
            if "cuts the loop" in message:
                return "adjust_loop", t("The kept range cuts into the loop."), t("Keep only the part of the loop inside the range")
            if "reaches into the loop" in message:
                return "allow_loop", t("This fade reaches into the loop, so every repeat would dip."), \
                    t("Fade inside the loop anyway")
            if "first two bytes" in message:
                return "adapt", t("A sample without a loop must start with two silent bytes (the replayer's no-loop marker)."), \
                    t("Add two zero bytes in front; the sound itself stays exactly the same")
        return None, message, ""

    def _attempt(self, kind: str, action):
        """Run `action(flags)`; on a refusal that a documented flag can resolve, ask the owner and retry."""
        flags: dict = {}
        while True:
            try:
                return action(flags)
            except ValidationError as exc:
                flag, problem, choice = self.refusal(kind, exc)
                if flag and flag not in flags and self.ask_flag(problem, choice):
                    flags[flag] = True
                    continue
                self.show_report(problem + " " + self.window.t("Nothing was changed."), True)
                self.window.message(problem, True)
                return None

    def ask_flag(self, problem: str, choice: str) -> bool:
        window = self.window
        answer = QMessageBox.question(window, window.t("This edit needs a choice"), problem + "\n\n" + choice + "?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def preview(self, kind: str) -> dict | None:
        """Report and audition the edited copy; the document is not touched."""
        if self.current() is None:
            return None

        def run(flags):
            after, report = self.candidate(kind, flags)
            return after, report, flags

        found = self._attempt(kind, run)
        if found is None:
            self.last_preview = None
            self.wave.set_ghost(None)
            return None
        after, report, flags = found
        wav, _ = sample_tools.render_wav(after, "C-2", 1.0)
        self.last_preview = {"kind": kind, "sample": after, "report": report, "flags": flags, "wav": wav}
        self.wave.set_ghost(after)
        self.show_report(self.describe(kind, report))
        self.window.audition_wav(wav)
        return self.last_preview

    def apply_edit(self, kind: str) -> dict | None:
        """Apply the edit as one undoable patch. Returns the operation's result, or None when refused."""
        if self.current() is None:
            return None

        def run(flags):
            return self.window.run_patch([self.operation(kind, flags)], self.LABELS[kind]), flags

        found = self._attempt(kind, run)
        if found is None:
            return None
        result, _ = found
        report = result["results"][0]
        self.last_preview = None
        if not report.get("changed", True):
            self.show_report(self.window.t("Nothing changed: the sample already is like that."))
            return report
        self.show_report(self.window.t(self.LABELS[kind]) + " · " + self.window.t("applied, Ctrl+Z to undo"))
        self.window.message("{what} · Ctrl+Z to undo", what=self.window.t(self.LABELS[kind]))
        return report


class LevelsPanel(QWidget):
    """Loudness of every song sample against its role's target, with a Match button per sample."""

    COLUMNS = ("Slot", "Sample", "Role", "Level", "Target", "Difference", "")

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("levelsPanel")
        self._cache: dict = {}
        self._reference_cache: dict = {}
        self._stale = True
        self.rows: list[dict] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        top = QHBoxLayout()
        self.source = window._label("", "muted")
        self.source.setWordWrap(True)
        top.addWidget(self.source, 1)
        self.match_all = window._button("Match all", self.match_all_levels, "matchAll")
        self.match_all.setProperty("compact", True)
        top.addWidget(self.match_all)
        layout.addLayout(top)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("levelsTable")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.empty = window._label("Open a song with samples to see how loud each one is.", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty)
        self.legend = window._label("Differences above {limit} dB are flagged. Levels are the samples' own loudness at their "
                                    "volume, not a measurement of the mix.", "muted")
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.rebuild)
        self.retranslate()

    def retranslate(self):
        self.table.setHorizontalHeaderLabels([self.window.t(name) if name else "" for name in self.COLUMNS])
        self.legend.setText(self.window.t("Differences above {limit} dB are flagged. Levels are the samples' own loudness "
                                          "at their volume, not a measurement of the mix.", limit=f"{LEVEL_FLAG_DB:g}"))
        self.invalidate()

    # --- data --------------------------------------------------------------------------
    def reference(self) -> dict:
        """Targets: the sample bank in the Sample library tab when it exists, otherwise the built-in defaults."""
        path = self.window.sample_browser.library_path
        key = str(path)
        if key not in self._reference_cache:
            try:
                reference = synth_tools.resolve_reference("library" if synth_tools.library_exists(path) else "defaults", path)
            except (ValidationError, OSError, ValueError, KeyError):
                reference = synth_tools.resolve_reference("defaults")
            self._reference_cache = {key: reference}
        return self._reference_cache[key]

    def invalidate(self):
        """The song, the language or the bank changed: rebuild when the view is on screen."""
        self._stale = True
        if self.isVisible():
            self.timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if self._stale:
            self.rebuild()

    def measure(self, sample: Sample) -> dict:
        key = hash((sample.pcm, sample.loop_start, sample.loop_length, sample.volume))
        if key not in self._cache:
            self._cache = {**self._cache, key: loudness.measure(sample)} if len(self._cache) < 200 else {key: loudness.measure(sample)}
        return self._cache[key]

    def update_format(self):
        self.invalidate()

    def entries(self) -> list[dict]:
        window = self.window
        if not window.document or window.module_format == "xm":   # the targets are 8-bit MOD levels
            return []
        module, reference = window.document.module, self.reference()
        sources = module.metadata.get("sample_sources", {}) if isinstance(module.metadata, dict) else {}
        found = []
        for slot, sample in enumerate(module.samples, 1):
            if not sample.pcm:
                continue
            recorded = sources.get(str(slot)) if isinstance(sources, dict) else None
            role = loudness.sample_role(sample, recorded.get("role") if isinstance(recorded, dict) else None)
            level = self.measure(sample)["loudness_db"]
            target = loudness.target_db(role, reference)
            found.append({"slot": slot, "name": sample.name or f"Sample {slot}", "role": role, "level": level,
                          "target": target, "difference": round(level - target, 1),
                          "flagged": abs(level - target) > LEVEL_FLAG_DB})
        return found

    def rebuild(self):
        self._stale = False
        window = self.window
        self.rows = self.entries()
        reference = self.reference() if window.document else None
        if reference is not None:
            self.source.setText(window.t("Targets from the sample bank at {path}", path=self.window.sample_browser.library_path)
                                if reference["source"] == "library" else
                                window.t("Targets: built-in reference levels (no sample bank found; pick one in the Sample library tab)"))
        else:
            self.source.setText("")
        self.table.setRowCount(len(self.rows))
        colors = window.palette_colors
        for index, row in enumerate(self.rows):
            values = (f"{row['slot']:02X}", row["name"], window.t(row["role"].capitalize()), f"{row['level']:.1f} dB",
                      f"{row['target']:.1f} dB", (f"{row['difference']:+.1f} dB" + (" !" if row["flagged"] else "")))
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment((Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if column < 3
                                                                       else Qt.AlignmentFlag.AlignRight)))
                if row["flagged"] and column == 5:
                    item.setForeground(QColor(colors["warning"]))
                    item.setToolTip(window.t("More than {limit} dB from the target: use Match.", limit=f"{LEVEL_FLAG_DB:g}"))
                self.table.setItem(index, column, item)
            # Rebuilt with the table, so not one of the window's retranslated (bound) widgets.
            button = make_button(window.t("Match"), lambda _=False, slot=row["slot"]: self.match([slot]), f"match{row['slot']}")
            button.setProperty("compact", True)
            button.setToolTip(window.t("Set this sample's volume to its role's target level."))
            button.setEnabled(row["difference"] != 0)
            self.table.setCellWidget(index, 6, button)
        self.empty.setText(window.t("Levels are measured on 8-bit MOD samples: there is nothing to match in an XM module.")
                           if window.module_format == "xm" else
                           window.t("Open a song with samples to see how loud each one is."))
        self.empty.setVisible(not self.rows)
        self.table.setVisible(bool(self.rows))
        self.match_all.setEnabled(any(row["difference"] for row in self.rows))

    # --- matching ------------------------------------------------------------------------
    def match(self, slots: list[int], label: str = "Match level") -> dict | None:
        """One undoable patch matching `slots` to their targets (sample_match_level)."""
        window = self.window
        if not window.document or not slots:
            return None
        ops = [{"op": "sample_match_level", "slot": slot} for slot in slots]
        if self.reference()["source"] == "library":
            ops = [{**op, "library": str(window.sample_browser.library_path)} for op in ops]
        try:
            result = window.run_patch(ops, label)
        except ValidationError as exc:
            window.message("Cannot match the level: {detail}", True, detail=exc)
            return None
        changed = [item for item in result["results"] if item.get("changed")]
        window.message("Matched {count} sample levels · Ctrl+Z to undo", count=len(changed))
        return result

    def match_all_levels(self):
        return self.match([row["slot"] for row in self.rows], "Match all levels")


class SampleWorkshop(QWidget):
    """The "Song samples" tab body: the sample editor, and the levels view one click away."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.switch = switch = QHBoxLayout()   # placed by the window, under the sample list
        switch.setSpacing(6)
        self.edit_button = window._button("Edit", lambda: self.show_page(0), "pageEdit")
        self.levels_button = window._button("Levels", lambda: self.show_page(1), "pageLevels")
        for control in (self.edit_button, self.levels_button):
            control.setCheckable(True)
            control.setProperty("compact", True)
            switch.addWidget(control)
        switch.addStretch()
        self.pages = QStackedWidget()
        self.editor = SampleEditor(window)
        self.levels = LevelsPanel(window)
        self.pages.addWidget(self.editor)
        self.pages.addWidget(self.levels)
        layout.addWidget(self.pages, 1)
        self.show_page(0)

    def show_page(self, index: int):
        self.pages.setCurrentIndex(index)
        self.edit_button.setChecked(index == 0)
        self.levels_button.setChecked(index == 1)
        if index == 1:
            self.levels.rebuild()


__all__ = ["LevelsPanel", "SampleEditor", "SampleWorkshop", "WaveEditor", "even"]
