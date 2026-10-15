"""Editable musical documents, independent of any GUI toolkit or audio device."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Callable

from . import mod, project
from .model import Cell, Module, NOTES, NOTE_TO_PERIOD, ValidationError, cell, playback_plan, require_int, validate


def fingerprint(module: Module) -> str:
    value = json.dumps(project.to_dict(module), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Document:
    def __init__(self, module: Module, path: Path | None = None):
        validate(module)
        self.module = module
        self.path = path.resolve() if path else None
        self.revision = 0
        self._saved = fingerprint(module)
        self._undo: list[tuple[str, Module]] = []
        self._redo: list[tuple[str, Module]] = []

    @classmethod
    def open(cls, path: Path) -> Document:
        module = project.load(path) if path.suffix.lower() == ".json" else mod.read(path)
        return cls(module, path)

    @property
    def dirty(self) -> bool:
        return fingerprint(self.module) != self._saved

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def apply(self, label: str, operation: Callable[[Module], None]) -> bool:
        candidate = copy.deepcopy(self.module)
        operation(candidate)
        validate(candidate)
        # Validate the control-flow timeline before accepting an edit as well.
        playback_plan(candidate)
        if candidate == self.module:
            return False
        self._undo.append((label, self.module))
        self._undo = self._undo[-50:]
        self._redo.clear()
        self.module = candidate
        self.revision += 1
        return True

    def undo(self) -> bool:
        if not self._undo:
            return False
        label, previous = self._undo.pop()
        self._redo.append((label, self.module))
        self.module = previous
        self.revision += 1
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        label, following = self._redo.pop()
        self._undo.append((label, self.module))
        self.module = following
        self.revision += 1
        return True

    def replace_cell(self, pattern: int, row: int, channel: int, value: Cell) -> bool:
        require_int(pattern, "pattern", 0, len(self.module.patterns) - 1)
        return self.apply("Modifier une cellule", lambda module: module.patterns[pattern].put(row, channel, value))

    def rename(self, title: str) -> bool:
        return self.apply("Renommer le morceau", lambda module: setattr(module, "title", title))

    def set_timing(self, bpm: int, speed: int) -> bool:
        require_int(bpm, "tempo", 33, 255)
        require_int(speed, "vitesse", 1, 31)

        def change(module: Module):
            pattern = module.patterns[module.orders[0]]
            available = [ch for ch in range(4) if pattern.get(0, ch).command == 15]
            available += [ch for ch in range(4) if ch not in available and pattern.get(0, ch).effect == "000"]
            if len(available) < 2:
                raise ValidationError("Il faut deux colonnes d'effet libres ou Fxx sur la première ligne pour fixer tempo et vitesse sans effacer d'autres effets.")
            for channel in range(4):
                old = pattern.get(0, channel)
                if old.command == 15:
                    pattern.put(0, channel, Cell(old.period, old.sample))
            for channel, parameter in zip(available[:2], (speed, bpm)):
                old = pattern.get(0, channel)
                pattern.put(0, channel, Cell(old.period, old.sample, 15, parameter))
            if isinstance(module.metadata.get("timing"), dict):
                module.metadata["timing"].update(bpm=bpm, speed=speed)

        return self.apply("Modifier le tempo de départ", change)

    def set_sample(self, index: int, volume: int, finetune: int) -> bool:
        require_int(index, "sample", 0, len(self.module.samples) - 1)
        require_int(volume, "volume", 0, 64)
        require_int(finetune, "finetune", -8, 7)

        def change(module: Module):
            module.samples[index].volume = volume
            module.samples[index].finetune = finetune

        return self.apply("Régler le sample", change)

    def transpose(self, pattern: int, channel: int, semitones: int) -> bool:
        require_int(pattern, "pattern", 0, len(self.module.patterns) - 1)
        require_int(channel, "voie", 0, 3)
        require_int(semitones, "demi-tons", -12, 12)

        def change(module: Module):
            selected = module.patterns[pattern]
            for row in range(64):
                old = selected.get(row, channel)
                if old.note:
                    target = NOTES.index(old.note) + semitones
                    if not 0 <= target < len(NOTES):
                        raise ValidationError("La transposition sortirait des notes C-1 à B-3 ; aucune note n'a été modifiée.")
                    selected.put(row, channel, Cell(NOTE_TO_PERIOD[NOTES[target]], old.sample, old.command, old.param))

        return self.apply("Transposer la voie du pattern", change)

    def gate_note(self, pattern: int, row: int, channel: int, ticks: int) -> bool:
        require_int(pattern, "pattern", 0, len(self.module.patterns) - 1)
        require_int(row, "row", 0, 63)
        require_int(channel, "voie", 0, 3)
        require_int(ticks, "ticks", 1, 15)
        old = self.module.patterns[pattern].get(row, channel)
        if not old.period:
            raise ValidationError("Sélectionne une cellule contenant une note.")
        return self.replace_cell(pattern, row, channel, cell(old.note, old.sample, f"EC{ticks:X}"))

    def save_project(self, path: Path) -> None:
        if path.suffix.lower() != ".json":
            raise ValidationError("Un projet éditable doit avoir une extension .json.")
        project.write_json(path, project.to_dict(self.module))
        self.path = path.resolve()
        self._saved = fingerprint(self.module)

    def export_mod(self, path: Path) -> None:
        if path.suffix.lower() != ".mod":
            raise ValidationError("L'export du module doit avoir une extension .mod.")
        project.atomic_bytes(path, mod.encode(self.module))


def listening_copy(module: Module, audible_channels: tuple[bool, ...]) -> Module:
    if len(audible_channels) != 4:
        raise ValidationError("Quatre états de voie sont attendus.")
    result = copy.deepcopy(module)
    for pattern in result.patterns:
        for (row, channel), value in list(pattern.cells.items()):
            if not audible_channels[channel]:
                # Preserve global timing/flow effects even on an inaudible lane.
                pattern.put(row, channel, Cell(0, 0, value.command, value.param))
    validate(result)
    return result
