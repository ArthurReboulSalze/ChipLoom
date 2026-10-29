"""Sound workshop, part 2: the Create tab.

A recipe editor generated from `sample_tools.recipe_schema()` (one form per recipe type, with the ranges the
core enforces), an immediate and debounced audition through `sample_tools.preview_recipe` with its
measurements, a canvas to draw a looped wave, and "Add to song" through the `recipe_sample` patch operation
(or `sample_set_pcm` for a drawn wave kept as plain PCM). "Start a synthesized song" runs the palette flow.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from . import sample_tools, synth, synth_tools
from .desktop_widgets import XM_REFUSED_TIP
from .model import ValidationError

PREVIEW_DELAY_MS = 300
PARAMETER_LABELS = {"shape": "Shape", "frequency": "Frequency (Hz)", "cycles": "Cycles", "duty": "Pulse width",
                    "length": "Length (bytes)", "smooth": "Smoothing", "binary": "1-bit noise", "seed": "Seed",
                    "peak": "Peak", "duration": "Duration (s)", "drive": "Drive", "points": "Points"}
SHAPES = {"sine": lambda x: math.sin(math.tau * x), "triangle": lambda x: 4 * abs(x - 0.5) - 1,
          "saw": lambda x: 2 * x - 1, "square": lambda x: 1.0 if x < 0.5 else -1.0}


class DrawCanvas(QWidget):
    """Draw one cycle of a wave with the mouse: values between -1 and 1 at 4 to 256 evenly spaced points."""

    changed = Signal()

    def __init__(self, window):
        super().__init__()
        self.window = window
        self._points = [round(math.sin(math.tau * index / 32), 4) for index in range(32)]
        self._last: int | None = None
        self.setMinimumSize(180, 110)
        self.setObjectName("drawCanvas")
        self.setCursor(Qt.CursorShape.CrossCursor)

    def points(self) -> list[float]:
        return list(self._points)

    def set_points(self, values: list[float]):
        self._points = [max(-1.0, min(1.0, round(float(value), 4))) for value in values]
        self.update()
        self.changed.emit()

    def resample(self, count: int):
        old = self._points
        self.set_points([old[min(len(old) - 1, index * len(old) // count)] for index in range(count)])

    def preset(self, name: str, count: int | None = None):
        count = count or len(self._points)
        if name == "clear":
            return self.set_points([0.0] * count)
        self.set_points([SHAPES[name](index / count) for index in range(count)])

    def _paint_to(self, x: float, y: float):
        count = len(self._points)
        index = max(0, min(count - 1, int(x / max(1, self.width()) * count)))
        value = max(-1.0, min(1.0, 1 - 2 * y / max(1, self.height())))
        if self._last is None or self._last == index:
            self._points[index] = round(value, 4)
        else:   # a fast stroke skips points: draw the straight line between the two
            first, previous = self._last, self._points[self._last]
            for step in range(min(first, index), max(first, index) + 1):
                self._points[step] = round(previous + (value - previous) * (step - first) / (index - first), 4)
        self._last = index
        self.update()
        self.changed.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._last = None
            self._paint_to(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._paint_to(event.position().x(), event.position().y())

    def mouseReleaseEvent(self, event):
        self._last = None

    def paintEvent(self, event):
        painter = QPainter(self)
        colors = self.window.palette_colors
        painter.fillRect(self.rect(), QColor(colors["panel"]))
        painter.setPen(QPen(QColor(colors["border"]), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        middle = self.height() / 2
        painter.drawLine(0, round(middle), self.width(), round(middle))
        count = len(self._points)
        step = self.width() / count
        painter.setPen(QPen(QColor(colors["loop"]), max(1, step - 1)))
        for index, value in enumerate(self._points):
            painter.drawLine(QPointF(index * step + step / 2, middle), QPointF(index * step + step / 2, middle - value * middle * 0.92))
        painter.setPen(QPen(QColor(colors["accent"]), 2))
        painter.drawPolyline(QPolygonF([QPointF(index * step + step / 2, middle - value * middle * 0.92)
                                        for index, value in enumerate(self._points)]))


class CreatePanel(QWidget):
    """The "Create" tab. See the module docstring."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("createPanel")
        self.schema = sample_tools.recipe_schema()
        self.types = {entry["type"]: entry for entry in self.schema["types"]}
        self.widgets: dict[str, tuple[dict, QWidget, QLabel]] = {}
        self.last: dict | None = None            # the latest audition: {"wav", "meta", "recipe"}
        self.preview_count = 0
        self._building = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(PREVIEW_DELAY_MS)
        self.timer.timeout.connect(self.render_preview)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(16)
        # column 1: what to make
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(window._label("RECIPE", "section"))
        self.kind = QComboBox()
        self.kind.setObjectName("recipeType")
        for entry in self.schema["types"]:
            self.kind.addItem(entry["type"].replace("_", " ").capitalize(), entry["type"])
        self.kind.currentIndexChanged.connect(self.type_changed)
        left.addWidget(self.kind)
        self.purpose = window._label("", "muted")
        self.purpose.setWordWrap(True)
        left.addWidget(self.purpose)
        self.form = QGridLayout()
        self.form.setHorizontalSpacing(8)
        self.form.setVerticalSpacing(5)
        self.form.setColumnStretch(1, 1)
        left.addLayout(self.form)
        left.addStretch()
        left.addWidget(self._palette_button())
        outer.addLayout(left, 3)
        # column 2: listen
        middle = QVBoxLayout()
        middle.setSpacing(6)
        middle.addWidget(window._label("SOUND", "section"))
        self.canvas_box = QWidget()
        canvas_layout = QVBoxLayout(self.canvas_box)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(4)
        self.canvas = DrawCanvas(window)
        self.canvas.changed.connect(self.changed)
        canvas_layout.addWidget(self.canvas, 1)
        presets = QHBoxLayout()
        presets.setSpacing(4)
        for name, text in (("sine", "Sine"), ("triangle", "Triangle"), ("saw", "Saw"), ("square", "Square"),
                           ("clear", "Clear")):
            control = window._button(text, lambda _=False, name=name: self.canvas.preset(name), f"draw{name.title()}")
            control.setProperty("compact", True)
            presets.addWidget(control)
        self.draw_points = QSpinBox()
        self.draw_points.setObjectName("drawPoints")
        self.draw_points.setRange(*self.schema["limits"]["draw_points"])
        self.draw_points.setValue(len(self.canvas.points()))
        self.draw_points.editingFinished.connect(lambda: self.canvas.resample(self.draw_points.value()))
        window._bind(self.draw_points, "Number of points along one cycle", "setToolTip")
        presets.addWidget(self.draw_points)
        presets.addStretch()
        canvas_layout.addLayout(presets)
        middle.addWidget(self.canvas_box, 1)
        listening = QHBoxLayout()
        self.listen_button = window._button("Listen", self.listen, "recipeListen")
        self.auto_listen = QCheckBox()
        window._bind(self.auto_listen, "Listen after each change", "setText")
        self.auto_listen.setChecked(True)
        listening.addWidget(self.listen_button)
        listening.addWidget(self.auto_listen)
        listening.addStretch()
        middle.addLayout(listening)
        self.measures = QLabel()
        self.measures.setObjectName("recipeMeasures")
        self.measures.setWordWrap(True)
        self.measures.setTextFormat(Qt.TextFormat.PlainText)
        self.measures.setAlignment(Qt.AlignmentFlag.AlignTop)
        middle.addWidget(self.measures, 1)
        outer.addLayout(middle, 3)
        # column 3: put it in the song
        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(window._label("ADD TO SONG", "section"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(1, 1)
        self.name = QLineEdit()
        self.name.setObjectName("recipeName")
        self.name.setMaxLength(self.schema["limits"]["name_length"])
        self.name.setText("Created")
        self.role = QComboBox()
        self.role.setObjectName("recipeRole")
        self.note = QComboBox()
        self.note.setObjectName("recipeNote")
        for name in self.schema["notes"]:
            self.note.addItem(name)
        self.note.setCurrentText("C-2")
        self.finetune = QSpinBox()
        self.finetune.setObjectName("recipeFinetune")
        self.finetune.setRange(*self.schema["limits"]["finetune"])
        self.match = QCheckBox()
        self.match.setObjectName("recipeMatch")
        window._bind(self.match, "Match the volume to the role's level", "setText")
        self.match.setChecked(True)
        self.volume = QSpinBox()
        self.volume.setObjectName("recipeVolume")
        self.volume.setRange(*self.schema["limits"]["volume"])
        self.volume.setValue(synth_tools.DEFAULT_VOLUME)
        self.volume.setEnabled(False)
        self.slot = QComboBox()
        self.slot.setObjectName("recipeSlot")
        self.pcm = QCheckBox()
        self.pcm.setObjectName("recipePcm")
        window._bind(self.pcm, "Keep the drawing as plain sample data instead of a recipe", "setText")
        pitch = QHBoxLayout()
        pitch.setSpacing(6)
        pitch.addWidget(self.note, 1)
        pitch.addWidget(self.finetune, 1)
        self.finetune.setPrefix(window.t("fine tune "))
        rows = (("Name", self.name), ("Role", self.role), ("Slot", self.slot), ("Note", pitch), ("Volume", self.volume))
        for row, (text, control) in enumerate(rows):
            grid.addWidget(window._label(text, "muted"), row, 0)
            if isinstance(control, QHBoxLayout):
                grid.addLayout(control, row, 1)
            else:
                grid.addWidget(control, row, 1)
        right.addLayout(grid)
        right.addWidget(self.match)
        right.addWidget(self.pcm)
        self.add_button = window._button("Add to song", self.add_to_song, "addRecipe")
        self.add_button.setObjectName("primary")
        right.addWidget(self.add_button)
        self.status = QLabel()
        self.status.setObjectName("createStatus")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        right.addWidget(self.status)
        right.addStretch()
        outer.addLayout(right, 2)

        for control in (self.name,):
            control.textChanged.connect(self.changed)
        for control in (self.role, self.note):
            control.currentIndexChanged.connect(self.changed)
        for control in (self.finetune, self.volume):
            control.valueChanged.connect(self.changed)
        self.match.toggled.connect(lambda on: (self.volume.setEnabled(not on), self.changed()))
        self.retranslate()
        self.type_changed()

    def _palette_button(self):
        window = self.window
        self.palette_button = window._button("Start a synthesized song…", self.start_synthesized_song, "startSynth")
        window._bind(self.palette_button, "Open a new song holding the starter palette of created samples (kick, snare, hat, bass, "
                     "leads, noise), volumes matched to their roles.", "setToolTip")
        return self.palette_button

    # --- the generated form -----------------------------------------------------------
    def retranslate(self):
        t = self.window.t
        self.finetune.setPrefix(t("fine tune "))
        current = self.role.currentData()
        self.role.blockSignals(True)
        self.role.clear()
        self.role.addItem(t("Automatic"), None)
        for role in self.schema["roles"]:
            self.role.addItem(t(role.capitalize()), role)
        self.role.setCurrentIndex(max(0, self.role.findData(current)))
        self.role.blockSignals(False)
        for index in range(self.kind.count()):
            self.kind.setItemText(index, t(self.kind.itemData(index).replace("_", " ").capitalize()))
        self.refresh_slots()
        self._describe_type()
        if self.last:
            self.show_measures(self.last["meta"])

    def current_type(self) -> dict:
        return self.types[self.kind.currentData()]

    def _describe_type(self):
        entry = self.current_type()
        self.purpose.setText(self.window.t(entry["purpose"]))

    def type_changed(self, *_):
        entry = self.current_type()
        self._building = True
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.widgets = {}
        defaults = entry["default_recipe"]
        row = 0
        for name, spec in entry["parameters"].items():
            if name == "points":
                continue    # drawn on the canvas
            control = self._control(name, spec, defaults.get(name))
            caption = QLabel(self.window.t(PARAMETER_LABELS.get(name, name.capitalize())))
            caption.setObjectName("muted")
            tip = self.window.t(spec.get("description", ""))
            caption.setToolTip(tip)
            control.setToolTip(tip)
            self.form.addWidget(caption, row, 0)
            self.form.addWidget(control, row, 1)
            self.widgets[name] = (spec, control, caption)
            row += 1
        jam = getattr(self.window, "jam", None)
        for _, control, _ in self.widgets.values():
            if jam is not None:
                jam.watch(control)          # rebuilt controls take part in the keyboard audition like the others
        self.canvas_box.setVisible(entry["type"] == "draw")
        self.pcm.setVisible(entry["type"] == "draw")
        self.measures.setMinimumHeight(0)
        self._describe_type()
        self._building = False
        self.apply_visibility()
        self.changed()

    def _control(self, name: str, spec: dict, default) -> QWidget:
        kind = spec["kind"]
        if kind == "choice":
            control = QComboBox()
            for choice in spec["choices"]:
                control.addItem(self.window.t(choice.capitalize()), choice)
            control.setCurrentIndex(max(0, control.findData(default)))
            control.currentIndexChanged.connect(self.value_changed)
        elif kind == "boolean":
            control = QCheckBox()
            control.setChecked(bool(default))
            control.toggled.connect(self.value_changed)
        elif kind == "integer":
            control = QDoubleSpinBox()          # a double spin box holds the 32-bit seeds a QSpinBox cannot
            control.setDecimals(0)
            control.setRange(spec["min"] - (1 if spec.get("default") == "auto" else 0), spec["max"])
            if spec.get("default") == "auto":
                control.setSpecialValueText(self.window.t("auto"))
                control.setValue(control.minimum())
            else:
                control.setValue(default if default is not None else spec["min"])
            control.valueChanged.connect(self.value_changed)
        else:
            control = QDoubleSpinBox()
            shown = str(default if default is not None else 0)
            control.setDecimals(max(3, min(6, len(shown.split(".")[1]) if "." in shown else 0)))   # the default must survive
            control.setRange(spec["min"], spec["max"])
            control.setSingleStep(0.01 if spec["max"] <= 1 else 1 if spec["max"] <= 100 else 10)
            control.setValue(default if default is not None else spec["min"])
            control.valueChanged.connect(self.value_changed)
        control.setObjectName(f"param_{name}")
        return control

    def value_changed(self, *_):
        if not self._building:
            self.apply_visibility()
            self.changed()

    def apply_visibility(self):
        """Parameters that do not apply to the chosen shape are hidden (and left out of the recipe)."""
        shape = self.widgets["shape"][1].currentData() if "shape" in self.widgets else None
        for spec, control, caption in self.widgets.values():
            applies = spec.get("applies_to")
            visible = not applies or shape in applies
            control.setVisible(visible)
            caption.setVisible(visible)

    def recipe(self) -> dict:
        """The recipe the form describes (valid for the core, or it raises when audited or added)."""
        recipe: dict = {"type": self.kind.currentData()}
        shape = self.widgets["shape"][1].currentData() if "shape" in self.widgets else None
        for name, (spec, control, _) in self.widgets.items():
            applies = spec.get("applies_to")
            if applies and shape not in applies:
                continue
            if spec["kind"] == "choice":
                recipe[name] = control.currentData()
            elif spec["kind"] == "boolean":
                recipe[name] = control.isChecked()
            elif spec["kind"] == "integer":
                if spec.get("default") == "auto" and control.value() < spec["min"]:
                    continue
                recipe[name] = int(control.value())
            else:
                recipe[name] = round(control.value(), 6)
        if recipe["type"] == "draw":
            recipe["points"] = self.canvas.points()
        return recipe

    def set_value(self, name: str, value):
        """Set one parameter from outside (tests, future presets)."""
        spec, control, _ = self.widgets[name]
        if spec["kind"] == "choice":
            control.setCurrentIndex(control.findData(value))
        elif spec["kind"] == "boolean":
            control.setChecked(bool(value))
        else:
            control.setValue(value)

    # --- listening -------------------------------------------------------------------------
    def changed(self, *_):
        """Something that changes the sound was edited: audition once the hand has rested."""
        if not self._building and self.isVisible():   # a hidden tab must never start making sounds
            self.timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if self.last is None:
            self.render_preview(play=False)         # measurements on arrival, silently

    def _volume(self) -> int:
        return synth_tools.DEFAULT_VOLUME if self.match.isChecked() else self.volume.value()

    def render_preview(self, play: bool | None = None):
        """Audition the recipe in memory. `play` forces or forbids playing (default: the auto-listen box)."""
        window = self.window
        recipe = self.recipe()
        try:
            wav, meta = sample_tools.preview_recipe(recipe, self.note.currentText(), 1.0, self._volume(),
                                                    self.finetune.value(), self.name.text() or "Created",
                                                    self.role.currentData())
        except (ValidationError, ValueError) as exc:
            self.last = None
            self.measures.setText(window.t("This recipe cannot be built: {detail}", detail=exc))
            self.measures.setProperty("error", True)
            self.measures.style().unpolish(self.measures)
            self.measures.style().polish(self.measures)
            return None
        self.preview_count += 1
        self.last = {"wav": wav, "meta": meta, "recipe": recipe}
        self.show_measures(meta)
        if self.auto_listen.isChecked() if play is None else play:
            window.audition_wav(wav)
        return self.last

    def jam_sample(self):
        """The recipe as a sample, for playing it from the keyboard (None while the recipe cannot be built)."""
        try:
            return synth.from_recipe(self.name.text() or "Created", self.recipe(), self._volume(), self.finetune.value())
        except (ValidationError, ValueError):
            return None

    def listen(self):
        self.timer.stop()
        return self.render_preview(play=True)

    def show_measures(self, meta: dict):
        t = self.window.t
        sample, level, audio = meta["sample"], meta["loudness"], meta["audio"]
        lines = [t("{bytes} bytes · {kind} · plays {rate:.0f} Hz at {note}", bytes=sample["bytes"],
                   kind=t("looped" if sample.get("looped") else "one-shot"), rate=meta["playback_rate"], note=meta["note"])]
        if sample.get("tuning_cents") is not None:
            lines.append(t("tuning off by {cents:+.1f} cents", cents=sample["tuning_cents"]))
        lines.append(t("Loudness {db:.1f} dB (role {role}, bank reference {reference:.1f} dB)", db=level["loudness_db"],
                       role=t(level["role"].capitalize()), reference=level["default_reference_db"]))
        peak = audio.get("peak_dbfs")
        lines.append(t("Peak {peak} dBFS · RMS {rms} dBFS · clipped {clipped}",
                       peak="-∞" if peak is None else f"{peak:.1f}",
                       rms="-∞" if audio.get("rms_dbfs") is None else f"{audio['rms_dbfs']:.1f}",
                       clipped=audio["clipped_samples"]))
        self.measures.setText("\n".join(lines))
        self.measures.setProperty("error", False)
        self.measures.style().unpolish(self.measures)
        self.measures.style().polish(self.measures)

    def update_format(self):
        """An XM takes the recipe, converted like `convert` converts a MOD sample; keeping a drawing as plain
        sample data is a MOD sample edit, so an XM keeps the drawing as a recipe."""
        xm = self.window.module_format == "xm"
        self.pcm.setEnabled(not xm)
        self.pcm.setToolTip(self.window.t(XM_REFUSED_TIP) if xm else "")

    # --- adding -----------------------------------------------------------------------------
    def refresh_slots(self):
        """Slot choices: the first free one, or any existing slot (replacing it asks first), or the next new one."""
        window, current = self.window, self.slot.currentData()
        self.slot.blockSignals(True)
        self.slot.clear()
        self.slot.addItem(window.t("First free slot"), None)
        if window.document:
            samples = window.document.module.samples
            limit = 128 if window.document.module.format == "xm" else 31
            for number in range(1, min(limit, len(samples) + 1) + 1):
                sample = samples[number - 1] if number <= len(samples) else None
                text = f"{number:02d} · {sample.name or window.t('Sample')}" if sample and sample.pcm \
                    else f"{number:02d} · {window.t('free')}"
                self.slot.addItem(text, number)
        self.slot.setCurrentIndex(max(0, self.slot.findData(current)))
        self.slot.blockSignals(False)

    def first_free_slot(self) -> int:
        samples = self.window.document.module.samples
        used = {value.sample for pattern in self.window.document.module.patterns for value in pattern.cells.values() if value.sample}
        return next((index for index, item in enumerate(samples, 1) if not item.pcm and index not in used), len(samples) + 1)

    def show_status(self, text: str, error: bool = False):
        self.status.setText(text)
        self.status.setProperty("error", error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def operation(self, replace: bool = False) -> dict:
        """The patch operation "Add to song" would run."""
        window = self.window
        name, recipe = self.name.text().strip() or "Created", self.recipe()
        slot = self.slot.currentData()
        if recipe["type"] == "draw" and self.pcm.isChecked() and self.pcm.isEnabled():
            slot = slot or self.first_free_slot()
            sample = sample_tools.draw_to_pcm(recipe["points"], recipe.get("cycles", 16), recipe.get("frequency", 261.625565),
                                              recipe.get("peak", 0.88))
            return {"op": "sample_set_pcm", "slot": slot, "name": name, "volume": self._volume(),
                    "finetune": self.finetune.value(), "replace": replace, **sample_tools.pcm_fields(sample)}
        op = {"op": "recipe_sample", "name": name, "recipe": recipe, "finetune": self.finetune.value(), "replace": replace}
        if slot:
            op["slot"] = slot
        if self.role.currentData():
            op["role"] = self.role.currentData()
        if self.match.isChecked():
            bank = window.sample_browser.library_path
            if synth_tools.library_exists(bank):
                op.update(match="library", library=str(bank))
            else:
                op["match"] = "defaults"
        else:
            op["volume"] = self.volume.value()
        return op

    def add_to_song(self) -> dict | None:
        window = self.window
        if not window.document:
            self.show_status(window.t("Open a song first."), True)
            return None
        slot = self.slot.currentData()
        samples = window.document.module.samples
        replace = False
        if slot and slot <= len(samples) and samples[slot - 1].pcm:
            answer = QMessageBox.question(window, window.t("Replace this sample?"),
                                          window.t("Slot {slot} holds {name!r}. Replace it with the new sound?",
                                                   slot=slot, name=samples[slot - 1].name),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return None
            replace = True
        try:
            result = window.run_patch([self.operation(replace)], "Add created sample")
        except ValidationError as exc:
            text = self.refusal_text(exc)
            self.show_status(text, True)
            window.message(text, True)
            return None
        info = result["results"][0]
        self.show_status(window.t("Added to slot {slot} · Ctrl+Z to undo", slot=info["slot"]))
        window.message("Added to slot {slot} · Ctrl+Z to undo", slot=info["slot"])
        self.refresh_slots()
        return info

    def refusal_text(self, exc: ValidationError) -> str:
        t = self.window.t
        if exc.code == "SAMPLE_SOURCE":
            return t("This song only allows samples from its declared source, so this sound cannot be added.") + " " + str(exc)
        if exc.code == "SAMPLE_SLOT":
            return t("That sample slot cannot be used: {detail}", detail=exc)
        return t("This sound cannot be added: {detail}", detail=exc)

    def start_synthesized_song(self):
        """The palette flow: a new project holding the starter palette, volumes matched to the bank or the defaults."""
        window = self.window
        if not window._discard_or_save():
            return None
        bank = window.sample_browser.library_path
        try:
            reference = synth_tools.resolve_reference("library" if synth_tools.library_exists(bank) else "defaults", bank)
            module, report = synth_tools.palette(window.t("Synth Palette"), reference=reference)
        except (ValidationError, ValueError, OSError) as exc:
            window.message("Cannot start a synthesized song: {detail}", True, detail=exc)
            return None
        window.open_module(module)
        window.message("Started a synthesized song with {count} created samples", count=len(report["slots"]))
        return module


def scroll_page(widget: QWidget) -> QScrollArea:
    """Wrap a workshop page so a small window scrolls instead of squeezing it."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(widget)
    return area

