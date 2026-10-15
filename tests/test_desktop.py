"""Optional Qt integration tests, using real FFmpeg WAVs and Qt's media player."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit
    from tracker4agents.desktop import STYLE, TrackerWindow
except ModuleNotFoundError:
    TrackerWindow = None

from tracker4agents import audio, mod, project
from tracker4agents.document import Document, fingerprint
from tracker4agents.model import Module, Pattern, Sample, cell, playback_plan
from tracker4agents.themes import THEMES

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 et FFmpeg requis pour les essais de fenêtre.")
class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["tracker4agents-tests"])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.app.setStyle("Fusion")
        # The Windows offscreen plugin does not enumerate installed fonts.
        if not QFontDatabase.families() and os.name == "nt":
            for name in ("segoeui.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.state_dir = self.directory / "state"
        self.window = TrackerWindow(ROOT / "examples/pixel_rush.project.json", self.state_dir, restore=False)
        self.window.output.setMuted(True)
        self.window.sample_output.setMuted(True)
        self.window.show()
        self.wait_for_audio()

    def wait_until(self, predicate, seconds=30):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)  # Release the GIL so QRunnable renderers can make progress.
        self.assertTrue(predicate(), self.window.statusBar().currentMessage())

    def wait_for_audio(self):
        self.wait_until(lambda: self.window._audio_ready and not self.window._loading_audio)
        self.assertEqual(self.window.player.error(), QMediaPlayer.Error.NoError)

    def tearDown(self):
        window = self.window
        if window.document and window.document.dirty:
            window.document.save_project(self.directory / "tear-down.project.json")
        window.close()
        window.pool.waitForDone(10000)
        self.app.processEvents()
        window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def test_open_both_existing_modules_and_invalid_input_keeps_current_document(self):
        for stem in ("first_light", "pixel_rush"):
            path = self.directory / f"{stem}.mod"
            # A fresh checkout has source scores, not generated export folders.
            path.write_bytes(mod.encode(Document.open(ROOT / f"examples/{stem}.project.json").module))
            before = path.read_bytes()
            self.assertTrue(self.window.open_document(path))
            self.wait_for_audio()
            self.assertEqual(mod.encode(self.window.document.module), before)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(self.window.orders.count(), len(self.window.document.module.orders))
            self.assertEqual(self.window.pattern_model.rowCount(), 64)
            self.assertEqual(self.window.pattern_model.columnCount(), 12)
        original = fingerprint(self.window.document.module)
        invalid = self.directory / "invalid.mod"
        invalid.write_bytes(b"not a module")
        self.assertFalse(self.window.open_document(invalid))
        self.assertEqual(fingerprint(self.window.document.module), original)
        screenshot = os.environ.get("TRACKER4AGENTS_SCREENSHOT")
        if screenshot:
            self.window.table.setCurrentIndex(self.window.pattern_model.index(0, 9))
            self.app.processEvents()
            Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
            self.assertTrue(self.window.grab().save(screenshot))

    def test_actual_playback_seek_follow_sample_and_channel_monitoring(self):
        window = self.window
        initial = fingerprint(window.document.module)
        full_mix = Path(window.player.source().toLocalFile())
        window.toggle_play()
        self.wait_until(lambda: window.player.position() >= 250, 5)
        self.assertEqual(window.player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        window.toggle_play()
        self.assertEqual(window.player.playbackState(), QMediaPlayer.PlaybackState.PausedState)
        window.orders.setCurrentIndex(2)
        expected = next(entry["seconds"] for entry in window.plan["timeline"] if entry["order"] == 2)
        self.assertAlmostEqual(window.player.position() / 1000, expected, delta=.05)
        window._sync_position()
        self.assertEqual(window.current_order, 2)
        window.play_sample()
        self.wait_until(lambda: window.sample_player.position() >= 30, 5)
        self.assertEqual(window.sample_player.error(), QMediaPlayer.Error.NoError)
        window.sample_player.stop()
        window.solos[1].click()
        self.wait_for_audio()
        solo = Path(window.player.source().toLocalFile())
        self.assertNotEqual(audio.sha256(solo), audio.sha256(full_mix))
        self.assertEqual(fingerprint(window.document.module), initial)
        window.mutes[1].click()  # Solo + mute => no audible lanes, with timing retained.
        self.wait_for_audio()
        self.assertEqual(audio.analyze_wav(Path(window.player.source().toLocalFile()))["peak"], 0)
        self.assertAlmostEqual(window.player.duration() / 1000, window.plan["duration_seconds"], places=2)
        window.stop()
        self.assertEqual(window.player.position(), 0)

    def test_edit_with_keyboard_undo_timing_and_export_reload(self):
        window = self.window
        index = window.pattern_model.index(0, 9)
        original = window.document.module.patterns[0].get(0, 3)
        window.table.setCurrentIndex(index)
        window.table.edit(index)
        self.app.processEvents()
        editor = window.table.findChild(QLineEdit)
        self.assertIsNotNone(editor)
        editor.selectAll()
        QTest.keyClicks(editor, "D-3")
        self.assertEqual(editor.text(), "D-3")
        QTest.keyClick(editor, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(window.document.module.patterns[0].get(0, 3).note, "D-3", window.statusBar().currentMessage())
        self.assertTrue(window.document.dirty)
        self.assertEqual(window.table.currentIndex().row(), 0)
        # Effects remain editable in the tracker after removing the ECx sidebar.
        self.assertTrue(window.pattern_model.setData(window.pattern_model.index(0, 11), "EC2"))
        self.assertEqual(window.document.module.patterns[0].get(0, 3).effect, "EC2")
        window.undo()
        window.undo()
        self.assertEqual(window.document.module.patterns[0].get(0, 3), original)
        self.assertFalse(window.document.dirty)
        window.redo()
        window.title_edit.setText("Window test")
        window.bpm.setValue(180)
        window.apply_song()
        self.assertEqual(window.document.module.title, "Window test")
        self.assertEqual(window.plan["timeline"][0]["bpm"], 180)
        window.undo()
        self.assertEqual(window.document.module.title, "Pixel Rush")
        window.redo()
        self.wait_for_audio()
        for suffix, method in ((".project.json", lambda: window.save_project(save_as=True)), (".mod", window.export_mod)):
            target = self.directory / f"edited{suffix}"
            with patch.object(window, "_save_path", return_value=target):
                method()
            self.assertEqual(mod.encode(Document.open(target).module), mod.encode(window.document.module))
        for extension in ("wav", "mp3"):
            target = self.directory / f"edited.{extension}"
            with patch.object(window, "_save_path", return_value=target):
                window.export_audio(extension)
            self.wait_until(lambda: not window._jobs)
            self.assertTrue(target.is_file())
            self.assertGreater(target.stat().st_size, 256)

    def test_fresh_window_restores_file_and_zero_volume_and_reloads_agent_edits(self):
        window = self.window
        source = self.directory / "shared.project.json"
        window.document.save_project(source)
        window.open_document(source)
        self.wait_for_audio()
        window.volume.setValue(0)
        window.loop.setChecked(False)
        window.follow.setChecked(False)
        window.close()
        self.app.processEvents()
        replacement = TrackerWindow(state_dir=self.state_dir)
        self.window = replacement
        replacement.output.setMuted(True)
        replacement.show()
        self.wait_for_audio()
        self.assertEqual(replacement.document.path, source)
        self.assertEqual(replacement.volume.value(), 0)
        self.assertEqual(replacement.output.volume(), 0)
        self.assertFalse(replacement.loop.isChecked())
        self.assertFalse(replacement.follow.isChecked())
        agent = Document.open(source)
        agent.rename("Agent update")
        agent.save_project(source)
        replacement.reload_document()
        self.assertEqual(replacement.document.module.title, "Agent update")
        window.deleteLater()

    def test_stale_audio_result_and_failed_render_do_not_trap_transport(self):
        window = self.window
        original_cache = window.cache.prepare

        def delayed(module, audible):
            if module.title == "First Light":
                time.sleep(.2)
            return original_cache(module, audible)

        with patch.object(window.cache, "prepare", side_effect=delayed):
            window.open_document(ROOT / "examples/first_light.project.json")
            QTest.qWait(30)
            window.open_document(ROOT / "examples/pixel_rush.project.json")
            self.wait_for_audio()
            self.wait_until(lambda: not window._jobs)
        self.assertEqual(window.document.module.title, "Pixel Rush")
        self.assertEqual(window.player.duration(), 48000)
        with patch.object(window.cache, "prepare", side_effect=audio.RenderError("test unavailable renderer")):
            window.prepare_audio()
            self.wait_until(lambda: not window._jobs)
        self.assertFalse(window._loading_audio)
        self.assertTrue(window.play_button.isEnabled())
        self.assertIn("test unavailable renderer", window.statusBar().currentMessage())
        window.play_button.click()
        self.wait_for_audio()

    def test_loop_returns_to_module_restart_after_intro(self):
        module = Module("Intro loop", [Sample("Loop", (0, 64, 0, -64), loop_length=4)], [
            Pattern(cells={(0, 0): cell("C-2", 1, "F06"), (0, 1): cell(effect="F7D"), (7, 0): cell(effect="D00")}),
            Pattern(cells={(0, 0): cell("E-2", 1), (7, 0): cell(effect="B01")}),
        ], [0, 1])
        source = self.directory / "intro.mod"
        source.write_bytes(mod.encode(module))
        self.assertTrue(self.window.open_document(source))
        self.wait_for_audio()
        plan = playback_plan(module)
        self.assertAlmostEqual(plan["loop_start_seconds"], .96)
        self.window.seek_to(1830)
        self.window.toggle_play()
        self.wait_until(lambda: 950 <= self.window.player.position() < 1500, 5)
        self.assertEqual(self.window.player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)

    def test_live_languages_and_themes_preserve_music_and_unapplied_fields(self):
        window = self.window
        original = fingerprint(window.document.module)
        self.assertEqual(window.language, "en")
        self.assertEqual(window.open_action.text(), "Open a MOD or project…")
        window.title_edit.setText("Pending title")
        window.bpm.setValue(172)
        window.sample_volume.setValue(23)
        for theme in THEMES:
            window.theme_combo.setCurrentIndex(window.theme_combo.findData(theme))
            for language in ("fr", "en"):
                window.language_combo.setCurrentIndex(window.language_combo.findData(language))
                self.app.processEvents()
                self.assertEqual(window.title_edit.text(), "Pending title")
                self.assertEqual(window.bpm.value(), 172)
                self.assertEqual(window.sample_volume.value(), 23)
                self.assertEqual(fingerprint(window.document.module), original)
                self.assertFalse(window.document.dirty)
                self.assertEqual(window.open_action.text(), "Ouvrir un MOD ou un projet…" if language == "fr" else "Open a MOD or project…")
                self.assertEqual(window.mutes[0].text(), "Voie 1" if language == "fr" else "Track 1")
                self.assertEqual(window.pattern_model.headerData(2, Qt.Orientation.Horizontal), "Effet" if language == "fr" else "Effect")
                self.assertIn(THEMES[theme]["bg"], window.styleSheet())
        window.set_language("fr")
        window.set_theme("amber")
        window.close()
        replacement = TrackerWindow(state_dir=self.state_dir)
        self.window = replacement
        replacement.output.setMuted(True)
        replacement.show()
        self.wait_for_audio()
        self.assertEqual((replacement.language, replacement.theme), ("fr", "amber"))
        self.assertEqual(replacement.theme_combo.currentText(), "Ambre")
        self.assertEqual(replacement.language_combo.currentData(), "fr")
        window.deleteLater()

    def test_clickable_track_headers_and_quick_mutes_keep_playback_running(self):
        window = self.window
        original = fingerprint(window.document.module)
        window.seek_to(10000)
        window.toggle_play()
        self.wait_until(lambda: window.player.position() > 10200)
        window.mutes[0].click()
        window.mutes[1].click()
        self.assertEqual(window.audible(), (False, False, True, True))
        self.assertIn("MUTED", window.mutes[0].text())
        self.assertEqual(window.pattern_model.data(window.pattern_model.index(0, 0), Qt.ItemDataRole.ForegroundRole).name(), THEMES[window.theme]["disabled"])
        self.wait_for_audio()
        self.wait_until(lambda: window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        self.assertGreaterEqual(window.player.position(), 10000)
        window.mutes[0].click()
        self.wait_for_audio()
        self.assertEqual(window.audible(), (True, False, True, True))
        self.assertEqual(window.mutes[0].text(), "Track 1")
        self.assertEqual(fingerprint(window.document.module), original)

    def test_meter_follows_decoded_audio_silence_and_sample_preview(self):
        window = self.window
        window.toggle_play()
        self.wait_until(lambda: window.meter.buffer_count >= 3 and max(window.meter.levels) > .001, 5)
        before = window.meter.buffer_count
        self.assertGreater(max(window.meter.raw_peaks), 0)
        window.stop()
        self.assertEqual(window.meter.levels, (0.0, 0.0))
        window.play_sample()
        self.wait_until(lambda: window.meter.buffer_count > before, 5)
        window.sample_player.stop()
        for control in window.mutes:
            control.click()
        self.wait_for_audio()
        before = window.meter.buffer_count
        window.toggle_play()
        self.wait_until(lambda: window.meter.buffer_count > before + 2, 5)
        self.assertEqual(window.meter.raw_peaks, (0.0, 0.0))
        self.assertEqual(window.meter.levels, (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
