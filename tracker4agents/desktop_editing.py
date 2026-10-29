"""Editing the song from the ChipLoom window: undoable transactions, Edit mode and outside changes.

`EditingMixin` runs every owner edit as one undoable `Document` transaction (`edit`, `apply_patch`, `run_patch`),
then presents it (`edited`: redraw, re-render or reload the real-time engine, journal it to the live session). It
holds Edit mode and the piano-key hint (`set_edit_mode`, `update_keys_hint`, `instrument_slot`), the song header and
sample fields (`apply_song`, `apply_sample`), transpose, undo and redo, and `apply_external` for a file the agent
saved on disk (reload or three-way merge, with the changed cells flashed).
Relies on: window.document, window.rt, window.player/sample_player, window.debounce, window.live, window.agent_panel,
window.pattern_model, window.table, the edit and sample widgets, `refresh_document`, `prepare_audio`, `is_playing`,
`playback_ms`, `keyboard_layout`, `message` and `t`.
"""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt, QUrl

from .desktop_sync import changed_cells, mark_clean
from .desktop_widgets import media_call
from .document import Document
from .model import playback_plan


class EditingMixin:
    """Undoable edits and Edit mode (see the module docstring)."""
    def run_patch(self, ops, label: str) -> dict:
        """Apply patch operations as one undoable transaction and present the change. Unlike `apply_patch`
        a refusal is raised (`ValidationError` with its code), for callers that explain it themselves."""
        result = self.document.patch(ops, label)
        if result["changed"]:
            self.edited(label)
        return result

    def edit(self, operation, label: str = "Edit"):
        if not self.document:
            return
        try:
            if operation():
                self.edited(label)
        except (OSError, ValueError, RuntimeError) as exc:
            self.message(str(exc), True)

    def edited(self, label: str = "Edit"):
        """The owner changed the document: redraw, re-render later and journal it as a human edit."""
        self.agent_panel.compare_edited()   # the owner wants to hear their edit, not the take
        self._debounce_play = False
        if self.rt is not None:
            # Real-time: the engine takes the edit at once; playback (if any) simply continues.
            media_call(self.sample_player, "stop")
            media_call(self.sample_player, "setSource", QUrl())
            self.refresh_document()
            self.rt.reload()
            self.message('Change applied · Ctrl+Z to undo')
            self.live.human_edit(label)
            return
        self._resume_ms = self.player.position()
        self._audio_token += 1
        self._loading_audio = self._await_media = False
        self.player.pause()
        media_call(self.sample_player, "stop")
        media_call(self.sample_player, "setSource", QUrl())
        self._audio_ready = False
        self.refresh_document()
        self.debounce.start()
        self.message('Change applied · Ctrl+Z to undo')
        self.live.human_edit(label)

    # --- tracker editing ---------------------------------------------------------------
    @property
    def edit_mode(self) -> bool:
        return self.edit_button.isChecked()

    def set_edit_mode(self, on: bool):
        on = bool(on)
        for control in (self.edit_button, self.edit_action):
            control.blockSignals(True)
            control.setChecked(on)
            control.blockSignals(False)
        self.table.set_edit_mode(on)
        self.message("Edit mode on: piano keys enter notes" if on else "Edit mode off")
        if on:
            self.table.setFocus()

    def update_keys_hint(self, *_):
        """The visible reminder of what the piano keys play: octave and keyboard layout."""
        octave, layout = self.edit_octave.value(), self.keyboard_layout()
        self.keys_hint.setText(self.t("Octave {octave} · Keyboard {layout}", octave=octave, layout=layout.upper()))
        self.keys_hint.setToolTip(self.t("The piano keys play notes: the lower row from octave {octave}, the upper rows from "
                                         "octave {next}. F1-F3 or numpad + and - change the octave.",
                                         octave=octave, next=min(self.edit_octave.maximum(), octave + 1)))

    def instrument_slot(self) -> int:
        """Song sample slot (1-31, instruments 1-128 in an XM) used for typed notes, or 0 when the song has no samples."""
        item = self.samples.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) + 1 if item else 0

    def apply_patch(self, ops, label: str, order: int | None = None) -> bool:
        """Run patch ops as one undoable transaction. Returns False when they were rejected.
        `order` selects that order afterwards (for edits that restructure the order list)."""
        if not self.document:
            return False
        try:
            result = self.document.patch(ops, label)
        except (OSError, ValueError, RuntimeError) as exc:
            self.message(str(exc), True)
            return False
        if result["changed"]:
            if order is not None:
                self.current_order = order
            self.edited(label)
        return True

    def apply_external(self, module, kind: str, conflicts: list[dict]):
        """Show a change made outside the window (the agent saved the file).

        `kind` "reload": the window had no local edits, the file replaces the module.
        `kind` "merge": `module` is the three-way merge of local edits into the file.
        Either way it is one undoable transaction; changed cells flash with the agent color."""
        document = self.document
        before = document.module
        playing = self._want_play if self._loading_audio else self.is_playing()
        position = self._resume_ms if self._loading_audio else self.playback_ms()
        replacement = copy.deepcopy(module)
        document.apply("Merge agent changes" if kind == "merge" else "Agent changes",
                       lambda target: target.__dict__.update(replacement.__dict__))
        if kind == "reload":
            mark_clean(document)
        cells = changed_cells(before, document.module)
        self.live.external_edit("Merge agent changes" if kind == "merge" else "Agent changes")
        media_call(self.sample_player, "stop")
        self.refresh_document()
        self.pattern_model.flash(cells)
        if self.rt is not None:
            self.rt.reload()
        else:
            self.prepare_audio(playing, position)
        if conflicts:
            where = ", ".join(f"P{item['pattern']:02X} r{item['row']:02X} ch{item['channel'] + 1}" if item["unit"] == "cell"
                              else item["unit"] for item in conflicts[:4])
            self.message("Agent changes merged with yours · {count} conflicts, agent version kept: {where}",
                         True, count=len(conflicts), where=where)
        elif kind == "merge":
            self.message("Agent changes merged with your edits · Ctrl+Z to undo")
        else:
            self.message("Reloaded the agent's changes · Ctrl+Z to undo")

    def apply_song(self):
        if not self.document:
            return
        title, bpm, speed = self.title_edit.text(), self.bpm.value(), self.speed.value()

        def apply():
            # One undo transaction covers title and initial timing together.
            source = Document(self.document.module)
            source.rename(title)
            initial = playback_plan(source.module)["timeline"][0]
            if (bpm, speed) != (initial["bpm"], initial["speed"]):
                source.set_timing(bpm, speed)
            replacement = source.module
            return self.document.apply("Régler le morceau", lambda module: module.__dict__.update(replacement.__dict__))

        self.edit(apply, "Set song")

    def apply_sample(self):
        if self.document and self.samples.currentItem():
            index = self.samples.currentItem().data(Qt.ItemDataRole.UserRole)
            if self.module_format == "xm":   # the XM fine tune runs -128..127: through the patch operation
                self.apply_patch([{"op": "sample", "slot": index + 1, "volume": self.sample_volume.value(),
                                   "finetune": self.finetune.value()}], "Set sample")
                return
            self.edit(lambda: self.document.set_sample(index, self.sample_volume.value(), self.finetune.value()), "Set sample")

    def transpose(self, semitones):
        index = self.table.currentIndex()
        if self.document and index.isValid():
            channel = self.pattern_model.channel_of(index.column())
            self.edit(lambda: self.document.transpose(self.pattern_model.pattern, channel, semitones), "Transpose track")
        else:
            self.message('Select a cell in the track you want to transpose.')

    def undo(self):
        if self.document and self.document.undo():
            self.edited("Undo")

    def redo(self):
        if self.document and self.document.redo():
            self.edited("Redo")
