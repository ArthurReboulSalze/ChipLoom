"""The Sample library tab: the active bank's entries, their audition, and their insertion into the song.

`SampleBrowser` searches the bank (`SampleLibrary.search`, in the background), shows the selected entry (waveform,
settings, the owner's tuning correction), auditions it (Listen, a double-click, a click when Auto-play is on, the
piano keys) and inserts it into the open document (`insert_entry`, one undoable step). Its header names the bank
(the active one shared with the agent, see `desktop_bank`) and switches to the Palettes page (`desktop_palettes`).
A MOD, XM, project or WAV dropped on the tab goes to `window.bank_drop`; an entry dragged from the list to the song
sample list is inserted there. Relies on: window.document, window.state, window.submit, window.cache,
window.sample_player, window.meter, window.samples, window.sample_mode, window.bank_changed, window.autoplay,
window.make_autoplay, `drag_hint`, `drag_hint_done`, `edited`, `pause_playback`, `message` and the binding helpers.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QListWidgetItem,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from . import sample_intake
from .desktop_bank import BankList, initial_library, retune_text
from .desktop_drops import drop_kind
from .desktop_palettes import PalettePanel
from .desktop_widgets import ElidedLabel, media_call
from .model import NOTES
from .sample_library import CATEGORIES, SampleLibrary

CATEGORY_LABELS = {"cycle": "Cyclic waves", "percussion": "Percussion", "texture": "Textures",
                   "effect": "Effects", "unclassified": "Unclassified", "silent": "Silent"}
ROLES = [("All roles", None), ("Bass", "bass-candidate"), ("Lead", "lead-candidate"),
         ("Arpeggio", "arpeggio-candidate"), ("Percussion", "percussion-candidate")]


class SampleBrowser(QWidget):
    PAGE_SIZE = 100

    def __init__(self, window, waveform_factory):
        super().__init__()
        self.window = window
        self.bank: SampleLibrary | None = None
        self.entry = self._jam = None
        self.page, self.total = 0, 0
        self._query_token = self._preview_token = 0
        self._loading = False
        self._error = False
        self.setObjectName("sampleLibraryBrowser")
        self.setMinimumWidth(0)
        self.setAcceptDrops(True)
        self.library_path = initial_library(window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 5, 0, 0)
        layout.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.bank_label = ElidedLabel("", "muted")
        self.bank_label.setObjectName("bankName")
        header.addWidget(self.bank_label, 1)
        self.page_buttons = []
        for text, index, name in (("Samples", 0, "pageSamples"), ("Palettes", 1, "pagePalettes")):
            control = window._button(text, lambda _=False, index=index: self.show_page(index), name)
            control.setCheckable(True)
            control.setProperty("compact", True)
            header.addWidget(control)
            self.page_buttons.append(control)
        layout.addLayout(header)

        filters = QHBoxLayout()
        filters.setSpacing(5)
        self.search = QLineEdit()
        self.search.setObjectName("sampleSearch")
        self.search.setMinimumWidth(80)
        window._bind(self.search, "Search samples…", "setPlaceholderText")
        self.search.setAccessibleName(window.t("Search samples…"))
        filters.addWidget(self.search, 1)
        self.category = QComboBox()
        self.category.setObjectName("sampleCategory")
        self.role = QComboBox()
        self.role.setObjectName("sampleRole")
        for combo in (self.category, self.role):
            combo.setMinimumContentsLength(9)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMaximumWidth(155)
            filters.addWidget(combo)
        self.compatible = QCheckBox()
        self.compatible.setObjectName("compatibleSamplesOnly")
        window._bind(self.compatible, "MOD compatible")
        self.compatible.setChecked(True)
        filters.addWidget(self.compatible)
        self.folder_button = window._button("Folder…", self.choose_library)
        self.folder_button.setObjectName("chooseSampleLibrary")
        filters.addWidget(self.folder_button)
        self.reload_button = window._button("Refresh", self.reload)
        filters.addWidget(self.reload_button)
        layout.addLayout(filters)

        self.pages = QStackedWidget()
        samples_page = QWidget()
        page_layout = QVBoxLayout(samples_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(5)
        content = QHBoxLayout()
        content.setSpacing(10)
        self.results = BankList()
        self.results.setObjectName("librarySamples")
        self.results.setMinimumWidth(190)
        self.results.setMinimumHeight(70)
        content.addWidget(self.results, 1)
        preview = QVBoxLayout()
        preview.setSpacing(3)
        self.title = window._label("Select a library sample", "itemTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        preview.addWidget(self.title)
        self.waveform = waveform_factory(window)
        self.waveform.setMinimumHeight(30)
        preview.addWidget(self.waveform, 1)
        self.details = window._label("", "muted")
        self.details.setWordWrap(True)
        self.details.setMinimumWidth(0)
        preview.addWidget(self.details)
        controls = QHBoxLayout()
        controls.addWidget(window._label("Note"))
        self.note = QComboBox()
        self.note.setObjectName("libraryPreviewNote")
        self.note.addItems(NOTES)
        self.note.setCurrentText("C-2")
        self.note.setMaxVisibleItems(12)
        controls.addWidget(self.note)
        self.listen = window._button("Listen", self.play)
        self.listen.setObjectName("listenLibrarySample")
        controls.addWidget(self.listen)
        self.stop_button = window._button("Stop", self.stop)
        controls.addWidget(self.stop_button)
        self.autoplay = window.make_autoplay("autoplayLibrary")
        controls.addWidget(self.autoplay)
        controls.addStretch()
        preview.addLayout(controls)
        content.addLayout(preview, 2)
        page_layout.addLayout(content, 1)

        actions = QHBoxLayout()
        actions.setSpacing(5)
        self.count = window._label("", "muted")
        self.count.setMinimumWidth(60)
        actions.addWidget(self.count)
        self.previous = window._button("‹", lambda: self.change_page(-1))
        self.next = window._button("›", lambda: self.change_page(1))
        for control in (self.previous, self.next):
            control.setFixedWidth(30)
            actions.addWidget(control)
        actions.addStretch()
        actions.addWidget(window._label("Slot"))
        self.target = QComboBox()
        self.target.setObjectName("libraryTargetSlot")
        self.target.setMinimumContentsLength(12)
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.setMaximumWidth(210)
        actions.addWidget(self.target)
        self.replace = QCheckBox()
        self.replace.setObjectName("replaceLibrarySlot")
        window._bind(self.replace, "Replace")
        window._bind(self.replace, "Existing notes using this slot will use the replacement.", "setToolTip")
        actions.addWidget(self.replace)
        self.adapt = QCheckBox()
        self.adapt.setObjectName("adaptLibrarySample")
        window._bind(self.adapt, "Adapt copy")
        window._bind(self.adapt, "Prepare a compatible copy for MOD; keep the library original.", "setToolTip")
        actions.addWidget(self.adapt)
        self.add_button = window._button("Add to song", self.add_to_song)
        self.add_button.setObjectName("addLibrarySample")
        actions.addWidget(self.add_button)
        page_layout.addLayout(actions)
        self.pages.addWidget(samples_page)
        self.palettes = PalettePanel(self)
        self.pages.addWidget(self.palettes)
        layout.addWidget(self.pages, 1)

        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(220)
        self.debounce.timeout.connect(self.reload)
        self.search.textChanged.connect(self.schedule_search)
        self.category.currentIndexChanged.connect(self.schedule_search)
        self.role.currentIndexChanged.connect(self.schedule_search)
        self.compatible.toggled.connect(self.schedule_search)
        self.results.currentItemChanged.connect(lambda *_: self.selected())
        self.results.itemClicked.connect(self.entry_clicked)
        self.results.itemDoubleClicked.connect(lambda *_: self.play())
        self.target.currentIndexChanged.connect(self.target_changed)
        self.replace.toggled.connect(self.update_controls)
        self.adapt.toggled.connect(self.update_controls)
        self.note.currentTextChanged.connect(lambda *_: self.cancel_preview())
        self.show_page(0)
        self.retranslate()
        self.update_slots()
        QTimer.singleShot(0, self.reload)

    def retranslate(self):
        for combo, entries in ((self.category, [("All types", None)] + [(CATEGORY_LABELS[key], key) for key in CATEGORIES]),
                               (self.role, ROLES)):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for label, key in entries:
                combo.addItem(self.window.t(label), key)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)
        self.folder_button.setToolTip(str(self.library_path))
        self.search.setAccessibleName(self.window.t("Search samples…"))
        self.show_bank()
        self.show_entry()
        self.update_slots(reset_confirmation=False)
        self.show_count()
        self.palettes.retranslate()

    # --- the bank ------------------------------------------------------------------------------------
    def show_bank(self):
        """Name the active bank in the tab's header (the full path in the tooltips)."""
        path = self.library_path
        self.bank_label.setText(self.window.t("Bank: {name}", name=path.name or str(path)))
        self.bank_label.setToolTip(self.window.t("Active bank: {path}", path=str(path)))
        self.folder_button.setToolTip(str(path))

    def show_page(self, index: int):
        self.pages.setCurrentIndex(index)
        for position, control in enumerate(self.page_buttons):
            control.setChecked(position == index)
        self.cancel_preview()

    def schedule_search(self, *_):
        self.page = 0
        self._query_token += 1
        self.cancel_preview()
        self.debounce.start()

    def choose_library(self):
        folder = QFileDialog.getExistingDirectory(self, self.window.t("Choose a sample library folder"),
            str(self.library_path), options=QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self.window.open_bank(Path(folder))

    def set_library(self, path: Path):
        """Show `path` and make it the active bank (shared with the agent); raises when the folder is neither
        a bank nor empty."""
        self.library_path = Path(path).resolve()
        self.window.state.values["sample_library"] = str(self.library_path)
        self.window._save_preferences()
        try:
            sample_intake.set_active_library(self.library_path)
        finally:
            self.page = 0
            self.reload()
            self.window.bank_changed()

    def reload(self):
        self.debounce.stop()
        self._query_token += 1
        token = self._query_token
        self.cancel_preview()
        self._loading = True
        self._error = False
        bank = SampleLibrary(self.library_path)
        self.bank = bank
        self.palettes.set_bank(bank)
        query, category, role = self.search.text(), self.category.currentData(), self.role.currentData()
        compatible, offset = self.compatible.isChecked(), self.page * self.PAGE_SIZE
        selected_id = self.entry["id"] if self.entry else None
        self.entry = None
        self.update_controls()
        self.count.setText(self.window.t("Loading…"))

        def operation():
            return bank.search(query, [role] if role else [], category, compatible, offset, self.PAGE_SIZE)

        def finished(result):
            if token != self._query_token:
                return
            self._loading = False
            self.total = result["total"]
            if self.page > 0 and offset >= self.total:
                self.page = 0
                self.reload()
                return
            self.results.blockSignals(True)
            self.results.clear()
            wanted = 0
            for index, entry in enumerate(result["samples"]):
                retune = retune_text(entry)
                item = QListWidgetItem(f"{entry['id']}  ·  {entry['name']}" + (f"  ·  {retune}" if retune else ""))
                item.setData(Qt.ItemDataRole.UserRole, entry["id"])
                item.setToolTip(" · ".join([self.window.t(CATEGORY_LABELS[entry["category"]]), *entry["tags"]]))
                self.results.addItem(item)
                if entry["id"] == selected_id:
                    wanted = index
            self.results.blockSignals(False)
            self.results.setCurrentRow(wanted if self.results.count() else -1)
            self.selected()
            self.show_count()

        def failed(detail):
            if token != self._query_token:
                return
            self._loading = False
            self._error = True
            self.total = 0
            self.results.clear()
            self.entry = None
            self.waveform.set_sample(None)
            self.title.setText(self.window.t("Sample library unavailable"))
            self.details.setText(self.window.t("Choose a folder containing library.json."))
            self.details.setToolTip(str(detail))
            self.show_count()
            self.update_controls()

        self.window.submit(operation, finished, failed)

    def select_entry(self, sample_id: str):
        """Show one entry: the search box takes its ID (the compatibility filter is lifted) and it is selected."""
        self.search.blockSignals(True)
        self.search.setText(sample_id)
        self.search.blockSignals(False)
        self.compatible.blockSignals(True)
        self.compatible.setChecked(False)
        self.compatible.blockSignals(False)
        self.page = 0
        self.entry = {"id": sample_id}
        self.show_page(0)
        self.reload()

    def show_count(self):
        self.count.setText(self.window.t("{count} samples", count=self.total))
        self.count.setToolTip(str(self.library_path))
        self.previous.setVisible(self.total > self.PAGE_SIZE)
        self.next.setVisible(self.total > self.PAGE_SIZE)
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled((self.page + 1) * self.PAGE_SIZE < self.total)

    def change_page(self, direction):
        self.page = max(0, self.page + direction)
        self.reload()

    def cancel_preview(self):
        self._preview_token += 1

    def shutdown(self):
        self._query_token += 1
        self.cancel_preview()
        self.debounce.stop()

    # --- drops -----------------------------------------------------------------------------------------
    @staticmethod
    def dropped(event):
        """(kind, path) of a module or WAV being dragged over the tab, else None."""
        found = drop_kind(event.mimeData())
        return found if found and found[0] in ("module", "wav") else None

    def dragEnterEvent(self, event):
        found = self.dropped(event)
        if found:
            event.acceptProposedAction()
            self.window.drag_hint("bank" if found[0] == "module" else "wav")
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.dropped(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.window.drag_hint_done()

    def dropEvent(self, event):
        found = self.dropped(event)
        self.window.drag_hint_done()
        if not found:
            event.ignore()
            return
        event.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.window.bank_drop(found[1]))

    # --- the selected entry ----------------------------------------------------------------------------
    def selected(self):
        self.cancel_preview()
        self.adapt.setChecked(False)
        item = self.results.currentItem()
        self.entry = self._jam = None
        if item and self.bank and not self._loading:
            try:
                self.entry = self.bank.get(item.data(Qt.ItemDataRole.UserRole))
                self._jam = self.bank.read_sample(self.entry["id"])
                self.waveform.set_sample(self._jam)
            except (OSError, ValueError, RuntimeError) as exc:
                self.window.message("Library sample unavailable: {detail}", True, detail=str(exc))
        if not self.entry:
            self.waveform.set_sample(None)
        self.show_entry()
        self.update_controls()

    def entry_clicked(self, item):
        """A click on an entry auditions it when Auto-play is on."""
        if item is not None and self.entry and self.window.autoplay():
            self.play()

    def jam_sample(self):
        """The sample the piano keys play: the selected entry, or the selected palette entry on the Palettes page."""
        if self.pages.currentIndex() == 1:
            return self.palettes.jam_sample()
        return self._jam if self.entry else None

    def show_entry(self):
        if not self.entry:
            self.title.setText(self.window.t("Sample library unavailable" if self._error else "Select a library sample"))
            self.details.setText(self.window.t("Choose a folder containing library.json.") if self._error else
                                 self.window.t("No matching samples") if self.bank and not self._loading else "")
            return
        entry = self.entry
        self.title.setText(f"{entry['id']} · {entry['name']}")
        self.title.setToolTip(self.title.text())
        loop = self.window.t("loop {start} → {end}", start=entry["loop_start"],
                             end=entry["loop_start"] + entry["loop_length"]) if entry["loop_length"] else self.window.t("no loop")
        text = self.window.t("{size} bytes · {loop} · fine tune {tune} · volume {volume}",
                             size=entry["bytes"], loop=loop, tune=entry["finetune"], volume=entry["volume"])
        retune = retune_text(entry)
        if retune:
            text += " · " + self.window.t("retune {retune}", retune=retune)
        self.details.setText(text)
        self.details.setToolTip(" · ".join(entry["tags"]))

    def update_slots(self, reset_confirmation=True):
        previous = self.target.currentData()
        confirmed = self.replace.isChecked()
        self.target.blockSignals(True)
        self.target.clear()
        self.target.addItem(self.window.t("New / free slot"), None)
        document = self.window.document
        if document:
            for index, sample in enumerate(document.module.samples, 1):
                name = sample.name or self.window.t("Empty")
                self.target.addItem(f"{index:02X} · {name}", index)
                self.target.setItemData(self.target.count() - 1, f"{index:02X} · {name}", Qt.ItemDataRole.ToolTipRole)
        self.target.setCurrentIndex(max(0, self.target.findData(previous)))
        self.target.blockSignals(False)
        self.replace.setChecked(False if reset_confirmation else confirmed)
        self.update_controls()

    def target_changed(self, *_):
        self.replace.setChecked(False)
        self.update_controls()

    def update_controls(self, *_):
        selected = bool(self.entry) and not self._loading
        self.listen.setEnabled(selected)
        self.note.setEnabled(selected)
        document = self.window.document
        slot = self.target.currentData()
        occupied = bool(document and slot is not None and slot <= len(document.module.samples)
                        and document.module.samples[slot - 1].pcm)
        self.replace.setVisible(occupied)
        incompatible = bool(self.entry and not self.entry["compatibility"]["compatible"])
        self.adapt.setVisible(incompatible)
        ready = selected and bool(document) and (not occupied or self.replace.isChecked())
        explanation = ""
        # An XM takes the sample converted like `convert` does (8-bit, played at C-4), in up to 128 instruments.
        limit = 128 if document and document.module.format == "xm" else 31
        if ready and incompatible:
            ready = self.adapt.isChecked()
            if ready:
                try:
                    self.bank.sample(self.entry["id"], adapt=True)
                except (OSError, ValueError, RuntimeError):
                    ready = False
            if not ready:
                explanation = "This sample needs a compatible copy before adding."
        if ready and slot is None:
            module = document.module
            used = {value.sample for pattern in module.patterns for value in pattern.cells.values() if value.sample}
            if len(module.samples) >= limit and not any(not sample.pcm and index not in used
                                                    for index, sample in enumerate(module.samples, 1)):
                ready = False
                explanation = "No free slot. Select an existing slot to replace."
        if occupied and not self.replace.isChecked():
            explanation = "Check Replace to use this occupied slot."
        mode = getattr(self.window, "sample_mode", None)
        if document and mode is not None and not mode.allows("library"):   # a synthesized song refuses the bank
            ready = False
            explanation = mode.hint("library")
        self.add_button.setEnabled(bool(ready))
        self.add_button.setToolTip(self.window.t(explanation) if explanation else "")
        self.target.setEnabled(bool(document))

    # --- auditions -------------------------------------------------------------------------------------
    def play(self):
        if self.entry:
            self.play_entry(self.entry["id"])

    def play_entry(self, sample_id: str, note: str | None = None):
        """Hear a bank entry at the preview note (the song pauses), rendered in the background."""
        if not self.bank:
            return
        self.cancel_preview()
        token = self._preview_token
        bank, note = self.bank, note or self.note.currentText()

        def finished(path):
            if token != self._preview_token:
                return
            self.window.meter.reset()
            self.window.pause_playback()
            media_call(self.window.sample_player, "stop")
            media_call(self.window.sample_player, "setSource", QUrl.fromLocalFile(str(path)))
            self.window.sample_player.play()

        def failed(detail):
            if token == self._preview_token:
                self.window.message("Library sample unavailable: {detail}", True, detail=detail)

        self.window.submit(lambda: self.window.cache.library_sample(bank, sample_id, note), finished, failed)

    def stop(self):
        self.cancel_preview()
        media_call(self.window.sample_player, "stop")
        self.window.meter.reset()

    # --- into the song ---------------------------------------------------------------------------------
    def add_to_song(self):
        if not self.add_button.isEnabled() or not self.entry or not self.window.document:
            return None
        return self.insert_entry(self.entry["id"], self.target.currentData(), self.replace.isChecked(),
                                 self.adapt.isChecked())

    def insert_entry(self, sample_id: str, slot: int | None, replace: bool = False, adapt: bool = False) -> dict | None:
        """Insert a bank entry into the document as one undoable step and select the slot it took."""
        window = self.window
        if not window.document or not self.bank:
            return None
        try:
            name = self.bank.get(sample_id)["name"]
            info = window.document.insert_library_sample(self.bank, sample_id, slot=slot, replace=replace, adapt=adapt)
            self.replace.setChecked(False)
            if info["changed"]:
                self.cancel_preview()
                window.edited("Add library sample")
                for row in range(window.samples.count()):
                    if window.samples.item(row).data(Qt.ItemDataRole.UserRole) == info["slot"] - 1:
                        window.samples.setCurrentRow(row)
                        break
                window.message("Added {name} to slot {slot} · Ctrl+Z to undo", name=name, slot=f"{info['slot']:02X}")
            return info
        except (OSError, ValueError, RuntimeError) as exc:
            window.message("Cannot add library sample: {detail}", True, detail=str(exc))
            return None


__all__ = ["CATEGORY_LABELS", "ROLES", "SampleBrowser"]
