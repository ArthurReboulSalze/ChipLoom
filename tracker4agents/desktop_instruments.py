"""Sound workshop, part 3: the Instruments tab.

An instrument is a sample, its default volume and fine tune and a short effect phrase, kept as a JSON file in
an instrument folder (`tracker4agents.instruments`). Here the owner saves the selected song sample plus a
phrase as an instrument, and applies one at the pattern cursor with the `apply_instrument` patch operation:
a note, the sample number and the phrase effects on the rows that follow, as one undoable change.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import instruments, loudness, synth_tools
from .desktop_widgets import XM_REFUSED_TIP
from .instruments import InstrumentLibrary
from .model import NOTES, ValidationError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROWS = 4


class InstrumentPanel(QWidget):
    """The "Instruments" tab. See the module docstring."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("instrumentPanel")
        saved = window.state.values.get("instrument_folder")
        self.folder = Path(saved) if isinstance(saved, str) and saved else ROOT / instruments.DEFAULT_LIBRARY
        self._items: list[dict] = []
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(window._label("INSTRUMENTS", "section"))
        folder_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("instrumentSearch")
        window._bind(self.search, "Search instruments…", "setPlaceholderText")
        self.search.textChanged.connect(self.refresh)
        folder_row.addWidget(self.search, 1)
        self.folder_button = window._button("Folder…", self.choose_folder, "instrumentFolder")
        self.folder_button.setProperty("compact", True)
        folder_row.addWidget(self.folder_button)
        left.addLayout(folder_row)
        self.list = QListWidget()
        self.list.setObjectName("instrumentList")
        self.list.setMinimumHeight(60)
        self.list.currentItemChanged.connect(self.selected_changed)
        self.list.itemDoubleClicked.connect(lambda item: self.apply_at_cursor())
        left.addWidget(self.list, 1)
        self.empty = window._label("", "muted")
        self.empty.setWordWrap(True)
        left.addWidget(self.empty)
        self.delete_button = window._button("Delete", self.delete_selected, "deleteInstrument")
        self.delete_button.setProperty("compact", True)
        left.addWidget(self.delete_button, 0, Qt.AlignmentFlag.AlignLeft)
        outer.addLayout(left, 3)

        middle = QVBoxLayout()
        middle.setSpacing(6)
        middle.addWidget(window._label("SAVE THE SELECTED SAMPLE", "section"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(1, 1)
        self.name = QLineEdit()
        self.name.setObjectName("instrumentName")
        self.name.setMaxLength(22)
        self.role = QComboBox()
        self.role.setObjectName("instrumentRole")
        grid.addWidget(window._label("Name", "muted"), 0, 0)
        grid.addWidget(self.name, 0, 1)
        grid.addWidget(window._label("Role", "muted"), 1, 0)
        grid.addWidget(self.role, 1, 1)
        middle.addLayout(grid)
        middle.addWidget(window._label("Phrase: one effect per row after the note (000 = nothing)", "muted"))
        self.phrase = QTableWidget(DEFAULT_ROWS, 1)
        self.phrase.setObjectName("instrumentPhrase")
        self.phrase.horizontalHeader().setStretchLastSection(True)
        self.phrase.horizontalHeader().hide()
        self.phrase.verticalHeader().setDefaultSectionSize(26)
        self.phrase.setMinimumHeight(60)
        self.phrase.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.set_phrase(["000"] * DEFAULT_ROWS)
        middle.addWidget(self.phrase, 1)
        phrase_buttons = QHBoxLayout()
        for text, callback, name in (("+ Row", self.add_row, "phraseAdd"), ("− Row", self.remove_row, "phraseRemove")):
            control = window._button(text, callback, name)
            control.setProperty("compact", True)
            phrase_buttons.addWidget(control)
        phrase_buttons.addStretch()
        middle.addLayout(phrase_buttons)
        self.save_button = window._button("Save instrument", self.save_instrument, "saveInstrument")
        middle.addWidget(self.save_button)
        outer.addLayout(middle, 3)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(window._label("APPLY AT THE CURSOR", "section"))
        apply_grid = QGridLayout()
        apply_grid.setHorizontalSpacing(8)
        apply_grid.setVerticalSpacing(5)
        apply_grid.setColumnStretch(1, 1)
        self.note = QComboBox()
        self.note.setObjectName("instrumentNote")
        for name in NOTES:
            self.note.addItem(name)
        self.note.setCurrentText("C-2")
        apply_grid.addWidget(window._label("Note", "muted"), 0, 0)
        apply_grid.addWidget(self.note, 0, 1)
        right.addLayout(apply_grid)
        self.overwrite = QCheckBox()
        self.overwrite.setObjectName("instrumentOverwrite")
        window._bind(self.overwrite, "Replace effects already in the way", "setText")
        right.addWidget(self.overwrite)
        self.apply_button = window._button("Apply at cursor", self.apply_at_cursor, "applyInstrument")
        self.apply_button.setObjectName("primary")
        right.addWidget(self.apply_button)
        self.status = QLabel()
        self.status.setObjectName("instrumentStatus")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        right.addWidget(self.status)
        right.addStretch()
        outer.addLayout(right, 2)

        self.apply_action = QAction(self)
        self.apply_action.setShortcut("Ctrl+I")
        self.apply_action.triggered.connect(lambda: self.apply_at_cursor())
        window.addAction(self.apply_action)
        self.retranslate()
        self.refresh()

    def library(self) -> InstrumentLibrary:
        return InstrumentLibrary(self.folder)

    # --- list ------------------------------------------------------------------------------
    def retranslate(self):
        t = self.window.t
        current = self.role.currentData()
        self.role.blockSignals(True)
        self.role.clear()
        self.role.addItem(t("Automatic"), None)
        for role in loudness.ROLES:
            self.role.addItem(t(role.capitalize()), role)
        self.role.setCurrentIndex(max(0, self.role.findData(current)))
        self.role.blockSignals(False)
        self.folder_button.setToolTip(str(self.folder))
        self.phrase.setVerticalHeaderLabels([t("row {number}", number=index) for index in range(self.phrase.rowCount())])
        self.refresh()

    def refresh(self, *_):
        window = self.window
        wanted = self.selected_id()
        try:
            found = self.library().list(self.search.text(), limit=500)
        except (ValidationError, ValueError, OSError) as exc:
            found = {"instruments": []}
            self.empty.setText(window.t("The instrument folder cannot be read: {detail}", detail=exc))
        else:
            self.empty.setText("" if found["instruments"] else
                               window.t("No instruments here yet. Select a sample in Song samples, write a phrase and press "
                                        "Save instrument.") if not self.search.text() else window.t("No instrument matches."))
            if found.get("invalid"):
                self.empty.setText(window.t("{count} instrument files could not be read.", count=len(found["invalid"])))
        self._items = found["instruments"]
        self.list.blockSignals(True)
        self.list.clear()
        for item in self._items:
            row = QListWidgetItem(window.t("{id} · {name} · {role} · {rows} phrase rows", id=item["id"], name=item["name"],
                                           role=window.t(item["role"].capitalize()) if item.get("role") else "—",
                                           rows=len(item["phrase"])))
            row.setData(Qt.ItemDataRole.UserRole, item["id"])
            row.setToolTip(str(self.folder / f"{item['id']}.json"))
            self.list.addItem(row)
            if item["id"] == wanted:
                self.list.setCurrentItem(row)
        self.list.blockSignals(False)
        self.update_buttons()

    def update_buttons(self):
        self.delete_button.setEnabled(self.selected_id() is not None)
        xm = self.window.module_format == "xm"
        self.apply_button.setEnabled(self.selected_id() is not None and bool(self.window.document) and not xm)
        self.apply_button.setToolTip(self.window.t(XM_REFUSED_TIP) if xm else "")
        self.save_button.setEnabled(bool(self.window.document and self.window.samples.currentItem()))

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def jam_sample(self):
        """The selected instrument's sample (volume and fine tune included), for the keyboard."""
        identifier = self.selected_id()
        if identifier is None:
            return None
        try:
            bank = self.window.sample_browser.library_path
            sample, _ = instruments.build_sample(self.library().get(identifier), bank, self.window.document.module
                                                 if self.window.document else None)
        except (ValidationError, ValueError, OSError, KeyError):
            return None
        return sample

    def selected_changed(self, *_):
        found = next((item for item in self._items if item["id"] == self.selected_id()), None)
        if found:
            self.name.setText(found["name"])
            self.role.setCurrentIndex(max(0, self.role.findData(found.get("role"))))
            self.set_phrase(found["phrase"] or ["000"])
        self.update_buttons()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self.window, self.window.t("Choose an instrument folder"), str(self.folder),
                                                  options=QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self.set_folder(Path(folder))

    def set_folder(self, path: Path):
        self.folder = Path(path)
        self.window.state.values["instrument_folder"] = str(self.folder)
        self.folder_button.setToolTip(str(self.folder))
        self.refresh()

    # --- phrase grid -------------------------------------------------------------------------
    def phrase_rows(self) -> list[str]:
        rows = []
        for index in range(self.phrase.rowCount()):
            item = self.phrase.item(index, 0)
            rows.append((item.text().strip().upper() if item else "") or "000")
        return rows

    def set_phrase(self, rows: list[str]):
        self.phrase.setRowCount(max(1, len(rows)))
        for index in range(self.phrase.rowCount()):
            item = QTableWidgetItem(rows[index] if index < len(rows) else "000")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.phrase.setItem(index, 0, item)
        self.phrase.setVerticalHeaderLabels([self.window.t("row {number}", number=index) for index in range(self.phrase.rowCount())])

    def add_row(self):
        if self.phrase.rowCount() < instruments.MAX_PHRASE:
            self.set_phrase(self.phrase_rows() + ["000"])

    def remove_row(self):
        if self.phrase.rowCount() > 1:
            self.set_phrase(self.phrase_rows()[:-1])

    # --- saving and applying ---------------------------------------------------------------------
    def save_instrument(self) -> dict | None:
        """Capture the selected song sample and the phrase in the grid as a new instrument file."""
        window = self.window
        item = window.samples.currentItem()
        if not window.document or item is None:
            self.show_status(window.t("Select a sample in Song samples first."), True)
            return None
        slot = item.data(Qt.ItemDataRole.UserRole) + 1
        name = self.name.text().strip() or window.document.module.samples[slot - 1].name.strip() or f"Sample {slot}"
        try:
            data = instruments.from_slot(window.document.module, slot, name, self.phrase_rows(), self.role.currentData())
            saved = self.library().save(data)
        except (ValidationError, ValueError, OSError) as exc:
            self.show_status(window.t("The instrument was not saved: {detail}", detail=exc), True)
            window.message("The instrument was not saved: {detail}", True, detail=exc)
            return None
        self.refresh()
        self.list.setCurrentRow(next((index for index, entry in enumerate(self._items) if entry["id"] == saved["id"]), -1))
        self.show_status(window.t("Saved {id} · {name}", id=saved["id"], name=saved["name"]))
        window.message("Saved {id} · {name}", id=saved["id"], name=saved["name"])
        return saved

    def operation(self) -> dict | None:
        window = self.window
        index = window.table.currentIndex()
        if not window.document or not index.isValid() or self.selected_id() is None:
            return None
        op = {"op": "apply_instrument", "pattern": window.pattern_model.pattern, "channel": window.pattern_model.channel_of(index.column()),
              "row": index.row(), "note": self.note.currentText(), "instrument": self.selected_id(),
              "instruments": str(self.folder)}
        if self.overwrite.isChecked():
            op["overwrite"] = True
        bank = window.sample_browser.library_path
        if synth_tools.library_exists(bank):
            op["library"] = str(bank)
        return op

    def apply_at_cursor(self, *_) -> dict | None:
        """Write the selected instrument at the pattern cursor as one undoable patch."""
        window = self.window
        if window.module_format == "xm":
            self.show_status(window.t(XM_REFUSED_TIP), True)
            return None
        op = self.operation()
        if op is None:
            self.show_status(window.t("Select an instrument and a pattern cell first."), True)
            return None
        try:
            result = window.run_patch([op], "Apply instrument")
        except ValidationError as exc:
            text = window.t("The instrument was not applied: {detail}", detail=exc)
            self.show_status(text, True)
            window.message(text, True)
            return None
        info = result["results"][0]
        text = window.t("{name}: {count} rows written at row {row}", name=info["name"], count=len(info["rows_written"]),
                        row=f"{op['row']:02X}")
        if info["skipped"]:
            text += " · " + window.t("{count} effects kept because something was already there", count=len(info["skipped"]))
        self.show_status(text)
        window.message("{what} · Ctrl+Z to undo", what=text)
        return info

    def show_status(self, text: str, error: bool = False):
        self.status.setText(text)
        self.status.setProperty("error", error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def delete_selected(self):
        identifier = self.selected_id()
        if identifier is None:
            return
        answer = QMessageBox.question(self.window, self.window.t("Delete this instrument?"),
                                      self.window.t("Delete {id}? The file is removed from the folder.", id=identifier),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.library().delete(identifier)
            self.refresh()

