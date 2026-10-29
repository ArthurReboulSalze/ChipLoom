"""The ChipLoom desktop window (Qt Widgets, PySide6). All musical edits go through Document.

`TrackerWindow` is assembled from mixins, one module per responsibility; read the one for the feature at hand:

- desktop.py              `TrackerWindow.__init__` (state and attribute set-up, start-up order), the text-binding
                          helpers (`t`, `_bind`, `_rebind`...), the status line (`message`), background tasks
                          (`submit`), `keyboard_layout`, `closeEvent`; `application()` and `main()`.
- desktop_layout.py       `_build_ui`: every widget of the window, the splitters, the "?" shortcut popup.
- desktop_menus.py        the menu bar and its actions.
- desktop_preferences.py  language, theme, retranslation, saved and restored preferences.
- desktop_files.py        open, reload, save, export, the library panel, drag and drop.
- desktop_song.py         `refresh_document`, format-dependent labels, song-sample selection, Mute and Solo.
- desktop_transport.py    playback (real-time libxmp or rendered WAV), seeking, auditions, audio buffer.
- desktop_editing.py      undoable edits, Edit mode, undo/redo, agent changes saved to disk.
- desktop_collab.py       the window's side of the live session (desktop_live holds the session itself).

Panels and helpers that take the window as an argument live in the other desktop_*.py modules (pattern grid,
playback engine, live bridge, sample workshop, sample library, create, instruments, orders, jam, widgets...).
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QMainWindow

from . import __version__
from .desktop_browser import BrowserDialog
from .desktop_collab import CollaborationMixin
from .desktop_editing import EditingMixin
from .desktop_files import FileActionsMixin
from .desktop_input import resolve_layout
from .desktop_jam import JamController
from .desktop_layout import WindowLayoutMixin
from .desktop_live import LiveBridge
from .desktop_menus import MenuBarMixin
from .desktop_pattern import PatternModel, PatternView, input_locale_name
from .desktop_playback import RealtimeTransport, valid_buffer
from .desktop_preferences import PreferencesMixin
from .desktop_services import AppState, AudioCache
from .desktop_song import SongViewMixin
from .desktop_sync import DiskSync
from .desktop_transport import TransportMixin
from .desktop_widgets import (ASSETS, Task, TaskSignals, Waveform, brand_icon, button, clock, label, media_call,
                              sample_name)
from .document import Document
from .i18n import error_text, translate
from .level_meter import WavLevels
from .themes import THEMES, stylesheet

# Module-level names desktop.py defined before the split, still importable from here.
from .desktop_files import ROOT  # noqa: F401
from .desktop_layout import CENTER_GAP, PATTERN_HINT, SHORTCUTS, XM_PATTERN_HINT  # noqa: F401
from .desktop_menus import ABOUT_TEXT, BUFFER_LABELS  # noqa: F401
from .desktop_song import CLEAR_MONITOR_TIP  # noqa: F401

STYLE = stylesheet('midnight')
__all__ = ["ASSETS", "PatternModel", "PatternView", "STYLE", "Task", "TaskSignals", "TrackerWindow", "Waveform",
           "application", "brand_icon", "button", "clock", "label", "main", "sample_name"]


class TrackerWindow(WindowLayoutMixin, MenuBarMixin, PreferencesMixin, FileActionsMixin, SongViewMixin,
                    TransportMixin, EditingMixin, CollaborationMixin, QMainWindow):
    """The main window. Its methods are spread over the mixins listed in the module docstring."""

    def __init__(self, initial: Path | None = None, state_dir: Path | None = None, restore: bool = True):
        super().__init__()
        self.setObjectName("Tracker4Agents")
        self.setWindowTitle(f"ChipLoom {__version__}")
        self.setWindowIcon(brand_icon())
        self.resize(1420, 980)
        self.setMinimumSize(1080, 710)
        self.browser_dialog: BrowserDialog | None = None
        self.setAcceptDrops(True)
        state_dir = state_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        self.state = AppState(state_dir)
        self.language, self.theme = self.state.values["language"], self.state.values["theme"]
        self.palette_colors = THEMES[self.theme]
        self._bindings = []
        self._last_message = ("Ready", False, {})
        self.cache = AudioCache(state_dir / "audio-cache")
        self.document: Document | None = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._jobs, self._task_counter, self._audio_token = {}, 0, 0
        self._loading_audio = self._audio_ready = self._await_media = self._want_play = False
        self._resume_ms = 0
        self._last_position = -1
        self._loop_epoch = 0
        self._refreshing = False
        self._shown_format = None    # the module format the window is dressed for (see _format_changed)
        self.current_order = 0
        self.plan = {"timeline": [], "duration_seconds": 0}
        self.times = []
        self.player, self.sample_player = QMediaPlayer(self), QMediaPlayer(self)
        self.output, self.sample_output = QAudioOutput(self), QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.sample_player.setAudioOutput(self.sample_output)
        self.live = LiveBridge(self)
        self.monitor_module = None   # a take heard in place of the document (A/B comparison), else None
        self.rt: RealtimeTransport | None = None
        self.audio_buffer = valid_buffer(self.state.values.get("audio_buffer"))
        self._rt_notice = None
        self._build_ui()
        self.jam = JamController(self)
        self.jam.watch_tree()
        self._setup_realtime()
        self.sync = DiskSync(self)
        self._restore_edit_settings()
        self._restore_layout()
        self._connect_live()
        self.apply_theme()
        self.retranslate()
        # The meter reads the rendered WAVs being played; Qt's buffer output would call Python from its
        # audio thread, which can deadlock with QMediaPlayer.stop() (see WavLevels).
        self.wav_levels = ((self.player, WavLevels()), (self.sample_player, WavLevels()))
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.playbackStateChanged.connect(lambda _: self._transport_labels())
        self.player.errorOccurred.connect(lambda error, text: self._media_error(text))
        self.sample_player.errorOccurred.connect(lambda error, text: self.message("Sample: {detail}", True, detail=text))
        self.player.durationChanged.connect(lambda duration: self.seek.setMaximum(duration))
        self.timer = QTimer(self)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self._sync_position)
        self.timer.start()
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(350)
        self._debounce_play = False
        self.debounce.timeout.connect(self._debounced_audio)
        self._fill_library()
        self.volume.setValue(max(0, min(100, int(self.state.values.get("volume", 65)))))
        self._volume(self.volume.value())
        self.loop.setChecked(bool(self.state.values.get("loop", True)))
        self.follow.setChecked(bool(self.state.values.get("follow", True)))
        last = self.state.values.get("last_file")
        source = initial or (Path(last) if restore and isinstance(last, str) and Path(last).is_file() else None)
        source = source or self._default_piece()
        if source:
            QTimer.singleShot(0, lambda: self.open_document(source))
        self.table.setFocus()   # keys play and type in the grid from the start; no button shows a focus ring

    def t(self, source, **values):
        return translate(self.language, source, **values)

    def _bind(self, target, source, method="setText"):
        self._bindings.append((target, source, method))
        getattr(target, method)(self.t(source))
        return target

    def _label(self, source, name=""):
        return self._bind(label("", name), source)

    def _button(self, source, callback, name=""):
        return self._bind(button("", callback, name), source)

    def _action(self, source):
        return self._bind(QAction(self), source)

    def _menu_action(self, menu, source, callback, shortcut=None):
        action = self._action(source)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    def _rebind(self, target, source, method="setText"):
        """Change the text a widget is translated from (the window's bound texts follow the language)."""
        self._bindings = [item for item in self._bindings if not (item[0] is target and item[2] == method)]
        self._bind(target, source, method)

    def message(self, text: str, error: bool = False, **values):
        self._last_message = (text, error, values)
        self._show_message()

    def _show_message(self):
        text, error, values = self._last_message
        values = {key: error_text(self.language, value) if key == "detail" else value for key, value in values.items()}
        text = self.t(text, **values)
        if error:
            text = error_text(self.language, text)
        self.statusBar().setStyleSheet(f"color:{self.palette_colors['error']}" if error else "")
        self.statusBar().showMessage(text, 12000 if error else 7000)

    def submit(self, operation, success, failure=None):
        self._task_counter += 1
        token = self._task_counter
        task = Task(token, operation)
        self._jobs[token] = (task, success, failure)
        task.signals.finished.connect(self._task_done)
        task.signals.failed.connect(self._task_failed)
        self.pool.start(task)
        return token

    def _task_done(self, token, result):
        job = self._jobs.pop(token, None)
        if job:
            job[1](result)

    def _task_failed(self, token, text):
        job = self._jobs.pop(token, None)
        if job:
            job[2](text) if job[2] else self.message(text, True)

    # Kept in this module: tests patch `tracker4agents.desktop.input_locale_name`.
    def keyboard_layout(self) -> str:
        """The concrete piano map in use: "qwerty" or "azerty" (Auto follows the input locale)."""
        return resolve_layout(self.keyboard_combo.currentData(), input_locale_name())

    def closeEvent(self, event):
        if not self._discard_or_save():
            event.ignore()
            return
        self.debounce.stop()
        self.sync.stop()
        if self.browser_dialog is not None:
            self.browser_dialog.close()
        self.live.shutdown()
        self.sample_browser.shutdown()
        self._audio_token += 1
        self.timer.stop()
        media_call(self.player, "stop")
        media_call(self.player, "setSource", QUrl())
        if self.rt is not None:
            self.rt.shutdown()
        media_call(self.sample_player, "stop")
        media_call(self.sample_player, "setSource", QUrl())
        self.state.values.update(volume=self.volume.value(), loop=self.loop.isChecked(), follow=self.follow.isChecked(),
                                 theme=self.theme, language=self.language, keyboard=self.keyboard_combo.currentData(),
                                 edit_octave=self.edit_octave.value(), edit_step=self.edit_step.value(),
                                 live=self.live.enabled, audio_buffer=self.audio_buffer)
        try:
            self.state.save()
        except OSError:
            pass
        self.pool.waitForDone(3000)
        event.accept()


def application() -> QApplication:
    # Group native Windows taskbar windows as ChipLoom rather than Python.
    import sys
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ChipLoom.Desktop")
    # Qt Multimedia's FFmpeg backend prints version banners at debug/info level.
    os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*.debug=false;qt.multimedia.*.info=false")
    app = QApplication.instance() or QApplication(["tracker4agents"])
    app.setOrganizationName("tracker4agents")
    app.setApplicationName("tracker4agents")
    # Keep the data-directory identity so existing sessions survive the new name.
    app.setApplicationDisplayName("ChipLoom")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(brand_icon())
    app.setDesktopFileName("chiploom")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    return app


def main(source: Path | None = None, state_dir: Path | None = None, restore: bool = True) -> int:
    app = application()
    window = TrackerWindow(source, state_dir, restore)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
