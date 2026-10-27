"""Real-time (libxmp + audio sink) playback in the window.

A fake sink that drains in real time stands in for the sound card, so the streaming, position, reload
and mute logic is covered on machines without an audio device. One smoke test uses the real sink.
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
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*.debug=false;qt.multimedia.*.info=false")
_LIVE_HOME = tempfile.mkdtemp(prefix="chiploom-home-")
os.environ.setdefault("CHIPLOOM_HOME", _LIVE_HOME)
atexit.register(shutil.rmtree, _LIVE_HOME, True)
try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    from tracker4agents import desktop_playback
    from tracker4agents.desktop import TrackerWindow
except ModuleNotFoundError:
    TrackerWindow = None

from tracker4agents.desktop_services import AppState
from tracker4agents.document import Document, fingerprint
from tracker4agents.model import Module, Pattern, Sample, cell
from tracker4agents.realtime import find_library

ROOT = Path(__file__).resolve().parents[1]
RATE, FRAME = 48000, 4


class FakeDevice:
    def __init__(self, sink):
        self.sink = sink

    def write(self, data):
        sink = self.sink
        sink._drain()
        room = max(0, sink.size - sink.queued)
        accepted = bytes(data[:room])
        sink.queued += len(accepted)
        sink.writes.append((time.monotonic(), accepted))
        return len(accepted)


class FakeSink(QObject):
    """A sound card that consumes audio in real time."""

    stateChanged = Signal(object)
    instances: list = []

    def __init__(self, volume=1.0):
        super().__init__()
        self.size = RATE // 4 * FRAME
        self.queued = 0
        self.volume = volume
        self.writes: list[tuple[float, bytes]] = []
        self.starts = 0
        self._last = time.monotonic()
        FakeSink.instances.append(self)

    def _drain(self):
        now = time.monotonic()
        self.queued = max(0, self.queued - int((now - self._last) * RATE) * FRAME)
        self._last = now

    def start(self):
        self.starts += 1
        self.queued, self._last = 0, time.monotonic()
        return FakeDevice(self)

    def stop(self):
        self.queued = 0

    def bufferSize(self):
        return self.size

    def bytesFree(self):
        self._drain()
        return self.size - self.queued

    def setVolume(self, volume):
        self.volume = volume


def peak(pcm: bytes) -> int:
    return max((abs(int.from_bytes(pcm[index:index + 2], "little", signed=True)) for index in range(0, len(pcm), 2)),
               default=0)


def short_song(rows: int = 8) -> Module:
    sample = Sample("Lead", (0, 0) + (60, 0, -60, 0) * 16, 64)
    cells = {(0, 0): cell("C-2", 1), (2, 1): cell("E-2", 1), (rows - 1, 3): cell(effect="D00")}
    return Module("Short", [sample], [Pattern(cells=cells)], [0])


@unittest.skipUnless(TrackerWindow is not None and find_library(), "PySide6 and libxmp required")
class RealtimePlaybackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["realtime-tests"])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.app.setStyle("Fusion")
        if not QFontDatabase.families() and os.name == "nt":
            for name in ("segoeui.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.patches = [patch.dict(os.environ, {"CHIPLOOM_HOME": str(self.directory / "home")}),
                        patch.object(desktop_playback, "make_sink", FakeSink),
                        patch.object(desktop_playback, "output_available", lambda: True)]
        for item in self.patches:
            item.start()
        os.environ.pop("CHIPLOOM_PLAYBACK", None)
        FakeSink.instances.clear()
        self.path = self.directory / "pixel.project.json"
        Document.open(ROOT / "examples/pixel_rush.project.json").save_project(self.path)
        self.window = self.make_window(self.path)

    def make_window(self, path):
        window = TrackerWindow(path, self.directory / "state", restore=False)
        window.output.setMuted(True)
        window.show()
        self.wait_until(lambda: window.document is not None and window._audio_ready, window=window)
        window.cache.prepare = unittest.mock.Mock(side_effect=AssertionError("a WAV was rendered"))
        return window

    def tearDown(self):
        window = self.window
        if window.document and window.document.dirty:
            window.document.save_project(self.directory / "tear-down.project.json")
        window.close()
        window.pool.waitForDone(10000)
        self.app.processEvents()
        window.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def wait_until(self, predicate, seconds=15, window=None):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate(), (window or self.window).statusBar().currentMessage())

    def pause(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)

    def sink(self):
        return FakeSink.instances[-1]

    def heard(self):
        return self.window.rt.heard()

    # --- streaming and position ------------------------------------------------------
    def test_play_streams_audio_and_the_view_follows_what_is_heard(self):
        window, rt = self.window, self.window.rt
        self.assertIsNotNone(rt)
        self.assertTrue(window.realtime_action.isChecked())
        self.assertEqual(window.seek.maximum(), round(window.plan["duration_seconds"] * 1000))
        window.toggle_play()
        self.assertTrue(rt.playing)
        self.assertEqual(window.play_button.text(), "Pause")
        self.pause(.9)
        milliseconds, marker = self.heard()
        self.assertTrue(500 < milliseconds < 1500, milliseconds)
        self.assertEqual((marker["order"], marker["row"] >= 0), (0, True))
        # The heard position trails what was rendered: it is the written frames minus those still queued.
        queued = rt._queued_frames()
        self.assertTrue(0 < queued <= desktop_playback.BUFFER_FRAMES)
        self.assertLess(milliseconds, rt._rendered * 1000 / RATE)
        self.assertGreater(window.seek.value(), 400)
        window._sync_position()
        _, marker = self.heard()
        self.assertEqual(window.pattern_model.playing_row, marker["row"])
        self.assertGreater(window.meter.buffer_count, 3)
        self.assertGreater(max(window.meter.raw_peaks), 0)
        self.assertGreater(peak(b"".join(data for _, data in self.sink().writes)), 1000)
        window.cache.prepare.assert_not_called()

    def test_row_highlight_tracks_the_heard_marker_through_orders(self):
        window = self.window
        window.toggle_play()
        window.seek_to(round(next(entry["seconds"] for entry in window.plan["timeline"] if entry["order"] == 3) * 1000))
        self.pause(.5)
        window._sync_position()
        self.assertEqual(window.current_order, 3)
        _, marker = self.heard()
        self.assertEqual(marker["order"], 3)
        self.assertEqual(window.pattern_model.pattern, marker["pattern"])
        self.assertEqual(window.pattern_model.playing_row, marker["row"])

    def test_pause_parks_on_the_heard_row_and_resumes_from_it_and_stop_rewinds(self):
        window, rt = self.window, self.window.rt
        window.toggle_play()
        self.pause(1.0)
        window.toggle_play()
        self.assertFalse(rt.playing)
        self.assertEqual(window.play_button.text(), "Play")
        paused = rt.position_ms()
        self.assertTrue(500 < paused < 1500, paused)
        self.pause(.3)
        self.assertEqual(rt.position_ms(), paused)  # frozen while paused
        window.toggle_play()
        self.pause(.4)
        self.assertGreaterEqual(rt.position_ms(), paused)
        window.stop()
        self.assertFalse(rt.playing)
        self.assertEqual((rt.position_ms(), window.player.position()), (0, 0))
        window._sync_position()
        self.assertEqual(window.seek.value(), 0)

    def test_seek_while_playing_and_while_stopped(self):
        window, rt = self.window, self.window.rt
        window.toggle_play()
        self.pause(.3)
        window.seek_to(5000)
        self.pause(.2)
        self.assertTrue(4800 <= rt.position_ms() < 6500, rt.position_ms())
        window.orders.setCurrentIndex(4)
        self.pause(.2)
        self.assertEqual(self.heard()[1]["order"], 4)
        window.stop()
        window.seek_to(8000)
        self.assertEqual(rt.position_ms(), 8000)
        window.seek_row(0)
        window.toggle_play()
        self.pause(.3)
        self.assertGreaterEqual(rt.position_ms(), 7800)
        self.assertEqual(window.start_playback(), None)  # already playing: a live "play" request changes nothing
        self.assertTrue(rt.playing)
        window.cache.prepare.assert_not_called()

    # --- edits ---------------------------------------------------------------------------
    def test_an_edit_while_playing_reloads_the_engine_instantly_and_keeps_playing(self):
        window, rt = self.window, self.window.rt
        start = round(next(entry["seconds"] for entry in window.plan["timeline"] if entry["order"] == 2) * 1000)
        window.toggle_play()
        window.seek_to(start)
        self.pause(.4)
        before = b"".join(data for _, data in self.sink().writes[-20:])
        self.assertGreater(peak(before), 1000)
        pattern = window.document.module.orders[2]
        reloads, order = rt.reloads, self.heard()[1]["order"]
        edited_at = time.monotonic()
        self.assertTrue(window.apply_patch([{"op": "clear", "pattern": pattern, "row": 0, "rows": 64, "channel": 0,
                                            "channels": 4}], "Silence"))
        self.assertEqual(rt.reloads, reloads + 1)  # immediate, no debounce
        self.assertTrue(rt.playing)
        self.pause(.5)
        self.assertTrue(rt.playing)
        self.assertEqual(self.heard()[1]["order"], order)  # same part of the song, not restarted
        self.assertEqual(self.heard()[1]["bpm"], 160)  # and still at the song's tempo, not libxmp's 125 default
        after = b"".join(data for moment, data in self.sink().writes if moment > edited_at)
        self.assertGreater(len(after), RATE * FRAME // 4)
        self.assertEqual(peak(after), 0)  # everything rendered after the edit is the edited, silent pattern
        window.undo()  # undo is just another reload
        self.assertEqual(rt.reloads, reloads + 2)
        self.pause(.6)
        self.assertGreater(peak(b"".join(data for _, data in self.sink().writes[-10:])), 1000)
        window.cache.prepare.assert_not_called()

    def test_edits_while_stopped_reload_and_play_starts_from_the_cursor_position(self):
        window, rt = self.window, self.window.rt
        window.seek_to(7000)
        reloads = rt.reloads
        window.apply_patch([{"op": "set", "pattern": 0, "row": 1, "channel": 1, "cell": "C-2 01 ..."}], "Note")
        self.assertEqual(rt.reloads, reloads + 1)
        self.assertEqual(rt.position_ms(), 7000)
        window.toggle_play()
        self.pause(.3)
        self.assertGreaterEqual(rt.position_ms(), 6800)
        self.assertEqual(self.heard()[1]["bpm"], 160)
        window.cache.prepare.assert_not_called()

    def test_agent_patches_and_file_reloads_reach_the_engine(self):
        window, rt = self.window, self.window.rt
        window.toggle_play()
        self.pause(.2)
        reloads = rt.reloads
        window.live.session.apply_patch([{"op": "set", "pattern": 0, "row": 5, "channel": 2, "cell": "G-2 01 ..."}], "agent")
        self.assertEqual(rt.reloads, reloads + 1)
        agent = Document.open(self.path)
        agent.rename("Rewritten")
        agent.save_project(self.path)
        self.wait_until(lambda: window.document.module.title == "Rewritten")
        self.assertEqual(rt.reloads, reloads + 2)
        self.assertTrue(rt.playing)
        window.cache.prepare.assert_not_called()

    def test_mute_and_solo_apply_to_the_engine_without_rendering(self):
        window, rt = self.window, self.window.rt
        window.toggle_play()
        self.pause(.2)
        reloads = rt.reloads
        window.mutes[0].click()
        self.assertEqual(rt.engine.audible, (False, True, True, True))
        window.solos[1].click()
        self.assertEqual(rt.engine.audible, (False, True, False, False))
        window.solos[1].click()
        window.mutes[0].click()
        self.assertEqual(rt.engine.audible, (True, True, True, True))
        self.assertEqual(rt.reloads, reloads)
        self.assertTrue(rt.playing)
        window.cache.prepare.assert_not_called()
        # Muting every lane silences the stream while the song keeps running.
        for control in window.mutes:
            control.click()
        self.pause(.5)
        written = self.sink().writes[-3:]
        self.assertEqual(peak(b"".join(data for _, data in written)), 0)
        self.assertTrue(rt.playing)

    def test_the_loop_checkbox_controls_the_engine_and_a_finished_song_rests_at_the_start(self):
        window, rt = self.window, self.window.rt
        path = self.directory / "short.project.json"
        Document(short_song()).save_project(path)
        self.assertTrue(window.open_document(path))
        self.wait_until(lambda: window.document.module.title == "Short" and window._audio_ready)
        self.assertTrue(rt.engine.loop)
        window.toggle_play()
        self.pause(2.4)  # looped at least twice (the song lasts about one second)
        self.assertTrue(rt.playing)
        window.loop.setChecked(False)
        self.assertFalse(rt.engine.loop)
        self.wait_until(lambda: not rt.playing, 6)
        self.assertEqual(rt.position_ms(), 0)
        self.assertEqual(window.play_button.text(), "Play")
        window.toggle_play()  # plays again from the start
        self.assertTrue(rt.playing)
        window.loop.setChecked(True)
        self.assertTrue(rt.engine.loop)

    def test_volume_and_preferences(self):
        window = self.window
        window.volume.setValue(30)
        self.assertEqual(window.rt.volume, .3)
        window.toggle_play()
        self.assertAlmostEqual(self.sink().volume, .3)
        window.volume.setValue(80)
        self.assertAlmostEqual(self.sink().volume, .8)
        window.realtime_action.setChecked(False)  # back to the rendered path
        self.assertIsNone(window.rt)
        self.assertIs(AppState(self.directory / "state").values["realtime"], False)
        window.cache.prepare = unittest.mock.Mock(wraps=type(window.cache).prepare.__get__(window.cache))
        window.prepare_audio()
        self.wait_until(lambda: window._audio_ready, 30)
        self.assertTrue(window.cache.prepare.called)
        window.realtime_action.setChecked(True)
        self.assertIsNotNone(window.rt)
        self.assertTrue(window._audio_ready)

    def test_the_session_state_remembers_the_preference(self):
        window = self.window
        window.realtime_action.setChecked(False)
        window.close()
        self.app.processEvents()
        self.window = self.make_rendered_window()
        self.assertIsNone(self.window.rt)
        self.assertFalse(self.window.realtime_action.isChecked())
        self.assertTrue(self.window.realtime_action.isEnabled())
        self.assertEqual(self.window.play_button.toolTip(), "")  # switched off by choice, not a missing library

    def make_rendered_window(self):
        window = TrackerWindow(self.path, self.directory / "state", restore=False)
        window.output.setMuted(True)
        window.show()
        self.wait_until(lambda: window.document is not None and window._audio_ready, 30, window=window)
        return window

    # --- fallback ------------------------------------------------------------------------
    def test_without_libxmp_the_rendered_player_is_used_and_the_user_is_told_once(self):
        self.window.close()
        with patch.object(desktop_playback, "find_library", return_value=None):
            window = self.window = TrackerWindow(self.path, self.directory / "state2", restore=False)
        window.output.setMuted(True)
        window.show()
        self.assertIsNone(window.rt)
        self.assertFalse(window.realtime_action.isChecked())
        self.assertIn("libxmp", window.play_button.toolTip())
        self.wait_until(lambda: window._audio_ready, 30)
        self.assertEqual(window.player.error().name, "NoError")
        self.assertIn("libxmp", window._last_message[0])
        window.toggle_play()
        self.wait_until(lambda: window.player.position() > 50, 10)
        self.assertTrue(window.is_playing())
        window.stop()
        self.assertEqual(window.cache.directory.name, "audio-cache")

    def test_the_environment_override_forces_rendered_playback(self):
        self.window.close()
        with patch.dict(os.environ, {"CHIPLOOM_PLAYBACK": "rendered"}):
            window = self.window = self.make_rendered_window()
        self.assertIsNone(window.rt)
        self.assertFalse(window.realtime_action.isEnabled())
        self.assertEqual(window.play_button.toolTip(), "")

    def test_a_module_libxmp_refuses_falls_back_to_the_rendered_path(self):
        window = self.window
        with patch.object(window.rt.engine, "load", side_effect=desktop_playback.RealtimeError("boom")):
            window.prepare_audio(False, 0)
        self.assertIsNone(window.rt)
        self.assertIn("boom", window.play_button.toolTip())
        self.wait_until(lambda: window._audio_ready or window._loading_audio, 5)

    def test_documents_are_never_modified_by_playback(self):
        window = self.window
        original = fingerprint(window.document.module)
        window.toggle_play()
        window.seek_to(3000)
        self.pause(.4)
        window.stop()
        self.assertEqual(fingerprint(window.document.module), original)
        self.assertFalse(window.document.dirty)


@unittest.skipUnless(TrackerWindow is not None and find_library(), "PySide6 and libxmp required")
class RealSinkSmokeTest(unittest.TestCase):
    def test_the_real_audio_sink_plays_the_song_silently(self):
        app = QApplication.instance() or QApplication(["realtime-smoke"])
        if not desktop_playback.output_available():
            self.skipTest("no audio output device")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CHIPLOOM_HOME": directory}):
            os.environ.pop("CHIPLOOM_PLAYBACK", None)
            window = TrackerWindow(ROOT / "examples/pixel_rush.project.json", Path(directory) / "state", restore=False)
            window.volume.setValue(0)  # real device, no sound
            window.show()
            deadline = time.monotonic() + 10
            while not (window.rt and window._audio_ready) and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            self.assertIsNotNone(window.rt)
            window.toggle_play()
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.005)
            self.assertIn(window.rt.sink.state().name, ("ActiveState", "IdleState"))
            self.assertGreater(window.rt.position_ms(), 500)
            self.assertLessEqual(window.rt.underruns, 2)
            window.close()
            window.pool.waitForDone(5000)


if __name__ == "__main__":
    unittest.main()
