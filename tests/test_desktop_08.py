"""0.8 consolidation of the window: block drag and drop, A/B listening to a take, the agent-connected
indicator and asynchronous `open` requests.

Mouse gestures are real Qt mouse events sent to the pattern viewport (offscreen). The A/B tests use the
real-time engine behind the same fake sound card as test_desktop_realtime; one A/B test covers the
rendered fallback. Everything runs on temporary projects.
"""
from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
import importlib
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*.debug=false;qt.multimedia.*.info=false")
_LIVE_HOME = tempfile.mkdtemp(prefix="chiploom-home-")
os.environ.setdefault("CHIPLOOM_HOME", _LIVE_HOME)
atexit.register(shutil.rmtree, _LIVE_HOME, True)
try:
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QFontDatabase, QKeyEvent, QMouseEvent
    from PySide6.QtWidgets import QAbstractItemView, QApplication, QMessageBox
    from tracker4agents import desktop_live, desktop_playback
    from tracker4agents.desktop import TrackerWindow
    from tracker4agents.desktop_widgets import media_call
except ModuleNotFoundError:
    TrackerWindow = None

from tracker4agents.document import Document, fingerprint
from tracker4agents.live import LiveClient, discover
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell
from tracker4agents.realtime import find_library
from tracker4agents.themes import THEMES

PACKAGE = __package__ + "." if __package__ else ""
LEFT, NONE = (Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton) if TrackerWindow else (None, None)
CTRL = Qt.KeyboardModifier.ControlModifier if TrackerWindow else None
NO_MODIFIER = Qt.KeyboardModifier.NoModifier if TrackerWindow else None


def song(title="Eight") -> Module:
    samples = [Sample(name, (0, 0) + (60, 0, -60, 0) * 16, 64) for name in ("Kick", "Snare", "Lead")]
    cells = {(0, 0): cell("C-2", 1), (1, 0): cell("D-2", 2), (0, 1): cell("E-2", 1, "C20"), (1, 1): cell("F-2", 3),
             (8, 2): cell("G-2", 1)}
    return Module(title, samples, [Pattern(name="Intro", cells=cells), Pattern(name="Verse")], [0, 1, 0])


def looping_sample() -> Sample:
    return Sample("Lead", (0, 0) + (100, 0, -100, 0) * 16, 64, 0, 2, 64)


def loud_song(title="Current") -> Module:
    """One pattern with a looping note held all through it."""
    return Module(title, [looping_sample()], [Pattern(cells={(0, 0): cell("C-2", 1), (63, 3): cell(effect="D00")})], [0])


def silent_take(title="Quiet take") -> Module:
    return Module(title, [looping_sample()], [Pattern(cells={(63, 3): cell(effect="D00")})], [0])


