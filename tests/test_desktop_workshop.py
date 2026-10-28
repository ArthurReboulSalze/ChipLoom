"""The sound workshop and the "Open in a browser" dialog in the Qt window.

Sample editor (loop, trim, gain, fade with preview, refusals and one undo step each), the Create tab (recipe
form from the schema, debounced audition, drawing, "Add to song", the synthesized-song flow), the levels view,
instruments, and the browser dialog. Everything runs on temporary projects and instrument folders; the sample
bank folder is pointed at an empty directory so the built-in reference levels are used.
"""
from __future__ import annotations

import importlib
import shutil
import unittest
from unittest.mock import Mock, patch

try:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QMouseEvent
    from PySide6.QtWidgets import QApplication, QMessageBox

    from tracker4agents import desktop_browser, desktop_create
except ModuleNotFoundError:
    QApplication = None

from tracker4agents import sample_tools, synth, synth_tools
from tracker4agents.document import fingerprint
from tracker4agents.live import LiveServer
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell

PACKAGE = __package__ + "." if __package__ else ""
base = importlib.import_module(PACKAGE + "test_desktop_08")
YES = QMessageBox.StandardButton.Yes if QApplication else None
NO = QMessageBox.StandardButton.No if QApplication else None
LEFT = Qt.MouseButton.LeftButton if QApplication else None
NOBUTTON = Qt.MouseButton.NoButton if QApplication else None
NOMOD = Qt.KeyboardModifier.NoModifier if QApplication else None


def song(title="Workshop") -> Module:
    loud = Sample("Loud", (0, 0) + (120, 0, -120, 0) * 16, 64, 0, 2, 64)               # loop 2..66, peak 120
    shot = Sample("Shot", (0, 0) + (40, 30, 20, 10, 0, -10, -20, -30) * 8, 40)          # one-shot, 66 bytes
    quiet = Sample("Quiet", (3, -3) * 33, 40, 0, 0, 66)                                 # looped from byte 0
    cells = {(0, 0): cell("C-2", 1), (1, 0): cell("E-2", 2), (2, 1): cell("G-2", 3)}
    return Module(title, [loud, shot, quiet], [Pattern(name="Intro", cells=cells), Pattern(name="Verse")], [0, 1, 0])


class Workshop(base.WindowCase):
    make_song = staticmethod(song)

    def setUp(self):
        super().setUp()
        self.window.sample_browser.library_path = self.directory / "no-sample-bank"   # built-in reference levels
        self.workshop = self.window.sample_workshop
        self.editor = self.workshop.editor
        self.levels = self.workshop.levels
        self.create = self.window.create_panel

    def select(self, slot: int):
        self.window.samples.setCurrentRow(slot - 1)
        self.app.processEvents()

    def sample(self, slot: int) -> Sample:
        return self.window.document.module.samples[slot - 1]

    def state(self):
        document = self.window.document
        return fingerprint(document.module), document.revision

    def one_undo(self, action):
        """`action` changes the song in exactly one undoable step."""
        window = self.window
        before, revision = self.state()
        result = action()
        self.assertIsNotNone(result)
        self.assertEqual(window.document.revision, revision + 1)
        self.assertNotEqual(fingerprint(window.document.module), before)
        window.undo()
        self.assertEqual(fingerprint(window.document.module), before)
        window.redo()
        return result


