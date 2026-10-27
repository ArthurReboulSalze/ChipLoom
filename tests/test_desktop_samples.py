"""Qt interactions against a local fixture bank and actual audio decoding."""
from __future__ import annotations

import copy
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
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import QApplication
    from tracker4agents.desktop import TrackerWindow
except ModuleNotFoundError:
    TrackerWindow = None

from tracker4agents import mod, project
from tracker4agents.document import Document, fingerprint
from tracker4agents.model import Module, Pattern, Sample
from tracker4agents.sample_library import SampleLibrary
from tracker4agents.themes import THEMES

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class DesktopSampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["sample-browser-tests"])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.app.setStyle("Fusion")
        if not QFontDatabase.families() and os.name == "nt":
            for name in ("segoeui.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sample browser ")
        self.root = Path(self.temporary.name)
        samples = [Sample("Fixture pulse", (80, -80) * 16, 40, 0, 0, 32),
                   Sample("Fixture noise", (0, 0, 50, -60, 35, -50, 20, -10, 0, 0), 30),
                   Sample("Fixture adapt", (0, 0, 80, -80, 20, -20, 0, 0), 35)]
        raw = bytearray(mod.encode(Module("Fixture bank", samples, [Pattern()], [0])))
        raw[2108 + 42:2110 + 42] = b"\x32\x20"
        source = self.root / "source.mod"
        source.write_bytes(raw)
        self.bank = SampleLibrary(self.root / "bank")
        self.bank.extract(source)
        self.window = TrackerWindow(ROOT / "examples/pixel_rush.project.json", self.root / "state", restore=False)
        self.window.output.setMuted(True)
        self.window.sample_output.setMuted(True)
        self.window.show()
        self.browser = self.window.sample_browser
        self.browser.set_library(self.bank.path)
        self.window.sample_tabs.setCurrentIndex(1)
        self.wait_until(lambda: self.window._audio_ready and not self.browser._loading and self.browser.total == 2)

    def wait_until(self, predicate, seconds=15):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(predicate(), self.window.statusBar().currentMessage())

    def select(self, sample_id):
        for row in range(self.browser.results.count()):
            if self.browser.results.item(row).data(Qt.ItemDataRole.UserRole) == sample_id:
                self.browser.results.setCurrentRow(row)
                self.app.processEvents()
                return
        self.fail(f"Missing result {sample_id}")

    def tearDown(self):
        if self.window.document and self.window.document.dirty:
            self.window.document.save_project(self.root / "test-project.json")
        self.window.close()
        self.window.pool.waitForDone(10000)
        self.app.processEvents()
        self.window.deleteLater()
        self.app.processEvents()
        self.temporary.cleanup()

    def test_filters_and_search_do_not_change_the_song(self):
        before = fingerprint(self.window.document.module)
        self.browser.category.setCurrentIndex(self.browser.category.findData("cycle"))
        self.wait_until(lambda: not self.browser._loading and not self.browser.debounce.isActive() and self.browser.total == 1)
        self.browser.role.setCurrentIndex(self.browser.role.findData("bass-candidate"))
        self.wait_until(lambda: not self.browser._loading and not self.browser.debounce.isActive())
        self.assertEqual(self.browser.entry["id"], "SMP-0001")
        self.browser.search.setText("not present")
        self.wait_until(lambda: not self.browser._loading and not self.browser.debounce.isActive() and self.browser.total == 0)
        self.assertFalse(self.browser.add_button.isEnabled())
        self.assertIn("No matching", self.browser.details.text())
        self.assertEqual(fingerprint(self.window.document.module), before)

    def test_audition_changes_note_and_feeds_real_meter_without_editing(self):
        before = fingerprint(self.window.document.module)
        self.select("SMP-0001")
        self.browser.note.setCurrentText("C-1")
        self.browser.listen.click()
        self.wait_until(lambda: self.window.sample_player.position() >= 30)
        first = self.window.sample_player.source().toLocalFile()
        self.assertEqual(self.window.sample_player.error(), QMediaPlayer.Error.NoError)
        self.browser.stop_button.click()
        buffers = self.window.meter.buffer_count
        self.browser.note.setCurrentText("C-2")
        self.browser.listen.click()
        self.wait_until(lambda: self.window.meter.buffer_count > buffers and self.window.sample_player.position() >= 30)
        self.assertNotEqual(first, self.window.sample_player.source().toLocalFile())
        self.assertGreater(max(self.window.meter.raw_peaks), 0)
        self.assertEqual(fingerprint(self.window.document.module), before)

    def test_add_undo_redo_save_and_export_embed_the_original_pcm(self):
        before = fingerprint(self.window.document.module)
        old_count = len(self.window.document.module.samples)
        self.select("SMP-0001")
        self.browser.add_button.click()
        module = self.window.document.module
        self.assertEqual(len(module.samples), old_count + 1)
        self.assertEqual(module.samples[-1], self.bank.sample("SMP-0001")[0])
        self.assertEqual(module.metadata["sample_sources"][str(old_count + 1)]["library_id"], "SMP-0001")
        self.assertTrue(self.window.document.dirty)
        self.assertEqual(self.window.samples.currentItem().data(Qt.ItemDataRole.UserRole), old_count)
        self.window.undo()
        self.assertEqual(fingerprint(self.window.document.module), before)
        self.window.redo()
        source, exported = self.root / "saved.json", self.root / "saved.mod"
        self.window.document.save_project(source)
        self.window.document.export_mod(exported)
        self.assertEqual(mod.encode(project.load(source)), exported.read_bytes())
        self.assertEqual(mod.read(exported).samples[old_count].pcm, self.bank.sample("SMP-0001")[0].pcm)

    def test_occupied_slot_requires_replace_and_does_not_rewrite_notes(self):
        before = fingerprint(self.window.document.module)
        patterns = copy.deepcopy(self.window.document.module.patterns)
        self.browser.target.setCurrentIndex(self.browser.target.findData(1))
        self.assertFalse(self.browser.add_button.isEnabled())
        self.browser.add_to_song()
        self.assertEqual(fingerprint(self.window.document.module), before)
        self.browser.replace.setChecked(True)
        self.assertTrue(self.browser.add_button.isEnabled())
        self.browser.add_button.click()
        self.assertEqual(self.window.document.module.samples[0], self.bank.sample("SMP-0001")[0])
        self.assertEqual(self.window.document.module.patterns, patterns)
        self.assertFalse(self.browser.replace.isChecked())
        unchanged = fingerprint(self.window.document.module)
        self.browser.replace.setChecked(True)
        self.browser.add_button.click()  # Replacing with the same entry is a no-op.
        self.assertEqual(fingerprint(self.window.document.module), unchanged)
        self.assertFalse(self.browser.replace.isChecked())
        self.window.undo()
        self.assertEqual(fingerprint(self.window.document.module), before)

    def test_adaptation_is_explicit_and_library_pcm_is_preserved(self):
        self.browser.compatible.setChecked(False)
        self.wait_until(lambda: not self.browser._loading and not self.browser.debounce.isActive() and self.browser.total == 3)
        self.select("SMP-0003")
        original = self.bank.read_sample("SMP-0003").pcm
        self.assertFalse(self.browser.add_button.isEnabled())
        self.browser.adapt.setChecked(True)
        self.assertTrue(self.browser.add_button.isEnabled())
        self.browser.add_button.click()
        self.assertEqual(self.window.document.module.samples[-1].pcm, (0, 0) + original)
        self.assertEqual(self.bank.read_sample("SMP-0003").pcm, original)

    def test_full_song_requires_an_explicit_replacement(self):
        module = copy.deepcopy(self.window.document.module)
        while len(module.samples) < 31:
            module.samples.append(copy.deepcopy(module.samples[0]))
        self.window.document = Document(module)
        self.window.refresh_document()
        self.assertFalse(self.browser.add_button.isEnabled())
        self.browser.target.setCurrentIndex(self.browser.target.findData(31))
        self.assertFalse(self.browser.add_button.isEnabled())
        self.browser.replace.setChecked(True)
        self.assertTrue(self.browser.add_button.isEnabled())
        self.browser.add_button.click()
        self.assertEqual(len(self.window.document.module.samples), 31)
        self.assertEqual(self.window.document.module.samples[30], self.bank.sample("SMP-0001")[0])

    def test_missing_library_and_recovery_do_not_disrupt_the_project(self):
        before = fingerprint(self.window.document.module)
        self.browser.set_library(self.root / "missing")
        self.wait_until(lambda: not self.browser._loading and self.browser._error)
        self.assertFalse(self.browser.listen.isEnabled())
        self.assertFalse(self.browser.add_button.isEnabled())
        self.assertIn("unavailable", self.browser.title.text())
        self.browser.set_library(self.bank.path)
        self.wait_until(lambda: not self.browser._loading and self.browser.total == 2)
        self.assertTrue(self.browser.listen.isEnabled())
        self.assertEqual(fingerprint(self.window.document.module), before)

    def test_language_theme_and_minimum_width_preserve_browser_choices(self):
        before = fingerprint(self.window.document.module)
        self.browser.role.setCurrentIndex(self.browser.role.findData("bass-candidate"))
        self.wait_until(lambda: not self.browser._loading and not self.browser.debounce.isActive())
        self.browser.target.setCurrentIndex(self.browser.target.findData(1))
        self.browser.replace.setChecked(True)
        self.window.resize(1080, 710)
        for theme in THEMES:
            self.window.set_theme(theme)
            for language in ("fr", "en"):
                self.window.set_language(language)
                self.app.processEvents()
                self.assertEqual(self.browser.role.currentData(), "bass-candidate")
                self.assertEqual(self.browser.target.currentData(), 1)
                self.assertTrue(self.browser.replace.isChecked())
                self.assertEqual(fingerprint(self.window.document.module), before)
                self.assertEqual(self.window.sample_tabs.tabText(1), "Bibliothèque" if language == "fr" else "Sample library")
                self.assertEqual(self.browser.add_button.text(), "Ajouter au morceau" if language == "fr" else "Add to song")
                self.assertEqual(self.window.table.horizontalScrollBar().maximum(), 0)
                self.assertLessEqual(self.browser.add_button.geometry().right(), self.browser.width())
                self.assertLess(self.window.table.columnViewportPosition(11), self.window.table.viewport().width())

    def test_stop_cancels_a_pending_audition_and_library_path_is_saved(self):
        original = self.window.cache.library_sample
        def slow(*args):
            time.sleep(.15)
            return original(*args)
        with patch.object(self.window.cache, "library_sample", side_effect=slow):
            self.browser.play()
            self.browser.stop()
            self.wait_until(lambda: not self.window._jobs)
        self.assertNotEqual(self.window.sample_player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.window.state.save()
        from tracker4agents.desktop_services import AppState
        self.assertEqual(AppState(self.root / "state").values["sample_library"], str(self.bank.path))
        original_window = self.window
        original_window.close()
        self.app.processEvents()
        self.window = TrackerWindow(state_dir=self.root / "state")
        self.window.output.setMuted(True)
        self.window.sample_output.setMuted(True)
        self.browser = self.window.sample_browser
        self.window.show()
        self.wait_until(lambda: self.window._audio_ready and not self.browser._loading and self.browser.total == 2)
        self.assertEqual(self.browser.library_path, self.bank.path)
        original_window.deleteLater()
