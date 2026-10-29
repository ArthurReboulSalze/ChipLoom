"""The Tuning page of the Song samples tab: how the selected song sample is tuned, and keeping it in the bank.

`TuningPanel` shows the measured tuning of the selected slot (`sample_intake.tuning`: the note written C sounds
and its cents) and offers, through the document's undoable patch path (`window.run_patch` / `window.edit`, so the
live session sees them as the owner's edits):
- XM: relative note −12 / −1 / +1 / +12 and the finetune (−128..127);
- MOD: the finetune (−8..7), and "transpose this sample's notes" −12 / −1 / +1 / +12, which moves the notes of the
  patterns that play the slot (a MOD sample cannot hold whole semitones).
"Save tuning to bank" stores the difference between the slot's playback rate and its bank entry's as the entry's
`retune` (`SampleLibrary.edit(retune=...)`); "Add to bank…" opens the add sheet. Relies on: window.document,
window.samples (the selected slot), window.module_format, window.sample_browser (bank, library_path, reload),
window.run_patch, window.edit, window.add_slot_to_bank, window.message and the text-binding helpers.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QSpinBox, QVBoxLayout, QWidget

from . import sample_intake
from .model import NOTE_TO_PERIOD, NOTES, XM_KEY_OFF, XM_NOTES, Cell, Sample, ValidationError, playback_plan
from .sample_library import playback_rate

STEPS = (-12, -1, 1, 12)


def retune_between(slot_sample: Sample, fmt: str, entry_sample: Sample, origin: str) -> dict:
    """The slot's tuning relative to its bank entry's, from playback rates: whole semitones and residual cents."""
    slot_rate, _ = playback_rate(slot_sample, fmt)
    entry_rate, _ = playback_rate(entry_sample, origin)
    cents = 1200 * math.log2(slot_rate / entry_rate)
    semitones = round(cents / 100)
    return {"semitones": semitones, "cents": round(cents - 100 * semitones)}


def transpose_slot_notes(module, slot: int, semitones: int) -> int:
    """Move every note that plays `slot` by `semitones`, in place; returns how many cells moved. A note without a
    sample number plays its channel's last one, so the channels are followed along the playback timeline; patterns
    the timeline never reaches count only the notes that name the slot."""
    xm = module.format == "xm"
    moved = 0
    playing: set[tuple[int, int, int]] = set()
    current = [0] * module.channels
    reached = set()
    for item in playback_plan(module)["timeline"]:
        reached.add(item["pattern"])
        for channel in range(module.channels):
            value = module.patterns[item["pattern"]].get(item["row"], channel)
            if value.sample:
                current[channel] = value.sample
            if value.period and current[channel] == slot:
                playing.add((item["pattern"], item["row"], channel))
    for index, pattern in enumerate(module.patterns):
        for (row, channel), old in list(pattern.cells.items()):
            if (index, row, channel) not in playing and not (index not in reached and old.sample == slot):
                continue
            if xm:
                if not old.period or old.period == XM_KEY_OFF:
                    continue
                target = old.period - 1 + semitones
                if not 0 <= target < len(XM_NOTES):
                    raise ValidationError(f"Transposing {old.note} by {semitones} leaves C-0..B-7.", "NOTE_RANGE")
                pattern.put(row, channel, Cell(target + 1, old.sample, old.command, old.param, old.volume))
            else:
                if not old.note:
                    continue
                target = NOTES.index(old.note) + semitones
                if not 0 <= target < len(NOTES):
                    raise ValidationError(f"Transposing {old.note} by {semitones} leaves C-1..B-3.", "NOTE_RANGE")
                pattern.put(row, channel, Cell(NOTE_TO_PERIOD[NOTES[target]], old.sample, old.command, old.param))
            moved += 1
    return moved


class TuningPanel(QWidget):
    """See the module docstring."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("tuningPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.title = window._label("Select a sample", "itemTitle")
        layout.addWidget(self.title)
        self.measured = QLabel()
        self.measured.setObjectName("measuredTuning")
        self.measured.setWordWrap(True)
        self.measured.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.measured)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        layout.addLayout(grid)
        # Row 0: the relative note (XM) or the notes of the slot (MOD), stepped by buttons.
        self.step_caption = window._label("Relative note", "muted")
        grid.addWidget(self.step_caption, 0, 0)
        self.step_value = QLabel()
        self.step_value.setObjectName("relativeNote")
        grid.addWidget(self.step_value, 0, 1)
        steps = QHBoxLayout()
        steps.setSpacing(4)
        self.step_buttons = {}
        for delta in STEPS:
            control = window._button(f"{delta:+d}", lambda _=False, delta=delta: self.step(delta), f"tune{delta:+d}")
            control.setProperty("compact", True)
            control.setFixedWidth(44)
            self.step_buttons[delta] = control
            steps.addWidget(control)
        steps.addStretch()
        grid.addLayout(steps, 0, 2)
        # Row 1: the finetune, applied with a button.
        self.finetune_caption = window._label("Fine tune", "muted")
        grid.addWidget(self.finetune_caption, 1, 0)
        self.finetune = QSpinBox()
        self.finetune.setObjectName("tuningFinetune")
        self.finetune.setRange(-8, 7)
        self.finetune.setMinimumWidth(96)
        grid.addWidget(self.finetune, 1, 1)
        self.apply_button = window._button("Apply fine tune", self.apply_finetune, "applyTuning")
        self.apply_button.setProperty("compact", True)
        self.apply_button.setProperty("tone", "apply")
        grid.addWidget(self.apply_button, 1, 2, Qt.AlignmentFlag.AlignLeft)
        # Row 2: the bank.
        self.bank_caption = window._label("Bank", "muted")
        grid.addWidget(self.bank_caption, 2, 0)
        self.bank_label = QLabel()
        self.bank_label.setObjectName("tuningBankEntry")
        grid.addWidget(self.bank_label, 2, 1)
        bank_row = QHBoxLayout()
        bank_row.setSpacing(6)
        self.save_button = window._button("Save tuning to bank", self.save_tuning, "saveTuning")
        self.add_button = window._button("Add to bank…", self.add_to_bank, "addToBank")
        for control in (self.save_button, self.add_button):
            control.setProperty("compact", True)
            bank_row.addWidget(control)
        bank_row.addStretch()
        grid.addLayout(bank_row, 2, 2)
        grid.setColumnStretch(2, 1)
        self.note = window._label("", "muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        layout.addStretch()
        self.retranslate()

    def retranslate(self):
        xm = self.window.module_format == "xm"
        t = self.window.t
        self.step_caption.setText(t("Relative note") if xm else t("Notes of this sample"))
        for delta, control in self.step_buttons.items():
            control.setToolTip(t("Raise or lower the sample by {count} semitones (the PCM is not touched).", count=abs(delta))
                               if xm else
                               t("Transpose the notes that play this sample by {count} semitones, in every pattern.",
                                 count=abs(delta)))
        self.finetune.setToolTip(t("XM fine tune, 1/128 of a semitone.") if xm else t("MOD fine tune, 1/8 of a semitone."))
        self.save_button.setToolTip(t("Store how this slot is tuned, relative to its bank entry, as the entry's correction "
                                      "applied on insertion."))
        self.add_button.setToolTip(t("Put this sample in the bank with its own name, role and tags."))
        self.note.setText(t("Tuning is measured, not judged: confirm by listening. A MOD sample cannot hold whole "
                            "semitones, so its notes are transposed instead.") if not xm else
                          t("Tuning is measured, not judged: confirm by listening."))
        self.load()

    def update_format(self):
        xm = self.window.module_format == "xm"
        self.finetune.setRange(*((-128, 127) if xm else (-8, 7)))
        self.retranslate()

    # --- the selected sample -------------------------------------------------------------------------
    def current(self) -> tuple[int, Sample] | None:
        window = self.window
        item = window.samples.currentItem()
        if not window.document or item is None:
            return None
        slot = item.data(Qt.ItemDataRole.UserRole) + 1
        return slot, window.document.module.samples[slot - 1]

    def bank_entry(self, slot: int) -> dict | None:
        """The bank entry recorded for `slot` in `metadata.sample_sources`, when the active bank holds it."""
        window = self.window
        bank = window.sample_browser.bank
        sources = window.document.module.metadata.get("sample_sources") if window.document else None
        recorded = sources.get(str(slot)) if isinstance(sources, dict) else None
        library_id = recorded.get("library_id") if isinstance(recorded, dict) else None
        if not library_id or bank is None:
            return None
        try:
            return bank.get(library_id)
        except (ValidationError, OSError):
            return None

    def load(self):
        found = self.current()
        t = self.window.t
        enabled = found is not None
        for control in (*self.step_buttons.values(), self.finetune, self.apply_button, self.add_button):
            control.setEnabled(enabled)
        if not enabled:
            self.title.setText(t("Select a sample"))
            self.measured.setText("")
            self.step_value.setText("")
            self.bank_label.setText("")
            self.save_button.setEnabled(False)
            return
        slot, sample = found
        xm = self.window.module_format == "xm"
        self.title.setText(f"{slot:02X} · {sample.name or t('Sample')}")
        info = sample_intake.tuning(sample, self.window.module_format)
        if info["pitched"]:
            self.measured.setText(t("Written {reference} sounds {note} {cents:+d} cents", reference=info["reference_note"],
                                    note=info["written_c_sounds"], cents=round(info["cents"])))
        else:
            self.measured.setText(t("Not pitched ({reason})", reason=info.get("reason", "")))
        self.step_value.setText(f"{sample.relative_note:+d}" if xm else t("in the patterns"))
        self.finetune.blockSignals(True)
        self.finetune.setValue(sample.finetune)
        self.finetune.blockSignals(False)
        entry = self.bank_entry(slot)
        self.entry = entry
        if entry is None:
            self.bank_label.setText(t("not from the bank"))
            self.save_button.setEnabled(False)
        else:
            retune = entry.get("retune") or {}
            stored = f" · {retune.get('semitones', 0):+d} st {retune.get('cents', 0):+d} c" if retune else ""
            self.bank_label.setText(f"{entry['id']} · {entry['name']}{stored}")
            self.save_button.setEnabled(True)

    # --- edits -----------------------------------------------------------------------------------------
    def step(self, delta: int) -> dict | None:
        """XM: move the relative note; MOD: transpose the notes that play this slot."""
        found = self.current()
        if found is None:
            return None
        slot, sample = found
        window = self.window
        if window.module_format == "xm":
            target = sample.relative_note + delta
            if not -96 <= target <= 95:
                window.message("The relative note stays within -96..95.", True)
                return None
            try:
                result = window.run_patch([{"op": "sample", "slot": slot, "relative_note": target}], "Tune sample")
            except ValidationError as exc:
                window.message("Cannot tune this sample: {detail}", True, detail=exc)
                return None
            window.message("Relative note {value:+d} · Ctrl+Z to undo", value=target)
            return result
        moved = []

        def change(module):
            moved.append(transpose_slot_notes(module, slot, delta))

        window.edit(lambda: window.document.apply("Transpose sample notes", change), "Transpose sample notes")
        if moved and moved[0]:
            window.message("Moved {count} notes of sample {slot} by {delta:+d} semitones · Ctrl+Z to undo",
                           count=moved[0], slot=f"{slot:02X}", delta=delta)
        elif moved:
            window.message("No note plays sample {slot}.", slot=f"{slot:02X}")
        return {"moved": moved[0] if moved else 0}

    def apply_finetune(self) -> dict | None:
        found = self.current()
        if found is None:
            return None
        slot, sample = found
        window = self.window
        value = self.finetune.value()
        try:
            result = window.run_patch([{"op": "sample", "slot": slot, "finetune": value}], "Tune sample")
        except ValidationError as exc:
            window.message("Cannot tune this sample: {detail}", True, detail=exc)
            return None
        if result["changed"]:
            window.message("Fine tune {value:+d} · Ctrl+Z to undo", value=value)
        return result

    # --- the bank ----------------------------------------------------------------------------------------
    def save_tuning(self) -> dict | None:
        found = self.current()
        window = self.window
        if found is None:
            return None
        slot, sample = found
        entry = self.bank_entry(slot)
        bank = window.sample_browser.bank
        if entry is None or bank is None:
            window.message("This slot is not recorded as a bank entry.", True)
            return None
        try:
            retune = retune_between(sample, window.module_format, bank.read_sample(entry["id"]), entry["format_origin"])
            bank.edit(entry["id"], retune=retune)
        except (ValidationError, OSError, ValueError) as exc:
            window.message("Cannot save the tuning: {detail}", True, detail=exc)
            return None
        window.message("Tuning of {id} saved: {semitones:+d} st {cents:+d} c", id=entry["id"], **retune)
        window.sample_browser.reload()
        self.load()
        return retune

    def add_to_bank(self):
        found = self.current()
        if found is not None:
            return self.window.add_slot_to_bank(found[0])
        return None


__all__ = ["STEPS", "TuningPanel", "retune_between", "transpose_slot_notes"]