# --- sample editor ---------------------------------------------------------------------------------
@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class SampleEditorTests(Workshop):
    def test_the_tabs_are_song_samples_library_create_instruments_agent(self):
        window = self.window
        self.assertEqual([window.sample_tabs.tabText(index) for index in range(window.sample_tabs.count())],
                         ["Song samples", "Sample library", "Create", "Instruments", "Agent"])
        window.set_language("fr")
        self.assertEqual([window.sample_tabs.tabText(index) for index in range(window.sample_tabs.count())],
                         ["Samples du morceau", "Bibliothèque", "Créer", "Instruments", "Agent"])
        self.assertEqual(self.editor.listen["loop"].text(), "Aperçu")
        self.assertEqual(window.browser_action.text(), "Ouvrir dans un navigateur…")

    def test_preview_reports_and_auditions_without_touching_the_song(self):
        window, editor = self.window, self.editor
        self.select(2)
        before = self.state()
        editor.loop_start.setValue(2)
        editor.loop_length.setValue(32)
        found = editor.preview("loop")
        self.assertEqual(found["kind"], "loop")
        self.assertTrue(found["report"]["looped"])
        self.assertEqual((found["sample"].loop_start, found["sample"].loop_length), (2, 32))
        self.assertTrue(found["wav"].startswith(b"RIFF"))
        self.assertIsNotNone(editor.wave.ghost)                      # the edited copy is drawn over the original
        self.assertIn("Loop 2 → 34", editor.report.text())
        self.assertTrue(window.sample_player.source().toLocalFile().endswith(".wav"))   # and auditioned
        window.sample_player.stop()
        self.assertEqual(self.state(), before)
        self.assertFalse(window.document.dirty)
        editor.gain_db.setValue(-6)                                  # changing a field drops the stale preview
        self.assertIsNone(editor.last_preview)
        self.assertIsNone(editor.wave.ghost)
        self.assertEqual(editor.preview("gain")["report"]["db"], -6.0)
        window.sample_player.stop()
        self.assertEqual(self.state(), before)

    def test_each_edit_is_one_undoable_patch(self):
        editor = self.editor
        self.select(2)
        editor.loop_start.setValue(2)
        editor.loop_length.setValue(32)
        self.one_undo(lambda: editor.apply_edit("loop"))
        self.assertEqual((self.sample(2).loop_start, self.sample(2).loop_length), (2, 32))
        self.window.undo()
        self.select(2)
        editor.trim_start.setValue(0)
        editor.trim_end.setValue(40)
        self.one_undo(lambda: editor.apply_edit("trim"))
        self.assertEqual(len(self.sample(2).pcm), 40)
        self.window.undo()
        self.select(2)
        editor.fade_out.setValue(16)
        self.one_undo(lambda: editor.apply_edit("fade"))
        self.assertEqual(self.sample(2).pcm[-1], 0)
        self.window.undo()
        self.select(1)
        editor.gain_db.setValue(-3)
        self.one_undo(lambda: editor.apply_edit("gain"))
        self.assertEqual(max(self.sample(1).pcm), round(120 * 10 ** (-3 / 20)))
        self.assertIn("Ctrl+Z", self.window.statusBar().currentMessage())

    def test_a_clipping_gain_is_refused_with_the_headroom_and_can_be_forced(self):
        editor = self.editor
        self.select(1)
        editor.gain_db.setValue(3)
        before = self.state()
        with patch.object(QMessageBox, "question", return_value=NO) as question:
            self.assertIsNone(editor.apply_edit("gain"))
        self.assertIn("would push loud bytes past the 8-bit limit", question.call_args.args[2])
        self.assertIn("clean gain is +0.5 dB", question.call_args.args[2])
        self.assertEqual(self.state(), before)
        self.assertTrue(editor.report.property("error"))
        self.assertIn("clean gain", editor.report.text())
        self.assertIn("Nothing was changed", editor.report.text())
        with patch.object(QMessageBox, "question", return_value=YES):
            report = editor.apply_edit("gain")
        self.assertGreater(report["clipped"], 0)
        self.assertEqual(max(self.sample(1).pcm), 127)

    def test_trimming_into_a_loop_offers_adjust_loop_and_a_bare_loop_removal_offers_adapt(self):
        editor = self.editor
        self.select(1)
        editor.trim_start.setValue(10)
        editor.trim_end.setValue(50)
        with patch.object(QMessageBox, "question", return_value=YES) as question:
            report = editor.apply_edit("trim")
        self.assertEqual(question.call_count, 1)
        self.assertIn("cuts into the loop", question.call_args.args[2])
        self.assertEqual((report["loop_start"], report["loop_length"], len(self.sample(1).pcm)), (0, 40, 40))
        self.window.undo()
        self.select(3)
        editor.loop_start.setValue(0)
        editor.loop_length.setValue(0)
        with patch.object(QMessageBox, "question", return_value=NO):
            self.assertIsNone(editor.apply_edit("loop"))
        self.assertEqual(len(self.sample(3).pcm), 66)
        with patch.object(QMessageBox, "question", return_value=YES) as question:
            report = editor.apply_edit("loop")
        self.assertIn("two silent bytes", question.call_args.args[2])
        self.assertEqual((len(self.sample(3).pcm), self.sample(3).loop_length), (68, 0))
        self.assertEqual(report["adaptations"], ["prepend-two-zero-bytes"])
        self.window.undo()
        # A fade that reaches into a loop asks for allow_loop.
        self.select(1)
        editor.fade_in.setValue(16)
        with patch.object(QMessageBox, "question", return_value=YES) as question:
            editor.apply_edit("fade")
        self.assertIn("every repeat would dip", question.call_args.args[2])

    def test_preview_also_surfaces_refusals(self):
        editor = self.editor
        self.select(1)
        editor.gain_db.setValue(3)
        with patch.object(QMessageBox, "question", return_value=NO):
            self.assertIsNone(editor.preview("gain"))
        self.assertTrue(editor.report.property("error"))
        self.assertIsNone(editor.wave.ghost)

    def wave_event(self, kind, x, buttons=LEFT, button=LEFT):
        wave = self.editor.wave
        point = QPointF(x, wave.height() / 2)
        QApplication.sendEvent(wave, QMouseEvent(kind, point, wave.mapToGlobal(point), button, buttons, NOMOD))

    def test_dragging_the_loop_handles_and_the_selection_fills_the_fields(self):
        editor, wave = self.editor, self.editor.wave
        self.select(1)
        before = self.state()
        end = wave.x_at(66)
        self.assertEqual(wave.handle_at(end), "loop_end")
        self.wave_event(QEvent.Type.MouseButtonPress, end)
        self.wave_event(QEvent.Type.MouseMove, wave.x_at(34), LEFT, NOBUTTON)
        self.wave_event(QEvent.Type.MouseButtonRelease, wave.x_at(34), NOBUTTON, LEFT)
        self.assertEqual((editor.loop_start.value(), editor.loop_length.value() % 2), (2, 0))
        self.assertTrue(28 <= editor.loop_length.value() <= 36)
        self.assertEqual(wave.loop, (editor.loop_start.value(), editor.loop_length.value()))
        start = wave.x_at(40)
        self.assertIsNone(wave.handle_at(wave.x_at(50)))
        self.wave_event(QEvent.Type.MouseButtonPress, start)
        self.wave_event(QEvent.Type.MouseMove, wave.x_at(58), LEFT, NOBUTTON)
        self.wave_event(QEvent.Type.MouseButtonRelease, wave.x_at(58), NOBUTTON, LEFT)
        low, high = wave.selection
        self.assertTrue(38 <= low <= 42 and 56 <= high <= 60 and low % 2 == high % 2 == 0)
        self.assertEqual((editor.trim_start.value(), editor.trim_end.value()), (low, high))
        editor.loop_to_selection()
        self.assertEqual((editor.loop_start.value(), editor.loop_length.value()), (low, high - low))
        self.wave_event(QEvent.Type.MouseButtonDblClick, wave.x_at(10))
        self.assertEqual(wave.selection, (0, 0))
        self.assertEqual(self.state(), before)   # dragging only fills fields; nothing is applied

    def test_an_empty_song_shows_a_helpful_empty_state(self):
        self.window.samples.clear()
        self.editor.load()
        self.assertFalse(self.editor.apply["gain"].isEnabled())
        self.assertIn("no samples", self.editor.info.text())
        self.assertIsNone(self.editor.apply_edit("gain"))

    def test_volume_and_finetune_keep_their_apply_button(self):
        self.select(2)
        self.editor.volume.setValue(33)
        self.editor.finetune.setValue(-2)
        self.editor.apply_button.click()
        self.assertEqual((self.sample(2).volume, self.sample(2).finetune), (33, -2))
        self.assertIs(self.window.sample_volume, self.editor.volume)


