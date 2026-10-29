"""Construction of the ChipLoom window's widgets and their geometry.

`WindowLayoutMixin._build_ui` builds the window once, top to bottom: the menus (`desktop_menus`), the header band
(file buttons, theme and language, song title and timing, transport, level meter), then the workspace: the library
panel on the left, and in the center a vertical splitter with the pattern area (order navigation, edit controls,
channel strip, pattern grid, hints) over the bottom tabs (Song samples, Sample library, Create, Instruments, Agent).

It creates most widget attributes the other mixins use (theme_combo, language_combo, title_edit, format_label, bpm,
speed, origin, summary, play_button, stop_button, seek, position_label, loop, volume, meter, library, orders,
order_editor, follow, edit_button, edit_step, edit_octave, keyboard_combo, keys_hint, table, channel_strip, mutes,
solos, pattern_model, pattern_hint, help_button, shortcut_popup, xm_hint, samples, sample_workshop, waveform,
sample_title, sample_info, sample_volume, finetune, sample_tabs, sample_browser, create_panel, instrument_panel,
agent_panel, tab_titles, live_status, web_status, center_splitter, workspace, play_action) and connects their signals
to methods of the other mixins. Relies on: window.live, window.language/theme, the text-binding helpers
(`_bind`, `_label`, `_button`, `t`) and `message`. Also here: the automatic height of the bottom tabs (`_fit_split`)
and the "?" shortcut popup.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFontDatabase, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHeaderView, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QSlider, QSpinBox, QSplitter, QTabWidget, QTreeWidget,
                               QVBoxLayout, QWidget)

from .desktop_create import CreatePanel, scroll_page
from .desktop_input import LAYOUTS
from .desktop_instruments import InstrumentPanel
from .desktop_live import AgentPanel, status_label
from .desktop_orders import OrderEditor
from .desktop_pattern import ChannelStrip, PatternModel, PatternView
from .desktop_samples import SampleBrowser
from .desktop_widgets import ASSETS, ElidedLabel, ShortcutPopup, Waveform, label, separator
from .desktop_workshop import SampleWorkshop
from .level_meter import LevelMeter
from .themes import THEMES
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
    ("Ctrl+wheel", "Widen or narrow the track columns, to see more or fewer channels"),
    ("Ctrl+click Mute / Solo", "Make every track audible again (clears all mutes and solos)"),
    ("Space", "Play / pause"),
    ("Ctrl+Z", "Undo"),
)
CENTER_GAP = 4   # px between the library panel's divider and the pattern/tabs column


class WindowLayoutMixin:
    """Builds the widgets of the window (see the module docstring)."""

    def _build_ui(self):
        """The whole window: menus, header band, then the library beside the grid over the bottom tabs."""
        self._build_menus()
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(central)
        outer.addWidget(self._build_header())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 12, 16, 8)
        outer.addWidget(body, 1)

        horizontal = QSplitter(Qt.Orientation.Horizontal)
        horizontal.setObjectName("workspace")
        body_layout.addWidget(horizontal, 1)
        horizontal.addWidget(self._build_library())

        center = QSplitter(Qt.Orientation.Vertical)
        # A comfortable gap between the library panel and the whole center column (pattern area and
        # bottom tabs alike): the splitter handle would otherwise touch their left edge.
        center_column = QWidget()
        center_layout = QVBoxLayout(center_column)
        center_layout.setContentsMargins(CENTER_GAP, 0, 0, 0)
        center_layout.addWidget(center)
        horizontal.addWidget(center_column)
        patterns_widget = self._build_pattern_area()
        center.addWidget(patterns_widget)
        center.addWidget(self._build_bottom_tabs())
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
        horizontal.setCollapsible(0, True)   # drag the divider to the left edge to hide the library, back to reopen it
        horizontal.setHandleWidth(9)
        horizontal.setSizes([210, 1175])
        horizontal.setStretchFactor(0, 0)
        horizontal.setStretchFactor(1, 1)
        self.workspace = horizontal
        horizontal.splitterMoved.connect(self._library_moved)
        self.table.zoomChanged.connect(lambda *_: self._save_preferences())
        self.message("Ready")
        self.play_action = QAction(self)
        self.play_action.setShortcut("Space")
        # Restrict Space to the pattern view: it must remain typeable in titles.
        self.play_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.play_action.triggered.connect(self.toggle_play)
        self.table.addAction(self.play_action)

    def _build_header(self):
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
        return header

    def _build_library(self):
        """The left panel: the logo, the example compositions and the recent files."""
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
        return library

    def _build_pattern_area(self):
        """Order navigation, edit controls, the channel strip, the pattern grid and its hints."""
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
        return patterns_widget

    def _build_bottom_tabs(self):
        """The tabs under the grid (song samples and workshop, library, Create, Instruments, Agent) and the status bar's permanent labels."""
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
        return self.sample_tabs

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