class WindowCase(unittest.TestCase):
    """A window on a temporary project, with its live server in a private CHIPLOOM_HOME."""
    playback = "rendered"
    fonts_ready = False
    make_song = staticmethod(song)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["desktop-08-tests"])
        cls.app.setQuitOnLastWindowClosed(False)
        if cls.app.property("chiploomFusion") is None:   # restyling widgets left by earlier modules can stall
            cls.app.setStyle("Fusion")
            cls.app.setProperty("chiploomFusion", True)
        if not WindowCase.fonts_ready:   # once per run: enumerating fonts can stall on a loaded machine
            WindowCase.fonts_ready = True
            if not QFontDatabase.families() and os.name == "nt":
                for name in ("segoeui.ttf", "consola.ttf"):
                    QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # Windows frees media files a little late
        self.directory = Path(self.temporary.name)
        self.home = self.directory / "home"
        self.patches = [patch.dict(os.environ, {"CHIPLOOM_HOME": str(self.home)})]
        if self.playback == "rendered":
            self.patches.append(patch.dict(os.environ, {"CHIPLOOM_PLAYBACK": "rendered"}))
        self.patches += self.extra_patches()
        for item in self.patches:
            item.start()
        if self.playback != "rendered":
            os.environ.pop("CHIPLOOM_PLAYBACK", None)
        self.path = self.directory / "work.project.json"
        Document(self.make_song()).save_project(self.path)
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.window = TrackerWindow(self.path, self.directory / "state", restore=False)
        self.window.output.setMuted(True)
        self.window.sample_output.setMuted(True)
        self.window.show()
        self.wait_until(lambda: self.window.document is not None and self.window.live.server is not None
                        and self.window._audio_ready)
        self.table, self.model = self.window.table, self.window.pattern_model

    def extra_patches(self):
        return []

    def tearDown(self):
        window = self.window
        window.document.dirty and window.document.save_project(self.directory / "tear-down.project.json")
        for player in (window.sample_player, window.player):   # let go of audition files before the window goes
            media_call(player, "stop")
        self.app.processEvents()
        window.close()
        window.pool.waitForDone(10000)
        self.app.processEvents()
        window.deleteLater()
        self.app.processEvents()
        self.pool.shutdown(wait=True)
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def wait_until(self, predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(predicate(), self.window.statusBar().currentMessage())

    def pause(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)

    def cell(self, row, channel, pattern=0):
        return self.window.document.module.patterns[pattern].get(row, channel)

    def agent(self):
        return LiveClient.discover(home=self.home)

    def call(self, method, **params):
        """An agent call from another thread while the GUI thread keeps processing events."""
        future = self.pool.submit(self.agent().call, method, **params)
        self.wait_until(future.done, 30)
        return future.result()

    def write_take(self, module, name="take.project.json"):
        target = self.directory / name
        Document(module).save_project(target)
        return target


# --- 1. dragging blocks ----------------------------------------------------------------------
@unittest.skipUnless(TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class BlockDragTests(WindowCase):
    def point(self, row, column):
        return self.table.visualRect(self.model.index(row, column)).center()

    def send(self, kind, pos, buttons=LEFT, modifiers=NO_MODIFIER, button=LEFT):
        viewport = self.table.viewport()
        QApplication.sendEvent(viewport, QMouseEvent(kind, QPointF(pos), QPointF(viewport.mapToGlobal(pos)),
                                                     button, buttons, modifiers))

    def press(self, row, column, modifiers=NO_MODIFIER):
        self.send(QEvent.Type.MouseButtonPress, self.point(row, column), LEFT, modifiers)

    def move(self, row, column, modifiers=NO_MODIFIER):
        self.send(QEvent.Type.MouseMove, self.point(row, column), LEFT, modifiers, NONE)

    def release(self, row, column, modifiers=NO_MODIFIER):
        self.send(QEvent.Type.MouseButtonRelease, self.point(row, column), NONE, modifiers)

    def drag(self, source, target, modifiers=NO_MODIFIER):
        self.press(*source)
        self.move(*source)
        self.move(*target, modifiers)
        self.release(*target, modifiers)

    def pattern_pixel(self, x, y):
        return self.table.viewport().grab().toImage().pixelColor(x, y).name()

    def test_dragging_a_selected_block_moves_it_with_a_drop_indicator_and_one_undo(self):
        window, table = self.window, self.table
        table.scrollToTop()
        table.select_block(0, 2, 0, 2)
        before, revision = fingerprint(window.document.module), window.document.revision
        self.press(0, 0)
        self.assertFalse(table.block_dragging())
        self.move(1, 0)
        self.move(5, 3)    # row 5, the note column of channel 2: the block (rows 0-1, channels 1-2) lands there
        self.assertTrue(table.block_dragging())
        self.assertEqual(table.drop_target(), (5, 1))
        rect = table.drop_rect()
        self.assertEqual(rect, table.visualRect(self.model.index(5, 3)).united(table.visualRect(self.model.index(6, 8))))
        self.assertEqual(self.pattern_pixel(rect.left() + 2, rect.center().y()), THEMES[window.theme]["accent"])
        self.assertEqual(fingerprint(window.document.module), before)   # nothing changes until the drop
        self.release(5, 3)
        self.assertFalse(table.block_dragging())
        self.assertIsNone(table.drop_rect())
        self.assertEqual((self.cell(5, 1), self.cell(6, 1)), (cell("C-2", 1), cell("D-2", 2)))
        self.assertEqual((self.cell(5, 2), self.cell(6, 2)), (cell("E-2", 1, "C20"), cell("F-2", 3)))
        self.assertEqual((self.cell(0, 0), self.cell(1, 0), self.cell(0, 1), self.cell(1, 1)), (cell(),) * 4)
        self.assertEqual(table.selection_block(), (5, 2, 1, 2))   # the selection follows the block
        self.assertEqual(window.document.revision, revision + 1)  # one patch
        self.assertEqual(window.live.session.changes()["entries"][-1]["label"], "Move block")
        window.undo()                                             # one undo step
        self.assertEqual(fingerprint(window.document.module), before)
        self.assertFalse(window.document.can_undo)

    def test_ctrl_drag_copies_the_block_and_the_source_stays(self):
        window, table = self.window, self.table
        table.scrollToTop()
        table.select_block(0, 2, 0, 1)
        before = fingerprint(window.document.module)
        self.press(1, 0)                   # grabbed by its second row
        self.move(3, 6, CTRL)              # Ctrl pressed during the drag
        self.assertTrue(table.block_dragging())
        self.assertEqual(table.drop_target(), (2, 2))   # the grab offset keeps the second row under the pointer
        self.assertEqual(self.pattern_pixel(table.drop_rect().left() + 2, table.drop_rect().center().y()),
                         THEMES[window.theme]["human_change"])
        self.release(3, 6, CTRL)
        self.assertEqual((self.cell(0, 0), self.cell(1, 0)), (cell("C-2", 1), cell("D-2", 2)))
        self.assertEqual((self.cell(2, 2), self.cell(3, 2)), (cell("C-2", 1), cell("D-2", 2)))
        self.assertEqual(table.selection_block(), (2, 2, 2, 1))
        self.assertEqual(window.live.session.changes()["entries"][-1]["label"], "Copy block")
        window.undo()
        self.assertEqual(fingerprint(window.document.module), before)

    def test_pressing_an_unselected_cell_still_drags_a_selection(self):
        window, table = self.window, self.table
        table.scrollToTop()
        table.select_block(0, 2, 0, 1)
        before = fingerprint(window.document.module)
        self.press(10, 6)
        self.move(10, 6)
        self.move(12, 8)
        self.assertFalse(table.block_dragging())
        self.release(12, 8)
        self.assertEqual(table.selection_block(), (10, 3, 2, 1))
        self.assertEqual(fingerprint(window.document.module), before)

    def test_clicking_the_selected_block_selects_just_that_cell_and_changes_nothing(self):
        window, table = self.window, self.table
        table.scrollToTop()
        table.select_block(0, 2, 0, 2)
        before, revision = fingerprint(window.document.module), window.document.revision
        self.press(1, 3)
        self.assertEqual(table.selection_block(), (0, 2, 0, 2))   # the block survives the press itself
        self.send(QEvent.Type.MouseMove, self.point(1, 3) + QPoint(3, 2), LEFT, NO_MODIFIER, NONE)   # a wobble
        self.assertFalse(table.block_dragging())
        self.release(1, 3)
        self.assertEqual(table.selection_block(), (1, 1, 1, 1))
        self.assertEqual((fingerprint(window.document.module), window.document.revision), (before, revision))

    def test_double_click_edits_a_cell_whether_or_not_it_is_selected(self):
        table = self.table
        table.scrollToTop()
        for selected in (True, False):
            table.select_block(0, 2, 0, 1) if selected else table.select_block(10, 1, 3, 1)
            point = self.point(0, 0)
            self.send(QEvent.Type.MouseButtonPress, point, LEFT)
            self.send(QEvent.Type.MouseButtonRelease, point, NONE)
            self.send(QEvent.Type.MouseButtonDblClick, point, LEFT)
            self.send(QEvent.Type.MouseButtonRelease, point, NONE)
            self.assertEqual(table.state(), QAbstractItemView.State.EditingState, f"selected={selected}")
            QApplication.sendEvent(QApplication.focusWidget(), QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                                                         NO_MODIFIER))
            self.pause(.02)
            self.assertNotEqual(table.state(), QAbstractItemView.State.EditingState)

    def test_escape_abandons_the_drag_and_the_rest_of_the_gesture_is_ignored(self):
        window, table = self.window, self.table
        table.scrollToTop()
        table.select_block(0, 2, 0, 2)
        before = fingerprint(window.document.module)
        self.press(0, 0)
        self.move(6, 0)
        self.assertTrue(table.block_dragging())
        QApplication.sendEvent(table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, NO_MODIFIER))
        self.assertFalse(table.block_dragging())
        self.assertIsNone(table.drop_rect())
        self.move(9, 7)                    # still holding the button: no selection is dragged out either
        self.release(9, 7)
        self.assertEqual(table.selection_block(), (0, 2, 0, 2))
        self.assertEqual(fingerprint(window.document.module), before)

    def test_dropping_where_it_was_changes_nothing_and_drops_clamp_to_the_pattern(self):
        window, table = self.window, self.table
        table.scrollToTop()
        table.select_block(0, 2, 0, 1)
        before, revision = fingerprint(window.document.module), window.document.revision
        self.press(0, 0)
        self.move(4, 0)
        self.move(0, 0)                    # back where it started
        self.release(0, 0)
        self.assertEqual((fingerprint(window.document.module), window.document.revision), (before, revision))
        self.assertFalse(window.document.dirty)
        self.press(0, 0)
        self.move(1, 0)
        table.scrollToBottom()
        self.move(63, 9)                   # past the last row and the last channel: clamped to rows 62-63, channel 4
        self.assertEqual(table.drop_target(), (62, 3))
        self.release(63, 9)
        self.assertEqual((self.cell(62, 3), self.cell(63, 3)), (cell("C-2", 1), cell("D-2", 2)))

    def test_the_view_scrolls_while_a_block_waits_near_its_edge(self):
        table = self.table
        table.scrollToTop()
        table.select_block(0, 1, 0, 1)
        self.press(0, 0)
        self.move(1, 0)
        edge = QPoint(table.visualRect(self.model.index(0, 0)).center().x(), table.viewport().height() - 5)
        self.send(QEvent.Type.MouseMove, edge, LEFT, NO_MODIFIER, NONE)
        self.assertTrue(table.block_dragging())
        first = table.drop_target()
        self.assertEqual(table.verticalScrollBar().value(), 0)
        table._drag_autoscroll()           # what the timer does while the pointer rests at the edge
        self.assertEqual(table.verticalScrollBar().value(), 1)
        self.assertEqual(table.drop_target()[0], first[0] + 1)   # the row under the pointer moved on
        self.send(QEvent.Type.MouseButtonRelease, edge, NONE)