@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class SynthesizedProjectTests(Workshop):
    """A project that declares sample_source "synthesized" refuses PCM edits and drawn PCM, with readable messages."""

    @staticmethod
    def make_song():
        return synth_tools.palette("Palette")[0]

    def test_pcm_edits_of_recipe_samples_are_refused_in_a_synthesized_project(self):
        editor = self.editor
        self.select(1)
        editor.gain_db.setValue(-1)
        before = self.state()
        with patch.object(QMessageBox, "question") as question:
            self.assertIsNone(editor.apply_edit("gain"))
            self.assertIsNone(editor.preview("gain"))
        question.assert_not_called()             # there is no flag for this: the owner is told why
        self.assertIn("declared source", editor.report.text())
        self.assertIn("synthesized", editor.report.text())
        self.assertEqual(self.state(), before)

    def test_drawn_pcm_is_refused_but_a_draw_recipe_is_added(self):
        create = self.create
        create.kind.setCurrentIndex(create.kind.findData("draw"))
        create.canvas.preset("saw", 16)
        create.pcm.setChecked(True)
        before = self.state()
        self.assertIsNone(create.add_to_song())
        self.assertTrue(create.status.property("error"))
        self.assertIn("declared source", create.status.text())
        self.assertEqual(self.state(), before)
        create.pcm.setChecked(False)
        info = create.add_to_song()
        self.assertEqual(info["slot"], 14)
        self.assertEqual(self.sample(14).recipe["type"], "draw")


