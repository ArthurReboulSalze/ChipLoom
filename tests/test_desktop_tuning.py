"""The Tuning page of the Song samples tab: fine tune, relative note (XM), transposing a slot's notes (MOD),
the measured tuning line and saving a slot's tuning to its bank entry. Runs on a temporary bank and home."""
from __future__ import annotations

import importlib
import shutil
import unittest

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:
    QApplication = None

from tracker4agents import convert
from tracker4agents.desktop_tuning import retune_between, transpose_slot_notes
from tracker4agents.document import fingerprint
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell

PACKAGE = __package__ + "." if __package__ else ""
base = importlib.import_module(PACKAGE + "test_desktop_08")
bank_tests = importlib.import_module(PACKAGE + "test_desktop_bank")


class TuningCase(bank_tests.BankCase):
    def setUp(self):
        super().setUp()
        self.workshop = self.window.sample_workshop
        self.panel = self.workshop.tuning
        self.workshop.show_page(2)

    def select(self, slot: int):
        self.window.samples.setCurrentRow(slot - 1)
        self.app.processEvents()

    def human_labels(self) -> list[str]:
        return [entry["label"] for entry in self.call("changes")["entries"] if entry["author"] == "human"]


class TransposeSlotNotesTests(unittest.TestCase):
    def test_only_the_notes_of_the_slot_move_and_the_range_is_checked(self):
        module = base.song()
        self.assertEqual(transpose_slot_notes(module, 1, 1), 3)
        self.assertEqual([module.patterns[0].get(0, 0).note, module.patterns[0].get(0, 1).note, module.patterns[0].get(8, 2).note],
                         ["C#2", "F-2", "G#2"])
        self.assertEqual(module.patterns[0].get(1, 0).note, "D-2")        # sample 2 is untouched
        self.assertEqual(module.patterns[0].get(0, 1).command, 0xC)        # effects stay
        self.assertEqual(transpose_slot_notes(module, 9, 12), 0)
        with self.assertRaises(ValidationError) as refused:
            transpose_slot_notes(module, 1, 24)
        self.assertEqual(refused.exception.code, "NOTE_RANGE")
        xm_song, _ = convert.mod_to_xm(base.song())
        self.assertEqual(transpose_slot_notes(xm_song, 3, -12), 1)
        self.assertEqual(xm_song.patterns[0].get(1, 1).note, "F-3")

    def test_retune_between_reads_playback_rates(self):
        entry = Sample("Entry", (0, 0, 60, -60), 64)
        found = retune_between(Sample("Slot", (0, 0, 60, -60), 64, 4), "mod", entry, "mod")   # ProTracker's +4 period
        self.assertEqual(found["semitones"], 0)
        self.assertLessEqual(abs(found["cents"] - 50), 1)
        xm_sample = convert.mod_sample_to_xm(entry)
        xm_sample.relative_note = 12
        found = retune_between(xm_sample, "xm", entry, "mod")
        self.assertEqual(found["semitones"], 12)
        self.assertLessEqual(abs(found["cents"]), 2)


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class ModTuningTests(TuningCase):
    def test_fine_tune_and_note_transposition_are_undoable_edits_the_live_session_sees(self):
        window, panel = self.window, self.panel
        self.select(1)
        self.assertEqual(panel.title.text(), "01 · Kick")
        self.assertTrue(panel.measured.text())
        self.assertEqual(panel.step_caption.text(), "Notes of this sample")
        self.assertEqual((panel.finetune.minimum(), panel.finetune.maximum()), (-8, 7))
        self.assertEqual(panel.bank_label.text(), "not from the bank")
        self.assertFalse(panel.save_button.isEnabled())
        before = fingerprint(window.document.module)
        panel.finetune.setValue(3)
        panel.apply_finetune()
        self.assertEqual(window.document.module.samples[0].finetune, 3)
        panel.step(1)
        pattern = window.document.module.patterns[0]
        self.assertEqual([pattern.get(0, 0).note, pattern.get(0, 1).note, pattern.get(8, 2).note], ["C#2", "F-2", "G#2"])
        self.assertEqual(pattern.get(1, 0).note, "D-2")
        self.assertIn("3 notes", window.statusBar().currentMessage())
        self.assertEqual(window.document.module.samples[0].finetune, 3)
        window.undo()
        self.assertEqual(window.document.module.patterns[0].get(0, 0).note, "C-2")
        window.undo()
        self.assertEqual(fingerprint(window.document.module), before)
        window.redo()
        window.redo()
        self.assertEqual(window.document.module.patterns[0].get(8, 2).note, "G#2")
        labels = self.human_labels()
        self.assertIn("Tune sample", labels)
        self.assertIn("Transpose sample notes", labels)

    def test_a_transposition_out_of_range_is_refused_and_changes_nothing(self):
        window, panel = self.window, self.panel
        self.select(1)
        panel.step(12)
        self.assertEqual(window.document.module.patterns[0].get(8, 2).note, "G-3")
        state = (fingerprint(window.document.module), window.document.revision)
        panel.step(12)
        self.assertEqual((fingerprint(window.document.module), window.document.revision), state)
        self.assertIn("B-3", window.statusBar().currentMessage())

    def test_saving_the_tuning_stores_the_difference_with_the_bank_entry(self):
        window, panel, browser = self.window, self.panel, self.browser
        info = browser.insert_entry("SMP-0002", None)
        self.assertEqual(info["slot"], 4)
        self.select(4)
        self.assertTrue(panel.bank_label.text().startswith("SMP-0002"))
        self.assertTrue(panel.save_button.isEnabled())
        panel.finetune.setValue(4)
        panel.apply_finetune()
        self.select(4)                                          # after an edit the list follows the cursor's cell again
        retune = panel.save_tuning()
        self.assertEqual(retune["semitones"], 0)
        self.assertLessEqual(abs(retune["cents"] - 50), 1)       # ProTracker's +4 period, not exactly 4/8 semitone
        self.assertEqual(self.bank.get("SMP-0002")["retune"], retune)
        text = f"{retune['cents']:+d} c"
        self.wait_until(lambda: not browser._loading and any(text in browser.results.item(row).text()
                                                              for row in range(browser.results.count())))
        self.assertIn(text, panel.bank_label.text())
        browser.insert_entry("SMP-0002", None)                 # the correction applies on the next insertion
        self.assertEqual(window.document.module.samples[4].finetune, 4)
        self.assertEqual(window.document.module.metadata["sample_sources"]["5"]["retune"]["cents"], retune["cents"])
        self.select(4)
        panel.finetune.setValue(0)
        panel.apply_finetune()
        self.select(4)
        self.assertEqual(panel.save_tuning(), {"semitones": 0, "cents": 0})
        self.assertIsNone(self.bank.get("SMP-0002")["retune"])


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class XmTuningTests(TuningCase):
    def setUp(self):
        super().setUp()
        song, _ = convert.mod_to_xm(base.song())
        self.assertTrue(self.window.open_module(song))
        self.wait_until(lambda: self.window._audio_ready and not self.browser._loading)
        self.workshop.show_page(2)

    def test_relative_note_steps_and_finetune_go_through_the_patch_path(self):
        window, panel = self.window, self.panel
        self.select(1)
        self.assertEqual(panel.step_caption.text(), "Relative note")
        self.assertEqual((panel.finetune.minimum(), panel.finetune.maximum()), (-128, 127))
        self.assertEqual(panel.step_value.text(), "+0")
        before = fingerprint(window.document.module)
        panel.step(12)
        panel.step(-1)
        self.assertEqual(window.document.module.samples[0].relative_note, 11)
        self.assertEqual(panel.step_value.text(), "+11")
        self.assertEqual(window.document.module.patterns[0].get(0, 0).note, "C-4")   # an XM keeps its notes
        panel.finetune.setValue(100)
        panel.apply_finetune()
        self.assertEqual(window.document.module.samples[0].finetune, 100)
        for _ in range(3):
            window.undo()
        self.assertEqual(fingerprint(window.document.module), before)
        self.assertIn("Tune sample", self.human_labels())
        window.set_language("fr")
        self.assertEqual(panel.step_caption.text(), "Note relative")

    def test_saving_an_xm_slot_records_whole_semitones(self):
        panel, browser = self.panel, self.browser
        info = browser.insert_entry("SMP-0001", None)
        self.select(info["slot"])
        panel.step(12)
        self.select(info["slot"])
        retune = panel.save_tuning()
        self.assertEqual(retune["semitones"], 12)
        self.assertLessEqual(abs(retune["cents"]), 2)
        self.assertEqual(self.bank.get("SMP-0001")["retune"]["semitones"], 12)
        self.wait_until(lambda: not browser._loading and any("+12 st" in browser.results.item(row).text()
                                                              for row in range(browser.results.count())))


class BuildSongTests(unittest.TestCase):
    def test_the_fixture_song_has_the_notes_the_tests_rely_on(self):
        module = Module("T", [Sample("A", (0, 0, 1, -1), 64)], [Pattern(cells={(0, 0): cell("C-2", 1)})], [0])
        self.assertEqual(transpose_slot_notes(module, 1, 2), 1)
        self.assertEqual(module.patterns[0].get(0, 0).note, "D-2")


if __name__ == "__main__":
    unittest.main()
