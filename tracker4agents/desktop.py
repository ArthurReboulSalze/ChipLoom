"""Qt Widgets desktop application. All musical edits go through Document."""

from __future__ import annotations

import bisect
import copy
import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QModelIndex, QStandardPaths, Qt, QThreadPool, QTimer, QTranslator, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QFontDatabase, QKeySequence, QPalette, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
                               QFrame, QGridLayout, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QSlider,
                               QSpinBox, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import __version__, audio, formats, project
from .desktop_create import CreatePanel, scroll_page
from .desktop_instruments import InstrumentPanel
from .desktop_browser import BrowserDialog
from .desktop_workshop import SampleWorkshop
from .desktop_live import HUMAN_AUTHORS, AgentPanel, LiveBridge, status_label
from .desktop_input import LAYOUTS, resolve_layout, valid_layout
from .desktop_jam import JamController
from .desktop_orders import OrderEditor
from .desktop_playback import (BUFFER_CHOICES, LIBXMP_HINT, RealtimeTransport, unavailable_reason, valid_buffer)
from .desktop_pattern import ChannelStrip, PatternModel, PatternView, input_locale_name
from .desktop_samples import SampleBrowser
from .desktop_services import AppState, AudioCache
from .desktop_sync import DiskSync, changed_cells, mark_clean
from .desktop_widgets import (ASSETS, ElidedLabel, ShortcutPopup, Task, TaskSignals, Waveform, brand_icon, button,
                              clock, label, sample_name, separator, ui_icons)
from .document import Document
from .i18n import error_text, translate
from .level_meter import LevelMeter, WavLevels
from .model import playback_plan
from .realtime import RealtimeError
from .themes import THEMES, stylesheet
from .web.brand import MAX_CHANNELS, channel_color

ROOT = Path(__file__).resolve().parents[1]
STYLE = stylesheet('midnight')
ABOUT_TEXT = (
    "MOD and XM tracker.\n"
    "Double-click a cell to edit it, or turn on Edit mode (Ctrl+E) and play notes on the keyboard.\n"
    "Piano keys: lower row = base octave, upper row = the next one; F1-F3 or numpad +/- change the octave. "
    "In Smp and Effect columns type hexadecimal digits.\n"
    "The piano keys also play what they type: the current instrument with Edit mode off, the selected sound in "
    "Song samples, Sample library, Create and Instruments. Space still plays and pauses.\n"
    "Ctrl+C / X / V: copy, cut, paste cells (as grid text) · Del: clear · Alt+arrows: move the block · "
    "Ctrl+Up/Down: transpose (Shift: octave).\n"
    "The file reloads by itself when the agent saves it; F5 forces a reload.\n"
    "Click a track header to mute or unmute it; the grid scrolls sideways when the channels do not fit.\n"
    "An XM adds a volume column and key off (key 1, the key before 2, in Edit mode; === in a cell).\n"
    "Space in patterns: play/pause · Ctrl+Z: undo.\n"
    "Real-time playback uses libxmp (ProTracker mode) while exports use libopenmpt, so small differences in sound are expected.\n"
    "Four-channel ProTracker MOD, MOD with 2 to 32 channels and the FastTracker II XM profile; IT is planned.")
PATTERN_HINT = "Piano keys play the current instrument · Ctrl+E: Edit mode · Ctrl+C/X/V: blocks · Alt+arrows: move · Double-click: edit"
XM_PATTERN_HINT = "XM: Vol is the volume byte in hex (40 = full), effects run 0-9 then A-Z · key 1 enters key off (===)"
# The key reference behind the "?" button: (keys, what they do). The descriptions are translated when shown.
SHORTCUTS = (
    ("Piano keys", "Play the current instrument; in Edit mode they enter notes"),
    ("Ctrl+E", "Edit mode: hex digits also fill Smp and Effect"),
    ("Ctrl+C / X / V", "Copy, cut and paste a block of cells (as grid text)"),
    ("Del", "Clear the selected cells"),
    ("Alt+arrows", "Move the selected block (drag it too; Ctrl copies)"),
    ("Ctrl+↑ / ↓", "Transpose the selection (Shift: an octave)"),
    ("Double-click", "Edit a cell"),
    ("Row number", "Click to seek there"),
    ("Space", "Play / pause"),
    ("Ctrl+Z", "Undo"),
)
CENTER_GAP = 4   # px between the library panel's divider and the pattern/tabs column
BUFFER_LABELS = {"low": "Low · 80 ms", "normal": "Normal · 150 ms", "high": "High · 300 ms",
                 "very_high": "Very high · 600 ms"}
__all__ = ["ASSETS", "PatternModel", "PatternView", "STYLE", "Task", "TaskSignals", "TrackerWindow", "Waveform",
           "application", "brand_icon", "button", "clock", "label", "main", "sample_name"]