# --- the Create tab -----------------------------------------------------------------------------------
@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class CreateTests(Workshop):
    def setUp(self):
        super().setUp()
        self.window.sample_tabs.setCurrentIndex(2)      # the audition only runs while the tab is on screen
        self.app.processEvents()
        self.create.timer.stop()

    def test_the_form_follows_the_recipe_schema(self):
        create = self.create
        schema = sample_tools.recipe_schema()
        self.assertEqual([create.kind.itemData(i) for i in range(create.kind.count())], [t["type"] for t in schema["types"]])
        create.kind.setCurrentIndex(create.kind.findData("wave"))
        self.assertEqual(create.recipe(), schema["types"][0]["default_recipe"])
        spec, control, caption = create.widgets["frequency"]
        self.assertEqual((control.minimum(), control.maximum()), (spec["min"], spec["max"]))
        self.assertTrue(create.widgets["duty"][1].isVisibleTo(create))
        self.assertFalse(create.widgets["seed"][1].isVisibleTo(create))
        create.set_value("shape", "noise")                      # parameters that do not apply disappear
        self.assertFalse(create.widgets["duty"][1].isVisibleTo(create))
        self.assertTrue(create.widgets["seed"][1].isVisibleTo(create))
        recipe = create.recipe()
        self.assertEqual((recipe["shape"], "duty" in recipe, "frequency" in recipe), ("noise", False, False))
        create.set_value("seed", 4_000_000_000)
        self.assertEqual(create.recipe()["seed"], 4_000_000_000)
        create.kind.setCurrentIndex(create.kind.findData("kick"))
        self.assertEqual(set(create.recipe()), {"type", "duration", "peak", "seed", "drive"})
        for name in ("peak", "drive"):
            _, control, _ = create.widgets[name]
            self.assertLessEqual(control.maximum(), 1)

    def test_the_audition_is_debounced_and_shows_its_measurements(self):
        create, window = self.create, self.window
        create.timer.stop()
        calls = Mock(wraps=sample_tools.preview_recipe)
        with patch.object(desktop_create.sample_tools, "preview_recipe", calls):
            create.kind.setCurrentIndex(create.kind.findData("wave"))
            for value in (200, 220, 240, 260):
                create.set_value("frequency", value)
            create.volume.setValue(30)
            self.assertEqual(calls.call_count, 0)               # nothing rendered while the hand is moving
            self.wait_until(lambda: calls.call_count == 1)
            self.pause(.5)
            self.assertEqual(calls.call_count, 1)               # one audition for the whole burst
        self.assertEqual(create.last["recipe"]["frequency"], 260)
        self.assertIn("bytes", create.measures.text())
        self.assertIn("Loudness", create.measures.text())
        self.assertIn("dBFS", create.measures.text())
        self.assertTrue(window.sample_player.source().toLocalFile().endswith(".wav"))   # auto-listen
        window.sample_player.stop()
        create.auto_listen.setChecked(False)
        sources = []
        with patch.object(window, "audition_wav", side_effect=sources.append):
            create.set_value("frequency", 300)
            self.wait_until(lambda: create.last["recipe"]["frequency"] == 300)
            self.assertEqual(sources, [])
            create.listen_button.click()
        self.assertEqual(len(sources), 1)

    def test_an_invalid_recipe_is_explained_not_raised(self):
        create = self.create
        create.kind.setCurrentIndex(create.kind.findData("draw"))
        create.timer.stop()
        create.canvas.set_points([0.0] * 8)
        create.timer.stop()
        with patch.object(sample_tools, "preview_recipe", side_effect=ValidationError("points: broken", "RECIPE_INVALID")):
            self.assertIsNone(create.render_preview(play=False))
        self.assertIn("cannot be built", create.measures.text())

    def test_add_to_song_is_one_undoable_recipe_sample_patch(self):
        window, create = self.window, self.create
        create.kind.setCurrentIndex(create.kind.findData("kick"))
        create.name.setText("My kick")
        create.role.setCurrentIndex(create.role.findData("kick"))
        count = len(window.document.module.samples)
        info = self.one_undo(create.add_to_song)
        self.assertEqual(info["slot"], count + 1)
        added = self.sample(count + 1)
        self.assertEqual((added.name, added.recipe["type"]), ("My kick", "kick"))
        self.assertEqual(window.document.module.metadata["sample_sources"][str(count + 1)]["origin"], "synthesized")
        self.assertEqual(info["loudness"]["reference"], "defaults")        # volume matched to the role's level
        self.assertNotEqual(added.volume, 40)
        self.assertIn("slot", create.status.text())

    def test_an_explicit_volume_and_slot_and_the_replace_confirmation(self):
        create = self.create
        create.kind.setCurrentIndex(create.kind.findData("hat"))
        create.match.setChecked(False)
        create.volume.setValue(21)
        create.slot.setCurrentIndex(create.slot.findData(2))
        before = self.state()
        with patch.object(QMessageBox, "question", return_value=NO) as question:
            self.assertIsNone(create.add_to_song())
        self.assertIn("Slot 2", question.call_args.args[2])
        self.assertEqual(self.state(), before)
        with patch.object(QMessageBox, "question", return_value=YES):
            info = create.add_to_song()
        self.assertEqual(info["slot"], 2)
        self.assertEqual((self.sample(2).volume, self.sample(2).recipe["type"]), (21, "hat"))

    def test_drawing_on_the_canvas_becomes_a_sample(self):
        window, create = self.window, self.create
        create.kind.setCurrentIndex(create.kind.findData("draw"))
        self.assertTrue(create.canvas_box.isVisibleTo(create))
        canvas = create.canvas
        canvas.preset("clear", 8)
        self.assertEqual(canvas.points(), [0.0] * 8)

        def stroke(kind, x, y, buttons=LEFT):
            QApplication.sendEvent(canvas, QMouseEvent(kind, QPointF(x, y), canvas.mapToGlobal(QPointF(x, y)),
                                                       LEFT if kind != QEvent.Type.MouseMove else NOBUTTON, buttons, NOMOD))

        width, height = canvas.width(), canvas.height()
        stroke(QEvent.Type.MouseButtonPress, width * 0.05, height * 0.1)         # near the top: +0.8
        stroke(QEvent.Type.MouseMove, width * 0.95, height * 0.9)                # fast stroke to the bottom: interpolated
        stroke(QEvent.Type.MouseButtonRelease, width * 0.95, height * 0.9, NOBUTTON)
        points = canvas.points()
        self.assertGreater(points[0], 0.7)
        self.assertLess(points[-1], -0.7)
        self.assertEqual(points, sorted(points, reverse=True))                   # no gaps: a straight descent
        create.timer.stop()
        create.set_value("cycles", 4)
        create.pcm.setChecked(True)                                              # keep it as plain sample data
        create.name.setText("Drawn saw")
        before_count = len(window.document.module.samples)
        info = self.one_undo(create.add_to_song)
        added = self.sample(info["slot"])
        self.assertEqual(info["slot"], before_count + 1)
        expected = sample_tools.draw_to_pcm(points, 4, create.recipe()["frequency"], create.recipe()["peak"])
        self.assertEqual(added.pcm, expected)
        self.assertEqual((added.loop_start, added.loop_length), (0, len(expected)))
        self.assertEqual(window.document.module.metadata["sample_sources"][str(info["slot"])]["origin"], "drawn")
        create.pcm.setChecked(False)                                             # or as the recipe that rebuilds it
        info = create.add_to_song()
        self.assertEqual(self.sample(info["slot"]).pcm, synth.from_recipe("x", create.recipe()).pcm)

    def test_start_a_synthesized_song_opens_the_palette_as_a_new_project(self):
        window, create = self.window, self.create
        with patch.object(window, "_discard_or_save", return_value=False):
            self.assertIsNone(create.start_synthesized_song())
        self.assertEqual(window.document.module.title, "Workshop")
        module = create.start_synthesized_song()
        self.assertEqual(window.document.module.title, "Synth Palette")
        self.assertIs(window.document.module, module)
        self.assertIsNone(window.document.path)                                  # a new, unsaved project
        self.assertEqual(module.metadata["sample_source"], "synthesized")
        self.assertEqual(sum(bool(item.pcm) for item in module.samples), len(synth_tools.PALETTE))
        self.assertEqual(window.samples.count(), len(synth_tools.PALETTE))
        self.assertEqual(module.metadata["palette"]["reference"], "defaults")
        self.assertIn("synthesized", window.statusBar().currentMessage())


