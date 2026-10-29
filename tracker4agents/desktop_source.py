"""The sample mode switch of the header band: where the open song's samples come from.

`SampleModeSwitch` shows `metadata.sample_source` (library, synthesized, mixed; nothing checked when the project
declares none) as three buttons. Choosing a mode is one undoable edit, guarded by `sample_source.enforce`: a song
that holds library PCM cannot become synthesized, one that holds created samples cannot become library-only, and
the guard's own message says which slots stand in the way; "mixed" asks for an explicit confirmation. `allows(kind)`
and `hint(kind)` tell the library tab and the Create tab whether an insertion of `kind` ("library" or "recipe") is
allowed in the current mode. Relies on: window.document, window.edit, window.message and the text-binding helpers.
"""

from __future__ import annotations

import copy

from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QWidget

from . import sample_source
from .model import ValidationError

MODES = (("library", "Library"), ("synthesized", "Synthesized"), ("mixed", "Mixed"))
TIPS = {"library": "Only samples from the bank: created sounds are refused.",
        "synthesized": "Only sounds created by ChipLoom recipes: bank samples are refused.",
        "mixed": "Bank samples and created sounds together."}
HINTS = {"library": "This song is declared synthesized: bank samples are refused. Switch the sample mode in the header "
                    "to use the bank.",
         "recipe": "This song is declared library-only: created sounds are refused. Switch the sample mode in the header "
                   "to create sounds."}


class SampleModeSwitch(QWidget):
    """See the module docstring."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("sampleModeSwitch")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(window._label("Samples", "muted"))
        layout.addSpacing(4)
        self.buttons = {}
        for mode, text in MODES:
            control = window._button(text, lambda _=False, mode=mode: self.choose(mode), f"sampleMode_{mode}")
            control.setCheckable(True)
            control.setProperty("compact", True)
            window._bind(control, TIPS[mode], "setToolTip")
            layout.addWidget(control)
            self.buttons[mode] = control
        self.refresh()

    def declared(self) -> str | None:
        """The declared mode of the open song (None: nothing declared or an unreadable value)."""
        if not self.window.document:
            return None
        try:
            return sample_source.declared(self.window.document.module)
        except ValidationError:
            return None

    def refresh(self):
        current = self.declared()
        for mode, control in self.buttons.items():
            control.blockSignals(True)
            control.setChecked(mode == current)
            control.blockSignals(False)
            control.setEnabled(self.window.document is not None)
        self.setToolTip(self.window.t("No sample mode declared: anything goes. Click a mode to declare one.")
                        if current is None else "")

    def allows(self, kind: str) -> bool:
        current = self.declared()
        return not (kind == "library" and current == "synthesized" or kind == "recipe" and current == "library")

    def hint(self, kind: str) -> str:
        return "" if self.allows(kind) else self.window.t(HINTS[kind])

    def choose(self, mode: str) -> bool:
        """Declare `mode` as one undoable edit, after the core's guard (and a confirmation for mixed)."""
        window = self.window
        if not window.document:
            self.refresh()
            return False
        if mode == self.declared():
            self.refresh()
            return False
        if mode == "mixed":
            yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
            answer = QMessageBox.question(window, window.t("Allow both kinds of samples?"),
                                          window.t("A mixed song takes bank samples and created sounds together. The "
                                                   "agent only mixes them when you ask for it. Declare this song mixed?"),
                                          yes | no, no)
            if answer != yes:
                self.refresh()
                return False
        else:
            candidate = copy.deepcopy(window.document.module)
            candidate.metadata["sample_source"] = mode
            try:
                sample_source.enforce(candidate)
            except ValidationError as exc:
                window.message("Cannot switch to {mode}: {detail}", True, mode=window.t(dict(MODES)[mode]), detail=exc)
                self.refresh()
                return False

        def change(module):
            module.metadata["sample_source"] = mode

        window.edit(lambda: window.document.apply("Set sample source", change), "Set sample source")
        self.refresh()
        return self.declared() == mode


__all__ = ["HINTS", "MODES", "SampleModeSwitch"]
