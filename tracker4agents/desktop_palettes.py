"""The Palettes page of the Sample library tab: the sample sets of the bank's reference songs.

`PalettePanel` lists `bank.palettes()` with their summary; selecting one shows its entries (role, share of the
song's note starts, name), measured with `sample_intake.palette_tuning` ("in tune" or how many entries would be
retuned). A click on an entry auditions it; "Use in song" inserts the palette into the open document through
`SampleLibrary.use_palette` (retuned by relative note and finetune in an XM) as one undoable edit, then reports the
slot map. Relies on: the hosting `SampleBrowser` (window, bank, play_entry, cancel_preview), window.document,
window.module_format, window.submit, window.edited, window.message and the text-binding helpers.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout, QWidget

from . import sample_intake
from .model import ValidationError


class PalettePanel(QWidget):
    """See the module docstring."""

    def __init__(self, browser):
        super().__init__()
        self.browser, self.window = browser, browser.window
        window = self.window
        self.bank = None
        self.palette: dict | None = None
        self.tuning: dict | None = None
        self.rows: list[dict] = []
        self._token = 0
        self._stale = True
        self._jam_cache: dict = {}
        self.setObjectName("palettePanel")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.list = QListWidget()
        self.list.setObjectName("paletteList")
        self.list.setMinimumWidth(190)
        left.addWidget(self.list, 1)
        self.count = window._label("", "muted")
        left.addWidget(self.count)
        layout.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(4)
        self.title = window._label("Select a palette", "itemTitle")
        right.addWidget(self.title)
        self.summary = window._label("", "muted")
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        self.entries = QListWidget()
        self.entries.setObjectName("paletteEntries")
        right.addWidget(self.entries, 1)
        self.tuning_label = QLabel()
        self.tuning_label.setObjectName("paletteTuning")
        self.tuning_label.setWordWrap(True)
        right.addWidget(self.tuning_label)
        actions = QHBoxLayout()
        self.use_button = window._button("Use in song", self.use_in_song, "usePalette")
        actions.addWidget(self.use_button)
        self.report = window._label("", "muted")
        self.report.setWordWrap(True)
        actions.addWidget(self.report, 1)
        right.addLayout(actions)
        layout.addLayout(right, 2)
        self.list.currentItemChanged.connect(lambda *_: self.palette_selected())
        self.entries.itemClicked.connect(self.entry_clicked)
        self.entries.currentItemChanged.connect(lambda *_: self.browser.cancel_preview())
        self.retranslate()

    def retranslate(self):
        self.show_palette()
        self.show_count()

    # --- the list ------------------------------------------------------------------------------------
    def set_bank(self, bank):
        """The library tab (re)loaded a bank: list its palettes when the page is on screen, later otherwise."""
        self.bank = bank
        self._jam_cache = {}
        self._stale = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def refresh(self):
        self._stale = False
        self._token += 1
        token, bank = self._token, self.bank
        if bank is None:
            return
        selected = self.palette["id"] if self.palette else None

        def finished(result):
            if token != self._token:
                return
            self.rows = result["palettes"]
            self.list.blockSignals(True)
            self.list.clear()
            wanted = -1
            for index, row in enumerate(self.rows):
                item = QListWidgetItem(f"{row['id']}  ·  {row['format'].upper()} {row['channels']}ch  ·  {row['summary']}")
                item.setData(Qt.ItemDataRole.UserRole, row["id"])
                item.setToolTip(self.window.t("{played} of {entries} entries played · {bpm} BPM · {seconds:.0f} s",
                                              played=row["played"], entries=row["entries"], bpm=row["bpm"],
                                              seconds=row["duration_seconds"]))
                self.list.addItem(item)
                if row["id"] == selected:
                    wanted = index
            self.list.blockSignals(False)
            self.list.setCurrentRow(wanted)
            if wanted < 0:
                self.palette = self.tuning = None
                self.show_palette()
            self.show_count()

        def failed(detail):
            if token == self._token:
                self.rows = []
                self.list.clear()
                self.palette = self.tuning = None
                self.show_palette()
                self.count.setText(self.window.t("No palettes in this bank"))
                self.count.setToolTip(str(detail))

        self.window.submit(bank.palettes, finished, failed)

    def show_count(self):
        self.count.setText(self.window.t("{count} palettes", count=len(self.rows)) if self.rows else
                           self.window.t("No palettes in this bank"))

    def palette_selected(self):
        item = self.list.currentItem()
        self.browser.cancel_preview()
        if item is None or self.bank is None:
            self.palette = self.tuning = None
            self.show_palette()
            return
        self._token += 1
        token, bank, palette_id = self._token, self.bank, item.data(Qt.ItemDataRole.UserRole)

        def operation():
            palette = bank.palette(palette_id)
            return palette, sample_intake.palette_tuning(bank, palette)

        def finished(result):
            if token != self._token:
                return
            self.palette, self.tuning = result
            self.show_palette()

        def failed(detail):
            if token == self._token:
                self.palette = self.tuning = None
                self.show_palette()
                self.window.message("Palette unavailable: {detail}", True, detail=detail)

        self.title.setText(palette_id)
        self.window.submit(operation, finished, failed)

    def show_palette(self):
        t = self.window.t
        self.entries.clear()
        self.report.setText("")
        if not self.palette:
            self.title.setText(t("Select a palette"))
            self.summary.setText("")
            self.tuning_label.setText("")
            self.use_button.setEnabled(False)
            return
        palette = self.palette
        self.title.setText(palette["id"])
        self.summary.setText(palette.get("summary") or "")
        total = sum(entry.get("note_starts", 0) for entry in palette["entries"]) or 1
        names = {}
        try:
            names = {entry["id"]: self.bank.get(entry["id"])["name"] for entry in palette["entries"]}
        except (ValidationError, OSError):
            pass
        for entry in palette["entries"]:
            share = f"{100 * entry.get('note_starts', 0) / total:.0f}%"
            role = t(entry["role"].capitalize()) if entry.get("role") else "—"
            item = QListWidgetItem(f"{role:<10} {share:>4}   {entry['id']}  ·  {names.get(entry['id'], '')}")
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            item.setToolTip(t("{starts} note starts · confidence {confidence}", starts=entry.get("note_starts", 0),
                              confidence=t(entry.get("confidence") or "low")))
            self.entries.addItem(item)
        self.tuning_label.setText(self.tuning_text())
        self.use_button.setEnabled(bool(self.window.document))

    def tuning_text(self) -> str:
        t = self.window.t
        if not self.tuning:
            return ""
        if self.tuning["consistent"]:
            return t("Tuning: in tune") if self.tuning["entries"] else t("Tuning: no pitched entry to compare")
        off = [row for row in self.tuning["entries"] if not row["in_tune"]]
        return t("Tuning: {count} to retune ({ids})", count=len(off), ids=", ".join(row["id"] for row in off))

    # --- auditions -----------------------------------------------------------------------------------
    def entry_clicked(self, item):
        if item is not None:
            self.browser.play_entry(item.data(Qt.ItemDataRole.UserRole))

    def jam_sample(self):
        """The selected palette entry's sample, for the piano keys (None when nothing is selected)."""
        item = self.entries.currentItem()
        if item is None or self.bank is None:
            return None
        sample_id = item.data(Qt.ItemDataRole.UserRole)
        if sample_id not in self._jam_cache:
            try:
                self._jam_cache[sample_id] = self.bank.read_sample(sample_id)
            except (ValidationError, OSError):
                return None
        return self._jam_cache[sample_id]

    # --- into the song -------------------------------------------------------------------------------
    def use_in_song(self, adapt: bool = False) -> dict | None:
        """Insert the palette as one undoable edit; an XM is retuned by relative note and finetune."""
        window = self.window
        if not self.palette or not window.document or self.bank is None:
            return None
        module = window.document.module
        try:
            candidate, info = self.bank.use_palette(self.palette["id"], module, adapt=adapt,
                                                    retune=module.format == "xm")
        except ValidationError as exc:
            if exc.code == "SAMPLE_INCOMPATIBLE" and not adapt:
                yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
                answer = QMessageBox.question(window, window.t("Adapt this palette?"),
                                              window.t("Some entries are outside the MOD profile. Prepare compatible "
                                                       "copies for this song? The bank originals are kept."), yes | no, no)
                return self.use_in_song(True) if answer == yes else None
            self.report.setText(str(exc))
            window.message("Cannot use this palette: {detail}", True, detail=exc)
            return None
        except (OSError, ValueError) as exc:
            window.message("Cannot use this palette: {detail}", True, detail=exc)
            return None
        changed = window.document.apply("Use palette", lambda target: target.__dict__.update(candidate.__dict__))
        if changed:
            window.edited("Use palette")
        slots = ", ".join(f"{item['slot']:02X} {item['role']} {item['id']}" for item in info["slot_map"])
        retuned = info.get("retuned") or []
        text = window.t("Inserted {count} samples: {slots}", count=info["inserted"], slots=slots)
        if retuned:
            text += " · " + window.t("{count} retuned", count=len(retuned))
        self.report.setText(text)
        window.message("Palette {id} used: {count} samples · Ctrl+Z to undo", id=info["palette"], count=info["inserted"])
        return info


__all__ = ["PalettePanel"]