# --- levels ------------------------------------------------------------------------------------------------
@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class LevelsTests(Workshop):
    @staticmethod
    def make_song():
        return synth_tools.palette("Palette")[0]

    def row(self, slot):
        return next(item for item in self.levels.rows if item["slot"] == slot)

    def test_levels_list_every_sample_and_flag_differences_above_six_db(self):
        self.workshop.show_page(1)
        levels = self.levels
        self.assertEqual(len(levels.rows), len(synth_tools.PALETTE))
        self.assertEqual(levels.table.rowCount(), len(synth_tools.PALETTE))
        self.assertIn("built-in reference levels", levels.source.text())
        self.window.apply_patch([{"op": "sample", "slot": 1, "volume": 3}], "Too quiet")
        self.pause(.3)                                                           # the view follows edits, debounced
        self.assertTrue(self.row(1)["flagged"])
        self.assertLess(self.row(1)["difference"], -6)
        self.assertIn(" !", levels.table.item(0, 5).text())
        self.assertGreater(abs(float(levels.table.item(0, 5).text().split()[0])), 6)
        self.window.set_language("fr")
        self.assertEqual(levels.table.horizontalHeaderItem(5).text(), "Écart")

    def test_match_sets_one_sample_to_its_target_as_one_undo_step(self):
        self.window.apply_patch([{"op": "sample", "slot": 1, "volume": 3}], "Too quiet")
        self.workshop.show_page(1)
        levels = self.levels
        levels.rebuild()
        self.assertTrue(self.row(1)["flagged"])
        before, revision = self.state()
        levels.table.cellWidget(0, 6).click()
        self.assertEqual(self.window.document.revision, revision + 1)
        self.assertEqual(self.sample(1).recipe["type"], "kick")                  # a recipe sample stays a recipe
        levels.rebuild()
        self.assertFalse(self.row(1)["flagged"])
        self.assertLess(abs(self.row(1)["difference"]), 1)
        self.window.undo()
        self.assertEqual(self.sample(1).volume, 3)
        self.assertEqual(fingerprint(self.window.document.module), before)      # the earlier "Too quiet" edit stays

    def test_match_all_is_a_single_patch(self):
        self.window.apply_patch([{"op": "sample", "slot": 1, "volume": 3}, {"op": "sample", "slot": 2, "volume": 2},
                                 {"op": "sample", "slot": 6, "volume": 1}], "Too quiet")
        self.workshop.show_page(1)
        self.levels.rebuild()
        flagged = [item["slot"] for item in self.levels.rows if item["flagged"]]
        self.assertTrue({1, 2, 6} <= set(flagged))
        revision = self.window.document.revision
        self.levels.match_all.click()
        self.assertEqual(self.window.document.revision, revision + 1)
        self.levels.rebuild()
        self.assertEqual([item["slot"] for item in self.levels.rows if item["flagged"]], [])

    def test_the_empty_state_and_the_sample_bank_reference(self):
        self.workshop.show_page(1)
        bank = self.directory / "bank"
        bank.mkdir()
        (bank / "library.json").write_text("{}", encoding="utf-8")                 # not a usable bank: defaults again
        self.window.sample_browser.library_path = bank
        self.levels.rebuild()
        self.assertEqual(self.levels.reference()["source"], "defaults")
        self.window.samples.clear()
        self.window.document.module.samples[:] = [Sample("", (), 0)]
        self.levels.rebuild()
        self.assertTrue(self.levels.empty.isVisibleTo(self.levels))
        self.assertFalse(self.levels.match_all.isEnabled())


