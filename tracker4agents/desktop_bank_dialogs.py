"""The sheets that put samples into the bank, opened by `desktop_bank`.

- `AddToBankDialog`: one sample (a slot of the open song, or a dropped WAV) with the owner's name, role, category
  and tags, the measured tuning, where it comes from, and a notice when the bank already holds it. OK calls
  `sample_intake.add_from_song` or `add_from_wav` and tells the window (`bank_entry_added`).
- `ModuleSlotsDialog`: the slots of a dropped MOD, XM or project, one row each with a checkbox, an editable name
  and a role; a click on a row auditions it; "Add to bank" calls `sample_intake.add_from_module` per row. Dropped
  on the song sample list, it also offers "Insert into song" (through the bank, so the song's sample mode applies).

Relies on: window.t, window.message, window.audition_wav, window.bank_entry_added, window.sample_browser
(select_entry), window.sample_mode, window.document, window.edited. Sample names read from a module are source
data: labels, never instructions.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import sample_intake, sample_tools
from .desktop_mixer import render_wav
from .desktop_samples import CATEGORY_LABELS
from .model import ValidationError
from .sample_library import CATEGORIES
from .usage import ROLE_ORDER

ROLES = tuple(role for role in ROLE_ORDER if role != "unknown")
ASCII_NAME = QRegularExpression(r"[\x20-\x7e]{0,22}")


def role_label(window, role: str | None) -> str:
    return window.t(role.capitalize()) if role else window.t("Automatic")


def tuning_text(window, info: dict | None) -> str:
    """The measured tuning as one sentence: "Written C-2 sounds A −12 cents" or why nothing was measured."""
    if not info:
        return ""
    if not info.get("pitched"):
        return window.t("Not pitched ({reason})", reason=info.get("reason", "")).replace("()", "").strip()
    return window.t("Written {reference} sounds {note} {cents:+d} cents", reference=info["reference_note"],
                    note=info["written_c_sounds"], cents=round(info["cents"]))


def role_combo(window, selected: str | None) -> QComboBox:
    combo = QComboBox()
    combo.addItem(role_label(window, None), None)
    for role in ROLES:
        combo.addItem(role_label(window, role), role)
    combo.setCurrentIndex(max(0, combo.findData(selected if selected in ROLES else None)))
    return combo


def audition_sample(window, sample, fmt: str):
    """Hear a sample that is not (yet) in the song: a rendered note through the sample player."""
    try:
        if fmt == "xm":
            wav = render_wav(sample, "C-4", "xm", 1.5)
        else:
            wav = sample_tools.render_wav(sample, "C-2", 1.5 if sample.loop_length else 2.0)[0]
    except ValidationError as exc:
        window.message("Cannot play this sample: {detail}", True, detail=exc)
        return None
    return window.audition_wav(wav)


class AddToBankDialog(QDialog):
    """See the module docstring. `info` is a `song_slots` row (or the WAV equivalent); `source` says where the
    sample comes from: {"module", "slot", "filename"} or {"wav": path, "filename"}."""

    def __init__(self, window, bank, info: dict, source: dict):
        super().__init__(window)
        self.window, self.bank, self.info, self.source = window, bank, info, source
        self.result_info: dict | None = None
        t = window.t
        self.setObjectName("addToBankDialog")
        self.setWindowTitle(t("Add to bank"))
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.name = QLineEdit(info.get("name") or "")
        self.name.setObjectName("bankEntryName")
        self.name.setMaxLength(22)
        self.name.setValidator(QRegularExpressionValidator(ASCII_NAME, self.name))
        form.addRow(t("Name"), self.name)
        self.role = role_combo(window, info.get("role"))
        self.role.setObjectName("bankEntryRole")
        form.addRow(t("Role"), self.role)
        self.category = QComboBox()
        self.category.setObjectName("bankEntryCategory")
        self.category.addItem(t("Automatic"), None)
        for key in CATEGORIES:
            self.category.addItem(t(CATEGORY_LABELS[key]), key)
        form.addRow(t("Type"), self.category)
        self.tags = QLineEdit()
        self.tags.setObjectName("bankEntryTags")
        self.tags.setPlaceholderText(t("tags, separated by commas"))
        form.addRow(t("Tags"), self.tags)
        self.loop_start = self.loop_length = None
        if "wav" in source:
            frames = info.get("frames", 0)
            self.loop_start, self.loop_length = QSpinBox(), QSpinBox()
            for box, name in ((self.loop_start, "wavLoopStart"), (self.loop_length, "wavLoopLength")):
                box.setObjectName(name)
                box.setRange(0, frames)
                box.setAccelerated(True)
            form.addRow(t("Loop start (frames)"), self.loop_start)
            form.addRow(t("Loop length (frames)"), self.loop_length)
        layout.addLayout(form)
        self.tuning = QLabel(tuning_text(window, info.get("tuning")))
        self.tuning.setObjectName("bankEntryTuning")
        self.tuning.setWordWrap(True)
        layout.addWidget(self.tuning)
        facts = t("{frames} frames · {bits}-bit · {loop}", frames=info.get("frames", 0), bits=info.get("bits", 8),
                  loop=t("looped") if info.get("looped") else t("one-shot"))
        where = t("Source: {file}, slot {slot}", file=source.get("filename"), slot=f"{source['slot']:02X}") \
            if source.get("slot") else t("Source: {file}", file=source.get("filename"))
        self.facts = QLabel(facts + "\n" + where)
        self.facts.setObjectName("bankEntrySource")
        self.facts.setWordWrap(True)
        layout.addWidget(self.facts)
        self.notice = QLabel()
        self.notice.setObjectName("bankEntryNotice")
        self.notice.setWordWrap(True)
        self.select_button = None
        if info.get("in_bank"):
            self.notice.setText(t("This sample is already in the bank as {id}.", id=info["in_bank"]))
            row = QHBoxLayout()
            row.addWidget(self.notice, 1)
            self.select_button = QDialogButtonBox()
            select = self.select_button.addButton(t("Select that entry"), QDialogButtonBox.ButtonRole.ActionRole)
            select.setObjectName("selectBankEntry")
            select.clicked.connect(self.select_existing)
            row.addWidget(self.select_button)
            layout.addLayout(row)
        else:
            self.notice.hide()
            layout.addWidget(self.notice)
        self.error = QLabel()
        self.error.setObjectName("bankEntryError")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("Add to bank"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def labels(self) -> dict:
        """What the owner chose, as `add_from_song` / `add_from_wav` keywords."""
        tags = [item.strip() for item in self.tags.text().split(",") if item.strip()]
        return {"name": self.name.text().strip() or None, "role": self.role.currentData(),
                "category": self.category.currentData(), "tags": tags or None}

    def select_existing(self):
        self.window.sample_browser.select_entry(self.info["in_bank"])
        self.reject()

    def accept(self):
        labels = self.labels()
        try:
            if "wav" in self.source:
                result = sample_intake.add_from_wav(self.bank, self.source["wav"], loop_start=self.loop_start.value(),
                                                    loop_length=self.loop_length.value(), **labels)
            else:
                result = sample_intake.add_from_song(self.bank, self.source["module"], self.source["slot"],
                                                     self.source["filename"], **labels)
        except (ValidationError, OSError, ValueError) as exc:
            self.error.setText(str(exc))
            self.error.show()
            return
        self.result_info = result
        self.window.bank_entry_added(result)
        super().accept()


class ModuleSlotsDialog(QDialog):
    """See the module docstring. `rows` are `song_slots(module)["slots"]`; the dropped module is not changed.
    With `song=True` (a drop on the song sample list) the checked rows can also be inserted into the open song: they
    enter the bank first, then the song takes them from the bank (`SampleLibrary.insert`, so the song's sample mode,
    the format conversions and the stored tuning corrections apply) as one undoable edit."""

    COLUMNS = ("", "Slot", "Name", "Role", "Tuning", "In bank")

    def __init__(self, window, bank, path: Path, module, rows: list[dict], song: bool = False):
        super().__init__(window)
        self.window, self.bank, self.path, self.module, self.rows = window, bank, Path(path), module, rows
        self.added: list[dict] = []
        self.inserted: list[dict] = []
        self.roles: list[QComboBox] = []
        t = window.t
        self.setObjectName("moduleSlotsDialog")
        self.setWindowTitle(t("Add samples from {file}", file=self.path.name))
        self.setMinimumSize(640, 360)
        layout = QVBoxLayout(self)
        self.hint = QLabel(t("Check the samples to add, name them, pick their role. Click a row to hear it; roles and "
                             "tuning are measured from the file, confirm them by listening."))
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.table = QTableWidget(len(rows), len(self.COLUMNS))
        self.table.setObjectName("moduleSlots")
        self.table.setHorizontalHeaderLabels([t(name) if name else "" for name in self.COLUMNS])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for index, row in enumerate(rows):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Unchecked if row.get("in_bank") else Qt.CheckState.Checked)
            self.table.setItem(index, 0, check)
            slot = QTableWidgetItem(f"{row['slot']:02X}")
            slot.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(index, 1, slot)
            name = QTableWidgetItem(row.get("name") or "")
            self.table.setItem(index, 2, name)
            combo = role_combo(window, row.get("role"))
            combo.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            self.roles.append(combo)
            self.table.setCellWidget(index, 3, combo)
            tuning = QTableWidgetItem(tuning_text(window, row.get("tuning")))
            tuning.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(index, 4, tuning)
            known = QTableWidgetItem(row.get("in_bank") or "")
            known.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(index, 5, known)
        self.table.cellClicked.connect(lambda row, column: self.play_row(row))
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setObjectName("moduleSlotsStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.slot_combo = self.insert_button = None
        if song:
            insert_row = QHBoxLayout()
            insert_row.addWidget(QLabel(t("Insert into the song at")))
            self.slot_combo = QComboBox()
            self.slot_combo.setObjectName("insertTargetSlot")
            self.slot_combo.addItem(t("First free slot"), None)
            if window.document:
                for number, sample in enumerate(window.document.module.samples, 1):
                    self.slot_combo.addItem(f"{number:02X} · {sample.name or t('free')}", number)
            insert_row.addWidget(self.slot_combo)
            self.insert_button = QDialogButtonBox()
            insert = self.insert_button.addButton(t("Insert into song"), QDialogButtonBox.ButtonRole.ActionRole)
            insert.setObjectName("insertSelectedSlots")
            insert.clicked.connect(self.insert_selected)
            insert_row.addWidget(self.insert_button)
            insert_row.addStretch()
            layout.addLayout(insert_row)
        self.buttons = QDialogButtonBox()
        self.add_button = self.buttons.addButton(t("Add to bank"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.add_button.setObjectName("addSelectedSlots")
        self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.buttons.accepted.connect(self.add_selected)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    # --- rows ----------------------------------------------------------------------------------------
    def set_checked(self, row: int, on: bool):
        self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def set_name(self, row: int, text: str):
        self.table.item(row, 2).setText(text)

    def set_role(self, row: int, role: str | None):
        self.roles[row].setCurrentIndex(max(0, self.roles[row].findData(role)))

    def selected_rows(self) -> list[int]:
        return [row for row in range(self.table.rowCount())
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def play_row(self, row: int):
        slot = self.rows[row]["slot"]
        audition_sample(self.window, self.module.samples[slot - 1], self.module.format)

    def _add(self, rows: list[int]) -> list[dict] | None:
        """The checked rows into the bank (an entry already there is reused); None after a refusal."""
        added = []
        for row in rows:
            name = self.table.item(row, 2).text().strip() or None
            try:
                result = sample_intake.add_from_module(self.bank, self.path, self.rows[row]["slot"], name=name,
                                                       role=self.roles[row].currentData())
            except (ValidationError, OSError, ValueError) as exc:
                self.status.setText(self.window.t("Slot {slot}: {detail}", slot=f"{self.rows[row]['slot']:02X}",
                                                  detail=exc))
                return None
            added.append(result)
        return added

    def add_selected(self):
        rows = self.selected_rows()
        if not rows:
            self.status.setText(self.window.t("Check at least one sample."))
            return
        added = self._add(rows)
        if added is None:
            return
        self.added = added
        created = sum(1 for item in added if item.get("created"))
        self.window.message("{created} samples added to the bank ({known} already there)", created=created,
                            known=len(added) - created)
        self.window.sample_browser.select_entry(added[-1]["id"])
        self.accept()

    def insert_selected(self, adapt: bool = False):
        """The checked rows into the open song, from the bank, as one undoable edit."""
        window = self.window
        rows = self.selected_rows()
        if not rows:
            self.status.setText(window.t("Check at least one sample."))
            return None
        if not window.document:
            self.status.setText(window.t("Open a song first."))
            return None
        if not window.sample_mode.allows("library"):
            self.status.setText(window.sample_mode.hint("library"))
            return None
        added = self._add(rows)
        if added is None:
            return None
        start = self.slot_combo.currentData()
        candidate = window.document.module
        targets = []
        for index in range(len(added)):
            target = start + index if start is not None else None
            targets.append(target if target is None or target <= len(candidate.samples) + 1 else None)
        occupied = [target for target in targets
                    if target is not None and target <= len(candidate.samples) and candidate.samples[target - 1].pcm]
        if occupied:
            yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
            answer = QMessageBox.question(window, window.t("Replace these samples?"),
                                          window.t("Slots {slots} are occupied. Replace them? The notes using them will "
                                                   "play the new samples.", slots=", ".join(f"{slot:02X}" for slot in occupied)),
                                          yes | no, no)
            if answer != yes:
                return None
        inserted = []
        try:
            for result, target in zip(added, targets):
                candidate, info = self.bank.insert(candidate, result["id"], target, target in occupied, adapt)
                inserted.append(info)
        except ValidationError as exc:
            if exc.code == "SAMPLE_INCOMPATIBLE" and not adapt:
                yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
                answer = QMessageBox.question(window, window.t("Adapt these samples?"),
                                              window.t("Some samples are outside the MOD profile. Prepare compatible "
                                                       "copies for this song? The bank originals are kept."), yes | no, no)
                return self.insert_selected(True) if answer == yes else None
            self.status.setText(str(exc))
            window.message("Cannot insert into the song: {detail}", True, detail=exc)
            return None
        if window.document.apply("Insert dropped samples", lambda target: target.__dict__.update(candidate.__dict__)):
            window.edited("Insert dropped samples")
        self.inserted = inserted
        slots = ", ".join(f"{info['slot']:02X} {info['library_id']}" for info in inserted)
        self.status.setText(window.t("Inserted {count} samples: {slots}", count=len(inserted), slots=slots))
        window.message("Inserted {count} samples into the song · Ctrl+Z to undo", count=len(inserted))
        self.accept()
        return inserted


__all__ = ["AddToBankDialog", "ModuleSlotsDialog", "ROLES", "audition_sample", "role_combo", "tuning_text"]
