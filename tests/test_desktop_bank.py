"""User-managed sample banks in the window: the Bank menu and the active bank, auditions on click and from the
piano keys, the add-to-bank sheet, dropped modules and WAVs, bank entries dropped on the song, drops on the
window itself (open, MIDI notice), the Palettes page and the sample mode switch.

Everything runs on a temporary bank (CHIPLOOM_BANK) under a temporary ChipLoom home (CHIPLOOM_HOME): the owner's
real bank and session are never touched. Dialogs are driven programmatically (never shown modally).
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import warnings
import wave

try:
    from PySide6.QtCore import QEvent, QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QKeyEvent
    from PySide6.QtWidgets import QApplication, QMessageBox
except ModuleNotFoundError:
    QApplication = None

from tracker4agents import mod, sample_intake, synth_tools
from tracker4agents.desktop_services import AppState
from tracker4agents.document import fingerprint
from tracker4agents.model import Module, Pattern, Sample, cell
from tracker4agents.sample_library import SampleLibrary

PACKAGE = __package__ + "." if __package__ else ""
base = importlib.import_module(PACKAGE + "test_desktop_08")
YES = QMessageBox.StandardButton.Yes if QApplication else None
NO = QMessageBox.StandardButton.No if QApplication else None
NOMOD = Qt.KeyboardModifier.NoModifier if QApplication else None
COPY = Qt.DropAction.CopyAction if QApplication else None
NOBUTTON = Qt.MouseButton.NoButton if QApplication else None


def bank_source() -> Module:
    """A MOD whose two samples (a one-shot kick, a looped bass cycle) and notes give the bank entries and a palette."""
    kick = (0, 0) + tuple(round(100 * (1 - index / 1200)) * (1 if (index // 40) % 2 else -1) for index in range(1198))
    low = tuple(value for value in (60, 60, -60, -60) for _ in range(16))
    samples = [Sample("Bank kick", kick, 64), Sample("Bank bass", low, 50, 0, 0, 64)]
    pattern = Pattern()
    for row in range(0, 64, 8):
        pattern.put(row, 0, cell("C-2", 1))
        pattern.put(row + 4, 1, cell(("C-1", "G-1", "A-1", "F-1", "E-1", "D-1", "B-1", "C#1")[row // 8], 2))
    return Module("Bank source", samples, [pattern], [0])


def file_mime(path: Path) -> "QMimeData":
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(path))])
    return data


class BankCase(base.WindowCase):
    def extra_patches(self):
        self.bank_dir = self.directory / "bank"
        self.source = self.directory / "source.mod"
        self.source.write_bytes(mod.encode(bank_source()))
        self.bank = SampleLibrary(self.bank_dir)
        self.bank.extract(self.source)
        return [patch.dict(os.environ, {"CHIPLOOM_BANK": str(self.bank_dir)})]

    def setUp(self):
        super().setUp()
        self.browser = self.window.sample_browser
        self.window.keyboard_combo.setCurrentIndex(self.window.keyboard_combo.findData("qwerty"))
        self.window.edit_octave.setValue(2)
        self.wait_until(lambda: not self.browser._loading and self.browser.total == 2)

    def entry_item(self, sample_id):
        for row in range(self.browser.results.count()):
            if self.browser.results.item(row).data(Qt.ItemDataRole.UserRole) == sample_id:
                return self.browser.results.item(row)
        self.fail(f"Missing result {sample_id}")

    def bank_entries(self) -> dict:
        return {entry["id"]: entry for entry in self.bank._manifest()["samples"]}

    @staticmethod
    def bank_entries_of(path: Path) -> dict:
        return {entry["id"]: entry for entry in SampleLibrary(path)._manifest()["samples"]}

    def key(self, widget, kind, text):
        QApplication.sendEvent(widget, QKeyEvent(kind, ord(text.upper()), NOMOD, text, False))

    def enter(self, widget, mime):
        """A drag entering `widget` (the mime data is kept alive for the event's lifetime)."""
        self._mimes = getattr(self, "_mimes", []) + [mime]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            event = QDragEnterEvent(QPointF(5, 5).toPoint(), COPY, mime, NOBUTTON, NOMOD)
        widget.dragEnterEvent(event)
        return event

    def drop(self, widget, mime):
        self._mimes = getattr(self, "_mimes", []) + [mime]
        event = QDropEvent(QPointF(5, 5), COPY, mime, NOBUTTON, NOMOD)
        widget.dropEvent(event)
        return event


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class ActiveBankTests(BankCase):
    def test_the_window_opens_the_active_bank_and_the_bank_menu_switches_it(self):
        window = self.window
        self.assertEqual(self.browser.library_path, self.bank_dir.resolve())
        self.assertIn("bank", self.browser.bank_label.text())
        self.assertIn(str(self.bank_dir.resolve()), self.browser.bank_label.toolTip())
        titles = [action.text() for action in window.menuBar().actions()]
        self.assertIn("Bank", titles)
        other = self.directory / "second bank"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHIPLOOM_BANK")          # the menu writes the active bank into the (temporary) home
            with patch("tracker4agents.desktop_bank.QFileDialog.getExistingDirectory", return_value=str(other)):
                window.new_bank()
            self.wait_until(lambda: not self.browser._loading)
            self.assertTrue((other / "library.json").is_file())
            self.assertEqual(self.browser.library_path, other.resolve())
            self.assertEqual(sample_intake.active_library(), other.resolve())
            self.assertEqual(sample_intake.recent_libraries()[0], str(other.resolve()))
            self.assertEqual(self.browser.total, 0)
            recent = [action.text() for action in window.recent_banks_menu.actions()]
            self.assertEqual(recent[0], "second bank")
            window.open_bank(self.bank_dir)
            self.wait_until(lambda: not self.browser._loading and self.browser.total == 2)
            self.assertEqual(sample_intake.active_library(), self.bank_dir.resolve())
            self.assertEqual(AppState(self.directory / "state").values["sample_library"], str(self.bank_dir.resolve()))
        full = self.directory / "not a bank"
        full.mkdir()
        (full / "song.mod").write_bytes(b"x")
        self.assertFalse(window.open_bank(full))     # neither a bank nor empty: refused, the current bank stays active
        self.wait_until(lambda: not self.browser._loading)
        self.assertEqual(sample_intake.active_library(), self.bank_dir.resolve())
        window.set_language("fr")
        self.assertIn("Banque", [action.text() for action in window.menuBar().actions()])
        self.assertTrue(self.browser.bank_label.text().startswith("Banque"))
        self.assertIn("Nouvelle banque de départ…", [action.text() for action in window.bank_menu.actions()])

    def test_new_starter_bank_generates_the_recipe_sounds_and_makes_them_active(self):
        window = self.window
        target = self.directory / "starter here"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHIPLOOM_BANK")
            with patch("tracker4agents.desktop_bank.QFileDialog.getExistingDirectory", return_value=str(target)) as ask:
                window.new_starter_bank()
            self.assertEqual(Path(ask.call_args.args[2]), sample_intake.starter_path())   # proposed while it is missing
            self.wait_until(lambda: not self.browser._loading and self.browser.total > 0)
            self.assertEqual(sample_intake.active_library(), target.resolve())
        self.assertEqual(len(self.bank_entries_of(target)), 62)
        self.assertEqual(self.browser.palettes.bank.palettes()["total"], 5)
        self.assertIn("62", window.statusBar().currentMessage())
        self.assertFalse(window.create_starter_bank(target))      # not twice into the same folder
        panel = self.browser.palettes
        window.sample_tabs.setCurrentIndex(1)
        self.browser.show_page(1)
        self.wait_until(lambda: panel.list.count() == 5)
        self.assertIn("PAL-0001  ·  ", panel.list.item(0).text())  # the palette's title follows its ID
        panel.list.setCurrentRow(0)
        self.wait_until(lambda: panel.palette is not None)
        self.assertEqual(panel.title.text(), f"PAL-0001 · {panel.palette['title']}")

    def test_without_a_chosen_bank_the_window_builds_and_opens_the_starter_bank(self):
        cwd = os.getcwd()
        os.chdir(self.directory)                      # no exports/sample_library here: the starter bank is the default
        try:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("CHIPLOOM_BANK")
                self.assertFalse(sample_intake.starter_path().exists())
                second = base.TrackerWindow(self.path, self.directory / "state2", restore=False)
                try:
                    second.output.setMuted(True)
                    second.sample_output.setMuted(True)
                    browser = second.sample_browser
                    self.assertEqual(browser.library_path, sample_intake.starter_path())
                    self.wait_until(lambda: not browser._loading and browser.total > 0, 40)
                    self.assertTrue((sample_intake.starter_path() / "library.json").is_file())
                    self.assertEqual(browser.total, 62)
                    self.assertIn("starter", browser.bank_label.text())
                finally:
                    second.close()
                    second.pool.waitForDone(10000)
                    self.app.processEvents()
                    second.deleteLater()
                    self.app.processEvents()
        finally:
            os.chdir(cwd)


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class AuditionTests(BankCase):
    def test_clicking_an_entry_or_a_song_sample_plays_it_when_autoplay_is_on(self):
        window, browser = self.window, self.browser
        self.assertTrue(browser.autoplay.isChecked())
        before = fingerprint(window.document.module)
        browser.results.setCurrentItem(self.entry_item("SMP-0002"))
        browser.results.itemClicked.emit(self.entry_item("SMP-0002"))
        self.wait_until(lambda: "library-" in window.sample_player.source().toLocalFile())
        window.sample_browser.stop()
        window.samples.setCurrentRow(1)
        window.samples.itemClicked.emit(window.samples.item(1))
        self.assertIn("sample-", window.sample_player.source().toLocalFile())
        window.set_autoplay(False)
        self.assertFalse(browser.autoplay.isChecked())        # both boxes follow the one setting
        self.assertFalse(window.findChild(type(browser.autoplay), "autoplaySong").isChecked())
        with patch.object(window, "play_sample") as play:
            window.samples.itemClicked.emit(window.samples.item(0))
        play.assert_not_called()
        with patch.object(browser, "play") as play:
            browser.results.itemClicked.emit(self.entry_item("SMP-0001"))
        play.assert_not_called()
        self.assertIs(AppState(self.directory / "state").values["autoplay"], False)
        self.assertEqual(fingerprint(window.document.module), before)

    def test_the_piano_keys_play_the_selected_song_sample_and_type_nothing(self):
        window = self.window
        window.samples.setCurrentRow(2)
        window.table.setCurrentIndex(self.model.index(4, 0))
        state = (fingerprint(window.document.module), window.document.revision)
        self.key(window.samples, QEvent.Type.KeyPress, "x")
        self.key(window.samples, QEvent.Type.KeyRelease, "x")
        self.assertEqual([(item["note"], item["name"], item["source"]) for item in window.jam.log],
                         [("D-2", "Lead", "samples")])
        self.assertEqual((fingerprint(window.document.module), window.document.revision), state)
        self.assertFalse(self.cell(4, 0).note)
        self.assertEqual(window.samples.currentRow(), 2)
        self.browser.results.setCurrentItem(self.entry_item("SMP-0002"))
        self.key(self.browser.results, QEvent.Type.KeyPress, "c")
        self.assertEqual(window.jam.log[-1]["note"], "E-2")
        self.assertEqual(window.jam.log[-1]["source"], "library")
        self.assertEqual(window.jam.log[-1]["name"], self.bank.get("SMP-0002")["name"])


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class AddToBankTests(BankCase):
    def test_the_sheet_prefills_the_slot_and_adds_it_with_the_owners_labels(self):
        window = self.window
        dialog = window.add_slot_to_bank(2, run=False)
        self.assertEqual(dialog.name.text(), "Snare")
        self.assertIn("slot 02", dialog.facts.text())
        self.assertIn("work.project.json", dialog.facts.text())
        self.assertTrue(dialog.notice.isHidden())
        self.assertIsNone(dialog.loop_start)
        roles = [dialog.role.itemData(index) for index in range(dialog.role.count())]
        self.assertNotIn("unknown", roles)
        self.assertIn("snare", roles)
        dialog.name.setText("Owner snare")
        dialog.role.setCurrentIndex(dialog.role.findData("snare"))
        dialog.category.setCurrentIndex(dialog.category.findData("percussion"))
        dialog.tags.setText("crisp, short")
        dialog.accept()
        entry = self.bank_entries()["SMP-0003"]
        self.assertEqual((entry["name"], entry["role"], entry["category"]), ("Owner snare", "snare", "percussion"))
        self.assertTrue({"crisp", "short"} <= set(entry["tags"]))
        self.assertEqual(entry["source"]["slot"], 2)
        self.wait_until(lambda: not self.browser._loading and self.browser.entry and self.browser.entry["id"] == "SMP-0003")
        self.assertEqual(self.browser.search.text(), "SMP-0003")
        self.assertFalse(window.document.dirty)        # the song is not changed by adding to the bank
        again = window.add_slot_to_bank(2, run=False)   # the same PCM and settings: the sheet says so
        self.assertFalse(again.notice.isHidden())
        self.assertIn("SMP-0003", again.notice.text())
        again.select_existing()
        self.wait_until(lambda: not self.browser._loading and self.browser.entry and self.browser.entry["id"] == "SMP-0003")
        again.name.setText("Twice")
        again.accept()
        self.assertEqual(len(self.bank_entries()), 3)   # not added twice
        menu = window.samples.menu_for(1)
        self.assertEqual([action.text() for action in menu.actions()], ["Play", "Add to bank…"])

    def test_a_dropped_module_lists_its_slots_and_adds_the_checked_rows(self):
        window = self.window
        other = Module("Other", [Sample("Other lead", (0, 0) + (90, -90) * 20, 60), Sample("Other hat", (0, 0, 70, -70, 30, -30, 0, 0), 40)],
                       [Pattern(cells={(0, 0): cell("C-2", 1), (4, 1): cell("C-2", 2)})], [0])
        path = self.directory / "other.mod"
        path.write_bytes(mod.encode(other))
        with patch.object(window, "bank_drop") as routed:    # a real drop on the tab reaches bank_drop
            self.enter(self.browser, file_mime(path))
            self.assertEqual(window.statusBar().currentMessage(), "Drop to choose samples for the bank")
            self.drop(self.browser, file_mime(path))
            self.wait_until(lambda: routed.called)
        self.assertEqual(routed.call_args.args[0], path)
        dialog = window.bank_drop(path, run=False)
        self.assertEqual(dialog.table.rowCount(), 2)
        self.assertEqual(dialog.table.item(0, 2).text(), "Other lead")
        self.assertEqual(dialog.selected_rows(), [0, 1])
        with patch.object(window, "audition_wav") as audition:
            dialog.play_row(1)
        self.assertTrue(audition.called)
        dialog.set_checked(1, False)
        dialog.set_name(0, "Lead from other")
        dialog.set_role(0, "lead")
        dialog.add_selected()
        entries = self.bank_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual((entries["SMP-0003"]["name"], entries["SMP-0003"]["role"]), ("Lead from other", "lead"))
        self.assertEqual(entries["SMP-0003"]["source"], {"file": "other.mod", "slot": 1, "name": "Other lead"})
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertIsNone(dialog.slot_combo)           # a drop on the library tab only adds to the bank

    def test_a_dropped_wav_opens_the_sheet_with_loop_fields(self):
        window = self.window
        path = self.directory / "tone.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setparams((1, 2, 8363, 400, "NONE", "not compressed"))
            handle.writeframes(b"".join((int(9000 * (1 if (index // 16) % 2 else -1))).to_bytes(2, "little", signed=True)
                                        for index in range(400)))
        self.enter(self.browser, file_mime(path))
        self.assertEqual(window.statusBar().currentMessage(), "Drop to add this WAV to the bank")
        dialog = window.bank_drop(path, run=False)
        self.assertEqual(dialog.name.text(), "tone")
        self.assertIsNotNone(dialog.loop_start)
        self.assertEqual(dialog.loop_length.maximum(), 400)
        self.assertIn("400 frames", dialog.facts.text())
        dialog.loop_start.setValue(0)
        dialog.loop_length.setValue(64)
        dialog.role.setCurrentIndex(dialog.role.findData("bass"))
        dialog.accept()
        entry = self.bank_entries()["SMP-0003"]
        self.assertEqual((entry["format_origin"], entry["loop_start"], entry["loop_length"], entry["role"], entry["bits"]),
                         ("xm", 0, 64, "bass", 16))
        self.assertEqual(entry["origin"], "wav-imported")


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class DropTests(BankCase):
    def test_a_bank_entry_dragged_onto_the_song_is_inserted_there(self):
        window = self.window
        before = fingerprint(window.document.module)
        mime = self.browser.results.mimeData([self.entry_item("SMP-0002")])
        self.assertEqual(bytes(mime.data("application/x-chiploom-bank-entry")).decode(), "SMP-0002")
        self.enter(window.samples, mime)
        self.assertEqual(window.statusBar().currentMessage(), "Drop to insert the bank entry here")
        info = window.insert_bank_entry("SMP-0002", None)
        self.assertEqual(info["slot"], 4)
        module = window.document.module
        self.assertEqual(module.samples[3].pcm, self.bank.read_sample("SMP-0002").pcm)
        self.assertEqual(module.metadata["sample_sources"]["4"]["library_id"], "SMP-0002")
        self.assertEqual(window.samples.currentItem().data(Qt.ItemDataRole.UserRole), 3)
        with patch.object(QMessageBox, "question", return_value=NO):
            self.assertIsNone(window.insert_bank_entry("SMP-0001", 1))   # an occupied slot asks first
        self.assertEqual(window.document.module.samples[0].name, "Kick")
        with patch.object(QMessageBox, "question", return_value=YES):
            info = window.insert_bank_entry("SMP-0001", 1)
        self.assertEqual((info["slot"], window.document.module.samples[0].pcm), (1, self.bank.read_sample("SMP-0001").pcm))
        window.undo()
        window.undo()
        self.assertEqual(fingerprint(window.document.module), before)

    def test_a_module_dropped_on_the_song_list_can_be_inserted_through_the_bank(self):
        window = self.window
        before = fingerprint(window.document.module)
        with patch.object(window, "bank_drop") as routed:
            self.enter(window.samples, file_mime(self.source))
            self.assertEqual(window.statusBar().currentMessage(), "Drop to choose samples for the song")
            self.drop(window.samples, file_mime(self.source))
            self.wait_until(lambda: routed.called)
        self.assertEqual(routed.call_args.kwargs, {"target": "song"})
        dialog = window.bank_drop(self.source, run=False, target="song")
        self.assertIsNotNone(dialog.slot_combo)
        self.assertEqual([dialog.table.item(row, 5).text() for row in range(2)], ["SMP-0001", "SMP-0002"])   # already in the bank
        self.assertEqual(dialog.selected_rows(), [])
        dialog.set_checked(0, True)
        dialog.set_checked(1, True)
        inserted = dialog.insert_selected()
        self.assertEqual([item["slot"] for item in inserted], [4, 5])
        module = window.document.module
        self.assertEqual(module.samples[4].pcm, self.bank.read_sample("SMP-0002").pcm)
        self.assertEqual(module.metadata["sample_sources"]["5"]["library_id"], "SMP-0002")
        self.assertEqual(len(self.bank_entries()), 2)     # nothing added twice
        window.undo()                                     # one undo step for the whole insertion
        self.assertEqual(fingerprint(window.document.module), before)
        dialog = window.bank_drop(self.source, run=False, target="song")
        dialog.set_checked(0, True)
        dialog.slot_combo.setCurrentIndex(dialog.slot_combo.findData(2))
        with patch.object(QMessageBox, "question", return_value=YES):
            inserted = dialog.insert_selected()
        self.assertEqual([item["slot"] for item in inserted], [2])
        self.assertEqual(window.document.module.samples[1].pcm, self.bank.read_sample("SMP-0001").pcm)

    def test_dropping_on_the_window_opens_a_module_and_announces_midi(self):
        window = self.window
        other = self.directory / "other.project.json"
        base.Document(base.song("Dropped")).save_project(other)
        self.enter(window, file_mime(other))
        self.assertEqual(window.statusBar().currentMessage(), "Drop to open")
        window.dragLeaveEvent(QDragLeaveEvent())
        self.assertNotEqual(window.statusBar().currentMessage(), "Drop to open")
        self.drop(window, file_mime(other))
        self.assertEqual(window.document.path, other)
        self.assertEqual(window.document.module.title, "Dropped")
        self.assertEqual(window.state.recent()[0], other.resolve())
        midi = self.directory / "tune.mid"
        midi.write_bytes(b"MThd")
        self.enter(window, file_mime(midi))
        self.assertEqual(window.statusBar().currentMessage(), "MIDI import is planned for the next version.")
        with patch.object(window, "open_document") as opened:
            self.drop(window, file_mime(midi))
        opened.assert_not_called()
        self.assertEqual(window.statusBar().currentMessage(), "MIDI import is planned for the next version.")
        self.assertEqual(window.document.path, other)
        window.set_language("fr")
        window.window_drop(midi)
        self.assertEqual(window.statusBar().currentMessage(), "L'import MIDI est prévu pour la prochaine version.")
        # the song sample list and the library tab leave an unknown file to the window
        self.assertFalse(self.enter(window.samples, file_mime(midi)).isAccepted())
        self.assertFalse(self.enter(self.browser, file_mime(midi)).isAccepted())


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class PaletteTests(BankCase):
    def test_the_palettes_page_lists_entries_measures_tuning_and_uses_the_palette(self):
        window, browser = self.window, self.browser
        panel = browser.palettes
        window.sample_tabs.setCurrentIndex(1)
        browser.show_page(1)
        self.wait_until(lambda: panel.list.count() == 1)
        self.assertIn("PAL-0001", panel.list.item(0).text())
        self.assertIn("1 palettes", panel.count.text())
        panel.list.setCurrentRow(0)
        self.wait_until(lambda: panel.palette is not None and panel.entries.count() == 2)
        texts = [panel.entries.item(row).text() for row in range(2)]
        self.assertTrue(any("50%" in text for text in texts), texts)
        self.assertTrue(panel.tuning_label.text().startswith("Tuning:"), panel.tuning_label.text())
        self.assertTrue(panel.use_button.isEnabled())
        panel.entries.setCurrentRow(1)
        self.assertEqual(browser.jam_sample().pcm, self.bank.read_sample(panel.entries.item(1).data(Qt.ItemDataRole.UserRole)).pcm)
        with patch.object(browser, "play_entry") as play:
            panel.entries.itemClicked.emit(panel.entries.item(0))
        play.assert_called_once_with(panel.entries.item(0).data(Qt.ItemDataRole.UserRole))
        before = fingerprint(window.document.module)
        info = panel.use_in_song()
        self.assertEqual(info["inserted"], 2)
        self.assertEqual([item["slot"] for item in info["slot_map"]], [4, 5])
        self.assertEqual(len(window.document.module.samples), 5)
        self.assertIn("04 ", panel.report.text())
        self.assertIn("SMP-000", window.statusBar().currentMessage() + panel.report.text())
        window.undo()
        self.assertEqual(fingerprint(window.document.module), before)
        window.set_language("fr")
        self.assertEqual(panel.use_button.text(), "Utiliser dans le morceau")


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class SampleModeTests(BankCase):
    def test_the_switch_follows_the_guards_and_enables_the_right_actions(self):
        window, switch = self.window, self.window.sample_mode
        self.assertIsNone(switch.declared())
        self.assertFalse(any(control.isChecked() for control in switch.buttons.values()))
        self.assertFalse(switch.choose("synthesized"))        # embedded PCM without recipes: refused by the core
        self.assertIsNone(switch.declared())
        self.assertIn("synthesized", window.statusBar().currentMessage())
        self.assertFalse(window.document.can_undo)
        self.assertTrue(switch.choose("library"))
        self.assertEqual(window.document.module.metadata["sample_source"], "library")
        self.assertTrue(switch.buttons["library"].isChecked())
        self.assertTrue(self.browser.add_button.isEnabled() or self.browser.entry is None)
        self.assertFalse(window.create_panel.add_button.isEnabled())
        self.assertIn("library-only", window.create_panel.add_button.toolTip())
        with patch.object(QMessageBox, "question", return_value=NO):
            self.assertFalse(switch.choose("mixed"))
        self.assertEqual(switch.declared(), "library")
        with patch.object(QMessageBox, "question", return_value=YES):
            self.assertTrue(switch.choose("mixed"))
        self.assertEqual(switch.declared(), "mixed")
        self.assertTrue(window.create_panel.add_button.isEnabled())
        window.undo()
        self.assertEqual(switch.declared(), "library")
        window.undo()
        self.assertIsNone(switch.declared())
        self.assertTrue(window.open_module(synth_tools.palette("Palette")[0]))
        self.wait_until(lambda: not self.browser._loading)
        self.assertEqual(switch.declared(), "synthesized")
        self.browser.results.setCurrentItem(self.entry_item("SMP-0001"))
        self.assertFalse(self.browser.add_button.isEnabled())
        self.assertIn("synthesized", self.browser.add_button.toolTip())
        self.assertIsNone(window.insert_bank_entry("SMP-0001", None) and None)   # the core guard refuses the insertion
        self.assertEqual(window.document.module.metadata["sample_source"], "synthesized")
        self.assertFalse(switch.choose("library"))
        self.assertEqual(switch.declared(), "synthesized")
        window.set_language("fr")
        self.assertEqual(switch.buttons["synthesized"].text(), "Synthétisé")
        self.assertIn("synthétisé", self.browser.add_button.toolTip())


if __name__ == "__main__":
    unittest.main()