class TrackerWindow(QMainWindow):
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

    def set_language(self, language):
        if language in ("en", "fr") and language != self.language:
            self.language = language
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(self.language_combo.findData(language))
            self.language_combo.blockSignals(False)
            self.retranslate()
            self._save_preferences()

    def set_theme(self, theme):
        if theme in THEMES and theme != self.theme:
            self.theme = theme
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(self.theme_combo.findData(theme))
            self.theme_combo.blockSignals(False)
            self.apply_theme()
            self._save_preferences()

    def _save_preferences(self):
        self.state.values.update(language=self.language, theme=self.theme, volume=self.volume.value(),
                                 loop=self.loop.isChecked(), follow=self.follow.isChecked(),
                                 keyboard=self.keyboard_combo.currentData(), edit_octave=self.edit_octave.value(),
                                 edit_step=self.edit_step.value(), live=self.live.enabled,
                                 audio_buffer=self.audio_buffer)
        try:
            self.state.save()
        except OSError as exc:
            self.message("Session could not be saved: {detail}", True, detail=exc)

    def apply_theme(self):
        self.palette_colors = THEMES[self.theme]
        self.setStyleSheet(stylesheet(self.theme, ui_icons(self.theme)))
        palette = QPalette()
        for role, key in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
                          (QPalette.ColorRole.Base, "panel"), (QPalette.ColorRole.Text, "text"),
                          (QPalette.ColorRole.Button, "button"), (QPalette.ColorRole.ButtonText, "text"),
                          (QPalette.ColorRole.Highlight, "selected"), (QPalette.ColorRole.HighlightedText, "text")):
            palette.setColor(role, QColor(self.palette_colors[key]))
        self.setPalette(palette)
        self._monitor_style()
        self.waveform.update()
        self.sample_browser.waveform.update()
        self.meter.update()
        self._show_message()

    def retranslate(self):
        # Standard Qt dialogs follow the explicit application language as well.
        app = QApplication.instance()
        previous = getattr(app, "_tracker_translator", None)
        if previous:
            app.removeTranslator(previous)
            previous.deleteLater()
        app._tracker_translator = None
        if self.language == "fr":
            translator = QTranslator(app)
            if translator.load("qtbase_fr", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
                app.installTranslator(translator)
                app._tracker_translator = translator
        for target, source, method in self._bindings:
            getattr(target, method)(self.t(source))
        for index, theme in enumerate(THEMES.values()):
            self.theme_combo.setItemText(index, self.t(theme["name"]))
        self.keyboard_combo.setItemText(0, self.t("Auto"))
        self._fill_library()
        for widget, title in self.tab_titles.items():
            self.sample_tabs.setTabText(self.sample_tabs.indexOf(widget), self.t(title))
        self.sample_browser.retranslate()
        self.sample_workshop.editor.retranslate()
        self.sample_workshop.levels.retranslate()
        self.create_panel.retranslate()
        self.instrument_panel.retranslate()
        if self.browser_dialog is not None:
            self.browser_dialog.retranslate()
        self.agent_panel.retranslate()
        self._update_buffer_ui()
        self.live.update_status()
        if self.document:
            self._song_labels()
            self._sample_labels()
        self._show_format_label()
        self.sample_workshop.editor.update_format()
        self.create_panel.update_format()
        self.sample_workshop.levels.update_format()
        self.pattern_model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, max(0, self.pattern_model.columnCount() - 1))
        self.update_keys_hint()
        self._transport_labels()
        self._monitor_style()
        self.waveform.update()
        self._show_message()

    def _monitor_style(self):
        audible = self.audible()
        for channel, control in enumerate(self.mutes):
            muted = control.isChecked()
            control.setText(self.t("Track {number} · MUTED" if muted else "Track {number}", number=channel + 1))
            control.setToolTip(self.t("Click to unmute track {number}" if muted else "Click to mute track {number}", number=channel + 1))
            control.setAccessibleName(control.text())
            control.setProperty("trackMuted", not audible[channel])
            color = self.channel_color(channel) if audible[channel] else self.palette_colors["disabled"]
            control.setStyleSheet(f"border-left:3px solid {color};color:{color};padding:3px 6px")
            self.solos[channel].setText(self.t("Solo"))
            self.solos[channel].setToolTip(self.t("Solo track {number}", number=channel + 1))
        self.pattern_model.refresh_colors()

    def _build_ui(self):
        file_menu = self._bind(self.menuBar().addMenu(""), "File", "setTitle")
        edit_menu = self._bind(self.menuBar().addMenu(""), "Edit", "setTitle")
        playback_menu = self._bind(self.menuBar().addMenu(""), "Playback", "setTitle")
        agent_menu = self._bind(self.menuBar().addMenu(""), "Agent", "setTitle")
        help_menu = self._bind(self.menuBar().addMenu(""), "Help", "setTitle")
        self.open_action = self._action('Open a MOD or project…')
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.choose_file)
        file_menu.addAction(self.open_action)
        self.save_action = self._action('Save project…')
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_project)
        file_menu.addAction(self.save_action)
        save_as = self._action('Save project as…')
        save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as.triggered.connect(lambda: self.save_project(save_as=True))
        file_menu.addAction(save_as)
        reload_action = self._action('Reload file')
        reload_action.setShortcut("F5")
        reload_action.triggered.connect(self.reload_document)
        file_menu.addAction(reload_action)
        self.export_action = self._action('Export MOD…')
        self.export_action.setShortcut("Ctrl+Shift+E")
        self.export_action.triggered.connect(self.export_mod)
        file_menu.addAction(self.export_action)
        self._menu_action(file_menu, "Export WAV…", lambda: self.export_audio("wav"))
        self._menu_action(file_menu, "Export MP3…", lambda: self.export_audio("mp3"))
        file_menu.addSeparator()
        self._menu_action(file_menu, "Quit", self.close, QKeySequence.StandardKey.Quit)
        self.undo_action = self._action('Undo')
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action = self._action('Redo')
        self.redo_action.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        self.redo_action.triggered.connect(self.redo)
        edit_menu.addActions([self.undo_action, self.redo_action])
        edit_menu.addSeparator()
        self.edit_action = self._action("Edit mode")
        self.edit_action.setCheckable(True)
        self.edit_action.setShortcut("Ctrl+E")
        self.edit_action.toggled.connect(self.set_edit_mode)
        edit_menu.addAction(self.edit_action)
        edit_menu.addSeparator()
        # Block shortcuts live in the pattern view (so text fields keep their own copy/paste);
        # the menu shows them as hints and triggers the same methods.
        self.cut_action = self._menu_action(edit_menu, "Cut cells\tCtrl+X", lambda: self.table.cut_block())
        self.copy_action = self._menu_action(edit_menu, "Copy cells\tCtrl+C", lambda: self.table.copy_block())
        self.paste_action = self._menu_action(edit_menu, "Paste cells\tCtrl+V", lambda: self.table.paste_block())
        self.clear_action = self._menu_action(edit_menu, "Clear cells\tDel", lambda: self.table.clear_block())
        self.instrument_action = self._menu_action(edit_menu, "Apply instrument at cursor\tCtrl+I",
                                                   lambda: self.instrument_panel.apply_at_cursor())
        self.realtime_action = self._action("Real-time playback")
        self.realtime_action.setCheckable(True)
        self.realtime_action.toggled.connect(self.set_realtime)
        playback_menu.addAction(self.realtime_action)
        buffer_menu = self._bind(playback_menu.addMenu(""), "Audio buffer", "setTitle")
        buffer_menu.setToolTipsVisible(True)
        self.buffer_actions, group = {}, QActionGroup(self)
        for key, milliseconds in BUFFER_CHOICES:
            action = self._action(BUFFER_LABELS[key])
            action.setCheckable(True)
            action.setActionGroup(group)
            action.triggered.connect(lambda checked=False, key=key: self.set_audio_buffer(key))
            buffer_menu.addAction(action)
            self.buffer_actions[key] = action
        self.live_action = self._action("Live collaboration")
        self.live_action.setCheckable(True)
        self.live_action.setChecked(self.live.enabled)
        self.live_action.toggled.connect(self.set_live)
        agent_menu.addAction(self.live_action)
        agent_menu.addSeparator()
        self._menu_action(agent_menu, "Accept proposal\tCtrl+Enter", lambda: self.agent_panel.accept_selected())
        self._menu_action(agent_menu, "Reject proposal", lambda: self.agent_panel.reject_selected())
        self._menu_action(agent_menu, "Show the Agent tab",
                          lambda: self.sample_tabs.setCurrentIndex(self.sample_tabs.indexOf(self.agent_panel)))
        agent_menu.addSeparator()
        self.browser_action = self._menu_action(agent_menu, "Open in a browser\u2026", self.open_browser)
        self._menu_action(agent_menu, "Compare a take with the current song", lambda: self.agent_panel.toggle_compare(),
                          "Ctrl+B")
        self._menu_action(help_menu, "About", lambda: QMessageBox.information(
            self, "ChipLoom", f"ChipLoom {__version__}\n" + self.t(ABOUT_TEXT)))

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)
        # The header band reads top to bottom: the file (open, save, export) and the look of the window; the song's
        # identity (title, format, tempo); the transport.
        header = QFrame()
        header.setObjectName("header")
        head = QVBoxLayout(header)
        head.setContentsMargins(16, 10, 16, 10)
        head.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self._button('Open…', self.choose_file))
        top.addWidget(self._button('Save project…', self.save_project))
        top.addSpacing(6)
        top.addWidget(separator())
        top.addSpacing(6)
        self.export_button = self._button('Export MOD…', self.export_mod)
        top.addWidget(self.export_button)
        top.addWidget(self._button('Export WAV…', lambda: self.export_audio("wav"), "exportWav"))
        top.addWidget(self._button('Export MP3…', lambda: self.export_audio("mp3"), "exportMp3"))
        top.addStretch()
        top.addWidget(self._label("Theme", "muted"))
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("themeSelector")
        for key, theme in THEMES.items():
            self.theme_combo.addItem(self.t(theme["name"]), key)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.theme))
        self.theme_combo.currentIndexChanged.connect(lambda: self.set_theme(self.theme_combo.currentData()))
        top.addWidget(self.theme_combo)
        top.addSpacing(8)
        top.addWidget(self._label("Language", "muted"))
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("languageSelector")
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Français", "fr")
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
        self.language_combo.currentIndexChanged.connect(lambda: self.set_language(self.language_combo.currentData()))
        top.addWidget(self.language_combo)
        head.addLayout(top)

        song = QGridLayout()
        song.setHorizontalSpacing(8)
        song.setVerticalSpacing(2)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("songTitle")
        self.title_edit.setMaxLength(20)
        self.title_edit.setMinimumWidth(150)
        self._bind(self.title_edit, 'Untitled', 'setPlaceholderText')
        self._bind(self.title_edit, 'Title', 'setAccessibleName')
        song.addWidget(self.title_edit, 0, 0)
        self.format_label = self._label('MOD · 4 CHANNELS · PAL', "formatBadge")
        song.addWidget(self.format_label, 0, 1)
        song.addWidget(self._label('Tempo', "muted"), 0, 2)
        self.bpm = QSpinBox()
        self.bpm.setRange(33, 255)
        self.bpm.setFixedWidth(72)
        song.addWidget(self.bpm, 0, 3)
        song.addWidget(self._label('Ticks / row', "muted"), 0, 4)
        self.speed = QSpinBox()
        self.speed.setRange(1, 31)
        self.speed.setFixedWidth(64)
        song.addWidget(self.speed, 0, 5)
        song.addWidget(self._button('Apply at start', self.apply_song, "applySong"), 0, 6)
        details = QHBoxLayout()
        details.setContentsMargins(4, 0, 0, 0)
        details.setSpacing(8)
        self.origin = self._label("", "muted")
        details.addWidget(self.origin)
        details.addWidget(label("·", "muted"))
        self.summary = self._label('Open a module to get started', "muted")
        details.addWidget(self.summary)
        details.addStretch()
        song.addLayout(details, 1, 0, 1, 7)
        song.setColumnStretch(0, 1)
        head.addLayout(song)

        transport = QHBoxLayout()
        transport.setSpacing(8)
        self.play_button = self._button('Play', self.toggle_play, "primary")
        self.play_button.setEnabled(False)
        self.play_button.setMinimumWidth(92)
        self.stop_button = self._button('Stop', self.stop)
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addSpacing(4)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setObjectName("seek")
        self.seek.sliderMoved.connect(self.seek_to)
        transport.addWidget(self.seek, 1)
        self.position_label = self._label("00:00 / 00:48", "muted")
        self.position_label.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        transport.addWidget(self.position_label)
        transport.addSpacing(6)
        self.loop = self._bind(QCheckBox(), "Loop")
        transport.addWidget(self.loop)
        transport.addSpacing(6)
        transport.addWidget(self._label('Volume', "muted"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(95)
        self.volume.valueChanged.connect(self._volume)
        transport.addWidget(self.volume)
        transport.addSpacing(6)
        self.meter = LevelMeter(self)
        self._bind(self.meter, "Stereo audio level: average level and peak, after the volume control.", "setToolTip")
        transport.addWidget(self.meter)
        head.addLayout(transport)
        outer.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 12, 16, 8)
        outer.addWidget(body, 1)

        horizontal = QSplitter(Qt.Orientation.Horizontal)
        horizontal.setObjectName("workspace")
        body_layout.addWidget(horizontal, 1)
        library = QWidget()
        library.setMaximumWidth(250)
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(0, 0, 4, 0)
        self.brand = QLabel()
        self.brand.setObjectName("brandLogo")
        self.brand.setAccessibleName("ChipLoom")
        self.brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo = QPixmap(str(ASSETS / "chiploom-logo.png"))
        self.brand.setPixmap(logo.scaled(190, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
        library_layout.addWidget(self.brand)
        library_layout.addWidget(self._label('LIBRARY', "section"))
        self.library = QTreeWidget()
        self.library.setHeaderHidden(True)
        self.library.itemActivated.connect(self._library_open)
        self.library.setMinimumWidth(195)
        library_layout.addWidget(self.library)
        library_hint = self._label("MOD, XM and JSON projects\nDrop a file here to open it.\nF5 reloads changes made by the agent.", "muted")
        library_hint.setWordWrap(True)
        library_layout.addWidget(library_hint)
        horizontal.addWidget(library)

        center = QSplitter(Qt.Orientation.Vertical)
        # A comfortable gap between the library panel and the whole center column (pattern area and
        # bottom tabs alike): the splitter handle would otherwise touch their left edge.
        center_column = QWidget()
        center_layout = QVBoxLayout(center_column)
        center_layout.setContentsMargins(CENTER_GAP, 0, 0, 0)
        center_layout.addWidget(center)
        horizontal.addWidget(center_column)
        patterns_widget = QWidget()
        patterns_layout = QVBoxLayout(patterns_widget)
        patterns_layout.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        navigation.setSpacing(6)
        navigation.addWidget(self._label('Order', "muted"))
        self.orders = QComboBox()
        self.orders.setObjectName("orders")
        self.orders.currentIndexChanged.connect(self.select_order)
        self.orders.setMinimumWidth(170)
        navigation.addWidget(self.orders)
        self.order_editor = OrderEditor(self)
        self.order_editor.build(navigation)
        navigation.addStretch()
        self.follow = self._bind(QCheckBox(), "Follow playback")
        navigation.addWidget(self.follow)
        patterns_layout.addLayout(navigation)
        editing = QHBoxLayout()
        editing.setSpacing(6)
        self.edit_button = self._button("Edit mode", lambda: None, "editMode")
        self.edit_button.setCheckable(True)
        self.edit_button.toggled.connect(self.set_edit_mode)
        self._bind(self.edit_button, "Type notes with the piano keys (Ctrl+E)", "setToolTip")
        editing.addWidget(self.edit_button)
        editing.addSpacing(6)
        editing.addWidget(self._label("Step", "muted"))
        self.edit_step = QSpinBox()
        self.edit_step.setObjectName("editStep")
        self.edit_step.setRange(0, 16)
        self.edit_step.setValue(1)
        self._bind(self.edit_step, "Rows to advance after each entry", "setToolTip")
        editing.addWidget(self.edit_step)
        editing.addSpacing(6)
        editing.addWidget(self._label("Octave", "muted"))
        self.edit_octave = QSpinBox()
        self.edit_octave.setObjectName("editOctave")
        self.edit_octave.setRange(1, 3)
        self.edit_octave.setValue(2)
        self._bind(self.edit_octave, "Base octave of the lower key row (F1-F3, numpad + and -)", "setToolTip")
        editing.addWidget(self.edit_octave)
        editing.addSpacing(6)
        editing.addWidget(self._label("Keyboard", "muted"))
        self.keyboard_combo = QComboBox()
        self.keyboard_combo.setObjectName("keyboardLayout")
        for layout_name in LAYOUTS:
            self.keyboard_combo.addItem(layout_name.upper() if layout_name != "auto" else self.t("Auto"), layout_name)
        editing.addWidget(self.keyboard_combo)
        self.keys_hint = label("", "muted")
        editing.addSpacing(6)
        editing.addWidget(self.keys_hint)
        self.edit_octave.valueChanged.connect(self.update_keys_hint)
        self.keyboard_combo.currentIndexChanged.connect(self.update_keys_hint)
        for control in (self.edit_step, self.edit_octave):
            control.valueChanged.connect(lambda *_: self._save_preferences())
        self.keyboard_combo.currentIndexChanged.connect(lambda *_: self._save_preferences())
        editing.addStretch()
        editing.addWidget(self._button('− 1 semitone', lambda: self.transpose(-1)))
        editing.addWidget(self._button('+ 1 semitone', lambda: self.transpose(1)))
        patterns_layout.addLayout(editing)
        self.table = PatternView(self)
        self.channel_strip = ChannelStrip(self.table)   # Mute and Solo above each channel, scrolling with the grid
        self.mutes, self.solos = [], []
        self.set_channels(4)
        patterns_layout.addWidget(self.channel_strip)
        self.table.setObjectName("patterns")
        self.pattern_model = PatternModel(self)
        self.table.setModel(self.pattern_model)
        self.table.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.selectionModel().currentChanged.connect(self.cell_selected)
        self.table.verticalHeader().sectionClicked.connect(lambda row: self.seek_row(row))
        patterns_layout.addWidget(self.table)
        hint_row = QHBoxLayout()
        hint_row.setSpacing(8)
        self.pattern_hint = ElidedLabel("", "muted")
        self._bind(self.pattern_hint, PATTERN_HINT)
        self._bind(self.pattern_hint, PATTERN_HINT, "setToolTip")
        hint_row.addWidget(self.pattern_hint, 1)
        self.help_button = self._button("?", self.show_shortcuts, "helpButton")
        self._bind(self.help_button, "Keyboard shortcuts of the grid", "setToolTip")
        self._bind(self.help_button, "Keyboard shortcuts of the grid", "setAccessibleName")
        hint_row.addWidget(self.help_button)
        patterns_layout.addLayout(hint_row)
        self.shortcut_popup = ShortcutPopup(self, SHORTCUTS)
        self.xm_hint = ElidedLabel("", "muted")
        self._bind(self.xm_hint, XM_PATTERN_HINT)
        self._bind(self.xm_hint, XM_PATTERN_HINT, "setToolTip")
        self.xm_hint.hide()
        patterns_layout.addWidget(self.xm_hint)
        center.addWidget(patterns_widget)

        sample_widget = QWidget()
        sample_layout = QHBoxLayout(sample_widget)
        sample_layout.setContentsMargins(0, 4, 0, 0)
        sample_layout.setSpacing(14)
        sample_left = QVBoxLayout()
        sample_left.addWidget(self._label('SAMPLES', "section"))
        self.samples = QListWidget()
        self.samples.setObjectName("samples")
        self.samples.setMinimumWidth(195)
        self.samples.setMinimumHeight(45)
        self.samples.setMaximumWidth(280)
        self.samples.currentRowChanged.connect(self.sample_selected)
        self.samples.itemDoubleClicked.connect(lambda item: self.play_sample())
        sample_left.addWidget(self.samples)
        sample_layout.addLayout(sample_left)
        self.song_samples_page = sample_widget
        self.sample_workshop = SampleWorkshop(self)
        sample_left.addLayout(self.sample_workshop.switch)
        editor = self.sample_workshop.editor
        # The editor owns these widgets; the window keeps the names it always had for them.
        self.waveform, self.sample_title, self.sample_info = editor.wave, editor.title, editor.info
        self.sample_volume, self.finetune = editor.volume, editor.finetune
        sample_layout.addWidget(self.sample_workshop, 1)
        self.sample_tabs = QTabWidget()
        self.sample_tabs.setObjectName("sampleTabs")
        self.sample_browser = SampleBrowser(self, Waveform)
        self.create_panel = CreatePanel(self)
        self.instrument_panel = InstrumentPanel(self)
        self.agent_panel = AgentPanel(self)
        self.tab_titles = {}
        for widget, title, page in ((sample_widget, "Song samples", scroll_page(sample_widget)),
                                    (self.sample_browser, "Sample library", self.sample_browser),
                                    (self.create_panel, "Create", scroll_page(self.create_panel)),
                                    (self.instrument_panel, "Instruments", scroll_page(self.instrument_panel)),
                                    (self.agent_panel, "Agent", self.agent_panel)):
            self.sample_tabs.addTab(page, self.t(title))
            self.tab_titles[page] = title
        self.live_status = status_label()
        self.statusBar().addPermanentWidget(self.live_status)
        self.web_status = QLabel()
        self.web_status.setObjectName("webStatus")
        self.web_status.setTextFormat(Qt.TextFormat.PlainText)
        self.web_status.hide()
        self.statusBar().addPermanentWidget(self.web_status)
        self.sample_tabs.currentChanged.connect(lambda *_: self.sample_browser.cancel_preview())
        center.addWidget(self.sample_tabs)
        self.sample_tabs.setMinimumHeight(150)
        patterns_widget.setMinimumHeight(170)
        center.setChildrenCollapsible(False)
        center.setHandleWidth(9)
        center.setStretchFactor(0, 1)   # the grid takes what the window gains; the workshop keeps its size
        center.setStretchFactor(1, 0)
        center.setSizes([560, 300])
        self.center_splitter = center
        self._split_moved = False    # until the owner drags the divider, the workshop's height follows the window's
        center.splitterMoved.connect(lambda *_: setattr(self, "_split_moved", True))

        horizontal.setChildrenCollapsible(False)
        horizontal.setHandleWidth(9)
        horizontal.setSizes([210, 1175])
        horizontal.setStretchFactor(0, 0)
        horizontal.setStretchFactor(1, 1)
        self.message("Ready")
        self.play_action = QAction(self)
        self.play_action.setShortcut("Space")
        # Restrict Space to the pattern view: it must remain typeable in titles.
        self.play_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.play_action.triggered.connect(self.toggle_play)
        self.table.addAction(self.play_action)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_split)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_split)

    def _fit_split(self):
        """Give the grid what the window has: the workshop below it takes 170 to 340 px, whatever is left over
        beyond 300 px for the grid and its controls. Stops once the owner has moved the divider."""
        splitter = self.center_splitter
        total = splitter.height()
        if self._split_moved or total <= 0 or splitter.sizes()[1] == 0:
            return
        bottom = max(170, min(340, total - 300))
        if abs(splitter.sizes()[1] - bottom) > 1:
            splitter.setSizes([total - bottom - splitter.handleWidth(), bottom])

    def show_shortcuts(self):
        """The "?" next to the grid: the key reference, as a popup that closes with a click elsewhere."""
        self.shortcut_popup.show_under(self.help_button)
        return self.shortcut_popup

    def _default_piece(self):
        for candidate in (ROOT / "examples/pixel_rush.project.json", ROOT / "examples/first_light.project.json"):
            if candidate.is_file():
                return candidate
        return None

    def _fill_library(self):
        self.library.clear()
        compositions = QTreeWidgetItem(self.library, [self.t('Compositions')])
        for name, stem in (("First Light", "first_light"), ("Pixel Rush", "pixel_rush")):
            source = ROOT / "examples" / f"{stem}.project.json"
            if source.is_file():
                item = QTreeWidgetItem(compositions, [name])
                item.setData(0, Qt.ItemDataRole.UserRole, str(source))
        recent = QTreeWidgetItem(self.library, [self.t('Recent files')])
        for path in self.state.recent():
            item = QTreeWidgetItem(recent, [path.name])
            item.setToolTip(0, str(path))
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
        self.library.expandAll()

    def _library_open(self, item, column=0):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.open_document(Path(path))

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

    def _discard_or_save(self) -> bool:
        if not self.document or not self.document.dirty:
            return True
        answer = QMessageBox.question(self, self.t("Unsaved changes"), self.t('Save the project changes before continuing?'),
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            self.save_project()
            return not self.document.dirty
        return True

    def choose_file(self):
        source, _ = QFileDialog.getOpenFileName(self, self.t('Open a module or project'), str(ROOT / "exports"),
                                               self.t('Modules and projects (*.mod *.MOD *.xm *.XM *.json);;All files (*)'),
                                               options=QFileDialog.Option.DontUseNativeDialog)
        if source:
            self.open_document(Path(source))

    def reload_document(self):
        if self.document and self.document.path:
            self.open_document(self.document.path)

    def open_document(self, path: Path, ask: bool = True) -> bool:
        if ask and not self._discard_or_save():
            return False
        try:
            document = Document.open(path)
            plan = playback_plan(document.module)
        except (OSError, ValueError, RuntimeError) as exc:
            self.message("Cannot open: {detail}", True, detail=exc)
            return False
        self._install_document(document, plan)
        return True

    def open_module(self, module, path: Path | None = None) -> bool:
        """Open a module built in memory (a new project) as the window's document."""
        try:
            document = Document(module, path)
            plan = playback_plan(module)
        except (OSError, ValueError, RuntimeError) as exc:
            self.message("Cannot open: {detail}", True, detail=exc)
            return False
        self._install_document(document, plan)
        return True

    def _install_document(self, document: Document, plan):
        path = document.path
        self.stop()
        self.debounce.stop()
        self._audio_token += 1
        self.document, self.plan = document, plan
        self.agent_panel.end_compare(restore=False)
        self.pattern_model.clear_flashes()
        self.pattern_model.set_overlay(None)
        self.current_order = 0
        self._refreshing = True
        self.set_channels(document.module.channels)
        for control in self.mutes + self.solos:
            control.setChecked(False)
        self._refreshing = False
        if path is not None:
            self.state.remember(path)
            try:
                self.state.save()
            except OSError as exc:
                self.message("Session could not be saved: {detail}", True, detail=exc)
        self._fill_library()
        self.refresh_document()
        self.sync.watch(document.path, document.module)
        self.live.attach(document)
        self.prepare_audio(False, 0)

    def refresh_document(self):
        if not self.document:
            return
        self._refreshing = True
        module = self.document.module
        self.set_channels(module.channels)   # an agent can replace the module by one with other channels
        self._format_changed()
        self.plan = playback_plan(module)
        self.times = [entry["seconds"] for entry in self.plan["timeline"]]
        if self.rt is not None:
            self.seek.setMaximum(round(self.plan["duration_seconds"] * 1000))
        self.current_order = min(self.current_order, len(module.orders) - 1)
        self.title_edit.setText(module.title)
        initial = self.plan["timeline"][0]
        self.bpm.setValue(initial["bpm"])
        self.speed.setValue(initial["speed"])
        self._song_labels()
        self.orders.clear()
        for order, pattern in enumerate(module.orders):
            self.orders.addItem(f"{order:02X}  ·  {module.patterns[pattern].name or f'Pattern {pattern:02X}'}", pattern)
        self.orders.setCurrentIndex(self.current_order)
        # The model redraws in place, so the cursor, the block selection and the scroll position survive.
        self.pattern_model.refresh(module.orders[self.current_order])
        selected = self.samples.currentItem()
        selected_slot = selected.data(Qt.ItemDataRole.UserRole) if selected else 0
        self.samples.clear()
        wanted = 0
        for index, sample in enumerate(module.samples):
            if sample.pcm:
                item = QListWidgetItem(f"{index + 1:02X}  {sample_name(sample, index + 1)}")
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.samples.addItem(item)
                if index == selected_slot:
                    wanted = self.samples.count() - 1
        self.samples.setCurrentRow(wanted)
        self._refreshing = False
        self.sample_selected(self.samples.currentRow())
        self.cell_selected(self.table.currentIndex())
        self.sample_browser.update_slots()
        self.create_panel.refresh_slots()
        self.sample_workshop.levels.invalidate()
        self.undo_action.setEnabled(self.document.can_undo)
        self.redo_action.setEnabled(self.document.can_redo)
        self.order_editor.refresh()
        self._monitor_style()
        self._update_title()

    def _song_labels(self):
        module = self.document.module
        self.summary.setText(self.t("{bpm} BPM  ·  {orders} orders  ·  {samples} samples  ·  {seconds:.2f} s",
            bpm=self.plan["timeline"][0]["bpm"], orders=len(module.orders),
            samples=sum(bool(sample.pcm) for sample in module.samples), seconds=self.plan["duration_seconds"]))
        self.origin.setText(self.document.path.name if self.document.path else self.t("New project"))
        self.origin.setToolTip(str(self.document.path) if self.document.path else "")

    def _update_title(self):
        if self.document:
            hearing = f" [{self.t('listening to a take')}]" if self.monitor_module is not None else ""
            self.setWindowTitle(f"{'* ' if self.document.dirty else ''}{self.document.module.title}{hearing} — ChipLoom {__version__}")

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

    def audible(self):
        """One boolean per channel of the module: not muted, and soloed when any channel is."""
        solo = any(control.isChecked() for control in self.solos)
        return tuple(not mute.isChecked() and (not solo or self.solos[index].isChecked())
                     for index, mute in enumerate(self.mutes))

    def channel_color(self, channel: int) -> str:
        """The colour of a channel: the theme's four, then their tinted variants (the web studio's palette)."""
        return channel_color(self.theme, max(0, min(MAX_CHANNELS - 1, channel)))

    def set_channels(self, count: int):
        """One Mute and one Solo button per channel of the module above the grid, keeping the states of the
        channels both modules have."""
        if len(self.mutes) == count:
            return
        states = [(mute.isChecked(), solo.isChecked()) for mute, solo in zip(self.mutes, self.solos)]
        self.mutes, self.solos = self.channel_strip.rebuild(count, states, self.monitor_changed)

    @property
    def module_format(self) -> str:
        return self.document.module.format if self.document else "mod"

    def _rebind(self, target, source, method="setText"):
        """Change the text a widget is translated from (the window's bound texts follow the language)."""
        self._bindings = [item for item in self._bindings if not (item[0] is target and item[2] == method)]
        self._bind(target, source, method)

    def _format_changed(self):
        """What depends on the module's format: the export labels, the octave range, the hints and the sample
        operations an XM does not offer (the header line follows the channel count and is always refreshed)."""
        module = self.document.module if self.document else None
        self._show_format_label()
        if module is None or module.format == self._shown_format:
            return
        self._shown_format = module.format
        xm = module.format == "xm"
        self._rebind(self.export_action, "Export XM…" if xm else "Export MOD…")
        self._rebind(self.export_button, "Export XM…" if xm else "Export MOD…")
        self.xm_hint.setVisible(xm)
        low, high = (0, 7) if xm else (1, 3)
        if (self.edit_octave.minimum(), self.edit_octave.maximum()) != (low, high):
            value = self.edit_octave.value()
            if xm and value <= 3:
                value = 4    # the lower key row of an XM starts at C-4, middle C
            elif not xm and value > 3:
                value = 2
            self.edit_octave.blockSignals(True)
            self.edit_octave.setRange(low, high)
            self.edit_octave.setValue(value)
            self.edit_octave.blockSignals(False)
            self.update_keys_hint()
        self.sample_workshop.editor.update_format()
        self.sample_browser.update_controls()
        self.create_panel.update_format()
        self.instrument_panel.update_buttons()
        self.sample_workshop.levels.update_format()

    def _show_format_label(self):
        module = self.document.module if self.document else None
        if module is None:
            self.format_label.setText(self.t("MOD · 4 CHANNELS · PAL"))
            return
        text = self.t("{format} · {channels} CHANNELS", format=module.format.upper(), channels=module.channels)
        self.format_label.setText(text + (" · PAL" if module.format == "mod" else ""))

    def prepare_audio(self, play=False, position=0):
        if not self.document:
            return
        self.debounce.stop()
        self._audio_token += 1
        if self.rt is not None:
            try:
                self.rt.prepare(play, position)
            except RealtimeError as exc:
                self._realtime_failed(exc)
            else:
                self._loading_audio = self._await_media = self._want_play = False
                self._audio_ready = True
                self._resume_ms = position
                self.play_button.setEnabled(True)
                self.seek.setMaximum(round(self.plan["duration_seconds"] * 1000))
                self._transport_labels()
                self.message('Ready to play')
                return
        token = self._audio_token
        self._loading_audio, self._audio_ready, self._await_media = True, False, False
        self._last_position = -1  # the playhead jumps while a new render loads; that is not a seek
        self._want_play, self._resume_ms = play, position
        self.meter.reset()
        self.player.stop()
        self.player.setSource(QUrl())
        self.play_button.setText(self.t('Preparing…'))
        self.play_button.setEnabled(False)
        self.message('Preparing playback…')
        module, audible = self.listening_module(), self.audible()

        def operation():
            return self.cache.prepare(module, audible) if token == self._audio_token else None

        def success(path):
            if token != self._audio_token or path is None:
                return
            self._await_media = True
            self.player.setSource(QUrl.fromLocalFile(str(path)))

        def failure(text):
            if token == self._audio_token:
                self._loading_audio = False
                self.play_button.setText(self.t('Play'))
                self.play_button.setEnabled(True)
                self.message("Audio unavailable: {detail}", True, detail=text)

        self.submit(operation, success, failure)

    def _media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia and self.loop.isChecked() and self._audio_ready:
            # Let the backend finish its end-of-stream transition before seeking.
            # Reentrant restart here can leave Qt's renderer blocked on stop().
            token, epoch = self._audio_token, self._loop_epoch
            QTimer.singleShot(0, lambda: self._restart_loop(token, epoch))
            return
        if self._await_media and status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._await_media = False
            self._loading_audio, self._audio_ready = False, True
            self.player.setPosition(min(self._resume_ms, max(0, self.player.duration() - 1)))
            self.play_button.setEnabled(True)
            self._transport_labels()
            self.message(self._rt_notice or 'Ready to play')
            self._rt_notice = None  # the real-time notice is shown once
            if self._want_play:
                self.player.play()

    def _restart_loop(self, token, epoch):
        if (token == self._audio_token and epoch == self._loop_epoch
                and self._audio_ready and self.loop.isChecked()
                and self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia):
            self.meter.reset()
            self.player.setPosition(round(self.plan["loop_start_seconds"] * 1000))
            self.player.play()

    def _media_error(self, text):
        self._loading_audio = self._await_media = False
        self._audio_ready = False
        self.play_button.setText(self.t('Play'))
        self.play_button.setEnabled(self.document is not None)
        self.message("Playback failed: {detail}", True, detail=text)

    def _transport_labels(self):
        self.play_button.setText(self.t("Preparing…" if self._loading_audio else
            "Pause" if self.is_playing() else "Play"))

    def _volume(self, volume):
        self.output.setVolume(volume / 100)
        self.sample_output.setVolume(volume / 100)
        if self.rt is not None:
            self.rt.set_volume(volume / 100)

    def toggle_play(self):
        if not self.document or self._loading_audio:
            return
        self.sample_browser.cancel_preview()
        self.sample_player.stop()
        if self.rt is not None:
            self.rt.pause() if self.rt.playing else self.rt.play()
        elif not self._audio_ready:
            self.prepare_audio(True, self._resume_ms)
        elif self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        self.sample_browser.cancel_preview()
        self._loop_epoch += 1
        self._want_play = False
        self._resume_ms = 0
        self.player.stop()
        if self.rt is not None:
            self.rt.stop()
        self.sample_player.stop()
        self.meter.reset()

    def seek_to(self, milliseconds):
        self._loop_epoch += 1
        self.meter.reset()
        self._resume_ms = milliseconds
        if self.rt is not None:
            self.rt.seek_ms(milliseconds)
        elif self._audio_ready:
            self.player.setPosition(milliseconds)

    def seek_row(self, row):
        target = next((entry for entry in self.plan["timeline"] if entry["order"] == self.current_order and entry["row"] == row), None)
        if target:
            self.seek_to(round(target["seconds"] * 1000))

    def select_order(self, order):
        if self._refreshing or not self.document or order < 0:
            return
        self.current_order = order
        self.pattern_model.refresh(self.document.module.orders[order])
        self.order_editor.refresh()
        self.live.context_changed()
        target = next((entry for entry in self.plan["timeline"] if entry["order"] == order), None)
        if target:
            self.seek_to(round(target["seconds"] * 1000))
        else:
            self.message("This order is not reached in the module's playback cycle.")

    def _sync_position(self):
        playing = self.is_playing()
        active = (playing or self.sample_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                  or (self.rt is not None and self.rt.jam_active))
        marker = None
        if self.rt is not None:
            levels = self.rt.heard_levels()   # the song's, or the notes played from the keyboard
            if levels:
                self.meter.feed_levels(*levels)
        for player, wav in self.wav_levels:
            if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                levels = wav.at(player.source().toLocalFile(), player.position())
                if levels:
                    self.meter.feed_levels(*levels)
                break
        self.meter.tick(active, self.volume.value() / 100)
        if not self.document or self._loading_audio:
            return
        if self.rt is not None:
            milliseconds, marker = self.rt.heard()
            duration = round(self.plan["duration_seconds"] * 1000)
        else:
            milliseconds, duration = self.player.position(), self.player.duration()
        if not self.seek.isSliderDown():
            self.seek.setValue(milliseconds)
        self.position_label.setText(f"{clock(milliseconds)} / {clock(duration)}")
        if not self.times:
            return
        # In real-time mode the row comes from the marker of the audio being heard, not from the clock.
        entry = marker or self.plan["timeline"][max(0, bisect.bisect_right(self.times, milliseconds / 1000) - 1)]
        # Follow the playhead while it moves (playing or seeking), but let a paused view be browsed
        # and edited: order edits and agent selections must not be pulled back to the playhead.
        moving = (self._last_position >= 0 and milliseconds != self._last_position) or playing
        self._last_position = milliseconds
        if self.follow.isChecked() and moving and entry["order"] != self.current_order:
            self._refreshing = True
            self.current_order = entry["order"]
            self.orders.setCurrentIndex(self.current_order)
            self.pattern_model.refresh(entry["pattern"])
            self.order_editor.refresh()
            self._refreshing = False
        if entry["pattern"] == self.pattern_model.pattern:
            self.pattern_model.highlight(entry["row"])
            if self.follow.isChecked() and playing:
                self.table.scroll_to_row(entry["row"])   # vertically only: a grid scrolled sideways stays where it is

    def cell_selected(self, index, previous=QModelIndex()):
        if not self.document or not index.isValid():
            return
        if self.edit_mode:
            return  # while typing, the instrument is the one chosen in the sample list
        value = self.document.module.patterns[self.pattern_model.pattern].get(
            index.row(), self.pattern_model.channel_of(index.column()))
        if value.sample:
            for row in range(self.samples.count()):
                if self.samples.item(row).data(Qt.ItemDataRole.UserRole) == value.sample - 1:
                    self.samples.setCurrentRow(row)
                    break

    def sample_selected(self, row):
        if self._refreshing:
            return
        self.sample_workshop.editor.load()   # the waveform, the edit fields, or the empty state
        self.instrument_panel.update_buttons()
        if not self.document or row < 0:
            return
        index = self.samples.item(row).data(Qt.ItemDataRole.UserRole)
        sample = self.document.module.samples[index]
        self._sample_labels()
        self.sample_volume.setValue(sample.volume)
        self.finetune.setValue(sample.finetune)

    def _sample_labels(self):
        if not self.document or not self.samples.currentItem():
            return
        index = self.samples.currentItem().data(Qt.ItemDataRole.UserRole)
        sample = self.document.module.samples[index]
        self.sample_title.setText(f"{index + 1:02X} · {sample_name(sample, index + 1)}")
        looping = self.t("loop {start} → {end}", start=sample.loop_start, end=sample.loop_start + sample.loop_length) if sample.loop_length else self.t("no loop")
        self.sample_info.setText(self.sample_summary(sample, looping))

    def sample_summary(self, sample, looping: str) -> str:
        """The one-line facts of a song sample: size, bit depth, loop and what the preview plays."""
        if self.module_format != "xm":
            return self.t("{size} bytes · mono 8-bit · {loop} · C-2 preview", size=len(sample.pcm), loop=looping)
        return self.t("{size} bytes · mono {bits}-bit · {loop} ({mode}) · panning {panning} · relative note {note:+d} "
                      "· C-4 preview", size=len(sample.pcm) * sample.bits // 8, bits=sample.bits, loop=looping,
                      mode=self.t(sample.loop_mode), panning=sample.panning, note=sample.relative_note)

    def play_sample(self):
        if not self.document or not self.samples.currentItem():
            return
        try:
            index = self.samples.currentItem().data(Qt.ItemDataRole.UserRole)
            path = self.cache.sample(self.document.module, index)
            self.meter.reset()
            self.pause_playback()
            self.sample_player.setSource(QUrl.fromLocalFile(str(path)))
            self.sample_player.play()
        except (OSError, ValueError, RuntimeError) as exc:
            self.message(str(exc), True)

    def run_patch(self, ops, label: str) -> dict:
        """Apply patch operations as one undoable transaction and present the change. Unlike `apply_patch`
        a refusal is raised (`ValidationError` with its code), for callers that explain it themselves."""
        result = self.document.patch(ops, label)
        if result["changed"]:
            self.edited(label)
        return result

    def audition_wav(self, wav: bytes) -> Path:
        """Play a short in-memory WAV (an edit preview, a recipe audition) without touching the song."""
        path = self.cache.directory / f"audition-{hashlib.sha1(wav).hexdigest()[:20]}.wav"
        if not path.is_file():
            project.atomic_bytes(path, wav)
        self.meter.reset()
        self.pause_playback()
        self.sample_player.stop()
        self.sample_player.setSource(QUrl.fromLocalFile(str(path)))
        self.sample_player.play()
        return path

    def edit(self, operation, label: str = "Edit"):
        if not self.document:
            return
        try:
            if operation():
                self.edited(label)
        except (OSError, ValueError, RuntimeError) as exc:
            self.message(str(exc), True)

    def edited(self, label: str = "Edit"):
        """The owner changed the document: redraw, re-render later and journal it as a human edit."""
        self.agent_panel.compare_edited()   # the owner wants to hear their edit, not the take
        self._debounce_play = False
        if self.rt is not None:
            # Real-time: the engine takes the edit at once; playback (if any) simply continues.
            self.sample_player.stop()
            self.sample_player.setSource(QUrl())
            self.refresh_document()
            self.rt.reload()
            self.message('Change applied · Ctrl+Z to undo')
            self.live.human_edit(label)
            return
        self._resume_ms = self.player.position()
        self._audio_token += 1
        self._loading_audio = self._await_media = False
        self.player.pause()
        self.sample_player.stop()
        self.sample_player.setSource(QUrl())
        self._audio_ready = False
        self.refresh_document()
        self.debounce.start()
        self.message('Change applied · Ctrl+Z to undo')
        self.live.human_edit(label)

    # --- tracker editing ---------------------------------------------------------------
    @property
    def edit_mode(self) -> bool:
        return self.edit_button.isChecked()

    def set_edit_mode(self, on: bool):
        on = bool(on)
        for control in (self.edit_button, self.edit_action):
            control.blockSignals(True)
            control.setChecked(on)
            control.blockSignals(False)
        self.table.set_edit_mode(on)
        self.message("Edit mode on: piano keys enter notes" if on else "Edit mode off")
        if on:
            self.table.setFocus()

    def _restore_edit_settings(self):
        values = self.state.values
        octave, step = values.get("edit_octave"), values.get("edit_step")
        controls = (self.edit_octave, self.edit_step, self.keyboard_combo)
        for control in controls:
            control.blockSignals(True)  # restoring must not write the half-restored session back
        self.edit_octave.setValue(octave if type(octave) is int and 1 <= octave <= 3 else 2)
        self.edit_step.setValue(step if type(step) is int and 0 <= step <= 16 else 1)
        self.keyboard_combo.setCurrentIndex(self.keyboard_combo.findData(valid_layout(values.get("keyboard"))))
        for control in controls:
            control.blockSignals(False)

    def update_keys_hint(self, *_):
        """The visible reminder of what the piano keys play: octave and keyboard layout."""
        octave, layout = self.edit_octave.value(), self.keyboard_layout()
        self.keys_hint.setText(self.t("Octave {octave} · Keyboard {layout}", octave=octave, layout=layout.upper()))
        self.keys_hint.setToolTip(self.t("The piano keys play notes: the lower row from octave {octave}, the upper rows from "
                                         "octave {next}. F1-F3 or numpad + and - change the octave.",
                                         octave=octave, next=min(self.edit_octave.maximum(), octave + 1)))

    def keyboard_layout(self) -> str:
        """The concrete piano map in use: "qwerty" or "azerty" (Auto follows the input locale)."""
        return resolve_layout(self.keyboard_combo.currentData(), input_locale_name())

    def instrument_slot(self) -> int:
        """Song sample slot (1-31, instruments 1-128 in an XM) used for typed notes, or 0 when the song has no samples."""
        item = self.samples.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) + 1 if item else 0

    def apply_patch(self, ops, label: str, order: int | None = None) -> bool:
        """Run patch ops as one undoable transaction. Returns False when they were rejected.
        `order` selects that order afterwards (for edits that restructure the order list)."""
        if not self.document:
            return False
        try:
            result = self.document.patch(ops, label)
        except (OSError, ValueError, RuntimeError) as exc:
            self.message(str(exc), True)
            return False
        if result["changed"]:
            if order is not None:
                self.current_order = order
            self.edited(label)
        return True

    def apply_external(self, module, kind: str, conflicts: list[dict]):
        """Show a change made outside the window (the agent saved the file).

        `kind` "reload": the window had no local edits, the file replaces the module.
        `kind` "merge": `module` is the three-way merge of local edits into the file.
        Either way it is one undoable transaction; changed cells flash with the agent color."""
        document = self.document
        before = document.module
        playing = self._want_play if self._loading_audio else self.is_playing()
        position = self._resume_ms if self._loading_audio else self.playback_ms()
        replacement = copy.deepcopy(module)
        document.apply("Merge agent changes" if kind == "merge" else "Agent changes",
                       lambda target: target.__dict__.update(replacement.__dict__))
        if kind == "reload":
            mark_clean(document)
        cells = changed_cells(before, document.module)
        self.live.external_edit("Merge agent changes" if kind == "merge" else "Agent changes")
        self.sample_player.stop()
        self.refresh_document()
        self.pattern_model.flash(cells)
        if self.rt is not None:
            self.rt.reload()
        else:
            self.prepare_audio(playing, position)
        if conflicts:
            where = ", ".join(f"P{item['pattern']:02X} r{item['row']:02X} ch{item['channel'] + 1}" if item["unit"] == "cell"
                              else item["unit"] for item in conflicts[:4])
            self.message("Agent changes merged with yours · {count} conflicts, agent version kept: {where}",
                         True, count=len(conflicts), where=where)
        elif kind == "merge":
            self.message("Agent changes merged with your edits · Ctrl+Z to undo")
        else:
            self.message("Reloaded the agent's changes · Ctrl+Z to undo")

    # --- real-time playback -------------------------------------------------------------
    def _setup_realtime(self):
        """Use the libxmp transport when it can run, otherwise the rendered WAV path (and say why, once)."""
        wanted = self.state.values.get("realtime") is not False
        reason = unavailable_reason(wanted)
        self.rt = None
        if reason is None:
            try:
                self.rt = RealtimeTransport(self, latency_ms=dict(BUFFER_CHOICES)[self.audio_buffer])
            except RealtimeError:
                reason = "libxmp"
        if self.rt is not None:
            self.rt.state_changed.connect(self._transport_labels)
            self.rt.state_changed.connect(self.live.context_changed)
            self.rt.finished.connect(self.meter.reset)
            self.rt.failed.connect(self._rt_failed)
            self.rt.set_volume(self.volume.value() / 100)
        self._rt_notice = {"libxmp": LIBXMP_HINT,
                           "output": "Real-time playback needs an audio output device: playing rendered audio instead."
                           }.get(reason)
        forced = os.environ.get("CHIPLOOM_PLAYBACK", "").lower() == "rendered"
        self.realtime_action.blockSignals(True)
        self.realtime_action.setChecked(self.rt is not None)
        self.realtime_action.setEnabled(not forced)
        self.realtime_action.blockSignals(False)
        self._rt_unavailable = reason
        self._update_buffer_ui()

    def set_realtime(self, on: bool):
        """Switch between real-time (libxmp) and rendered (WAV + media player) playback."""
        self.state.values["realtime"] = bool(on)
        if self.document:
            self.stop()
        if self.rt is not None:
            self.rt.shutdown()
            self.rt.deleteLater()
        self._setup_realtime()
        self._save_preferences()
        if self.document:
            self.prepare_audio(False, 0)

    def _realtime_failed(self, exc):
        """libxmp refused the module: finish this session on the rendered path."""
        if self.rt is not None:
            self.rt.shutdown()
            self.rt.deleteLater()
            self.rt = None
        self.realtime_action.blockSignals(True)
        self.realtime_action.setChecked(False)
        self.realtime_action.blockSignals(False)
        self._rt_notice = "Real-time playback failed ({detail}): playing rendered audio instead."
        self._rt_notice = self.t(self._rt_notice, detail=exc)
        self._update_buffer_ui()
        self.play_button.setToolTip(self._rt_notice)

    def _rt_failed(self, message: str, fatal: bool):
        """The audio thread reported a problem: a module libxmp cannot load ends real-time playback."""
        if fatal and self.rt is not None:
            self._realtime_failed(message)
            self.prepare_audio(False, self._resume_ms)
        elif not fatal:
            self.message("Real-time playback failed: {detail}", True, detail=message)

    def set_audio_buffer(self, key: str):
        """Resize the audio queue and the sink now; a playing song continues on the row being heard."""
        self.audio_buffer = valid_buffer(key)
        if self.rt is not None:
            self.rt.set_latency(dict(BUFFER_CHOICES)[self.audio_buffer])
        self._update_buffer_ui()
        self._save_preferences()

    def _update_buffer_ui(self):
        """Check the current choice and show the latency in the tooltips."""
        for key, milliseconds in BUFFER_CHOICES:
            action = self.buffer_actions[key]
            action.blockSignals(True)
            action.setChecked(key == self.audio_buffer)
            action.blockSignals(False)
            action.setToolTip(self.t("Audio latency about {ms} ms. A larger buffer rides out window moves and heavy "
                                     "redraws without crackling, but sound reacts a little later to edits.", ms=milliseconds))
        milliseconds = dict(BUFFER_CHOICES)[self.audio_buffer]
        if self.rt is not None:
            self.play_button.setToolTip(self.t("Real-time playback (libxmp) · audio buffer {ms} ms", ms=milliseconds))
        else:
            self.play_button.setToolTip(self.t(self._rt_notice) if self._rt_notice else "")

    def is_playing(self) -> bool:
        if self.rt is not None:
            return self.rt.playing
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def playback_ms(self) -> int:
        return self.rt.position_ms() if self.rt is not None else self.player.position()

    def listening_module(self):
        """What the transport plays: the take being compared, otherwise the document's module."""
        return self.monitor_module if self.monitor_module is not None else self.document.module

    def listen_to(self, module=None):
        """Hear `module` (a take) at the current song position, or the document again with `None`.
        Playback state and position are kept; the document is never touched."""
        if module is self.monitor_module:
            return
        playing = self._want_play if self._loading_audio else self.is_playing()
        position = self._resume_ms if self._loading_audio else self.playback_ms()
        self.monitor_module = module
        self.sample_player.stop()
        if self.rt is not None:
            self.rt.reload()   # the audio thread swaps the module in on the row being played
        else:
            self.prepare_audio(playing, position)
        self._update_title()

    def pause_playback(self):
        """Pause the song (used before a sample audition or a proposal listening)."""
        if self.rt is not None:
            self.rt.pause()
        else:
            self.player.pause()

    # --- live collaboration -------------------------------------------------------------
    def _connect_live(self):
        """Report cursor, selection, order, playback and dirty state to the live session (debounced)."""
        self.table.selectionModel().selectionChanged.connect(self.live.context_changed)
        self.table.selectionModel().currentChanged.connect(self.live.context_changed)
        self.player.playbackStateChanged.connect(self.live.context_changed)
        self.loop.toggled.connect(lambda on: self.rt.set_loop(on) if self.rt is not None else None)
        self.live.enabled = type(self.state.values.get("live")) is not bool or self.state.values["live"]
        self.live_action.blockSignals(True)
        self.live_action.setChecked(self.live.enabled)
        self.live_action.blockSignals(False)
        self.live.update_status()

    def open_browser(self):
        """Agent menu, "Open in a browser...": address, LAN switch and connected browsers."""
        if self.browser_dialog is None:
            self.browser_dialog = BrowserDialog(self)
        self.browser_dialog.open()
        return self.browser_dialog

    def set_live(self, enabled: bool):
        self.live.set_enabled(enabled)
        self._save_preferences()

    def show_order(self, order: int):
        """Display an order without seeking the audio (used by agent requests and proposal previews)."""
        self._refreshing = True
        self.orders.setCurrentIndex(order)
        self._refreshing = False
        self.current_order = order
        self.pattern_model.refresh(self.document.module.orders[order])
        self.order_editor.refresh()
        self.live.context_changed()

    def show_pattern(self, pattern: int):
        orders = self.document.module.orders
        if self.pattern_model.pattern == pattern:
            return
        if pattern in orders:
            self.show_order(orders.index(pattern))
        else:
            self.pattern_model.refresh(pattern)

    def start_playback(self):
        if not self.document:
            return
        if self._loading_audio:
            self._want_play = True
        elif not self.is_playing():
            self.toggle_play()

    def _announce_change(self, entry: dict):
        """Status line for someone else's edit: an agent's, or a browser's (named as such)."""
        summary = "; ".join(entry["summary"][:2]) or "—"
        if entry["author"] in HUMAN_AUTHORS:
            self.message("Edit from a browser ({author}): {label} · {summary}", author=entry["author"],
                         label=entry["label"], summary=summary)
        else:
            self.message("{author}: {label} · {summary}", author=entry["author"], label=entry["label"], summary=summary)

    def agent_changed(self, entry: dict):
        """Someone else (an agent, an accepted proposal, a browser) changed the document through the session."""
        kind = "human_change" if entry["author"] in HUMAN_AUTHORS else "agent_change"
        if self.rt is not None:
            self.sample_player.stop()
            self.refresh_document()
            self.pattern_model.flash(entry["diff"].get("cells", []), kind)
            self.rt.reload()
            self._announce_change(entry)
            self.live.context_changed()
            return
        playing = self._want_play if self._loading_audio else self.is_playing()
        if not self._loading_audio:
            self._resume_ms = self.player.position()
        self._debounce_play = self._debounce_play or playing
        self._audio_token += 1
        self._loading_audio = self._await_media = self._audio_ready = False
        self.sample_player.stop()
        self.refresh_document()
        self.pattern_model.flash(entry["diff"].get("cells", []), kind)
        self.debounce.start()
        self._announce_change(entry)
        self.live.context_changed()

    def _debounced_audio(self):
        play, self._debounce_play = self._debounce_play, False
        position = self.player.position() if play and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState \
            else self._resume_ms
        self.prepare_audio(play, position)

    def apply_song(self):
        if not self.document:
            return
        title, bpm, speed = self.title_edit.text(), self.bpm.value(), self.speed.value()

        def apply():
            # One undo transaction covers title and initial timing together.
            source = Document(self.document.module)
            source.rename(title)
            initial = playback_plan(source.module)["timeline"][0]
            if (bpm, speed) != (initial["bpm"], initial["speed"]):
                source.set_timing(bpm, speed)
            replacement = source.module
            return self.document.apply("Régler le morceau", lambda module: module.__dict__.update(replacement.__dict__))

        self.edit(apply, "Set song")

    def apply_sample(self):
        if self.document and self.samples.currentItem():
            index = self.samples.currentItem().data(Qt.ItemDataRole.UserRole)
            if self.module_format == "xm":   # the XM fine tune runs -128..127: through the patch operation
                self.apply_patch([{"op": "sample", "slot": index + 1, "volume": self.sample_volume.value(),
                                   "finetune": self.finetune.value()}], "Set sample")
                return
            self.edit(lambda: self.document.set_sample(index, self.sample_volume.value(), self.finetune.value()), "Set sample")

    def transpose(self, semitones):
        index = self.table.currentIndex()
        if self.document and index.isValid():
            channel = self.pattern_model.channel_of(index.column())
            self.edit(lambda: self.document.transpose(self.pattern_model.pattern, channel, semitones), "Transpose track")
        else:
            self.message('Select a cell in the track you want to transpose.')

    def undo(self):
        if self.document and self.document.undo():
            self.edited("Undo")

    def redo(self):
        if self.document and self.document.redo():
            self.edited("Redo")

    def monitor_changed(self):
        if self._refreshing or not self.document:
            return
        self._monitor_style()
        self.live.context_changed()   # browser renders follow the window's mutes
        if self.rt is not None:
            self.rt.set_audible(self.audible())  # mutes and solos apply within one audio block, no render
            return
        # Further clicks during preparation retain the original playback intent.
        play = self._want_play if self._loading_audio else self.is_playing()
        position = self._resume_ms if self._loading_audio else self.playback_ms()
        self.prepare_audio(play, position)

    def _save_path(self, suffix, caption):
        directory = ROOT / "exports/edited"
        directory.mkdir(parents=True, exist_ok=True)
        title = self.document.module.title if self.document else "morceau"
        stem = "".join(char if char.isalnum() or char in "-_" else "_" for char in title).strip("_") or "morceau"
        path, _ = QFileDialog.getSaveFileName(self, self.t(caption), str(directory / f"{stem}{suffix}"),
            self.t("File {suffix} (*{suffix})", suffix=suffix), options=QFileDialog.Option.DontUseNativeDialog)
        return Path(path) if path else None

    def save_project(self, save_as=False):
        if not self.document:
            return
        current = self.document.path
        destination = current if current and current.suffix.lower() == ".json" and not save_as else self._save_path(".project.json", 'Save an editable project')
        if destination:
            try:
                self.document.save_project(destination)
                self.sync.saved()
                self.live.context_changed()
                self.state.remember(destination)
                self.state.save()
                self._fill_library()
                self._update_title()
                self.origin.setText(str(destination))
                self.message('Project saved')
            except (OSError, ValueError) as exc:
                self.message(str(exc), True)

    def export_mod(self):
        """Write the module file in its own format: .mod for a MOD, .xm for an XM."""
        if self.document:
            xm = self.document.module.format == "xm"
            destination = self._save_path(formats.extension(self.document.module),
                                          'Export XM module' if xm else 'Export MOD module')
            if destination:
                try:
                    self.document.export_mod(destination)
                    self.message("XM exported: {name}" if xm else "MOD exported: {name}", name=destination.name)
                except (OSError, ValueError) as exc:
                    self.message(str(exc), True)

    def export_audio(self, extension):
        if not self.document:
            return
        destination = self._save_path(f".{extension}", self.t("Export audible mix as {format}", format=extension.upper()))
        if not destination:
            return
        module, audible = self.document.module, self.audible()
        self.message('Exporting audio…')

        def operation():
            source = self.cache.prepare(module, audible)
            if extension == "mp3":
                audio.export_mp3(source, destination)
            else:
                project.atomic_bytes(destination, source.read_bytes())
            return destination

        self.submit(operation, lambda path: self.message("Audio exported: {name}", name=path.name))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.open_document(Path(url.toLocalFile()))
                break

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
        self.player.stop()
        self.player.setSource(QUrl())
        if self.rt is not None:
            self.rt.shutdown()
        self.sample_player.stop()
        self.sample_player.setSource(QUrl())
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
