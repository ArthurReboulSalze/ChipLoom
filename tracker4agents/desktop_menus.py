"""The menu bar of the ChipLoom window: File, Edit, Playback, Agent and Help.

`MenuBarMixin._build_menus` runs first in `_build_ui`. It creates the window's actions (open_action, save_action,
export_action, undo_action, redo_action, edit_action, cut/copy/paste/clear_action, instrument_action, realtime_action,
buffer_actions, live_action, browser_action, comment_action, song_comment_action) and connects them to methods of the other mixins (choose_file,
save_project, reload_document, export_mod, export_audio, undo, redo, set_edit_mode, set_realtime, set_audio_buffer,
set_live, open_browser). Widgets built later (table, instrument_panel, agent_panel, comment_panel, sample_tabs) are reached through
lambdas, so they need not exist yet. Relies on: window.live (created before the UI) and the text-binding helpers
`_bind`, `_action`, `_menu_action` and `t` of `TrackerWindow`.
"""

from __future__ import annotations

from PySide6.QtGui import QActionGroup, QKeySequence
from PySide6.QtWidgets import QMessageBox

from . import __version__
from .desktop_playback import BUFFER_CHOICES
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
    "Click a track header to mute or unmute it, Ctrl+click Mute or Solo to hear every track again; the grid scrolls sideways when the channels do not fit and Ctrl+wheel widens or narrows the tracks.\n"
    "An XM adds a volume column and key off (key 1, the key before 2, in Edit mode; === in a cell).\n"
    "Space in patterns: play/pause · Ctrl+Z: undo.\n"
    "Real-time playback uses libxmp (ProTracker mode) while exports use libopenmpt, so small differences in sound are expected.\n"
    "Four-channel ProTracker MOD, MOD with 2 to 32 channels and the FastTracker II XM profile; IT is planned.")

BUFFER_LABELS = {"low": "Low · 80 ms", "normal": "Normal · 150 ms", "high": "High · 300 ms",
                 "very_high": "Very high · 600 ms"}


class MenuBarMixin:
    """The menu bar and its actions (see the module docstring)."""

    def _build_menus(self):
        """Create the five menus and their actions, in menu order."""
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
        self.comment_action = self._menu_action(agent_menu, "Comment on the selection…",
                                                lambda: self.comment_panel.comment_selection(), "Ctrl+M")
        self.song_comment_action = self._menu_action(agent_menu, "Comment on the whole song…",
                                                     lambda: self.comment_panel.comment_song())
        agent_menu.addSeparator()
        self.browser_action = self._menu_action(agent_menu, "Open in a browser\u2026", self.open_browser)
        self._menu_action(agent_menu, "Compare a take with the current song", lambda: self.agent_panel.toggle_compare(),
                          "Ctrl+B")
        self._menu_action(help_menu, "About", lambda: QMessageBox.information(
            self, "ChipLoom", f"ChipLoom {__version__}\n" + self.t(ABOUT_TEXT)))
