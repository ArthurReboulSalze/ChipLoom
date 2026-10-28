"""Keyboard note audition ("jam"): the two-row piano keys play the current sound as they are pressed.

Where the keys play what:
- the pattern, Edit mode on: the note is entered (as always) and heard with the sample it writes;
- the pattern, Edit mode off: the current instrument at the pressed pitch, nothing written;
- Song samples, Sample library, Create and Instruments (focus on a list, a button, the tab bar ... but not in a
  text field): the selected sample, library entry, recipe or instrument.

With the real-time engine a key starts a voice in the audio thread (`desktop_mixer`), so the sound follows the
key within a few tens of milliseconds, mixed with the song when it plays; a looped sample stops (10 ms fade) when
the key is released and a one-shot plays to its end. Without it the existing sample player takes over, one note
at a time. Key auto-repeat is ignored everywhere.
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QPlainTextEdit,
                               QTextEdit, QWidget)

from . import sample_tools
from .desktop_input import note_name, semitone
from .desktop_mixer import render_wav
from .desktop_widgets import media_call
from .model import Sample, ValidationError

FALLBACK_CACHE = 32
LOG_LIMIT = 200
OCTAVE_KEYS = {Qt.Key.Key_F1: 1, Qt.Key.Key_F2: 2, Qt.Key.Key_F3: 3}
TEXT_WIDGETS = (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)


class JamController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.log: list[dict] = []                 # every note started: key, note, sample name, source, engine
        self._held: dict[int, bool] = {}          # key -> its sample is looped (keys still down)
        self._wavs: OrderedDict = OrderedDict()   # fallback renders
        app = QApplication.instance()
        if app is not None:   # a key released after the focus moved must not leave a note ringing
            app.focusChanged.connect(lambda *_: self.release_all())

    def watch(self, widget: QWidget):
        """Listen to the keys of one widget. Filters sit on the widgets that can hold the focus on the sound pages
        (never on text fields, which keep their keys), not on the whole application: that would run Python for
        every event of every widget."""
        if not isinstance(widget, TEXT_WIDGETS) and widget is not self.window.instrument_panel.phrase:
            widget.installEventFilter(self)

    def watch_tree(self):
        """Watch the sound pages' widgets, the tab bar and the pattern grid (for key releases)."""
        window = self.window
        for _, page in self.pages():
            self.watch(page)
            for child in page.findChildren(QWidget):
                self.watch(child)
        self.watch(window.sample_tabs.tabBar())
        self.watch(window.table)

    # --- notes ----------------------------------------------------------------------
    def note_for(self, text: str) -> str | None:
        """The note a typed character plays at the current layout and base octave, or None."""
        offset = semitone(self.window.keyboard_layout(), text)
        return None if offset is None else note_name(self.window.edit_octave.value(), offset, self.window.module_format)

    def note_on(self, key: int, note: str, sample: Sample | None, source: str) -> bool:
        """Play `sample` at `note` for as long as `key` is held (looped samples)."""
        window = self.window
        if sample is None or not sample.pcm or note is None:
            return False
        looped = bool(sample.loop_length)
        rt = window.rt
        if key in self._held:
            self.note_off(key)
        fmt = window.module_format   # the notes are spelled, and tuned, for the open module's format
        if rt is not None:
            rt.jam_on(key, note, sample, sample.name, fmt)
        else:
            self._fallback_on(note, sample, fmt)
        self._held[key] = looped
        self.log.append({"key": key, "note": note, "name": sample.name, "looped": looped, "source": source,
                         "engine": "rt" if rt is not None else "fallback"})
        del self.log[:-LOG_LIMIT]
        return True

    def note_off(self, key: int) -> bool:
        looped = self._held.pop(key, None)
        if looped is None:
            return False
        if self.window.rt is not None:
            self.window.rt.jam_off(key)
        elif looped:
            media_call(self.window.sample_player, "stop")   # a one-shot is left to finish
        return True

    def release_all(self):
        for key in list(self._held):
            self.note_off(key)

    def _fallback_on(self, note: str, sample: Sample, fmt: str = "mod"):
        """No real-time engine: one rendered note at a time through the sample player."""
        key = (hash(sample.pcm), sample.loop_start, sample.loop_length, sample.volume, sample.finetune, note, fmt,
               sample.bits, sample.relative_note, sample.loop_mode)
        if key not in self._wavs:
            seconds = 1.5 if sample.loop_length else 2.0
            try:
                if fmt == "xm":
                    self._wavs[key] = render_wav(sample, note, fmt, seconds)
                else:
                    self._wavs[key] = sample_tools.render_wav(sample, note, seconds)[0]
            except ValidationError:
                return
            while len(self._wavs) > FALLBACK_CACHE:
                self._wavs.popitem(last=False)
        self.window.audition_wav(self._wavs[key])

    # --- what to play ------------------------------------------------------------------
    def song_sample(self, slot: int) -> Sample | None:
        window = self.window
        if not window.document or not 1 <= slot <= len(window.document.module.samples):
            return None
        sample = window.document.module.samples[slot - 1]
        return sample if sample.pcm else None

    def press_pattern(self, key: int, note: str, slot: int = 0, cell_sample: int = 0) -> bool:
        """The pattern's keys: the instrument chosen in the sample list (what Edit mode writes), else the cell's own."""
        return self.note_on(key, note, self.song_sample(slot or cell_sample), "pattern")

    def pages(self) -> tuple[tuple[str, QWidget], ...]:
        window = self.window
        return (("samples", window.song_samples_page), ("library", window.sample_browser),
                ("create", window.create_panel), ("instruments", window.instrument_panel))

    def context_of(self, widget: QWidget | None) -> str | None:
        """Which workshop page `widget` is in ("samples", "library", "create", "instruments"), or None.
        Text fields and the phrase grid keep their keys for typing."""
        window = self.window
        if widget is None or isinstance(widget, TEXT_WIDGETS) or widget is window.instrument_panel.phrase \
                or (isinstance(widget, QComboBox) and widget.isEditable()):
            return None
        if widget is window.sample_tabs.tabBar():
            current = window.sample_tabs.currentWidget()
            return next((name for name, page in self.pages() if current is page or current.isAncestorOf(page)), None)
        return next((name for name, page in self.pages() if widget is page or page.isAncestorOf(widget)), None)

    def context_sample(self, context: str) -> Sample | None:
        window = self.window
        if context == "samples":
            return self.song_sample(window.instrument_slot())
        if context == "library":
            return window.sample_browser.jam_sample()
        if context == "create":
            return window.create_panel.jam_sample()
        return window.instrument_panel.jam_sample()

    # --- keys outside the pattern (the pattern handles its own) -----------------------------
    def eventFilter(self, obj, event):
        kind = event.type()
        if kind not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        key = event.key()
        if kind == QEvent.Type.KeyRelease:
            if key in self._held and not event.isAutoRepeat():
                self.note_off(key)
            return False
        context = self.context_of(obj if isinstance(obj, QWidget) else None)
        if context is None or event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                                                   | Qt.KeyboardModifier.MetaModifier):
            return False
        window = self.window
        if key in OCTAVE_KEYS and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            window.edit_octave.setValue(OCTAVE_KEYS[key])
            return True
        if event.modifiers() & Qt.KeyboardModifier.KeypadModifier and key in (Qt.Key.Key_Plus, Qt.Key.Key_Minus):
            window.edit_octave.setValue(window.edit_octave.value() + (1 if key == Qt.Key.Key_Plus else -1))
            return True
        note = self.note_for(event.text())
        if note is None:
            if event.text().isprintable() and event.text() and semitone(window.keyboard_layout(), event.text()) is not None:
                return True       # a piano key outside C-1..B-3 at this octave: nothing plays, nothing types ahead
            return False
        if event.isAutoRepeat():
            return True
        self.note_on(key, note, self.context_sample(context), context)
        return True

