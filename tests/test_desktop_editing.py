"""Tracker editing in the Qt window: keyboard entry, blocks, order list and live reload from disk.

Everything runs on temporary projects; the shipped examples are never modified.
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# These tests drive QMediaPlayer; the real-time (libxmp) path is covered by test_desktop_realtime.
os.environ.setdefault("CHIPLOOM_PLAYBACK", "rendered")
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*.debug=false;qt.multimedia.*.info=false")
# Windows opened by tests must not leave live-session discovery files in the user's own ChipLoom folder.
_LIVE_HOME = tempfile.mkdtemp(prefix="chiploom-home-")
os.environ.setdefault("CHIPLOOM_HOME", _LIVE_HOME)
atexit.register(shutil.rmtree, _LIVE_HOME, True)
try:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFontDatabase, QGuiApplication, QKeyEvent
    from PySide6.QtWidgets import QApplication
    from tracker4agents.desktop import TrackerWindow
except ModuleNotFoundError:
    TrackerWindow = Qt = None

from tracker4agents.desktop_input import (format_block, hex_digit, note_name, parse_block, resolve_layout,
                                          semitone, valid_layout)
from tracker4agents.desktop_services import AppState
from tracker4agents.document import Document, fingerprint
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell
from tracker4agents.patch import pattern_grid
from tracker4agents.themes import THEMES

ROOT = Path(__file__).resolve().parents[1]
# Without PySide6 the window tests are skipped; the Qt-free input tests still run.
CTRL, ALT, SHIFT = ((Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier,
                     Qt.KeyboardModifier.ShiftModifier) if Qt else (None, None, None))


def song() -> Module:
    samples = [Sample(name, (0, 0) + (60, 0, -60, 0) * 8, 40) for name in ("Kick", "Snare", "Lead")]
    return Module("Editing", samples, [Pattern(name="Intro"), Pattern(name="Verse")], [0, 1, 0])


class InputTests(unittest.TestCase):
    """The Qt-free input helpers."""

    def test_layout_maps_resolution_and_validation(self):
        self.assertEqual(semitone("qwerty", "z"), 0)
        self.assertEqual(semitone("qwerty", "q"), 12)
        self.assertEqual(semitone("azerty", "w"), 0)
        self.assertEqual(semitone("azerty", "a"), 12)
        self.assertEqual(semitone("azerty", "é"), 13)
        self.assertIsNone(semitone("qwerty", "é"))
        self.assertEqual(note_name(2, 0), "C-2")
        self.assertEqual(note_name(1, 12), "C-2")
        self.assertIsNone(note_name(3, 12))
        self.assertEqual(hex_digit("azerty", "é"), "2")
        self.assertIsNone(hex_digit("qwerty", "é"))
        self.assertEqual(hex_digit("qwerty", "c"), "C")
        self.assertEqual(valid_layout("bogus"), "auto")
        self.assertEqual(valid_layout(["qwerty"]), "auto")
        self.assertEqual(resolve_layout("auto", "fr_FR"), "azerty")
        self.assertEqual(resolve_layout("auto", "en_US"), "qwerty")
        self.assertEqual(resolve_layout("qwerty", "fr_FR"), "qwerty")
        self.assertEqual(resolve_layout("nonsense", "fr_BE"), "azerty")

    def test_block_text_round_trip_and_agent_grid(self):
        block = [[cell("C-2", 1), cell(), cell("G#2", 5, "C20"), cell()], [cell(), cell(), cell(), cell(effect="F06")]]
        self.assertEqual(parse_block(format_block(block)), block)
        module = song()
        module.patterns[0].put(3, 1, cell("E-2", 2, "A03"))
        lines = pattern_grid(module, 0, 2, 3)
        parsed = parse_block("Pattern 00 (Intro)\n" + "\n".join(lines))
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[1][1], cell("E-2", 2, "A03"))
        with self.assertRaises(ValidationError):
            parse_block("nothing useful here")
        with self.assertRaises(ValidationError):
            parse_block("C-2 01 ... | broken")
        with self.assertRaises(ValidationError):
            parse_block("C-2 01 ... | --- -- ...\nC-2 01 ...")

    def test_new_theme_colors_exist_everywhere(self):
        for name, theme in THEMES.items():
            for key in ("agent_change", "proposal", "human_change"):
                self.assertRegex(theme[key], r"^#[0-9a-f]{6}$", (name, key))


@unittest.skipUnless(TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class EditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["editing-tests"])
        cls.app.setQuitOnLastWindowClosed(False)
        if cls.app.property("chiploomFusion") is None:   # restyling widgets left by earlier modules can stall
            cls.app.setStyle("Fusion")
            cls.app.setProperty("chiploomFusion", True)
        if not QFontDatabase.families() and os.name == "nt":
            for name in ("segoeui.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "work.project.json"
        Document(song()).save_project(self.path)
        self.open_window()

    def open_window(self, configure=True):
        self.window = TrackerWindow(self.path, self.directory / "state", restore=False)
        self.window.output.setMuted(True)
        self.window.sample_output.setMuted(True)
        self.window.show()
        self.wait_until(lambda: self.window.document is not None and self.window.samples.count() == 3)
        if configure:
            self.window.keyboard_combo.setCurrentIndex(self.window.keyboard_combo.findData("qwerty"))
            self.window.edit_octave.setValue(2)
            self.window.edit_step.setValue(1)
        self.table, self.model = self.window.table, self.window.pattern_model

    def tearDown(self):
        window = self.window
        window.document.dirty and window.document.save_project(self.directory / "tear-down.project.json")
        window.close()
        window.pool.waitForDone(10000)
        self.app.processEvents()
        window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def wait_until(self, predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(predicate(), self.window.statusBar().currentMessage())

    # --- helpers ---------------------------------------------------------------------
    def press(self, text="", key=None, modifiers=None):
        if modifiers is None:
            modifiers = Qt.KeyboardModifier.NoModifier
        if key is None:
            key = ord(text.upper()) if text and text.isascii() else int(Qt.Key.Key_unknown)
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(self.table, QKeyEvent(kind, key, modifiers, text))

    def type_keys(self, text):
        for char in text:
            self.press(char)

    def go(self, row, column):
        self.table.setCurrentIndex(self.model.index(row, column))

    def cell(self, row, channel, pattern=0):
        return self.window.document.module.patterns[pattern].get(row, channel)

    def patch(self, ops, label="Test"):
        self.window.apply_patch(ops, label)

    def agent_saves(self, ops):
        agent = Document.open(self.path)
        agent.patch(ops, "Agent")
        agent.save_project(self.path)
        return agent.module

    # --- keyboard entry --------------------------------------------------------------
    def test_qwerty_notes_use_current_instrument_octave_and_edit_step(self):
        window = self.window
        window.samples.setCurrentRow(2)
        window.edit_step.setValue(2)
        self.go(0, 0)
        self.type_keys("zs")  # edit mode is off: nothing happens
        self.assertEqual(self.cell(0, 0), cell())
        self.assertFalse(window.document.dirty)
        window.edit_action.setChecked(True)
        self.assertTrue(window.edit_mode and window.edit_button.isChecked())
        self.type_keys("zs")
        self.assertEqual(self.cell(0, 0), cell("C-2", 3))
        self.assertEqual(self.cell(2, 0), cell("C#2", 3))
        self.assertEqual(self.table.currentIndex().row(), 4)
        self.press("q")  # upper row = next octave
        self.assertEqual(self.cell(4, 0).note, "C-3")
        window.edit_octave.setValue(1)
        self.press("z")
        self.assertEqual(self.cell(6, 0).note, "C-1")
        self.press(key=Qt.Key.Key_F3)
        self.assertEqual(window.edit_octave.value(), 3)
        self.press(key=Qt.Key.Key_Minus, modifiers=Qt.KeyboardModifier.KeypadModifier)
        self.assertEqual(window.edit_octave.value(), 2)
        window.edit_step.setValue(0)
        self.go(10, 3)
        self.press("x")
        self.assertEqual(self.cell(10, 1).note, "D-2")
        self.assertEqual(self.table.currentIndex().row(), 10)
        # An unmapped letter must not move the cursor through type-ahead search.
        self.press("k")
        self.assertEqual(self.table.currentIndex().row(), 10)
        window.edit_octave.setValue(3)
        before = fingerprint(window.document.module)
        self.go(12, 0)
        self.press("q")  # C-4 does not exist
        self.assertEqual(fingerprint(window.document.module), before)
        self.assertIn("C-1..B-3", window.statusBar().currentMessage())

    def test_each_entry_is_one_undo_step(self):
        window = self.window
        window.edit_action.setChecked(True)
        self.go(0, 0)
        self.type_keys("zxc")
        self.assertEqual([self.cell(row, 0).note for row in range(3)], ["C-2", "D-2", "E-2"])
        window.undo()
        self.assertEqual([self.cell(row, 0).note for row in range(3)], ["C-2", "D-2", None])
        window.undo()
        window.undo()
        self.assertFalse(window.document.dirty)

    def test_azerty_keys_and_unshifted_number_row_digits(self):
        window = self.window
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("azerty"))
        self.assertEqual(window.keyboard_layout(), "azerty")
        window.edit_action.setChecked(True)
        window.edit_step.setValue(0)
        self.go(0, 0)
        self.press("w")
        self.assertEqual(self.cell(0, 0).note, "C-2")
        self.press("é")  # number-row key 2: C#
        self.assertEqual(self.cell(0, 0).note, "C#3")
        self.press("a")
        self.assertEqual(self.cell(0, 0).note, "C-3")
        self.press("z")  # QWERTY C is just Z on an AZERTY map: D-3
        self.assertEqual(self.cell(0, 0).note, "D-3")
        self.go(1, 5)
        self.press("c")
        self.press("é")
        self.press("à")  # 0
        self.assertEqual(self.cell(1, 1).effect, "C20")

    def test_auto_layout_follows_french_input_locale(self):
        window = self.window
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("auto"))
        with patch("tracker4agents.desktop.input_locale_name", return_value="fr_FR"):
            self.assertEqual(window.keyboard_layout(), "azerty")
        with patch("tracker4agents.desktop.input_locale_name", return_value="en_GB"):
            self.assertEqual(window.keyboard_layout(), "qwerty")

    def test_hexadecimal_entry_in_sample_and_effect_columns(self):
        window = self.window
        window.edit_action.setChecked(True)
        window.edit_step.setValue(0)
        self.go(0, 1)
        before = fingerprint(window.document.module)
        self.press("0")
        self.assertEqual(self.model.data(self.model.index(0, 1)), "0_")  # progressive display
        self.assertEqual(fingerprint(window.document.module), before)
        self.press("3")
        self.assertEqual(self.cell(0, 0).sample, 3)
        self.assertEqual(self.model.data(self.model.index(0, 1)), "03")
        self.press("1")
        self.press("f")  # slot 1F does not exist in this three-sample song: rejected as a whole
        self.assertEqual(self.cell(0, 0).sample, 3)
        self.assertTrue(window.statusBar().currentMessage())
        self.press("2")  # cannot start a sample number up to 1F: complete at once
        self.assertEqual(self.cell(0, 0).sample, 2)
        self.go(0, 2)
        self.press("c")
        self.press("2")
        self.assertEqual(self.model.data(self.model.index(0, 2)), "C2_")
        self.press("0")
        self.assertEqual(self.cell(0, 0).effect, "C20")
        self.go(0, 2)
        self.press("c")
        self.press(key=Qt.Key.Key_Escape)  # cancels a half-typed value
        self.assertEqual(self.model.data(self.model.index(0, 2)), "C20")
        self.press("g")  # not a hex digit: ignored
        self.assertEqual(self.cell(0, 0).effect, "C20")
        self.press(key=Qt.Key.Key_Backspace)
        self.assertEqual(self.cell(0, 0).effect, "000")
        self.assertEqual(self.cell(0, 0).sample, 2)

    def test_delete_clears_the_selected_block(self):
        window = self.window
        self.patch([{"op": "write", "pattern": 0, "row": 0, "channel": 0, "cells": ["C-2 01 ...", "D-2 01 ...", "E-2 01 ..."]},
                    {"op": "write", "pattern": 0, "row": 0, "channel": 1, "cells": ["G-2 02 ...", "A-2 02 ...", "B-2 02 ..."]}])
        self.table.select_block(0, 2, 0, 2)
        self.assertEqual(self.table.selection_block(), (0, 2, 0, 2))
        self.press(key=Qt.Key.Key_Delete)
        self.assertEqual([self.cell(row, channel) for row in (0, 1) for channel in (0, 1)], [cell()] * 4)
        self.assertEqual(self.cell(2, 0).note, "E-2")
        window.undo()
        self.assertEqual(self.cell(0, 1).note, "G-2")

    # --- blocks ----------------------------------------------------------------------
    def block_song(self):
        self.patch([{"op": "write", "pattern": 0, "row": 0, "channel": 0, "cells": ["C-2 01 ...", "D-2 01 ...", "E-2 02 F06", "G-2 02 ..."]},
                    {"op": "write", "pattern": 0, "row": 0, "channel": 1, "cells": ["--- -- ...", "A-2 03 C20", "--- -- ...", "B-2 03 ..."]}])

    def test_copy_paste_round_trip_through_clipboard_text_and_one_undo(self):
        window = self.window
        self.block_song()
        before = fingerprint(window.document.module)
        self.table.select_block(0, 4, 0, 2)
        self.press("c", key=Qt.Key.Key_C, modifiers=CTRL)
        text = QGuiApplication.clipboard().text()
        self.assertEqual(text.splitlines()[1], "D-2 01 ... | A-2 03 C20")
        self.assertEqual(parse_block(text)[2][0], cell("E-2", 2, "F06"))
        self.assertEqual(fingerprint(window.document.module), before)
        self.go(8, 6)  # paste lands on the cursor row and channel
        self.press("v", key=Qt.Key.Key_V, modifiers=CTRL)
        self.assertEqual([self.cell(8 + row, 2) for row in range(4)], [self.cell(row, 0) for row in range(4)])
        self.assertEqual([self.cell(8 + row, 3) for row in range(4)], [self.cell(row, 1) for row in range(4)])
        self.assertEqual(self.table.selection_block(), (8, 4, 2, 2))
        window.undo()
        self.assertEqual(self.cell(8, 2), cell())
        self.assertEqual(window.document.module.patterns[0].cells.get((8, 2)), None)
        # Text printed by the agent (with row prefixes, four channels) pastes at the cursor row.
        module = window.document.module
        QGuiApplication.clipboard().setText("Pattern 00\n" + "\n".join(pattern_grid(module, 0, 0, 4)))
        self.go(20, 5)
        self.press("v", key=Qt.Key.Key_V, modifiers=CTRL)
        self.assertEqual(self.cell(21, 1), cell("A-2", 3, "C20"))  # four channels: shifted to fit from channel 0
        self.assertEqual(self.cell(22, 0), cell("E-2", 2, "F06"))
        garbage = fingerprint(window.document.module)
        QGuiApplication.clipboard().setText("C-2 01 ... | nope")
        self.press("v", key=Qt.Key.Key_V, modifiers=CTRL)
        self.assertEqual(fingerprint(window.document.module), garbage)

    def test_cut_then_undo_restores_the_source(self):
        window = self.window
        self.block_song()
        before = fingerprint(window.document.module)
        self.table.select_block(1, 2, 0, 1)
        self.press("x", key=Qt.Key.Key_X, modifiers=CTRL)
        self.assertEqual((self.cell(1, 0), self.cell(2, 0)), (cell(), cell()))
        self.assertEqual(self.cell(1, 1).note, "A-2")  # the second channel was not selected
        window.undo()
        self.assertEqual(fingerprint(window.document.module), before)

    def test_alt_arrows_move_the_block_and_the_selection_follows(self):
        window = self.window
        self.block_song()
        before = fingerprint(window.document.module)
        self.table.select_block(0, 2, 0, 2)
        self.press(key=Qt.Key.Key_Down, modifiers=ALT)
        self.assertEqual(self.table.selection_block(), (1, 2, 0, 2))
        self.assertEqual(self.cell(0, 0), cell())
        self.assertEqual(self.cell(1, 0), cell("C-2", 1))
        self.assertEqual(self.cell(2, 1), cell("A-2", 3, "C20"))
        self.press(key=Qt.Key.Key_Right, modifiers=ALT)
        self.assertEqual(self.table.selection_block(), (1, 2, 1, 2))
        self.assertEqual(self.cell(1, 1), cell("C-2", 1))
        self.assertEqual(self.cell(2, 2), cell("A-2", 3, "C20"))
        self.press(key=Qt.Key.Key_Right, modifiers=ALT)
        self.press(key=Qt.Key.Key_Right, modifiers=ALT)  # already against channel 3
        self.assertEqual(self.table.selection_block(), (1, 2, 2, 2))
        self.assertIn("edge", window.statusBar().currentMessage())
        self.press(key=Qt.Key.Key_Up, modifiers=ALT)
        self.assertEqual(self.table.selection_block(), (0, 2, 2, 2))
        for _ in range(4):
            window.undo()
        self.assertEqual(fingerprint(window.document.module), before)

    def test_alt_up_at_the_first_row_does_nothing(self):
        self.block_song()
        before = fingerprint(self.window.document.module)
        self.table.select_block(0, 2, 0, 1)
        self.press(key=Qt.Key.Key_Up, modifiers=ALT)
        self.assertEqual(fingerprint(self.window.document.module), before)
        self.assertEqual(self.table.selection_block(), (0, 2, 0, 1))

    def test_ctrl_arrows_transpose_selection_by_semitone_or_octave(self):
        window = self.window
        self.block_song()
        self.table.select_block(0, 4, 0, 1)
        self.press(key=Qt.Key.Key_Up, modifiers=CTRL)
        self.assertEqual([self.cell(row, 0).note for row in range(4)], ["C#2", "D#2", "F-2", "G#2"])
        self.press(key=Qt.Key.Key_Down, modifiers=CTRL | SHIFT)
        self.assertEqual([self.cell(row, 0).note for row in range(4)], ["C#1", "D#1", "F-1", "G#1"])
        self.assertEqual(self.cell(1, 1).note, "A-2")  # other channels untouched
        before = fingerprint(window.document.module)
        self.press(key=Qt.Key.Key_Down, modifiers=CTRL | SHIFT)  # would leave C-1..B-3
        self.assertEqual(fingerprint(window.document.module), before)
        self.assertTrue(window.statusBar().currentMessage())

    def test_double_click_editing_still_works_as_one_patch(self):
        window = self.window
        self.assertTrue(self.model.setData(self.model.index(0, 0), "d-3"))
        self.assertEqual(self.cell(0, 0).note, "D-3")
        self.assertTrue(self.model.setData(self.model.index(0, 1), "03"))
        self.assertEqual(self.cell(0, 0).sample, 3)
        self.assertFalse(self.model.setData(self.model.index(0, 0), "H-9"))
        window.undo()
        window.undo()
        self.assertFalse(window.document.dirty)

    # --- order list ------------------------------------------------------------------
    def test_order_editor_operations_are_single_undoable_patches(self):
        window, editor = self.window, self.window.order_editor
        module = lambda: window.document.module
        self.assertEqual(module().orders, [0, 1, 0])
        self.assertTrue(editor.insert_current())
        self.assertEqual((module().orders, window.current_order, window.orders.currentIndex()), ([0, 0, 1, 0], 1, 1))
        window.undo()
        self.assertEqual(module().orders, [0, 1, 0])
        window.orders.setCurrentIndex(0)
        self.assertTrue(editor.new_pattern())
        self.assertEqual((module().orders, len(module().patterns), window.current_order), ([0, 2, 1, 0], 3, 1))
        self.assertEqual(window.pattern_model.pattern, 2)
        self.assertTrue(editor.duplicate_pattern())
        self.assertEqual((module().orders, window.current_order), ([0, 2, 3, 1, 0], 2))
        self.assertEqual(module().patterns[3].cells, module().patterns[2].cells)
        self.assertTrue(editor.move_order(-1))
        self.assertEqual((module().orders, window.current_order), ([0, 3, 2, 1, 0], 1))
        self.assertTrue(editor.move_order(1))
        self.assertEqual(module().orders, [0, 2, 3, 1, 0])
        self.assertTrue(editor.remove_order())
        self.assertEqual(module().orders, [0, 2, 1, 0])
        self.assertEqual(len(module().patterns), 3)  # the trailing unused pattern went with it
        self.assertTrue(editor.rename_pattern("Bridge"))
        self.assertEqual(module().patterns[module().orders[window.current_order]].name, "Bridge")
        self.assertIn("Bridge", window.orders.currentText())
        for _ in range(6):
            window.undo()
        self.assertEqual(module().orders, [0, 1, 0])
        self.assertEqual(len(module().patterns), 2)
        self.assertFalse(window.document.dirty)

    def test_order_editor_guards_and_button_states(self):
        window, editor = self.window, self.window.order_editor
        window.orders.setCurrentIndex(0)
        self.assertFalse(editor.buttons["up"].isEnabled())
        self.assertTrue(editor.buttons["down"].isEnabled())
        window.orders.setCurrentIndex(2)
        self.assertFalse(editor.buttons["down"].isEnabled())
        self.assertFalse(editor.move_order(1))
        self.patch([{"op": "set_orders", "orders": [0]}, {"op": "remove_pattern", "pattern": 1}])
        self.assertFalse(editor.buttons["remove"].isEnabled())
        self.assertFalse(editor.remove_order())
        self.assertEqual(window.document.module.orders, [0])

    def test_edit_controls_have_french_text_and_settings_persist(self):
        window = self.window
        window.set_language("fr")
        self.assertEqual(window.edit_button.text(), "Mode saisie")
        self.assertEqual(window.order_editor.buttons["duplicate"].text(), "Dupliquer")
        self.assertEqual(window.keyboard_combo.itemText(0), "Auto")
        window.set_language("en")
        window.keyboard_combo.setCurrentIndex(window.keyboard_combo.findData("azerty"))
        window.edit_octave.setValue(3)
        window.edit_step.setValue(4)
        window.close()
        state = AppState(self.directory / "state")
        self.assertEqual((state.values["keyboard"], state.values["edit_octave"], state.values["edit_step"]), ("azerty", 3, 4))
        state.values.update(keyboard="dvorak", edit_octave=99, edit_step="x")
        state.save()
        self.open_window(configure=False)
        self.assertEqual((self.window.keyboard_combo.currentData(), self.window.edit_octave.value(), self.window.edit_step.value()),
                         ("auto", 2, 1))

    # --- overlays and highlights -----------------------------------------------------
    def test_overlay_and_flash_never_modify_the_document(self):
        window, model = self.window, self.model
        self.block_song()
        original, counter = fingerprint(window.document.module), window.document.revision
        proposal = Document(window.document.module)
        proposal.patch([{"op": "set", "pattern": 0, "row": 0, "channel": 0, "cell": "F-3 02 C30"}], "Proposal")
        self.assertEqual(model.data(model.index(0, 0)), "C-2")
        model.set_overlay(proposal.module)
        self.assertEqual(model.data(model.index(0, 0)), "F-3")
        self.assertEqual(model.data(model.index(0, 2)), "C30")
        self.assertEqual(model.data(model.index(0, 0), Qt.ItemDataRole.EditRole), "C-2")
        self.assertEqual(model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole).name(), THEMES[window.theme]["proposal"])
        self.assertEqual(model.data(model.index(1, 0)), "D-2")  # unchanged cells show the document
        self.assertIsNone(model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole))
        model.set_overlay(None)
        self.assertEqual(model.data(model.index(0, 0)), "C-2")
        model.flash([{"pattern": 0, "row": 1, "channel": 0, "before": "", "after": ""}, (0, 2, 1), (3, 0)], "human_change", 80)
        self.assertEqual(set(model.flashed()), {(0, 1, 0), (0, 2, 1), (0, 3, 0)})
        self.assertEqual(model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole).name(), THEMES[window.theme]["human_change"])
        self.wait_until(lambda: not model.flashed(), 3)
        self.assertIsNone(model.data(model.index(1, 0), Qt.ItemDataRole.BackgroundRole))
        self.assertEqual((fingerprint(window.document.module), window.document.revision), (original, counter))
        for theme in THEMES:
            window.set_theme(theme)
            model.flash([(0, 0, 0)], "agent_change")
            self.assertEqual(model.data(model.index(0, 0), Qt.ItemDataRole.BackgroundRole).name(), THEMES[theme]["agent_change"])
        model.clear_flashes()
        self.assertFalse(model.flashed())

    def test_center_column_keeps_a_gap_from_the_library_and_the_tracker_never_scrolls_sideways(self):
        window = self.window
        panel = window.library.parentWidget()
        for width, height in ((1080, 710), (1420, 900)):
            window.resize(width, height)
            for theme in THEMES:
                for language in ("en", "fr"):
                    window.set_theme(theme)
                    window.set_language(language)
                    self.app.processEvents()
                    label = (width, theme, language)
                    panel_edge = window.library.mapTo(window, window.library.rect().topRight()).x()
                    for widget in (window.table, window.sample_tabs, window.orders):
                        left = widget.mapTo(window, widget.rect().topLeft()).x()
                        self.assertGreaterEqual(left - panel_edge, 18, (label, widget.objectName()))  # 10 + divider + 10
                    self.assertEqual(window.table.mapTo(window, window.table.rect().topLeft()).x(),
                                     window.sample_tabs.mapTo(window, window.sample_tabs.rect().topLeft()).x(), label)
                    self.assertEqual(window.table.horizontalScrollBar().maximum(), 0, label)
                    self.assertLess(window.table.columnViewportPosition(11), window.table.viewport().width(), label)
        self.assertIsNotNone(panel)

    def test_block_selection_survives_refresh_and_pattern_edits(self):
        self.block_song()
        self.table.select_block(1, 3, 0, 2)
        self.window.refresh_document()
        self.assertEqual(self.table.selection_block(), (1, 3, 0, 2))

    # --- live reload -----------------------------------------------------------------
    def test_external_save_reloads_in_place_and_flashes_changed_cells(self):
        window = self.window
        window.orders.setCurrentIndex(1)
        window.follow.setChecked(False)
        self.go(9, 4)
        revision = window.document.revision
        theirs = self.agent_saves([{"op": "set", "pattern": 1, "row": 5, "channel": 2, "cell": "G-2 03 ..."}])
        self.wait_until(lambda: window.document.module.patterns[1].get(5, 2).note == "G-2")
        self.assertEqual(fingerprint(window.document.module), fingerprint(theirs))
        self.assertFalse(window.document.dirty)
        self.assertGreater(window.document.revision, revision)
        self.assertEqual(window.current_order, 1)
        self.assertEqual((self.table.currentIndex().row(), self.table.currentIndex().column()), (9, 4))
        self.assertEqual(set(self.model.flashed()), {(1, 5, 2)})
        self.assertIn("agent", window.statusBar().currentMessage().lower())
        window.undo()  # the agent's change can be undone, leaving local state different from disk
        self.assertEqual(window.document.module.patterns[1].get(5, 2), cell())
        self.assertTrue(window.document.dirty)
        window.redo()
        self.assertFalse(window.document.dirty)

    def test_own_saves_are_ignored(self):
        window = self.window
        self.patch([{"op": "set", "pattern": 0, "row": 0, "channel": 0, "cell": "C-2 01 ..."}], "Local")
        revision = window.document.revision
        window.save_project()
        self.assertFalse(window.document.dirty)
        self.assertEqual(window.sync.check(), "unchanged")
        deadline = time.monotonic() + 1.8  # a watcher event for our own write must not reload anything
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertEqual(window.document.revision, revision)
        self.assertFalse(self.model.flashed())

    def test_unsaved_edits_are_merged_with_agent_changes_and_conflicts_reported(self):
        window = self.window
        self.patch([{"op": "set", "pattern": 0, "row": 0, "channel": 0, "cell": "C-2 01 ..."},
                    {"op": "set", "pattern": 0, "row": 3, "channel": 3, "cell": "A-2 02 ..."}], "Mine")
        mine = fingerprint(window.document.module)
        self.assertTrue(window.document.dirty)
        self.agent_saves([{"op": "set", "pattern": 0, "row": 0, "channel": 0, "cell": "E-2 03 ..."},
                          {"op": "set", "pattern": 0, "row": 7, "channel": 1, "cell": "G-2 03 ..."}])
        self.wait_until(lambda: window.document.module.patterns[0].get(7, 1).note == "G-2")
        module = window.document.module
        self.assertEqual(module.patterns[0].get(0, 0).note, "E-2")  # conflict: the agent's version is kept
        self.assertEqual(module.patterns[0].get(3, 3).note, "A-2")  # my other edit survives
        self.assertTrue(window.document.dirty)
        self.assertEqual(set(self.model.flashed()), {(0, 0, 0), (0, 7, 1)})
        self.assertRegex(window.statusBar().currentMessage(), "1 conflicts")
        self.assertIn("P00 r00 ch1", window.statusBar().currentMessage())
        window.undo()  # a single transaction restores my version
        self.assertEqual(fingerprint(window.document.module), mine)

    def test_merge_without_conflict_and_playback_state_survive_reload(self):
        window = self.window
        self.patch([{"op": "set", "pattern": 0, "row": 1, "channel": 0, "cell": "C-2 01 ..."}], "Mine")
        self.agent_saves([{"op": "set", "pattern": 0, "row": 2, "channel": 0, "cell": "D-2 01 ..."}])
        self.wait_until(lambda: window.document.module.patterns[0].get(2, 0).note == "D-2")
        self.assertEqual(window.document.module.patterns[0].get(1, 0).note, "C-2")
        self.assertNotIn("conflict", window.statusBar().currentMessage())
        self.wait_until(lambda: window._audio_ready and not window._loading_audio)

    def test_half_written_file_is_reported_and_retried_when_it_changes(self):
        window = self.window
        good = self.path.read_bytes()
        self.path.write_bytes(good[:40])
        self.assertEqual(window.sync.check(), "error")
        self.assertEqual(window.sync.check(), "error")
        self.assertEqual(window.document.module.title, "Editing")
        agent = Document(song())
        agent.rename("Whole again")
        agent.save_project(self.path)
        self.assertEqual(window.sync.check(), "reload")
        self.assertEqual(window.document.module.title, "Whole again")

    def test_f5_still_reopens_the_file(self):
        window = self.window
        agent = Document.open(self.path)
        agent.rename("Agent title")
        agent.save_project(self.path)
        window.reload_document()
        self.assertEqual(window.document.module.title, "Agent title")


if __name__ == "__main__":
    unittest.main()
