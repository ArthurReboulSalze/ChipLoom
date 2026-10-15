"""Qt Widgets desktop application. All musical edits go through Document."""

from __future__ import annotations

import bisect
from pathlib import Path

from PySide6.QtCore import (QAbstractTableModel, QLibraryInfo, QModelIndex, QObject, QRunnable, QStandardPaths,
                            Qt, QThreadPool, QTimer, QTranslator, QUrl, Signal)
from PySide6.QtGui import QAction, QColor, QFontDatabase, QKeySequence, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioFormat, QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
                               QFormLayout, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSlider,
                               QSpinBox, QSplitter, QTableView, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import __version__, audio, project
from .desktop_services import AppState, AudioCache
from .document import Document
from .i18n import error_text, translate
from .level_meter import LevelMeter
from .model import Cell, Sample, cell, playback_plan
from .themes import THEMES, stylesheet

ROOT = Path(__file__).resolve().parents[1]
STYLE = stylesheet('midnight')


def label(text: str, name: str = "") -> QLabel:
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        result.setObjectName(name)
    return result


def button(text: str, callback, name: str = "") -> QPushButton:
    result = QPushButton(text)
    if name:
        result.setObjectName(name)
    result.clicked.connect(callback)
    return result


def clock(milliseconds: int) -> str:
    seconds = max(0, milliseconds) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def sample_name(sample: Sample, slot: int) -> str:
    prefix = f"{slot:02X} "
    return sample.name[len(prefix):] if sample.name.startswith(prefix) else sample.name or "Sample"


class TaskSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str)


class Task(QRunnable):
    def __init__(self, token: int, operation):
        super().__init__()
        self.token, self.operation = token, operation
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.finished.emit(self.token, self.operation())
        except Exception as exc:
            self.signals.failed.emit(self.token, str(exc))


