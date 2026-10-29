"""How the ChipLoom window shows the song: header, order list, sample list, format and channel monitor.

`SongViewMixin.refresh_document` redraws everything from `window.document` (title, timing, summary, orders, pattern
grid, sample list, panels, undo state). It also holds what follows the module's format (`module_format`,
`_format_changed`: export labels, octave range, XM hints), the song-sample selection (`cell_selected`,
`sample_selected`, `sample_summary`), and the Mute and Solo strip above the grid (`audible`, `set_channels`,
`channel_color`, `_monitor_style`, `monitor_changed`, `clear_monitor`).
Relies on: window.document, window.plan/times/current_order/_refreshing, window.rt, the header widgets and panels
built by `desktop_layout`, and `prepare_audio`, `is_playing`, `playback_ms`, `update_keys_hint`, `_rebind`, `message`
and `t` from the other mixins.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QListWidgetItem

from . import __version__
from .desktop_widgets import sample_name
from .model import playback_plan
from .web.brand import MAX_CHANNELS, channel_color
CLEAR_MONITOR_TIP = "Ctrl+click: every track audible again"


class SongViewMixin:
    """The song as the window shows it (see the module docstring)."""

    def refresh_document(self):
        if not self.document:
            return
        self._refreshing = True
        module = self.document.module
        self.set_channels(module.channels)   # an agent can replace the module by one with other channels
        self._format_changed()
        self.plan = playback_plan(module)
        self.times = [entry["seconds"] for entry in self.plan["timeline"]]
        if self.rt is not None:
            self.seek.setMaximum(round(self.plan["duration_seconds"] * 1000))
        self.current_order = min(self.current_order, len(module.orders) - 1)
        self.title_edit.setText(module.title)
        initial = self.plan["timeline"][0]
        self.bpm.setValue(initial["bpm"])
        self.speed.setValue(initial["speed"])
        self._song_labels()
        self.orders.clear()
        for order, pattern in enumerate(module.orders):
            self.orders.addItem(f"{order:02X}  ·  {module.patterns[pattern].name or f'Pattern {pattern:02X}'}", pattern)
        self.orders.setCurrentIndex(self.current_order)
        # The model redraws in place, so the cursor, the block selection and the scroll position survive.
        self.pattern_model.refresh(module.orders[self.current_order])
        selected = self.samples.currentItem()
        selected_slot = selected.data(Qt.ItemDataRole.UserRole) if selected else 0
        self.samples.clear()
        wanted = 0
        for index, sample in enumerate(module.samples):
            if sample.pcm:
                item = QListWidgetItem(f"{index + 1:02X}  {sample_name(sample, index + 1)}")
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.samples.addItem(item)
                if index == selected_slot:
                    wanted = self.samples.count() - 1
        self.samples.setCurrentRow(wanted)
        self._refreshing = False
        self.sample_selected(self.samples.currentRow())
        self.cell_selected(self.table.currentIndex())
        self.sample_browser.update_slots()
        self.create_panel.refresh_slots()
        self.sample_workshop.levels.invalidate()
        self.undo_action.setEnabled(self.document.can_undo)
        self.redo_action.setEnabled(self.document.can_redo)
        self.order_editor.refresh()
        self._monitor_style()
        self.comment_panel.refresh()   # comments follow the document (open, reload, agent edits)
        self._update_title()

    def _song_labels(self):
        module = self.document.module
        self.summary.setText(self.t("{bpm} BPM  ·  {orders} orders  ·  {samples} samples  ·  {seconds:.2f} s",
            bpm=self.plan["timeline"][0]["bpm"], orders=len(module.orders),
            samples=sum(bool(sample.pcm) for sample in module.samples), seconds=self.plan["duration_seconds"]))
        self.origin.setText(self.document.path.name if self.document.path else self.t("New project"))
        self.origin.setToolTip(str(self.document.path) if self.document.path else "")

    def _update_title(self):
        if self.document:
            hearing = f" [{self.t('listening to a take')}]" if self.monitor_module is not None else ""
            self.setWindowTitle(f"{'* ' if self.document.dirty else ''}{self.document.module.title}{hearing} — ChipLoom {__version__}")

    @property
    def module_format(self) -> str:
        return self.document.module.format if self.document else "mod"

    def _format_changed(self):
        """What depends on the module's format: the export labels, the octave range, the hints and the sample
        operations an XM does not offer (the header line follows the channel count and is always refreshed)."""
        module = self.document.module if self.document else None
        self._show_format_label()
        if module is None or module.format == self._shown_format:
            return
        self._shown_format = module.format
        xm = module.format == "xm"
        self._rebind(self.export_action, "Export XM…" if xm else "Export MOD…")
        self._rebind(self.export_button, "Export XM…" if xm else "Export MOD…")
        self.xm_hint.setVisible(xm)
        low, high = (0, 7) if xm else (1, 3)
        if (self.edit_octave.minimum(), self.edit_octave.maximum()) != (low, high):
            value = self.edit_octave.value()
            if xm and value <= 3:
                value = 4    # the lower key row of an XM starts at C-4, middle C
            elif not xm and value > 3:
                value = 2
            self.edit_octave.blockSignals(True)
            self.edit_octave.setRange(low, high)
            self.edit_octave.setValue(value)
            self.edit_octave.blockSignals(False)
            self.update_keys_hint()
        self.sample_workshop.editor.update_format()
        self.sample_browser.update_controls()
        self.create_panel.update_format()
        self.instrument_panel.update_buttons()
        self.sample_workshop.levels.update_format()

    def _show_format_label(self):
        module = self.document.module if self.document else None
        if module is None:
            self.format_label.setText(self.t("MOD · 4 CHANNELS · PAL"))
            return
        text = self.t("{format} · {channels} CHANNELS", format=module.format.upper(), channels=module.channels)
        self.format_label.setText(text + (" · PAL" if module.format == "mod" else ""))

    def cell_selected(self, index, previous=QModelIndex()):
        if not self.document or not index.isValid():
            return
        if self.edit_mode:
            return  # while typing, the instrument is the one chosen in the sample list
        value = self.document.module.patterns[self.pattern_model.pattern].get(
            index.row(), self.pattern_model.channel_of(index.column()))
        if value.sample:
            for row in range(self.samples.count()):
                if self.samples.item(row).data(Qt.ItemDataRole.UserRole) == value.sample - 1:
                    self.samples.setCurrentRow(row)
                    break

    def sample_selected(self, row):
        if self._refreshing:
            return
        self.sample_workshop.editor.load()   # the waveform, the edit fields, or the empty state
        self.instrument_panel.update_buttons()
        if not self.document or row < 0:
            return
        index = self.samples.item(row).data(Qt.ItemDataRole.UserRole)
        sample = self.document.module.samples[index]
        self._sample_labels()
        self.sample_volume.setValue(sample.volume)
        self.finetune.setValue(sample.finetune)

    def _sample_labels(self):
        if not self.document or not self.samples.currentItem():
            return
        index = self.samples.currentItem().data(Qt.ItemDataRole.UserRole)
        sample = self.document.module.samples[index]
        self.sample_title.setText(f"{index + 1:02X} · {sample_name(sample, index + 1)}")
        looping = self.t("loop {start} → {end}", start=sample.loop_start, end=sample.loop_start + sample.loop_length) if sample.loop_length else self.t("no loop")
        self.sample_info.setText(self.sample_summary(sample, looping))

    def sample_summary(self, sample, looping: str) -> str:
        """The one-line facts of a song sample: size, bit depth, loop and what the preview plays."""
        if self.module_format != "xm":
            return self.t("{size} bytes · mono 8-bit · {loop} · C-2 preview", size=len(sample.pcm), loop=looping)
        return self.t("{size} bytes · mono {bits}-bit · {loop} ({mode}) · panning {panning} · relative note {note:+d} "
                      "· C-4 preview", size=len(sample.pcm) * sample.bits // 8, bits=sample.bits, loop=looping,
                      mode=self.t(sample.loop_mode), panning=sample.panning, note=sample.relative_note)

    def audible(self):
        """One boolean per channel of the module: not muted, and soloed when any channel is."""
        solo = any(control.isChecked() for control in self.solos)
        return tuple(not mute.isChecked() and (not solo or self.solos[index].isChecked())
                     for index, mute in enumerate(self.mutes))

    def channel_color(self, channel: int) -> str:
        """The colour of a channel: the theme's four, then their tinted variants (the web studio's palette)."""
        return channel_color(self.theme, max(0, min(MAX_CHANNELS - 1, channel)))

    def set_channels(self, count: int):
        """One Mute and one Solo button per channel of the module above the grid, keeping the states of the
        channels both modules have."""
        if len(self.mutes) == count:
            return
        states = [(mute.isChecked(), solo.isChecked()) for mute, solo in zip(self.mutes, self.solos)]
        self.mutes, self.solos = self.channel_strip.rebuild(count, states, self.monitor_changed, self.clear_monitor)

    def _monitor_style(self):
        audible = self.audible()
        for channel, control in enumerate(self.mutes):
            muted = control.isChecked()
            control.setText(self.t("Track {number} · MUTED" if muted else "Track {number}", number=channel + 1))
            control.setToolTip(self.t("Click to unmute track {number}" if muted else "Click to mute track {number}", number=channel + 1)
                               + "\n" + self.t(CLEAR_MONITOR_TIP))
            control.setAccessibleName(control.text())
            control.setProperty("trackMuted", not audible[channel])
            color = self.channel_color(channel) if audible[channel] else self.palette_colors["disabled"]
            control.setStyleSheet(f"border-left:3px solid {color};color:{color};padding:3px 6px")
            self.solos[channel].setText(self.t("Solo"))
            self.solos[channel].setToolTip(self.t("Solo track {number}", number=channel + 1) + "\n" + self.t(CLEAR_MONITOR_TIP))
        self.pattern_model.refresh_colors()

    def monitor_changed(self):
        if self._refreshing or not self.document:
            return
        self._monitor_style()
        self.live.context_changed()   # browser renders follow the window's mutes
        if self.rt is not None:
            self.rt.set_audible(self.audible())  # mutes and solos apply within one audio block, no render
            return
        # Further clicks during preparation retain the original playback intent.
        play = self._want_play if self._loading_audio else self.is_playing()
        position = self._resume_ms if self._loading_audio else self.playback_ms()
        self.prepare_audio(play, position)

    def clear_monitor(self):
        """Ctrl+click on any Mute or Solo: every track audible again, as one change for the engine or the render."""
        checked = [control for control in self.mutes + self.solos if control.isChecked()]
        for control in checked:
            control.blockSignals(True)
            control.setChecked(False)
            control.blockSignals(False)
        if checked:
            self.monitor_changed()
            self.message("Every track is audible again")