# --- instruments -----------------------------------------------------------------------------------------------
@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class InstrumentTests(Workshop):
    def setUp(self):
        super().setUp()
        self.panel = self.window.instrument_panel
        self.panel.set_folder(self.directory / "instruments")

    def save(self, slot=1, name="Pluck", phrase=("000", "C20", "C10")):
        self.select(slot)
        self.panel.name.setText(name)
        self.panel.set_phrase(list(phrase))
        return self.panel.save_instrument()

    def test_the_empty_folder_explains_what_to_do(self):
        self.assertEqual(self.panel.list.count(), 0)
        self.assertIn("No instruments", self.panel.empty.text())
        self.assertFalse(self.panel.apply_button.isEnabled())
        self.assertIsNone(self.panel.apply_at_cursor())
        self.assertTrue(self.panel.status.property("error"))

    def test_save_the_selected_sample_with_a_phrase(self):
        saved = self.save()
        self.assertEqual((saved["id"], saved["name"], saved["phrase"]), ("INS-0001", "Pluck", ["000", "C20", "C10"]))
        self.assertEqual(saved["sample"]["kind"], "pcm")
        self.assertTrue((self.directory / "instruments" / "INS-0001.json").is_file())
        self.assertEqual(self.panel.list.count(), 1)
        self.assertIn("INS-0001 · Pluck", self.panel.list.item(0).text())
        self.assertEqual(self.panel.selected_id(), "INS-0001")
        self.assertEqual(self.window.state.values["instrument_folder"], str(self.directory / "instruments"))
        second = self.save(2, "Second", ("000",))
        self.assertEqual(second["id"], "INS-0002")
        self.panel.search.setText("second")
        self.assertEqual(self.panel.list.count(), 1)
        self.panel.search.setText("")
        self.panel.set_phrase(["000"] * 3)
        self.panel.add_row()
        self.panel.remove_row()
        self.panel.remove_row()
        self.assertEqual(self.panel.phrase.rowCount(), 2)

    def test_a_bad_phrase_is_reported_not_saved(self):
        self.select(1)
        self.panel.set_phrase(["D00"])             # Dxx steers the song, never an instrument
        self.assertIsNone(self.panel.save_instrument())
        self.assertTrue(self.panel.status.property("error"))
        self.assertEqual(self.panel.library().ids(), [])

    def test_apply_at_the_cursor_is_one_undoable_patch_and_reuses_the_samples_slot(self):
        window, panel = self.window, self.panel
        self.save()
        window.table.setCurrentIndex(self.model.index(8, 3 * 2))                  # row 8, channel 3
        panel.note.setCurrentText("E-2")
        info = self.one_undo(panel.apply_at_cursor)
        self.assertEqual(info["slot"], 1)
        self.assertTrue(info["slot_reused"])
        written = window.document.module.patterns[0]
        self.assertEqual((written.get(8, 2).note, written.get(8, 2).sample), ("E-2", 1))
        self.assertEqual((written.get(9, 2).effect, written.get(10, 2).effect), ("C20", "C10"))
        self.assertEqual(info["rows_written"], [8, 9, 10])
        self.assertIn("3 rows written", panel.status.text())

    def test_the_shortcut_and_the_menu_apply_the_selected_instrument(self):
        window, panel = self.window, self.panel
        self.save()
        window.table.setCurrentIndex(self.model.index(20, 0))
        self.assertEqual(panel.apply_action.shortcut().toString(), "Ctrl+I")
        before = self.state()
        panel.apply_action.trigger()
        self.assertEqual(window.document.module.patterns[0].get(20, 0).note, "C-2")
        self.assertNotEqual(self.state(), before)
        window.undo()
        window.instrument_action.trigger()
        self.assertEqual(window.document.module.patterns[0].get(20, 0).note, "C-2")

    def test_existing_effects_are_kept_unless_asked(self):
        window, panel = self.window, self.panel
        self.save()
        window.apply_patch([{"op": "set", "pattern": 0, "row": 9, "channel": 3, "cell": "--- 00 A03"}], "Arpeggio")
        window.table.setCurrentIndex(self.model.index(8, 9))
        info = panel.apply_at_cursor()
        self.assertEqual(len(info["skipped"]), 1)
        self.assertEqual(window.document.module.patterns[0].get(9, 3).effect, "A03")
        self.assertIn("kept", panel.status.text())
        panel.overwrite.setChecked(True)
        panel.apply_at_cursor()
        self.assertEqual(window.document.module.patterns[0].get(9, 3).effect, "C20")

    def test_delete_asks_first(self):
        self.save()
        with patch.object(QMessageBox, "question", return_value=NO):
            self.panel.delete_selected()
        self.assertEqual(self.panel.list.count(), 1)
        with patch.object(QMessageBox, "question", return_value=YES):
            self.panel.delete_selected()
        self.assertEqual(self.panel.list.count(), 0)