class PatternModel(QAbstractTableModel):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.pattern, self.playing_row = window, 0, -1

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or not self.window.document else 64

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 12

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Vertical:
                return f"{section:02X}"
            return self.window.t(("Note", "Smp", "Effect")[section % 3])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not self.window.document:
            return None
        value = self.window.document.module.patterns[self.pattern].get(index.row(), index.column() // 3)
        part = index.column() % 3
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return (value.note or "---", f"{value.sample:02X}" if value.sample else "--", value.effect)[part]
        if role == Qt.ItemDataRole.ForegroundRole:
            channel = index.column() // 3
            colors = self.window.palette_colors
            return QColor(colors["channels"][channel] if self.window.audible()[channel] else colors["disabled"])
        if role == Qt.ItemDataRole.BackgroundRole:
            if index.row() == self.playing_row:
                return QColor(self.window.palette_colors["playing"])
            if index.row() % 4 == 0:
                return QColor(self.window.palette_colors["beat"])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.window.t("Double-click to edit. Notes C-1..B-3; sample and effect in hexadecimal.")
        return None

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not self.window.document:
            return False
        old = self.window.document.module.patterns[self.pattern].get(index.row(), index.column() // 3)
        text = str(value).strip().upper()
        try:
            part = index.column() % 3
            new = cell(None if text in ("", "---") else text, old.sample, old.effect) if part == 0 else (
                Cell(old.period, int(text, 16) if text not in ("", "--") else 0, old.command, old.param)
                if part == 1 else cell(old.note, old.sample, text or "000")
            )
            changed = self.window.document.replace_cell(self.pattern, index.row(), index.column() // 3, new)
            if changed:
                self.window.edited()
            return True
        except (ValueError, TypeError) as exc:
            self.window.message(str(exc), error=True)
            return False

    def refresh(self, pattern: int | None = None):
        self.beginResetModel()
        if pattern is not None:
            self.pattern = pattern
        self.endResetModel()

    def highlight(self, row: int):
        previous, self.playing_row = self.playing_row, row
        for changed in {previous, row}:
            if 0 <= changed < 64:
                self.dataChanged.emit(self.index(changed, 0), self.index(changed, 11), [Qt.ItemDataRole.BackgroundRole])


class Waveform(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.sample: Sample | None = None
        self.setMinimumHeight(130)

    def set_sample(self, sample: Sample | None):
        self.sample = sample
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rectangle = self.rect().adjusted(10, 12, -10, -12)
        colors = self.window.palette_colors
        painter.fillRect(self.rect(), QColor(colors["panel"]))
        painter.setPen(QPen(QColor(colors["border"]), 1))
        painter.drawLine(rectangle.left(), rectangle.center().y(), rectangle.right(), rectangle.center().y())
        if not self.sample or not self.sample.pcm:
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(rectangle, Qt.AlignmentFlag.AlignCenter, self.window.t("Select a sample"))
            return
        data = self.sample.pcm
        if self.sample.loop_length:
            start = rectangle.left() + rectangle.width() * self.sample.loop_start / len(data)
            end = rectangle.left() + rectangle.width() * (self.sample.loop_start + self.sample.loop_length) / len(data)
            painter.fillRect(int(start), rectangle.top(), max(1, int(end - start)), rectangle.height(), QColor(colors["loop"]))
        painter.setPen(QPen(QColor(colors["accent"]), 1.3))
        count = min(len(data), max(2, rectangle.width() * 2))
        path = QPainterPath()
        for index in range(count):
            value = data[min(len(data) - 1, index * len(data) // count)]
            x = rectangle.left() + index * rectangle.width() / max(1, count - 1)
            y = rectangle.center().y() - value * rectangle.height() * 0.46 / 128
            path.moveTo(x, y) if index == 0 else path.lineTo(x, y)
        painter.drawPath(path)


class TrackerWindow(QMainWindow):
    def __init__(self, initial: Path | None = None, state_dir: Path | None = None, restore: bool = True):
        super().__init__()
        self.setObjectName("Tracker4Agents")
        self.setWindowTitle(f"ChipLoom {__version__}")
        self.resize(1420, 900)
        self.setMinimumSize(1080, 710)
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
        self._loop_epoch = 0
        self._refreshing = False
        self.current_order = 0
        self.plan = {"timeline": [], "duration_seconds": 0}
        self.times = []
        self.player, self.sample_player = QMediaPlayer(self), QMediaPlayer(self)
        self.output, self.sample_output = QAudioOutput(self), QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.sample_player.setAudioOutput(self.sample_output)
        self._build_ui()
        self.apply_theme()
        self.retranslate()
        self.probes = []
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48000)
        audio_format.setChannelCount(2)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        for player in (self.player, self.sample_player):
            probe = QAudioBufferOutput(audio_format, self)
            player.setAudioBufferOutput(probe)
            # Marshal PCM to the GUI thread. A direct Python callback from Qt's
            # audio renderer can deadlock with stop()/close waiting for that thread.
            probe.audioBufferReceived.connect(lambda buffer, source=player: self._meter_buffer(buffer, source),
                                              Qt.ConnectionType.QueuedConnection)
            self.probes.append(probe)
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
        self.debounce.timeout.connect(lambda: self.prepare_audio(False, self._resume_ms))
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
                                 loop=self.loop.isChecked(), follow=self.follow.isChecked())
        try:
            self.state.save()
        except OSError as exc:
            self.message("Session could not be saved: {detail}", True, detail=exc)

    def apply_theme(self):
        self.palette_colors = THEMES[self.theme]
        self.setStyleSheet(stylesheet(self.theme))
        palette = QPalette()
        for role, key in ((QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
                          (QPalette.ColorRole.Base, "panel"), (QPalette.ColorRole.Text, "text"),
                          (QPalette.ColorRole.Button, "button"), (QPalette.ColorRole.ButtonText, "text"),
                          (QPalette.ColorRole.Highlight, "selected"), (QPalette.ColorRole.HighlightedText, "text")):
            palette.setColor(role, QColor(self.palette_colors[key]))
        self.setPalette(palette)
        self._monitor_style()
        self.waveform.update()
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
        self._fill_library()
        if self.document:
            self._song_labels()
            self._sample_labels()
            index = self.table.currentIndex()
            if index.isValid():
                value = self.document.module.patterns[self.pattern_model.pattern].get(index.row(), index.column() // 3)
                self.cell_info.setText(self.t("Row {row:02X} · track {channel}\n{value}", row=index.row(), channel=index.column() // 3 + 1, value=value.text()))
        self.pattern_model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 11)
        self._transport_labels()
        self._monitor_style()
        self.waveform.update()
        self._show_message()

    def _meter_buffer(self, buffer, player):
        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.meter.feed(buffer)

    def _monitor_style(self):
        audible = self.audible()
        for channel, control in enumerate(self.mutes):
            muted = control.isChecked()
            control.setText(self.t("Track {number} · MUTED" if muted else "Track {number}", number=channel + 1))
            control.setToolTip(self.t("Click to unmute track {number}" if muted else "Click to mute track {number}", number=channel + 1))
            control.setAccessibleName(control.text())
            control.setProperty("trackMuted", not audible[channel])
            color = self.palette_colors["channels"][channel] if audible[channel] else self.palette_colors["disabled"]
            control.setStyleSheet(f"border-left:3px solid {color};color:{color}")
            self.solos[channel].setText(self.t("Solo"))
            self.solos[channel].setToolTip(self.t("Solo track {number}", number=channel + 1))
        self.pattern_model.dataChanged.emit(self.pattern_model.index(0, 0), self.pattern_model.index(63, 11), [Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole])

    def _build_ui(self):
        file_menu = self._bind(self.menuBar().addMenu(""), "File", "setTitle")
        edit_menu = self._bind(self.menuBar().addMenu(""), "Edit", "setTitle")
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
        self._menu_action(help_menu, "About", lambda: QMessageBox.information(
            self, "ChipLoom", f"ChipLoom {__version__}\n" + self.t("Four-channel MOD tracker.\nDouble-click a cell to edit it.\nClick a track header to mute or unmute it.\nSpace in patterns: play/pause.\nCtrl+Z: undo · F5: reload file.\nProTracker M.K. profile; XM and IT are planned.")))

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 14, 20, 10)
        self.setCentralWidget(central)
        top = QHBoxLayout()
        top.addWidget(self._button('Open…', self.choose_file))
        top.addWidget(self._button('Save project…', self.save_project))
        top.addWidget(self._button('Export MOD…', self.export_mod))
        top.addStretch()
        top.addWidget(self._label("Theme"))
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName("themeSelector")
        for key, theme in THEMES.items():
            self.theme_combo.addItem(self.t(theme["name"]), key)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.theme))
        self.theme_combo.currentIndexChanged.connect(lambda: self.set_theme(self.theme_combo.currentData()))
        top.addWidget(self.theme_combo)
        top.addWidget(self._label("Language"))
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("languageSelector")
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Français", "fr")
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
        self.language_combo.currentIndexChanged.connect(lambda: self.set_language(self.language_combo.currentData()))
        top.addWidget(self.language_combo)
        top.addWidget(self._label('MOD · 4 CHANNELS · PAL', "muted"))
        outer.addLayout(top)
        heading = QHBoxLayout()
        self.title = self._label("ChipLoom", "title")
        heading.addWidget(self.title)
        heading.addStretch()
        self.summary = self._label('Open a module to get started', "muted")
        heading.addWidget(self.summary)
        outer.addLayout(heading)
        self.origin = self._label("", "muted")
        outer.addWidget(self.origin)
        transport = QHBoxLayout()
        self.play_button = self._button('Play', self.toggle_play, "primary")
        self.play_button.setEnabled(False)
        self.stop_button = self._button('Stop', self.stop)
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setObjectName("seek")
        self.seek.sliderMoved.connect(self.seek_to)
        transport.addWidget(self.seek, 1)
        self.position_label = self._label("00:00 / 00:00", "muted")
        transport.addWidget(self.position_label)
        self.loop = self._bind(QCheckBox(), "Loop")
        transport.addWidget(self.loop)
        transport.addWidget(self._label('Volume'))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(95)
        self.volume.valueChanged.connect(self._volume)
        transport.addWidget(self.volume)
        self.meter = LevelMeter(self)
        self._bind(self.meter, "Stereo audio level: average level and peak, after the volume control.", "setToolTip")
        transport.addWidget(self.meter)
        outer.addLayout(transport)

        horizontal = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(horizontal, 1)
        library = QWidget()
        library.setMaximumWidth(250)
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(0, 0, 10, 0)
        library_layout.addWidget(self._label('LIBRARY', "section"))
        self.library = QTreeWidget()
        self.library.setHeaderHidden(True)
        self.library.itemActivated.connect(self._library_open)
        self.library.setMinimumWidth(195)
        library_layout.addWidget(self.library)
        library_hint = self._label("MOD and JSON projects\nDrop a file here to open it.\nF5 reloads changes made by the agent.", "muted")
        library_hint.setWordWrap(True)
        library_layout.addWidget(library_hint)
        horizontal.addWidget(library)

        center = QSplitter(Qt.Orientation.Vertical)
        horizontal.addWidget(center)
        patterns_widget = QWidget()
        patterns_layout = QVBoxLayout(patterns_widget)
        patterns_layout.setContentsMargins(0, 0, 0, 0)
        navigation = QHBoxLayout()
        navigation.addWidget(self._label('Order'))
        self.orders = QComboBox()
        self.orders.setObjectName("orders")
        self.orders.currentIndexChanged.connect(self.select_order)
        self.orders.setMinimumWidth(205)
        navigation.addWidget(self.orders)
        self.follow = self._bind(QCheckBox(), "Follow playback")
        navigation.addWidget(self.follow)
        navigation.addStretch()
        navigation.addWidget(self._button('− 1 semitone', lambda: self.transpose(-1)))
        navigation.addWidget(self._button('+ 1 semitone', lambda: self.transpose(1)))
        patterns_layout.addLayout(navigation)
        channel_row = QHBoxLayout()
        self.mutes, self.solos = [], []
        for channel in range(4):
            group = QHBoxLayout()
            mute, solo = QPushButton(), QPushButton()
            mute.setObjectName(f"muteTrack{channel + 1}")
            solo.setObjectName(f"soloTrack{channel + 1}")
            solo.setFixedWidth(54)
            for control in (mute, solo):
                control.setCheckable(True)
                control.toggled.connect(self.monitor_changed)
                group.addWidget(control, 1 if control is mute else 0)
            self.mutes.append(mute)
            self.solos.append(solo)
            channel_row.addLayout(group, 1)
        patterns_layout.addLayout(channel_row)
        self.table = QTableView()
        self.table.setObjectName("patterns")
        self.pattern_model = PatternModel(self)
        self.table.setModel(self.pattern_model)
        self.table.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.table.verticalHeader().setDefaultSectionSize(25)
        self.table.horizontalHeader().setMinimumSectionSize(54)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.selectionModel().currentChanged.connect(self.cell_selected)
        self.table.verticalHeader().sectionClicked.connect(lambda row: self.seek_row(row))
        patterns_layout.addWidget(self.table)
        pattern_hint = self._label("Double-click: edit a cell · Click a row number: seek · Samples and effects are hexadecimal", "muted")
        pattern_hint.setWordWrap(True)
        patterns_layout.addWidget(pattern_hint)
        center.addWidget(patterns_widget)

        sample_widget = QWidget()
        sample_layout = QHBoxLayout(sample_widget)
        sample_layout.setContentsMargins(0, 8, 0, 0)
        sample_left = QVBoxLayout()
        sample_left.addWidget(self._label('SAMPLES', "section"))
        self.samples = QListWidget()
        self.samples.setObjectName("samples")
        self.samples.setMinimumWidth(195)
        self.samples.setMaximumWidth(280)
        self.samples.currentRowChanged.connect(self.sample_selected)
        self.samples.itemDoubleClicked.connect(lambda item: self.play_sample())
        sample_left.addWidget(self.samples)
        sample_layout.addLayout(sample_left)
        sample_right = QVBoxLayout()
        self.sample_title = self._label('Select a sample', "section")
        sample_right.addWidget(self.sample_title)
        self.waveform = Waveform(self)
        sample_right.addWidget(self.waveform, 1)
        self.sample_info = self._label("", "muted")
        sample_right.addWidget(self.sample_info)
        sample_actions = QHBoxLayout()
        sample_actions.addWidget(self._button('Play sample', self.play_sample))
        sample_actions.addWidget(self._label('Volume'))
        self.sample_volume = QSpinBox()
        self.sample_volume.setRange(0, 64)
        sample_actions.addWidget(self.sample_volume)
        sample_actions.addWidget(self._label('Fine tune'))
        self.finetune = QSpinBox()
        self.finetune.setRange(-8, 7)
        sample_actions.addWidget(self.finetune)
        sample_actions.addWidget(self._button('Apply', self.apply_sample))
        sample_right.addLayout(sample_actions)
        sample_layout.addLayout(sample_right, 1)
        center.addWidget(sample_widget)
        center.setSizes([490, 240])

        inspector = QWidget()
        inspector.setMaximumWidth(245)
        inspector.setMinimumWidth(205)
        side = QVBoxLayout(inspector)
        side.setContentsMargins(12, 0, 0, 0)
        side.addWidget(self._label('SONG', "section"))
        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setMaxLength(20)
        form.addRow(self._label('Title'), self.title_edit)
        self.bpm = QSpinBox()
        self.bpm.setRange(33, 255)
        form.addRow(self._label('Tempo'), self.bpm)
        self.speed = QSpinBox()
        self.speed.setRange(1, 31)
        form.addRow(self._label('Ticks / row'), self.speed)
        side.addLayout(form)
        side.addWidget(self._button('Apply at start', self.apply_song))
        side.addWidget(self._label('CELL', "section"))
        self.cell_info = self._label('Select a cell', "muted")
        self.cell_info.setWordWrap(True)
        side.addWidget(self.cell_info)
        gate_form = QFormLayout()
        self.gate = QSpinBox()
        self.gate.setRange(1, 15)
        self.gate.setValue(3)
        gate_form.addRow(self._label('Cut after'), self.gate)
        side.addLayout(gate_form)
        cut = self._button('Apply ECx', self.gate_note)
        self._bind(cut, "Replace the selected cell's effect with a note cut after this many ticks.", "setToolTip")
        side.addWidget(cut)
        hint = self._label("EC3 cuts after 3 ticks. Use a value lower than the ticks per row to shorten a note.", "muted")
        hint.setWordWrap(True)
        side.addWidget(hint)
        side.addStretch()
        side.addWidget(self._button('Export WAV…', lambda: self.export_audio("wav")))
        side.addWidget(self._button('Export MP3…', lambda: self.export_audio("mp3")))
        horizontal.addWidget(inspector)
        horizontal.setSizes([210, 950, 225])
        horizontal.setStretchFactor(0, 0)
        horizontal.setStretchFactor(1, 1)
        horizontal.setStretchFactor(2, 0)
        self.message("Ready")
        self.play_action = QAction(self)
        self.play_action.setShortcut("Space")
        # Restrict Space to the pattern view: it must remain typeable in titles.
        self.play_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.play_action.triggered.connect(self.toggle_play)
        self.table.addAction(self.play_action)

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
                                               self.t('Modules and projects (*.mod *.MOD *.json);;All files (*)'),
                                               options=QFileDialog.Option.DontUseNativeDialog)
        if source:
            self.open_document(Path(source))

    def reload_document(self):
        if self.document and self.document.path:
            self.open_document(self.document.path)

    def open_document(self, path: Path) -> bool:
        if not self._discard_or_save():
            return False
        try:
            document = Document.open(path)
            plan = playback_plan(document.module)
        except (OSError, ValueError, RuntimeError) as exc:
            self.message("Cannot open: {detail}", True, detail=exc)
            return False
        self.stop()
        self.debounce.stop()
        self._audio_token += 1
        self.document, self.plan = document, plan
        self.current_order = 0
        self._refreshing = True
        for control in self.mutes + self.solos:
            control.setChecked(False)
        self._refreshing = False
        self.state.remember(path)
        try:
            self.state.save()
        except OSError as exc:
            self.message("Session could not be saved: {detail}", True, detail=exc)
        self._fill_library()
        self.refresh_document()
        self.prepare_audio(False, 0)
        return True

    def refresh_document(self):
        if not self.document:
            return
        self._refreshing = True
        module = self.document.module
        self.plan = playback_plan(module)
        self.times = [entry["seconds"] for entry in self.plan["timeline"]]
        self.current_order = min(self.current_order, len(module.orders) - 1)
        self.title.setText(module.title or self.t('Untitled'))
        self.title_edit.setText(module.title)
        initial = self.plan["timeline"][0]
        self.bpm.setValue(initial["bpm"])
        self.speed.setValue(initial["speed"])
        self._song_labels()
        self.orders.clear()
        for order, pattern in enumerate(module.orders):
            self.orders.addItem(f"{order:02X}  ·  {module.patterns[pattern].name or f'Pattern {pattern:02X}'}", pattern)
        self.orders.setCurrentIndex(self.current_order)
        selection = self.table.currentIndex()
        selected_cell = (selection.row(), selection.column()) if selection.isValid() else None
        self.pattern_model.refresh(module.orders[self.current_order])
        if selected_cell:
            self.table.setCurrentIndex(self.pattern_model.index(*selected_cell))
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
        self.undo_action.setEnabled(self.document.can_undo)
        self.redo_action.setEnabled(self.document.can_redo)
        self._monitor_style()
        self._update_title()

    def _song_labels(self):
        module = self.document.module
        self.title.setText(module.title or self.t("Untitled"))
        self.summary.setText(self.t("{bpm} BPM  ·  {orders} orders  ·  {samples} samples  ·  {seconds:.2f} s",
            bpm=self.plan["timeline"][0]["bpm"], orders=len(module.orders),
            samples=sum(bool(sample.pcm) for sample in module.samples), seconds=self.plan["duration_seconds"]))
        self.origin.setText(str(self.document.path) if self.document.path else self.t("New project"))

    def _update_title(self):
        if self.document:
            self.setWindowTitle(f"{'* ' if self.document.dirty else ''}{self.document.module.title} — ChipLoom {__version__}")

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
        solo = any(control.isChecked() for control in self.solos)
        return tuple(not mute.isChecked() and (not solo or self.solos[index].isChecked())
                     for index, mute in enumerate(self.mutes))

    def prepare_audio(self, play=False, position=0):
        if not self.document:
            return
        self.debounce.stop()
        self._audio_token += 1
        token = self._audio_token
        self._loading_audio, self._audio_ready, self._await_media = True, False, False
        self._want_play, self._resume_ms = play, position
        self.meter.reset()
        self.player.stop()
        self.player.setSource(QUrl())
        self.play_button.setText(self.t('Preparing…'))
        self.play_button.setEnabled(False)
        self.message('Preparing playback…')
        module, audible = self.document.module, self.audible()

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
            self.message('Ready to play')
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
            "Pause" if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState else "Play"))

    def _volume(self, volume):
        self.output.setVolume(volume / 100)
        self.sample_output.setVolume(volume / 100)

    def toggle_play(self):
        if not self.document or self._loading_audio:
            return
        self.sample_player.stop()
        if not self._audio_ready:
            self.prepare_audio(True, self._resume_ms)
        elif self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        self._loop_epoch += 1
        self._want_play = False
        self._resume_ms = 0
        self.player.stop()
        self.sample_player.stop()
        self.meter.reset()

    def seek_to(self, milliseconds):
        self._loop_epoch += 1
        self.meter.reset()
        self._resume_ms = milliseconds
        if self._audio_ready:
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
        target = next((entry for entry in self.plan["timeline"] if entry["order"] == order), None)
        if target:
            self.seek_to(round(target["seconds"] * 1000))
        else:
            self.message("This order is not reached in the module's playback cycle.")

    def _sync_position(self):
        active = any(player.playbackState() == QMediaPlayer.PlaybackState.PlayingState for player in (self.player, self.sample_player))
        self.meter.tick(active, self.volume.value() / 100)
        if not self.document or self._loading_audio:
            return
        milliseconds = self.player.position()
        if not self.seek.isSliderDown():
            self.seek.setValue(milliseconds)
        self.position_label.setText(f"{clock(milliseconds)} / {clock(self.player.duration())}")
        if not self.times:
            return
        entry = self.plan["timeline"][max(0, bisect.bisect_right(self.times, milliseconds / 1000) - 1)]
        if self.follow.isChecked() and entry["order"] != self.current_order:
            self._refreshing = True
            self.current_order = entry["order"]
            self.orders.setCurrentIndex(self.current_order)
            self.pattern_model.refresh(entry["pattern"])
            self._refreshing = False
        if entry["pattern"] == self.pattern_model.pattern:
            self.pattern_model.highlight(entry["row"])
            if self.follow.isChecked() and self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.table.scrollTo(self.pattern_model.index(entry["row"], 0), QAbstractItemView.ScrollHint.EnsureVisible)

    def cell_selected(self, index, previous=QModelIndex()):
        if not self.document or not index.isValid():
            return
        value = self.document.module.patterns[self.pattern_model.pattern].get(index.row(), index.column() // 3)
        self.cell_info.setText(self.t("Row {row:02X} · track {channel}\n{value}", row=index.row(), channel=index.column() // 3 + 1, value=value.text()))
        if value.sample:
            for row in range(self.samples.count()):
                if self.samples.item(row).data(Qt.ItemDataRole.UserRole) == value.sample - 1:
                    self.samples.setCurrentRow(row)
                    break

    def sample_selected(self, row):
        if self._refreshing or not self.document or row < 0:
            return
        index = self.samples.item(row).data(Qt.ItemDataRole.UserRole)
        sample = self.document.module.samples[index]
        self.waveform.set_sample(sample)
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
        self.sample_info.setText(self.t("{size} bytes · mono 8-bit · {loop} · C-2 preview", size=len(sample.pcm), loop=looping))

    def play_sample(self):
        if not self.document or not self.samples.currentItem():
            return
        try:
            index = self.samples.currentItem().data(Qt.ItemDataRole.UserRole)
            path = self.cache.sample(self.document.module, index)
            self.meter.reset()
            self.player.pause()
            self.sample_player.setSource(QUrl.fromLocalFile(str(path)))
            self.sample_player.play()
        except (OSError, ValueError, RuntimeError) as exc:
            self.message(str(exc), True)

    def edit(self, operation):
        if not self.document:
            return
        try:
            if operation():
                self.edited()
        except (OSError, ValueError, RuntimeError) as exc:
            self.message(str(exc), True)

    def edited(self):
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

        self.edit(apply)

    def apply_sample(self):
        if self.document and self.samples.currentItem():
            index = self.samples.currentItem().data(Qt.ItemDataRole.UserRole)
            self.edit(lambda: self.document.set_sample(index, self.sample_volume.value(), self.finetune.value()))

    def transpose(self, semitones):
        index = self.table.currentIndex()
        if self.document and index.isValid():
            self.edit(lambda: self.document.transpose(self.pattern_model.pattern, index.column() // 3, semitones))
        else:
            self.message('Select a cell in the track you want to transpose.')

    def gate_note(self):
        index = self.table.currentIndex()
        if self.document and index.isValid():
            self.edit(lambda: self.document.gate_note(self.pattern_model.pattern, index.row(), index.column() // 3, self.gate.value()))

    def undo(self):
        if self.document and self.document.undo():
            self.edited()

    def redo(self):
        if self.document and self.document.redo():
            self.edited()

    def monitor_changed(self):
        if self._refreshing or not self.document:
            return
        self._monitor_style()
        # Further clicks during preparation retain the original playback intent.
        play = self._want_play if self._loading_audio else self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        position = self._resume_ms if self._loading_audio else self.player.position()
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
                self.state.remember(destination)
                self.state.save()
                self._fill_library()
                self._update_title()
                self.origin.setText(str(destination))
                self.message('Project saved')
            except (OSError, ValueError) as exc:
                self.message(str(exc), True)

    def export_mod(self):
        if self.document:
            destination = self._save_path(".mod", 'Export MOD module')
            if destination:
                try:
                    self.document.export_mod(destination)
                    self.message("MOD exported: {name}", name=destination.name)
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
        self._audio_token += 1
        self.timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.sample_player.stop()
        self.sample_player.setSource(QUrl())
        self.state.values.update(volume=self.volume.value(), loop=self.loop.isChecked(), follow=self.follow.isChecked(),
                                 theme=self.theme, language=self.language)
        try:
            self.state.save()
        except OSError:
            pass
        self.pool.waitForDone(3000)
        event.accept()


def application() -> QApplication:
    app = QApplication.instance() or QApplication(["tracker4agents"])
    app.setOrganizationName("tracker4agents")
    app.setApplicationName("tracker4agents")
    # Keep the data-directory identity so existing sessions survive the new name.
    app.setApplicationDisplayName("ChipLoom")
    app.setApplicationVersion(__version__)
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
