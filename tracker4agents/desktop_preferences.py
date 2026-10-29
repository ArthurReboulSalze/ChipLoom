"""Language, theme and the preferences the window remembers between sessions.

`PreferencesMixin` switches the language (`set_language`, `retranslate`: every bound text, the Qt standard dialogs
and each panel's own `retranslate`) and the theme (`set_theme`, `apply_theme`), writes the session values
(`_save_preferences`) and restores them at start-up (`_restore_edit_settings`, `_restore_layout`, and whether the
library panel is hidden). Relies on: window.state (AppState), window.language/theme/palette_colors, window._bindings,
the header combos (theme_combo, language_combo, keyboard_combo), the edit controls, the panels built by
`desktop_layout`, and `_monitor_style`, `_song_labels`, `_sample_labels`, `_show_format_label`, `_update_buffer_ui`,
`update_keys_hint`, `_transport_labels`, `_fill_library` and `message` from the other mixins.
"""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .desktop_input import valid_layout
from .desktop_pattern import valid_zoom
from .desktop_widgets import ui_icons
from .themes import THEMES, stylesheet


class PreferencesMixin:
    """Language, theme and saved preferences (see the module docstring)."""
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
                                 audio_buffer=self.audio_buffer, library_hidden=self.library_hidden(),
                                 column_zoom=self.table.column_zoom)
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
        self.comment_panel.retranslate()
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

    def _restore_layout(self):
        """The library panel hidden or shown and the zoom of the track columns, as the owner left them."""
        values = self.state.values
        self.table.column_zoom = valid_zoom(values.get("column_zoom"))
        self.table.fit_columns()
        if values.get("library_hidden") is True:
            self.workspace.setSizes([0, sum(self.workspace.sizes()) or 1385])

    def library_hidden(self) -> bool:
        return self.workspace.sizes()[0] == 0

    def _library_moved(self, *_):
        # The divider moves continuously while dragged: the session is written only when the panel closes or opens.
        if self.library_hidden() != (self.state.values.get("library_hidden") is True):
            self._save_preferences()