# --- open in a browser ----------------------------------------------------------------------------------------------
@unittest.skipUnless(base.TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class BrowserDialogTests(Workshop):
    def dialog(self):
        return self.window.open_browser()

    def join(self, name="Tablet"):
        token, device = self.window.live.session.web.join(listener="loopback", agent="Test UA", name=name)
        return device

    def test_the_dialog_shows_the_address_with_copy_and_open_and_no_code(self):
        window = self.window
        dialog = self.dialog()
        self.assertTrue(dialog.isVisible())
        server = window.live.server
        self.assertEqual(dialog.url.text(), server.web_urls()["local"])
        self.assertTrue(dialog.url.text().endswith("/web/"))
        for gone in ("code", "countdown", "new_button", "pairing", "revoke_button", "revoke_all_button"):
            self.assertFalse(hasattr(dialog, gone), gone)
        self.assertNotIn("code", dialog.intro.text().replace("No code is needed", ""))
        dialog.copy_button.click()
        self.assertEqual(QGuiApplication.clipboard().text(), dialog.url.text())
        with patch.object(desktop_browser.QDesktopServices, "openUrl", return_value=True) as opener:
            dialog.open_button.click()
        opener.assert_called_once()
        self.assertEqual(opener.call_args.args[0].toString(), dialog.url.text())
        dialog.close()

    def test_a_joined_browser_is_listed_and_counted_in_the_status_bar(self):
        window = self.window
        dialog = self.dialog()
        self.assertFalse(window.web_status.isVisible())
        self.assertIn("No browser", dialog.empty.text())
        self.join()
        dialog.tick()
        self.assertEqual(dialog.devices_table.rowCount(), 1)
        self.assertEqual(dialog.devices_table.item(0, 0).text(), "Tablet")
        self.assertEqual(dialog.devices_table.item(0, 1).text(), "Test UA")
        self.assertEqual(window.web_status.text(), "Browsers: 1")
        self.assertTrue(window.web_status.isVisible())
        self.join("Phone")
        dialog.tick()
        self.assertEqual(window.web_status.text(), "Browsers: 2")
        self.assertEqual(dialog.devices_table.rowCount(), 2)
        dialog.close()

    def test_the_lan_switch_calls_enable_lan_warns_and_is_remembered(self):
        window = self.window
        server = window.live.server
        lan = {"local": server.web_urls()["local"], "lan": ["http://192.168.1.20:5000/web/"], "lan_enabled": True}
        dialog = self.dialog()
        warning = "Anyone on that network who knows the address can listen and edit, and the traffic is plain HTTP."
        with patch.object(server, "enable_lan", return_value=lan["lan"]) as enable, \
                patch.object(server, "web_urls", return_value=lan), \
                patch.object(server, "web_info", return_value={**lan, "warning": warning}):
            dialog.lan.setChecked(True)
            enable.assert_called_once_with(True)
            self.assertTrue(dialog.warning.isVisibleTo(dialog))
            self.assertEqual(dialog.warning.text(), warning)
            self.assertEqual(dialog.url.text(), "http://192.168.1.20:5000/web/")   # the address to type on the tablet
            self.assertIs(window.state.values["web_lan"], True)
        with patch.object(server, "enable_lan", return_value=[]) as enable, \
                patch.object(server, "web_urls", return_value={**lan, "lan": [], "lan_enabled": False}), \
                patch.object(server, "web_info", return_value={"note": "local only"}):
            dialog.lan.setChecked(False)
            enable.assert_called_once_with(False)
            self.assertFalse(dialog.warning.isVisibleTo(dialog))
            self.assertIs(window.state.values["web_lan"], False)
        dialog.close()

    def test_a_lan_failure_is_shown_and_the_choice_reverts(self):
        window = self.window
        dialog = self.dialog()
        for code in ("LIVE_LAN", "LIVE_HOST"):
            with patch.object(window.live.server, "enable_lan", side_effect=ValidationError("No private address.", code)):
                dialog.lan.setChecked(True)
            self.assertFalse(dialog.lan.isChecked())
            self.assertIn("No private address", dialog.warning.text())
            self.assertIs(window.state.values["web_lan"], False)
        dialog.close()

    def test_the_lan_choice_is_applied_again_when_the_window_starts(self):
        window = self.window
        window.state.values["web_lan"] = True
        window.state.save()
        window.close()
        with patch.object(LiveServer, "enable_lan", return_value=[]) as enable:
            self.window = base.TrackerWindow(self.path, self.directory / "state", restore=False)
            self.window.show()
            self.wait_until(lambda: self.window.live.server is not None and self.window.live.server.running)
            enable.assert_called_with(True)

    def test_the_menu_entry_opens_it_and_live_off_explains_why_it_cannot_open(self):
        window = self.window
        self.assertEqual(window.browser_action.text(), "Open in a browser…")
        window.browser_action.trigger()
        self.assertTrue(window.browser_dialog.isVisible())
        window.live_action.setChecked(False)
        dialog = window.browser_dialog
        dialog.refresh()
        self.assertIn("turn it on", dialog.unavailable.text())
        self.assertFalse(dialog.copy_button.isEnabled())
        self.assertFalse(dialog.open_button.isEnabled())
        self.assertFalse(dialog.lan.isEnabled())
        self.assertFalse(dialog.open_url())
        dialog.close()

    def test_the_real_lan_warning_reads_plainly_and_is_translated(self):
        window = self.window
        server = window.live.server
        text = "Anyone on that network who knows the address can listen and edit, and the traffic is plain HTTP. Turn it on only on a network you trust."
        lan = {"local": server.web_urls()["local"], "lan": ["http://192.168.1.20:5000/web/"], "lan_enabled": True}
        window.set_language("fr")
        dialog = self.dialog()
        with patch.object(server, "web_urls", return_value=lan), patch.object(server, "enable_lan", return_value=lan["lan"]), \
                patch.object(server, "web_info", return_value={**lan, "warning": text}):
            dialog.lan.setChecked(True)
            self.assertIn("réseau de confiance", dialog.warning.text())
        dialog.close()

    def test_the_dialog_speaks_french(self):
        window = self.window
        window.set_language("fr")
        dialog = self.dialog()
        self.assertEqual(dialog.windowTitle(), "Ouvrir dans un navigateur")
        self.assertEqual(dialog.copy_button.text(), "Copier")
        self.assertEqual(dialog.open_button.text(), "Ouvrir")
        self.assertEqual(dialog.lan.text(), "Autoriser les appareils de mon réseau local")
        self.assertIn("Aucun code", dialog.intro.text())
        self.assertEqual(dialog.devices_table.horizontalHeaderItem(0).text(), "Appareil")
        dialog.close()

    def test_browser_edits_are_named_as_such_and_the_context_carries_the_mutes(self):
        window, session = self.window, self.window.live.session
        session.apply_patch([{"op": "set", "pattern": 0, "row": 12, "channel": 1, "cell": "C-2 01 ..."}], "human-web",
                            "Browser note")
        self.assertTrue(window.statusBar().currentMessage().startswith("Edit from a browser (human-web): Browser note"))
        self.assertEqual(set(self.model.flashed().values()), {"human_change"})
        self.assertEqual(session.context()["audible"], [True, True, True, True])
        window.mutes[1].click()
        self.wait_until(lambda: session.context()["audible"] == [True, False, True, True])
        window.solos[0].click()
        self.wait_until(lambda: session.context()["audible"] == [True, False, False, False])


if __name__ == "__main__":
    unittest.main()