# --- 2. A/B listening ------------------------------------------------------------------------
@unittest.skipUnless(TrackerWindow is not None and find_library(), "PySide6 and libxmp required")
class CompareRealtimeTests(WindowCase):
    playback = "realtime"
    make_song = staticmethod(loud_song)

    def extra_patches(self):
        rt_tests = importlib.import_module(PACKAGE + "test_desktop_realtime")
        self.fake = rt_tests.FakeSink
        self.fake.instances.clear()
        return [patch.object(desktop_playback, "make_sink", rt_tests.FakeSink),
                patch.object(desktop_playback, "output_available", lambda: True)]

    def setUp(self):
        super().setUp()
        self.window.cache.prepare = Mock(side_effect=AssertionError("a WAV was rendered"))
        self.session = self.window.live.session
        self.take = self.session.add_take(self.write_take(silent_take()), "Quiet", "agent")
        self.panel = self.window.agent_panel
        self.wait_until(lambda: self.panel.take_list.count() == 1)

    def recent_peak(self, seconds=.3):
        deadline = time.monotonic() - seconds
        data = b"".join(chunk for moment, chunk in self.fake.instances[-1].writes if moment > deadline)
        return max((abs(int.from_bytes(data[i:i + 2], "little", signed=True)) for i in range(0, len(data), 2)), default=0)

    def test_comparing_switches_what_is_heard_at_the_same_position_and_never_edits_the_document(self):
        window, panel, rt = self.window, self.panel, self.window.rt
        self.assertIsNotNone(rt)
        document = window.document
        state = (fingerprint(document.module), document.revision, document.dirty, document.can_undo, self.session.revision)
        window.toggle_play()
        self.pause(.7)
        self.assertGreater(self.recent_peak(), 1000)      # the current song (A) is loud
        self.assertFalse(panel.compare_stop_button.isEnabled())
        panel.take_list.setCurrentRow(0)
        panel.compare_button.click()
        self.assertEqual((panel.compare["side"], panel.compare["take"]), ("B", self.take["id"]))
        self.assertIs(window.monitor_module, panel.compare["module"])
        self.assertIn("take t1 · Quiet (B)", panel.compare_label.text())
        self.assertEqual(panel.compare_label.property("side"), "B")
        self.assertEqual(panel.compare_button.text(), "Listen to current song (A)")
        self.assertIn("listening to a take", window.windowTitle())
        self.assertTrue(rt.wait_idle())
        started = rt.position_ms()
        self.assertGreater(started, 400)                  # same place in the song, not restarted
        self.pause(.8)
        self.assertEqual(self.recent_peak(.3), 0)         # the take (B) is silent
        self.assertGreater(rt.position_ms(), started)
        self.assertTrue(rt.playing)
        panel.compare_button.click()                      # back to A, still the same song position
        self.assertEqual(panel.compare["side"], "A")
        self.assertIsNone(window.monitor_module)
        self.assertEqual(panel.compare_label.property("side"), "A")
        self.assertEqual(panel.compare_button.text(), "Listen to take (B)")
        self.assertNotIn("listening to a take", window.windowTitle())
        self.pause(.8)
        self.assertGreater(self.recent_peak(.3), 1000)
        self.assertGreater(rt.position_ms(), started)
        window.cache.prepare.assert_not_called()
        self.assertEqual((fingerprint(document.module), document.revision, document.dirty, document.can_undo,
                          self.session.revision), state)
        panel.end_compare()
        self.assertIsNone(panel.compare)
        self.assertFalse(panel.compare_stop_button.isEnabled())
        self.assertEqual(panel.compare_label.text(), "")

    def test_ctrl_b_switches_and_starts_the_transport_when_stopped(self):
        window, panel, rt = self.window, self.panel, self.window.rt
        self.assertFalse(rt.playing)
        panel.take_list.setCurrentRow(0)
        window.agent_panel.toggle_compare()               # what the Ctrl+B menu action calls
        self.assertTrue(rt.playing)
        self.assertEqual(panel.compare["side"], "B")
        agent_menu = next(item.menu() for item in window.menuBar().actions() if item.text() == window.t("Agent"))
        action = next(item for item in agent_menu.actions() if "Compare" in item.text())
        self.assertEqual(action.shortcut().toString(), "Ctrl+B")
        action.trigger()
        self.assertEqual(panel.compare["side"], "A")
        action.trigger()
        self.assertEqual(panel.compare["side"], "B")

    def test_an_edit_while_hearing_the_take_returns_to_the_current_song(self):
        window, panel = self.window, self.panel
        panel.take_list.setCurrentRow(0)
        panel.toggle_compare()
        self.assertIsNotNone(window.monitor_module)
        self.assertTrue(window.apply_patch([{"op": "set", "pattern": 0, "row": 1, "channel": 2, "cell": "E-2 01 ..."}], "Mine"))
        self.assertEqual(panel.compare["side"], "A")      # the owner hears their own edit
        self.assertIsNone(window.monitor_module)
        self.assertEqual(panel.compare_button.text(), "Listen to take (B)")
        # An agent's change does not pull the owner away from the take being compared.
        panel.toggle_compare()
        self.assertEqual(panel.compare["side"], "B")
        self.session.apply_patch([{"op": "set", "pattern": 0, "row": 2, "channel": 2, "cell": "G-2 01 ..."}], "agent", "Idea")
        self.assertEqual(panel.compare["side"], "B")
        self.assertIsNotNone(window.monitor_module)

    def test_opening_another_document_ends_the_comparison(self):
        window, panel = self.window, self.panel
        panel.take_list.setCurrentRow(0)
        panel.toggle_compare()
        other = self.write_take(loud_song("Other"), "other.project.json")
        self.assertTrue(window.open_document(other, ask=False))
        self.assertIsNone(panel.compare)
        self.assertIsNone(window.monitor_module)
        self.assertEqual(window.document.module.title, "Other")

    def test_without_a_take_there_is_nothing_to_compare(self):
        window, panel = self.window, self.panel
        panel.end_compare()
        panel.take_list.clear()
        self.assertFalse(panel.toggle_compare())
        self.assertIn("take", window.statusBar().currentMessage())
        self.assertIsNone(panel.compare)

    def test_take_selection_survives_panel_refreshes(self):
        panel = self.panel
        self.session.add_take(self.write_take(silent_take("Second"), "second.project.json"), "Second", "agent")
        self.wait_until(lambda: panel.take_list.count() == 2)
        panel.take_list.setCurrentRow(1)
        panel.refresh()
        self.assertEqual(panel.take_list.currentRow(), 1)
        self.assertEqual(panel.chosen_take()["label"], "Second")


