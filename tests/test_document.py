from __future__ import annotations

from array import array
import copy
from pathlib import Path
import tempfile
import unittest
import wave

from tracker4agents import demo, mod, project
from tracker4agents.desktop_services import AppState, AudioCache
from tracker4agents.document import Document, fingerprint, listening_copy
from tracker4agents.model import Cell, Module, Pattern, Sample, ValidationError, cell, playback_plan

ROOT = Path(__file__).resolve().parents[1]


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.document = Document(demo.create())

    def test_invalid_edit_is_atomic_and_does_not_change_history(self):
        before = fingerprint(self.document.module)
        with self.assertRaises(ValidationError):
            self.document.replace_cell(0, 0, 0, Cell(123, 1))
        self.assertEqual(fingerprint(self.document.module), before)
        self.assertFalse(self.document.dirty)
        self.assertFalse(self.document.can_undo)

    def test_undo_redo_and_branch_after_undo(self):
        document = self.document
        self.assertFalse(document.rename(document.module.title))
        document.rename("Edited")
        self.assertTrue(document.dirty)
        self.assertTrue(document.undo())
        self.assertFalse(document.dirty)
        self.assertTrue(document.redo())
        self.assertEqual(document.module.title, "Edited")
        document.undo()
        document.set_sample(0, 12, -4)
        self.assertFalse(document.can_redo)
        self.assertTrue(document.dirty)

    def test_load_demos_from_both_formats_and_export_identically(self):
        for stem in ("first_light", "pixel_rush"):
            binary = ROOT / f"exports/{stem}/{stem}.mod"
            document = Document.open(binary)
            self.assertEqual(mod.encode(document.module), binary.read_bytes())
            source = Document.open(ROOT / f"examples/{stem}.project.json")
            self.assertEqual(mod.encode(source.module), binary.read_bytes())

    def test_save_preserves_recipes_and_mod_export_does_not_mark_project_saved(self):
        document = self.document
        document.rename("Saved variant")
        document.set_sample(0, 22, 3)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            document.export_mod(directory / "variant.mod")
            self.assertTrue(document.dirty)
            self.assertEqual(mod.encode(mod.read(directory / "variant.mod")), mod.encode(document.module))
            document.save_project(directory / "variant.project.json")
            loaded = Document.open(directory / "variant.project.json")
            self.assertEqual(loaded.module, document.module)
            self.assertIsNotNone(loaded.module.samples[0].recipe)
            self.assertFalse(document.dirty)
            document.undo()
            self.assertTrue(document.dirty)
            document.redo()
            self.assertFalse(document.dirty)

    def test_timing_preserves_notes_samples_and_other_effects(self):
        before = self.document.module
        self.document.set_timing(160, 4)
        after = self.document.module
        self.assertAlmostEqual(playback_plan(after)["duration_seconds"], 256 * 4 * 2.5 / 160)
        for channel in range(4):
            old, new = before.patterns[0].get(0, channel), after.patterns[0].get(0, channel)
            self.assertEqual((old.period, old.sample), (new.period, new.sample))
            if old.command not in (0, 15):
                self.assertEqual(new.effect, old.effect)

    def test_timing_refuses_to_erase_other_effects(self):
        module = copy.deepcopy(self.document.module)
        for channel in range(4):
            old = module.patterns[0].get(0, channel)
            module.patterns[0].put(0, channel, cell(old.note, old.sample, "C20"))
        document = Document(module)
        with self.assertRaises(ValidationError):
            document.set_timing(140, 6)
        self.assertFalse(document.dirty)

    def test_transpose_rejects_entire_transaction_if_one_note_exceeds_range(self):
        document = Document(Module("Bounds", [Sample("Wave", (0, 0, 32, -32))],
                                   [Pattern(cells={(0, 0): cell("C-2", 1), (1, 0): cell("B-3", 1)})], [0]))
        before = fingerprint(document.module)
        with self.assertRaises(ValidationError):
            document.transpose(0, 0, 1)
        self.assertEqual(fingerprint(document.module), before)
        document.transpose(0, 0, -1)
        self.assertEqual(document.module.patterns[0].get(1, 0).note, "A#3")

    def test_note_cut_is_undoable_and_keeps_instrument(self):
        previous = self.document.module.patterns[0].get(0, 0)
        self.document.gate_note(0, 0, 0, 3)
        changed = self.document.module.patterns[0].get(0, 0)
        self.assertEqual((changed.period, changed.sample), (previous.period, previous.sample))
        self.assertEqual(changed.effect, "EC3")
        self.document.undo()
        self.assertEqual(self.document.module.patterns[0].get(0, 0), previous)

    def test_muted_listening_copy_preserves_timing_flow_and_original(self):
        original = fingerprint(self.document.module)
        muted = listening_copy(self.document.module, (False, False, True, False))
        self.assertEqual(playback_plan(muted), playback_plan(self.document.module))
        for pattern in muted.patterns:
            for (_, channel), value in pattern.cells.items():
                if channel != 2:
                    self.assertEqual((value.period, value.sample), (0, 0))
        self.assertEqual(fingerprint(self.document.module), original)


class DesktopServicesTests(unittest.TestCase):
    def test_session_is_portable_bounded_and_survives_a_fresh_read(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            state = AppState(directory)
            for index in range(14):
                state.remember(directory / f"{index}.mod")
            state.values.update(volume=0, loop=False, follow=False)
            state.save()
            reopened = AppState(directory)
            self.assertEqual(len(reopened.recent()), 12)
            self.assertEqual(reopened.recent()[0], directory / "13.mod")
            self.assertEqual(reopened.values["volume"], 0)
            self.assertFalse(reopened.values["loop"])
            self.assertFalse(reopened.values["follow"])

    def test_corrupt_settings_do_not_prevent_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "session.json").write_text("broken", encoding="utf-8")
            self.assertEqual(AppState(directory).values["volume"], 65)
            project.write_json(directory / "session.json", {"volume": "bad", "loop": [], "recent_files": None})
            state = AppState(directory)
            self.assertEqual(state.values["volume"], 65)
            self.assertEqual(state.recent(), [])
            self.assertTrue(state.values["loop"])

    def test_sample_preview_uses_volume_finetune_and_new_cache_keys(self):
        module = Module("Wave", [Sample("Wave", (0, 64, 0, -64), 64, 0, 0, 4)], [Pattern()], [0])
        with tempfile.TemporaryDirectory() as folder:
            cache = AudioCache(Path(folder))
            full = cache.sample(module, 0)
            with wave.open(str(full)) as stream:
                rate = stream.getframerate()
                peak = max(array("h", stream.readframes(stream.getnframes())))
            module.samples[0].volume = 16
            module.samples[0].finetune = 7
            quieter = cache.sample(module, 0)
            self.assertNotEqual(full, quieter)
            with wave.open(str(quieter)) as stream:
                self.assertGreater(stream.getframerate(), rate)
                self.assertEqual(max(array("h", stream.readframes(stream.getnframes()))), peak // 4)


if __name__ == "__main__":
    unittest.main()
