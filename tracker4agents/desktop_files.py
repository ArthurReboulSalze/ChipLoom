"""Files of the ChipLoom window: open, reload, save, export, the library panel and drag and drop.

`FileActionsMixin` opens a MOD, XM or JSON project (`choose_file`, `open_document`, `open_module`, `reload_document`,
dropping a file on the window) and installs it as the window's `Document` (`_install_document`), asks before
discarding unsaved changes (`_discard_or_save`), saves the editable project (`save_project`), exports the module
(`export_mod`) and the audible mix (`export_audio`), and fills the library tree with the examples and recent files.
Relies on: window.document, window.state (recent files), window.cache and `submit` (background export),
window.sync (DiskSync), window.live, window.agent_panel, window.pattern_model, the channel controls (mutes, solos,
`set_channels`), `stop`, `prepare_audio`, `refresh_document`, `audible`, `_update_title`, `message` and `t`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTreeWidgetItem

from . import audio, formats, project
from .document import Document
from .model import playback_plan
ROOT = Path(__file__).resolve().parents[1]


class FileActionsMixin:
    """Open, save, export and the library panel (see the module docstring)."""

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