@unittest.skipUnless(TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class CompareRenderedTests(WindowCase):
    """Without the real-time engine the take is rendered through the audio cache, at the same position."""
    make_song = staticmethod(loud_song)

    def test_rendered_fallback_renders_the_take_and_keeps_the_document_untouched(self):
        window = self.window
        self.assertIsNone(window.rt)
        session = window.live.session
        session.add_take(self.write_take(silent_take()), "Quiet", "agent")
        panel = window.agent_panel
        self.wait_until(lambda: panel.take_list.count() == 1)
        document = window.document
        state = (fingerprint(document.module), document.revision, session.revision)
        rendered = []
        original = window.cache.prepare
        window.cache.prepare = lambda module, audible=(True,) * 4: (rendered.append(module), original(module, audible))[1]
        window.seek_to(1500)
        self.pause(.1)
        panel.take_list.setCurrentRow(0)
        with patch.object(window, "prepare_audio", wraps=window.prepare_audio) as prepare:
            panel.toggle_compare()
        self.assertEqual(prepare.call_args.args[1], 1500)   # position kept
        self.wait_until(lambda: window._audio_ready and not window._loading_audio)
        self.assertIs(rendered[-1], panel.compare["module"])
        self.assertEqual(rendered[-1].title, "Quiet take")
        with patch.object(window, "prepare_audio", wraps=window.prepare_audio) as prepare:
            panel.toggle_compare()
        self.wait_until(lambda: window._audio_ready and not window._loading_audio)
        self.assertEqual(rendered[-1].title, "Current")
        self.assertEqual(panel.compare["side"], "A")
        self.assertEqual((fingerprint(document.module), document.revision, session.revision), state)
        panel.end_compare()
        self.assertIsNone(window.monitor_module)


# --- 3. the agent-connected indicator -----------------------------------------------------------
@unittest.skipUnless(TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class AgentIndicatorTests(WindowCase):
    """The indicator reads `session.last_agent_activity` (every authenticated agent call, reads included)."""

    def test_a_read_only_agent_call_makes_the_agent_connected_and_it_expires(self):
        window, bridge, session = self.window, self.window.live, self.window.live.session
        self.assertEqual(window.live_status.text(), "Live: listening")
        self.assertIsNone(session.last_agent_activity)
        self.assertFalse(bridge.agent_connected())
        self.call("status")                                # a read: no journal entry, no proposal, no take
        self.assertEqual(self.call("changes")["entries"], [])
        self.assertIsNotNone(session.last_agent_activity)
        self.wait_until(lambda: window.live_status.text() == "Live: agent connected")   # the status timer follows it
        self.assertIn("Last agent activity", window.live_status.toolTip())
        session.last_agent_activity = time.monotonic() - desktop_live.ACTIVE_SECONDS - 5
        bridge.update_status()
        self.assertEqual(window.live_status.text(), "Live: listening")
        window.set_language("fr")
        session.last_agent_activity = time.monotonic()
        bridge.update_status()
        self.assertEqual(window.live_status.text(), "Direct : agent connecté")
        self.assertIn("Dernière activité de l'agent", window.live_status.toolTip())

    def test_the_owners_own_work_and_rejected_calls_do_not_count(self):
        window, bridge, session = self.window, self.window.live, self.window.live.session
        window.apply_patch([{"op": "set", "pattern": 0, "row": 3, "channel": 0, "cell": "C-2 01 ..."}], "Mine")
        window.undo()
        bridge.update_status()
        self.assertIsNone(session.last_agent_activity)
        info = discover(self.home)[0]
        with self.assertRaises(ValidationError):
            LiveClient(info["url"], "x" * 40).call("status")   # wrong token: refused before the session
        self.pause(.05)
        self.assertEqual((session.last_agent_activity, window.live_status.text()), (None, "Live: listening"))

    def test_odd_values_from_the_session_are_ignored(self):
        window, bridge, session = self.window, self.window.live, self.window.live.session
        session.last_agent_activity = time.monotonic()
        bridge.update_status()
        self.assertEqual(window.live_status.text(), "Live: agent connected")
        for bogus in (time.monotonic() + 1000, True, "now", -5, None):
            session.last_agent_activity = bogus
            bridge.update_status()
            self.assertEqual(window.live_status.text(), "Live: listening", repr(bogus))

    def test_agent_writes_proposals_and_takes_still_count_and_name_the_agent(self):
        window, bridge, session = self.window, self.window.live, self.window.live.session
        self.call("patch", ops=[{"op": "set", "pattern": 0, "row": 4, "channel": 0, "cell": "C-2 01 ..."}], author="bard")
        session.last_agent_activity = None                  # only the session events remain
        bridge.update_status()
        self.assertEqual(window.live_status.text(), "Live: agent connected")
        self.assertIn("bard", window.live_status.toolTip())


# --- 4. asynchronous open requests ---------------------------------------------------------------
@unittest.skipUnless(TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class OpenRequestTests(WindowCase):
    def add_take(self, title="Second take"):
        take = self.write_take(song(title))
        added = self.call("take", path=str(take), label="Alt mix")["take"]
        self.wait_until(lambda: self.window.agent_panel.take_list.count() >= 1)
        return take, added

    def dirty(self):
        self.window.apply_patch([{"op": "set", "pattern": 0, "row": 3, "channel": 3, "cell": "C-2 01 ..."}], "Unsaved")
        self.assertTrue(self.window.document.dirty)

    def request_during_prompt(self, answer, **request):
        """Send `open` while the owner's save/discard prompt is open; returns (reply, what the agent saw
        meanwhile). The prompt only closes once the agent's reply arrived: a handler that waited for the
        owner would deadlock the reply behind the prompt."""
        seen = {}
        future = self.pool.submit(self.agent().call, "open", **request)

        def question(*args, **kwargs):
            self.wait_until(future.done, 10)               # the agent already has its answer
            seen["reply"] = future.result()
            seen["status"] = self.call("status")
            seen["again"] = self.call("open", **request)
            seen["asked"] = args[2]
            return answer

        with patch.object(QMessageBox, "question", side_effect=question) as asked:
            self.wait_until(lambda: asked.called and not self.window.live._pending_open, 30)
        return seen

    def test_open_with_unsaved_changes_returns_pending_at_once_and_the_outcome_is_journaled(self):
        window = self.window
        take, added = self.add_take()
        self.dirty()
        started = time.monotonic()
        session = window.live.session
        with patch.object(session, "record_note", wraps=session.record_note) as note:
            seen = self.request_during_prompt(QMessageBox.StandardButton.Discard, take=added["id"])
            self.wait_until(lambda: note.called)
        self.assertEqual((note.call_args.args[1], note.call_args.kwargs["outcome"]), ("human", "opened"))
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual((seen["reply"]["handled"], seen["reply"]["prompt"]), ("pending", True))
        self.assertRegex(seen["reply"]["request_id"], r"^o\d+$")
        self.assertEqual(seen["again"]["handled"], False)  # one question at a time
        self.assertIn("waiting", seen["again"]["reason"])
        self.assertIn("Save the project changes", seen["asked"])
        self.wait_until(lambda: window.document.module.title == "Second take")
        entries = self.call("changes")["entries"]
        outcome = entries[-1]
        self.assertEqual((outcome["kind"], outcome["request"], outcome["outcome"], outcome["request_id"]),
                         ("request", "open", "opened", seen["reply"]["request_id"]))
        self.assertEqual((outcome["take"], outcome["path"]), (added["id"], str(take.resolve())))
        self.assertIn("open", [entry["kind"] for entry in entries])    # the usual "Open" entry is there too
        self.assertEqual(self.call("status")["title"], "Second take")
        self.assertEqual(discover(self.home)[0]["path"], str(take.resolve()))

    def test_declined_and_failed_opens_are_journaled_too(self):
        window = self.window
        take, added = self.add_take()
        self.dirty()
        seen = self.request_during_prompt(QMessageBox.StandardButton.Cancel, take=added["id"])
        self.assertEqual(seen["reply"]["handled"], "pending")
        self.assertEqual(window.document.module.title, "Eight")
        self.assertTrue(window.document.dirty)
        declined = self.call("changes")["entries"][-1]
        self.assertEqual((declined["kind"], declined["outcome"]), ("request", "declined"))
        self.assertEqual(window.live._pending_open, None)
        take.unlink()                                       # the file disappears before the owner answers
        self.request_during_prompt(QMessageBox.StandardButton.Discard, take=added["id"])
        self.assertEqual(window.document.module.title, "Eight")
        failed = self.call("changes")["entries"][-1]
        self.assertEqual((failed["kind"], failed["outcome"]), ("request", "failed"))

    def test_open_without_unsaved_changes_still_answers_directly(self):
        window = self.window
        take, added = self.add_take()
        opened = self.call("open", take=added["id"])
        self.assertTrue(opened["handled"] is True and opened["opened"] == str(take.resolve()))
        self.assertEqual(window.document.module.title, "Second take")

    def test_a_waiting_request_lets_the_owners_own_dialog_finish_first(self):
        window = self.window
        _, added = self.add_take()
        self.dirty()
        modal = Mock(return_value=object())
        with patch.object(QApplication, "activeModalWidget", modal):
            reply = self.call("open", take=added["id"])
            self.assertEqual(reply["handled"], "pending")
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard) as asked:
                self.pause(.6)
                self.assertFalse(asked.called)              # the owner's other dialog is still open
                modal.return_value = None
                self.wait_until(lambda: asked.called and window.live._pending_open is None)
        self.assertEqual(window.document.module.title, "Second take")

    def test_closing_the_window_drops_a_waiting_request(self):
        window = self.window
        _, added = self.add_take()
        self.dirty()
        with patch.object(QApplication, "activeModalWidget", Mock(return_value=object())):
            self.assertEqual(self.call("open", take=added["id"])["handled"], "pending")
            window.live.shutdown()
            self.assertIsNone(window.live._pending_open)
            self.pause(.4)


if __name__ == "__main__":
    unittest.main()
