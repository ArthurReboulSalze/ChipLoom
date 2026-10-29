"""User-managed sample banks in the ChipLoom window: the Bank menu and the active bank, auditions on click,
adding a song sample to the bank, and drag and drop between the bank and the song.

`BankMixin` (mixed into `TrackerWindow`):
- `_build_bank_menu(menu)`: Bank → Open bank…, New bank…, New starter bank…, Recent banks, Open bank folder.
- `open_bank(path)`, `choose_bank()`, `new_bank()`, `new_starter_bank()`, `open_bank_folder()`: the active bank is
  shared with the agent through `sample_intake.set_active_library`; `bank_changed()` refreshes what shows it.
  `initial_library(window)` picks the bank opened at start and `ensure_bank(path)` builds the starter bank
  (`starter_bank.build`) when it is the active one and missing.
- `make_autoplay(name)` / `set_autoplay(on)`: the "Auto-play" boxes (library tab and song samples), one remembered
  setting (`state.values["autoplay"]`, on by default).
- `add_slot_to_bank(slot)`: the add-to-bank sheet for a song slot (`desktop_bank_dialogs.AddToBankDialog`).
- `bank_drop(path, target)`: a file dropped on the Sample library tab or the song sample list (.mod/.xm/.json: the
  slots dialog, .wav: the sheet). `desktop_drops` reads drags and shows the hints.
- `insert_bank_entry(sample_id, slot)`: a bank entry dragged onto the song sample list (asks before replacing).

`BankList` is the library tab's result list (a drag source carrying the entry ID as `BANK_MIME`); `SongSampleList`
the song sample list (drop target for entries and modules, right-click menu with Play and Add to bank…).
Relies on: window.sample_browser (library_path, bank, set_library, insert_entry, select_entry, reload),
window.samples, window.document, window.state, window.module_format, `play_sample`, `drag_hint`, `drag_hint_done`,
`message`, `_save_preferences` and the text-binding helpers (`_bind`, `_menu_action`, `t`).
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QFileDialog, QListWidget, QMenu, QMessageBox

from . import sample_intake
from .desktop_drops import BANK_MIME, MODULE_SUFFIXES, drop_kind
from .model import ValidationError
from .sample_library import DEFAULT_LIBRARY, SampleLibrary

DROP_SUFFIXES = MODULE_SUFFIXES + (".wav",)
ROOT = Path(__file__).resolve().parents[1]


def initial_library(window) -> Path:
    """The bank the window opens at start: the active bank when one was chosen (or `CHIPLOOM_BANK` is set),
    otherwise a folder the owner chose in an earlier session, otherwise the active bank by default (the
    repository's bank, or the starter bank, which `SampleBrowser.reload` builds when it does not exist yet)."""
    chosen = os.environ.get("CHIPLOOM_BANK") or (sample_intake._home() / sample_intake.BANK_FILE).exists()
    saved = window.state.values.get("sample_library")
    if not chosen and saved:
        try:
            path = Path(saved).resolve()
            if (path / "library.json").exists():
                return path
        except (OSError, ValueError):
            pass
    try:
        return sample_intake.active_library()
    except (OSError, ValueError):
        return ROOT / DEFAULT_LIBRARY


def ensure_bank(path: Path) -> Path:
    """Build the starter bank when `path` is its place and it does not exist yet (called off the GUI thread)."""
    if path == sample_intake.starter_path() and not (path / "library.json").exists():
        from .starter_bank import build
        try:
            build(path)
        except ValidationError:   # built meanwhile by the agent or another window
            pass
    return path


def retune_text(entry: dict | None) -> str:
    """An entry's stored tuning correction as "+12 st +20 c" (empty when there is none)."""
    retune = (entry or {}).get("retune")
    if not retune:
        return ""
    parts = []
    if retune.get("semitones"):
        parts.append(f"{retune['semitones']:+d} st")
    if retune.get("cents"):
        parts.append(f"{retune['cents']:+d} c")
    return " ".join(parts)


class BankList(QListWidget):
    """The library tab's results: dragging an entry carries its ID, for the song sample list."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def mimeData(self, items):
        data = QMimeData()
        if items:
            sample_id = items[0].data(Qt.ItemDataRole.UserRole)
            data.setData(BANK_MIME, str(sample_id).encode())
            data.setText(str(sample_id))
        return data


class SongSampleList(QListWidget):
    """The song's sample list: a bank entry dropped on a slot is inserted there, a dropped module opens the slot
    chooser (add to the bank, insert into the song); right-click offers Play and Add to bank…"""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    @staticmethod
    def accepts(event):
        found = drop_kind(event.mimeData())
        return found if found and found[0] in ("bank", "module") else None

    def dragEnterEvent(self, event):
        found = self.accepts(event)
        if found:
            event.acceptProposedAction()
            self.window.drag_hint("entry" if found[0] == "bank" else "song")
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.accepts(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.window.drag_hint_done()

    def dropEvent(self, event):
        found = self.accepts(event)
        self.window.drag_hint_done()
        if not found:
            event.ignore()
            return
        event.acceptProposedAction()
        kind, value = found
        if kind == "module":
            QTimer.singleShot(0, lambda: self.window.bank_drop(value, target="song"))
            return
        item = self.itemAt(event.position().toPoint())
        slot = item.data(Qt.ItemDataRole.UserRole) + 1 if item else None
        self.window.insert_bank_entry(value, slot)

    def slot_at(self, pos) -> int | None:
        item = self.itemAt(pos)
        return item.data(Qt.ItemDataRole.UserRole) + 1 if item else None

    def menu_for(self, slot: int | None) -> QMenu | None:
        """The right-click menu of a slot (None outside the items)."""
        if slot is None or not self.window.document:
            return None
        menu = QMenu(self)
        menu.addAction(self.window.t("Play"), self.window.play_sample)
        menu.addAction(self.window.t("Add to bank…"), lambda: self.window.add_slot_to_bank(slot))
        return menu

    def show_menu(self, pos):
        slot = self.slot_at(pos)
        if slot is not None:
            self.setCurrentItem(self.itemAt(pos))
        menu = self.menu_for(slot)
        if menu is not None:
            menu.exec(self.viewport().mapToGlobal(pos))


class BankMixin:
    """The Bank menu, the active bank, auto-play, add to bank and drops (see the module docstring)."""

    # --- the Bank menu and the active bank ------------------------------------------------------------
    def _build_bank_menu(self, menu):
        self.bank_menu = menu
        self._menu_action(menu, "Open bank…", self.choose_bank)
        self._menu_action(menu, "New bank…", self.new_bank)
        self._menu_action(menu, "New starter bank…", self.new_starter_bank)
        self.recent_banks_menu = self._bind(menu.addMenu(""), "Recent banks", "setTitle")
        menu.addSeparator()
        self._menu_action(menu, "Open bank folder", self.open_bank_folder)
        self._fill_recent_banks()

    def _fill_recent_banks(self):
        menu = self.recent_banks_menu
        menu.clear()
        recent = [item for item in sample_intake.recent_libraries()]
        for path in recent:
            action = menu.addAction(Path(path).name or path)
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, path=path: self.open_bank(Path(path)))
        menu.setEnabled(bool(recent))

    def bank_path(self) -> Path:
        return self.sample_browser.library_path

    def bank_changed(self):
        """The active bank changed (menu, library tab button, agent): refresh what names it."""
        self._fill_recent_banks()
        self.sample_browser.show_bank()
        self.sample_workshop.levels.invalidate()
        if hasattr(self.sample_workshop, "tuning"):
            self.sample_workshop.tuning.load()

    def open_bank(self, path: Path) -> bool:
        """Make `path` the active bank and show it in the library tab."""
        try:
            self.sample_browser.set_library(Path(path))
        except ValidationError as exc:
            self.message("Cannot open this bank: {detail}", True, detail=exc)
            return False
        self.message("Bank: {name}", name=str(self.bank_path()))
        return True

    def choose_bank(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("Open a sample bank folder"), str(self.bank_path()),
                                                  options=QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self.open_bank(Path(folder))

    def new_bank(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("Choose a new or empty folder for the bank"),
                                                  str(self.bank_path().parent),
                                                  options=QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self.create_bank(Path(folder))

    def create_bank(self, path: Path) -> bool:
        path = Path(path)
        try:
            if not (path / "library.json").exists():
                SampleLibrary(path).create()
        except (ValidationError, OSError) as exc:
            self.message("Cannot create a bank here: {detail}", True, detail=exc)
            return False
        return self.open_bank(path)

    def new_starter_bank(self):
        """Generate the ChipLoom starter bank (recipe sounds and palettes) in a folder and make it active."""
        default = sample_intake.starter_path()
        start = default if not default.exists() else self.bank_path().parent
        folder = QFileDialog.getExistingDirectory(self, self.t("Choose a new or empty folder for the starter bank"),
                                                  str(start), options=QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self.create_starter_bank(Path(folder))

    def create_starter_bank(self, path: Path) -> bool:
        from .starter_bank import build
        path = Path(path)
        try:
            result = build(path)
        except (ValidationError, OSError) as exc:
            self.message("Cannot build the starter bank here: {detail}", True, detail=exc)
            return False
        if not self.open_bank(path):
            return False
        self.message("Starter bank built: {count} sounds and {palettes} palettes in {path}", count=result["entries"],
                     palettes=result["palettes"], path=str(path))
        return True

    def open_bank_folder(self):
        path = self.bank_path()
        if not path.is_dir():
            self.message("The bank folder does not exist yet: {path}", True, path=str(path))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # --- auditions on click -------------------------------------------------------------------------
    def autoplay(self) -> bool:
        return self.state.values.get("autoplay") is not False

    def make_autoplay(self, name: str) -> QCheckBox:
        box = QCheckBox()
        box.setObjectName(name)
        self._bind(box, "Auto-play")
        self._bind(box, "Play a sample as soon as it is clicked.", "setToolTip")
        box.setChecked(self.autoplay())
        box.toggled.connect(self.set_autoplay)
        self._autoplay_boxes = getattr(self, "_autoplay_boxes", []) + [box]
        return box

    def set_autoplay(self, on: bool):
        on = bool(on)
        self.state.values["autoplay"] = on
        for box in getattr(self, "_autoplay_boxes", []):
            if box.isChecked() != on:
                box.blockSignals(True)
                box.setChecked(on)
                box.blockSignals(False)
        self._save_preferences()

    def song_sample_clicked(self, item):
        """A click on a song sample: hear it with its current tuning when Auto-play is on."""
        if item is not None and self.autoplay():
            self.play_sample()

    # --- adding to the bank -------------------------------------------------------------------------
    def add_slot_to_bank(self, slot: int, run: bool = True):
        """The add-to-bank sheet for `slot` of the open song (returned unshown with `run=False`, for tests)."""
        from .desktop_bank_dialogs import AddToBankDialog   # the dialogs import the library tab's labels
        if not self.document or not 1 <= slot <= len(self.document.module.samples) \
                or not self.document.module.samples[slot - 1].pcm:
            self.message("Select a song sample to add to the bank.", True)
            return None
        bank = self.sample_browser.bank or SampleLibrary(self.bank_path())
        module = self.document.module
        filename = self.document.path.name if self.document.path else (module.title or "song")
        try:
            info = next(row for row in sample_intake.song_slots(module, bank)["slots"] if row["slot"] == slot)
        except (ValidationError, OSError, StopIteration) as exc:
            self.message("Cannot read this sample: {detail}", True, detail=exc)
            return None
        dialog = AddToBankDialog(self, bank, info, source={"module": module, "slot": slot, "filename": filename})
        if run:
            dialog.exec()
        return dialog

    def bank_drop(self, path: Path, run: bool = True, target: str = "bank"):
        """A file dropped on the Sample library tab (`target` "bank") or the song sample list ("song"): a module
        lists its slots to add to the bank (and, from the song list, to insert into the song), a WAV opens the
        add sheet."""
        from .desktop_bank_dialogs import AddToBankDialog, ModuleSlotsDialog
        path = Path(path)
        suffix = path.suffix.lower()
        bank = self.sample_browser.bank or SampleLibrary(self.bank_path())
        if suffix == ".wav":
            try:
                sample = sample_intake.read_wav(path)
            except (ValidationError, OSError) as exc:
                self.message("Cannot read this WAV: {detail}", True, detail=exc)
                return None
            info = {"slot": None, "name": sample.name, "frames": len(sample.pcm), "bits": sample.bits,
                    "looped": False, "role": None, "tuning": sample_intake.tuning(sample, "xm"), "in_bank": None}
            dialog = AddToBankDialog(self, bank, info, source={"wav": path, "filename": path.name})
        elif suffix in MODULE_SUFFIXES:
            try:
                module = sample_intake.load_song(path)
                rows = sample_intake.song_slots(module, bank)["slots"]
            except (ValidationError, OSError, ValueError) as exc:
                self.message("Cannot read this module: {detail}", True, detail=exc)
                return None
            dialog = ModuleSlotsDialog(self, bank, path, module, rows, song=target == "song")
        else:
            self.message("Drop a MOD, an XM, a project or a WAV file on the library to add its samples.", True)
            return None
        if run:
            dialog.exec()
        return dialog

    def bank_entry_added(self, result: dict):
        """A sample entered the bank (or was already there): show it in the library tab."""
        self.sample_browser.select_entry(result["id"])
        if result.get("created"):
            self.message("Added {name} to the bank as {id}", name=result["entry"]["name"], id=result["id"])
        else:
            self.message("Already in the bank as {id}", id=result["id"])

    # --- a bank entry dropped on the song ------------------------------------------------------------
    def insert_bank_entry(self, sample_id: str, slot: int | None = None) -> dict | None:
        """Insert a bank entry into `slot` (None: the first free slot), asking before replacing or adapting."""
        browser = self.sample_browser
        if not self.document or browser.bank is None:
            return None
        samples = self.document.module.samples
        occupied = slot is not None and slot <= len(samples) and bool(samples[slot - 1].pcm)
        try:
            entry = browser.bank.get(sample_id)
        except (ValidationError, OSError) as exc:
            self.message("Library sample unavailable: {detail}", True, detail=exc)
            return None
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        if occupied:
            answer = QMessageBox.question(self, self.t("Replace this sample?"),
                                          self.t("Slot {slot} holds {name!r}. Replace it with {entry}? The notes "
                                                 "using the slot will play the new sample.",
                                                 slot=f"{slot:02X}", name=samples[slot - 1].name, entry=entry["name"]),
                                          yes | no, no)
            if answer != yes:
                return None
        adapt = False
        if self.module_format != "xm" and not entry["compatibility"]["compatible"]:
            answer = QMessageBox.question(self, self.t("Adapt this sample?"),
                                          self.t("{entry} is outside the MOD profile. Prepare a compatible copy for "
                                                 "this song? The bank original is kept.", entry=entry["name"]),
                                          yes | no, no)
            if answer != yes:
                return None
            adapt = True
        return browser.insert_entry(sample_id, slot, occupied, adapt)


__all__ = ["BANK_MIME", "DROP_SUFFIXES", "BankList", "BankMixin", "SongSampleList", "ensure_bank", "initial_library",
           "retune_text"]
