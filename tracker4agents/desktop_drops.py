"""Files dropped on the ChipLoom window: what each target does with them, and the hint shown while dragging.

`drop_kind(mime)` reads a drag: ("module", path) for a MOD, XM or project, ("wav", path), ("midi", path), ("bank",
sample_id) for a bank entry dragged from the library tab, or None. `DropMixin` (mixed into `TrackerWindow`) handles
drops anywhere on the window that has no dedicated target (the pattern grid, the header, the LIBRARY panel...): a
module opens exactly like File → Open (`open_document`: the unsaved-changes prompt, the recent files, the live
session), a MIDI file goes to `midi_dropped`, the small hook where a MIDI import will plug in (for now it says the
import is planned). `drag_hint(kind)` shows what a drop will do in the status bar and `drag_hint_done()` restores the
last message; the dedicated targets (`desktop_samples.SampleBrowser`, `desktop_bank.SongSampleList`) use them too.
Relies on: window.open_document, window.message, window._show_message, window.statusBar and window.t.
"""

from __future__ import annotations

from pathlib import Path

MODULE_SUFFIXES = (".mod", ".xm", ".json")
MIDI_SUFFIXES = (".mid", ".midi")
BANK_MIME = "application/x-chiploom-bank-entry"
MIDI_PLANNED = "MIDI import is planned for the next version."
HINTS = {"open": "Drop to open", "bank": "Drop to choose samples for the bank", "wav": "Drop to add this WAV to the bank",
         "song": "Drop to choose samples for the song", "entry": "Drop to insert the bank entry here",
         "midi": MIDI_PLANNED}


def drop_kind(mime) -> tuple[str, object] | None:
    """What a drag carries (see the module docstring); only the first usable local file counts."""
    if mime.hasFormat(BANK_MIME):
        return "bank", bytes(mime.data(BANK_MIME)).decode("ascii", "replace")
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        suffix = path.suffix.lower()
        if suffix in MODULE_SUFFIXES:
            return "module", path
        if suffix == ".wav":
            return "wav", path
        if suffix in MIDI_SUFFIXES:
            return "midi", path
    return None


class DropMixin:
    """Drops on the window itself and the drag hints (see the module docstring)."""

    def drag_hint(self, kind: str):
        """Say in the status bar what dropping here will do."""
        self.statusBar().setStyleSheet("")
        self.statusBar().showMessage(self.t(HINTS[kind]))

    def drag_hint_done(self):
        self._show_message()

    def midi_dropped(self, path: Path):
        """The MIDI import hook: a future import dialog opens here; until then the owner is told it is planned."""
        self.message(MIDI_PLANNED)
        return None

    def window_drop(self, path: Path) -> bool:
        """A file dropped where no dedicated target took it: open a module, announce the MIDI plan."""
        suffix = Path(path).suffix.lower()
        if suffix in MIDI_SUFFIXES:
            self.midi_dropped(Path(path))
            return True
        if suffix in MODULE_SUFFIXES:
            return self.open_document(Path(path))
        return False

    def dragEnterEvent(self, event):
        found = drop_kind(event.mimeData())
        if found and found[0] in ("module", "midi"):
            event.acceptProposedAction()
            self.drag_hint("open" if found[0] == "module" else "midi")
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        found = drop_kind(event.mimeData())
        if found and found[0] in ("module", "midi"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.drag_hint_done()

    def dropEvent(self, event):
        found = drop_kind(event.mimeData())
        self.drag_hint_done()
        if found and found[0] in ("module", "midi"):
            event.acceptProposedAction()
            self.window_drop(found[1])
        else:
            event.ignore()


__all__ = ["BANK_MIME", "HINTS", "MIDI_PLANNED", "MIDI_SUFFIXES", "MODULE_SUFFIXES", "DropMixin", "drop_kind"]
