"""The live session inside the Qt window: an agent client talks to the window's real loopback server.

The client runs in worker threads while the test pumps the GUI event loop, exactly like a
separate `chiploom live` process would behave. Discovery files go to a temporary CHIPLOOM_HOME.
"""
from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
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
_LIVE_HOME = tempfile.mkdtemp(prefix="chiploom-home-")
os.environ.setdefault("CHIPLOOM_HOME", _LIVE_HOME)
atexit.register(shutil.rmtree, _LIVE_HOME, True)
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from tracker4agents.desktop import TrackerWindow
except ModuleNotFoundError:
    TrackerWindow = None

from tracker4agents.desktop_services import AppState
from tracker4agents.document import Document, fingerprint
from tracker4agents.live import LiveClient, LiveConflict, discover
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell
from tracker4agents.themes import THEMES


def song() -> Module:
    samples = [Sample(name, (0, 0) + (60, 0, -60, 0) * 8, 40) for name in ("Kick", "Snare", "Lead")]
    return Module("Live", samples, [Pattern(name="Intro"), Pattern(name="Verse")], [0, 1, 0])


def set_op(row, channel, text, pattern=0):
    return {"op": "set", "pattern": pattern, "row": row, "channel": channel, "cell": text}


@unittest.skipUnless(TrackerWindow is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class DesktopLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["live-tests"])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.app.setStyle("Fusion")
        if not QFontDatabase.families() and os.name == "nt":
            for name in ("segoeui.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.home = self.directory / "home"
        self.environment = patch.dict(os.environ, {"CHIPLOOM_HOME": str(self.home)})
        self.environment.start()
        self.path = self.directory / "live.project.json"
        Document(song()).save_project(self.path)
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.open_window()

    def open_window(self):
        self.window = TrackerWindow(self.path, self.directory / "state", restore=False)
        self.window.output.setMuted(True)
        self.window.sample_output.setMuted(True)
        self.window.show()
        self.wait_until(lambda: self.window.document is not None and self.window.live.server is not None)
        self.client = LiveClient.discover(home=self.home)
        self.model = self.window.pattern_model

    def tearDown(self):
        window = self.window
        window.document.dirty and window.document.save_project(self.directory / "tear-down.project.json")
        window.close()
        window.pool.waitForDone(10000)
        self.app.processEvents()
        window.deleteLater()
        self.app.processEvents()
        self.pool.shutdown(wait=True)
        self.environment.stop()
        self.temporary.cleanup()

    def wait_until(self, predicate, seconds=20):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(predicate(), self.window.statusBar().currentMessage())

    def call(self, method, **params):
        """An agent call from another thread while the GUI thread keeps processing events."""
        future = self.pool.submit(self.client.call, method, **params)
        self.wait_until(future.done, 30)
        return future.result()

    def cell(self, row, channel, pattern=0):
        return self.window.document.module.patterns[pattern].get(row, channel)

    def pause(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)

    # --- lifecycle -------------------------------------------------------------------
    def test_window_serves_a_discoverable_session_without_exposing_the_token(self):
        window = self.window
        sessions = discover(self.home)
        self.assertEqual(len(sessions), 1)
        self.assertEqual((sessions[0]["pid"], sessions[0]["kind"], sessions[0]["path"]),
                         (os.getpid(), "desktop", str(window.document.path)))
        self.assertEqual(window.live_status.text(), "Live: listening")
        self.assertIn(sessions[0]["url"], window.live_status.toolTip())
        for text in (window.live_status.text(), window.live_status.toolTip(), window.statusBar().currentMessage()):
            self.assertNotIn(sessions[0]["token"], text)
        status = self.call("status")
        self.assertTrue(status["window"])
        self.assertEqual(status["title"], "Live")
        self.assertEqual(status["orders"], [0, 1, 0])

    def test_closing_the_window_stops_the_server_and_removes_the_discovery_file(self):
        self.assertTrue(list((self.home / "live").glob("*.json")))
        self.window.close()
        self.assertFalse(self.window.live.server.running)
        self.assertEqual(list((self.home / "live").glob("*.json")), [])
        with self.assertRaises(ValidationError):
            self.client.call("ping")

    def test_live_collaboration_can_be_switched_off_and_is_remembered(self):
        window = self.window
        self.assertTrue(window.live_action.isChecked())
        window.live_action.setChecked(False)
        self.assertEqual(list((self.home / "live").glob("*.json")), [])
        self.assertEqual(window.live_status.text(), "Live: off")
        self.assertIs(AppState(self.directory / "state").values["live"], False)
        window.set_language("fr")
        self.assertEqual(window.live_status.text(), "Direct : désactivé")
        self.assertEqual(window.sample_tabs.tabText(2), "Agent")
        window.set_language("en")
        window.close()
        self.open_window_without_server()
        self.assertFalse(self.window.live_action.isChecked())
        self.assertEqual(list((self.home / "live").glob("*.json")), [])
        self.window.live_action.setChecked(True)
        self.assertEqual(len(discover(self.home)), 1)

    def open_window_without_server(self):
        self.window = TrackerWindow(self.path, self.directory / "state", restore=False)
        self.window.output.setMuted(True)
        self.window.show()
        self.wait_until(lambda: self.window.document is not None and self.window.live.session is not None)
        self.model = self.window.pattern_model

    # --- agent edits -----------------------------------------------------------------
    def test_agent_patch_changes_the_document_flashes_cells_and_is_journaled_as_agent(self):
        window = self.window
        window.table.setCurrentIndex(self.model.index(9, 4))
        self.wait_until(lambda: self.call("status").get("row") == 9)
        with patch.object(window, "message", wraps=window.message) as message:
            result = self.call("patch", ops=[set_op(2, 1, "G-2 02 ..."), set_op(3, 1, "A-2 02 ...")], label="Add a line")
        self.assertTrue(result["changed"])
        self.assertEqual(self.cell(2, 1), cell("G-2", 2))
        self.assertTrue(window.document.dirty)
        self.assertEqual(set(self.model.flashed()), {(0, 2, 1), (0, 3, 1)})
        self.assertEqual(self.model.data(self.model.index(2, 3), Qt.ItemDataRole.BackgroundRole).name(),
                         THEMES[window.theme]["agent_change"])
        self.assertEqual((window.table.currentIndex().row(), window.table.currentIndex().column()), (9, 4))
        self.assertEqual(message.call_args_list[0].args[0], "{author}: {label} · {summary}")
        self.assertEqual(message.call_args_list[0].kwargs["label"], "Add a line")
        journal = self.call("changes")["entries"]
        self.assertEqual([(entry["author"], entry["label"]) for entry in journal], [("agent", "Add a line")])
        self.wait_until(lambda: window._audio_ready and not window._loading_audio)  # debounced re-render
        window.undo()  # the owner can take back the agent's work with the normal Ctrl+Z
        self.assertEqual(self.cell(2, 1), cell())
        self.assertEqual([entry["author"] for entry in self.call("changes")["entries"]], ["agent", "human"])

    def test_playback_intent_survives_an_agent_edit(self):
        window = self.window
        self.wait_until(lambda: window._audio_ready and not window._loading_audio)
        window.toggle_play()
        self.wait_until(lambda: window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        self.call("patch", ops=[set_op(0, 0, "C-2 01 ...")])
        self.wait_until(lambda: window._audio_ready and window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)

    def test_human_edits_are_synced_and_older_agent_patches_conflict(self):
        window = self.window
        revision = self.call("status")["revision"]
        self.assertTrue(window.apply_patch([set_op(5, 0, "C-2 01 ...")], "Typed note"))
        entries = self.call("changes", since=revision)["entries"]
        self.assertEqual([(entry["author"], entry["label"]) for entry in entries], [("human", "Typed note")])
        window.undo()
        window.redo()
        labels = [entry["label"] for entry in self.call("changes", since=revision)["entries"]]
        self.assertEqual(labels, ["Typed note", "Undo", "Redo"])
        with self.assertRaises(LiveConflict) as caught:
            self.call("patch", ops=[set_op(5, 0, "E-2 02 ...")], base_revision=revision)
        self.assertEqual(caught.exception.code, "LIVE_CONFLICT")
        self.assertEqual(self.cell(5, 0), cell("C-2", 1))
        newer = self.call("status")["revision"]
        self.assertTrue(self.call("patch", ops=[set_op(5, 0, "E-2 02 ...")], base_revision=newer)["changed"])

    def test_context_follows_cursor_selection_order_and_playback(self):
        window = self.window
        window.table.select_block(4, 3, 1, 2)
        self.wait_until(lambda: self.call("status").get("selection", {}).get("rows") == 3)
        status = self.call("status")
        self.assertEqual(status["selection"], {"pattern": 0, "row": 4, "rows": 3, "channel": 1, "channels": 2})
        self.assertEqual((status["order"], status["pattern"], status["playing"], status["dirty"]), (0, 0, False, False))
        window.orders.setCurrentIndex(1)
        self.wait_until(lambda: self.call("status").get("pattern") == 1)
        self.assertEqual(self.call("status")["order"], 1)

    def test_a_file_rewritten_on_disk_is_journaled_as_file_not_human(self):
        window = self.window
        agent = Document.open(self.path)
        agent.patch([set_op(7, 2, "D-2 03 ...")], "Script")
        agent.save_project(self.path)
        self.wait_until(lambda: self.cell(7, 2).note == "D-2")
        entries = self.call("changes")["entries"]
        self.assertEqual([entry["author"] for entry in entries], ["file"])
        self.assertEqual(set(self.model.flashed()), {(0, 7, 2)})
        self.assertFalse(window.document.dirty)
        self.assertEqual(self.call("status")["revision"], 1)

    # --- proposals -------------------------------------------------------------------
    def propose(self, *ops, label="Idea"):
        return self.call("patch", ops=list(ops), label=label, propose=True)["proposal"]

    def test_proposal_appears_in_agent_tab_previews_as_overlay_and_is_accepted_from_the_ui(self):
        window, panel = self.window, self.window.agent_panel
        proposal = self.propose(set_op(1, 0, "F-2 01 ..."), set_op(2, 3, "A-1 02 ..."), label="Bass idea")
        self.wait_until(lambda: panel.proposal_list.count() == 1)
        self.assertIn("Bass idea", panel.proposal_list.item(0).text())
        self.assertIn("2 cells", panel.proposal_list.item(0).text())
        self.assertEqual(window.sample_tabs.tabText(2), "Agent (1)")
        before = fingerprint(window.document.module)
        panel.proposal_list.setCurrentRow(0)
        self.assertIsNotNone(self.model.overlay)
        self.assertEqual(self.model.data(self.model.index(1, 0)), "F-2")  # proposed text is displayed...
        self.assertEqual(self.model.data(self.model.index(1, 0), Qt.ItemDataRole.EditRole), "---")  # ...the document is not
        self.assertEqual(self.model.data(self.model.index(1, 0), Qt.ItemDataRole.BackgroundRole).name(), THEMES[window.theme]["proposal"])
        self.assertEqual(fingerprint(window.document.module), before)
        self.assertIn("Bass idea", panel.details.toPlainText())
        self.assertTrue(panel.accept_button.isEnabled())
        panel.accept_button.click()
        self.assertIsNone(self.model.overlay)
        self.assertEqual((self.cell(1, 0), self.cell(2, 3)), (cell("F-2", 1), cell("A-1", 2)))
        self.assertEqual(panel.proposal_list.count(), 0)
        self.assertEqual(window.sample_tabs.tabText(2), "Agent")
        self.assertEqual(set(self.model.flashed()), {(0, 1, 0), (0, 2, 3)})
        self.assertEqual(self.call("proposals", status="accepted")["proposals"][0]["id"], proposal["id"])
        window.undo()  # one undo step takes the whole accepted proposal back
        self.assertEqual(fingerprint(window.document.module), before)

    def test_proposal_on_another_pattern_jumps_to_its_order_and_reject_leaves_the_document_alone(self):
        window, panel = self.window, self.window.agent_panel
        self.propose(set_op(6, 1, "G-2 01 ...", pattern=1), label="Verse hook")
        self.wait_until(lambda: panel.proposal_list.count() == 1)
        before = fingerprint(window.document.module)
        panel.proposal_list.setCurrentRow(0)
        self.assertEqual((window.current_order, self.model.pattern), (1, 1))
        self.assertEqual(self.model.data(self.model.index(6, 3)), "G-2")
        panel.reject_button.click()
        self.assertEqual(panel.proposal_list.count(), 0)
        self.assertIsNone(self.model.overlay)
        self.assertEqual(fingerprint(window.document.module), before)
        self.assertEqual(self.call("proposals", status="rejected")["proposals"][0]["label"], "Verse hook")

    def test_conflicting_acceptance_asks_and_can_be_forced(self):
        window, panel = self.window, self.window.agent_panel
        self.propose(set_op(4, 0, "F-2 01 ..."), label="Lead")
        self.wait_until(lambda: panel.proposal_list.count() == 1)
        window.apply_patch([set_op(4, 0, "C-2 02 ...")], "Mine")
        self.wait_until(lambda: panel.proposal_list.count() == 1 and "outdated" in panel.proposal_list.item(0).text())
        panel.proposal_list.setCurrentRow(0)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as question:
            self.assertFalse(panel.accept_selected())
        self.assertIn("P00 r04 ch1", question.call_args.args[2])
        self.assertEqual(self.cell(4, 0), cell("C-2", 2))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.assertTrue(panel.accept_selected())
        self.assertEqual(self.cell(4, 0), cell("F-2", 1))
        window.undo()
        self.assertEqual(self.cell(4, 0), cell("C-2", 2))

    def test_listening_to_a_proposal_does_not_touch_the_document(self):
        window, panel = self.window, self.window.agent_panel
        self.propose(set_op(0, 0, "C-2 01 ..."), label="Hear me")
        self.wait_until(lambda: panel.proposal_list.count() == 1)
        panel.proposal_list.setCurrentRow(0)
        before, revision = fingerprint(window.document.module), window.document.revision
        panel.listen_button.click()
        self.wait_until(lambda: window.sample_player.source().isValid() and not window._jobs)
        self.assertTrue(window.sample_player.source().toLocalFile().endswith(".wav"))
        window.sample_player.stop()
        self.assertEqual((fingerprint(window.document.module), window.document.revision), (before, revision))
        panel.clear_button.click()
        self.assertIsNone(self.model.overlay)
        self.assertEqual(panel.proposal_list.currentRow(), -1)

    # --- requests --------------------------------------------------------------------
    def test_select_play_seek_and_stop_requests_are_handled_by_the_window(self):
        window = self.window
        self.wait_until(lambda: window._audio_ready and not window._loading_audio)
        result = self.call("select", pattern=1, row=4, rows=2, channel=1, channels=2)
        self.assertTrue(result["handled"])
        self.assertEqual((window.current_order, self.model.pattern), (1, 1))
        self.assertEqual(window.table.selection_block(), (4, 2, 1, 2))
        self.assertEqual(self.call("select", pattern=0, row=0)["handled"], True)
        self.assertEqual(window.table.selection_block(), (0, 1, 0, 1))
        with self.assertRaises(ValidationError):
            self.call("select", pattern=9, row=0)
        started = self.call("play", order=2)
        self.assertEqual((started["handled"], started["order"]), (True, 2))
        self.wait_until(lambda: window.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        expected = next(entry["seconds"] for entry in window.plan["timeline"] if entry["order"] == 2)
        self.assertGreaterEqual(window.player.position() / 1000, expected - .05)
        self.assertTrue(self.call("seek", seconds=0.5)["handled"])
        self.assertTrue(self.call("stop")["handled"])
        self.assertNotEqual(window.player.playbackState(), QMediaPlayer.PlaybackState.PlayingState)
        self.wait_until(lambda: self.call("status")["playing"] is False)

    def make_take(self, title="Second take"):
        other = Document(song())
        other.rename(title)
        target = self.directory / "take.project.json"
        other.save_project(target)
        return target

    def test_open_request_respects_unsaved_changes(self):
        window, panel = self.window, self.window.agent_panel
        take = self.make_take()
        added = self.call("take", path=str(take), label="Alt mix")["take"]
        self.wait_until(lambda: panel.take_list.count() == 1)
        self.assertIn("Alt mix", panel.take_list.item(0).text())
        window.apply_patch([set_op(0, 0, "C-2 01 ...")], "Unsaved work")
        self.assertTrue(window.document.dirty)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel) as question:
            declined = self.call("open", take=added["id"])
        self.assertTrue(question.called)
        self.assertEqual((declined["handled"], declined["reason"]), (False, "owner declined"))
        self.assertEqual(window.document.module.title, "Live")
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            opened = self.call("open", take=added["id"])
        self.assertTrue(opened["handled"])
        self.assertEqual(window.document.module.title, "Second take")
        self.assertEqual(window.document.path, take.resolve())
        self.assertEqual(self.call("status")["title"], "Second take")
        self.assertEqual(self.call("changes")["entries"][-1]["kind"], "open")
        # The discovery file follows the new document.
        self.assertEqual(discover(self.home)[0]["path"], str(take.resolve()))

    def test_takes_open_from_the_panel_and_opening_withdraws_pending_proposals(self):
        window, panel = self.window, self.window.agent_panel
        self.call("take", path=str(self.make_take("Panel take")), label="From panel")
        self.propose(set_op(0, 0, "C-2 01 ..."))
        self.wait_until(lambda: panel.take_list.count() == 1 and panel.proposal_list.count() == 1)
        panel.take_list.setCurrentRow(0)
        panel.open_button.click()
        self.assertEqual(window.document.module.title, "Panel take")
        self.wait_until(lambda: panel.proposal_list.count() == 0)
        self.assertEqual(self.call("proposals", status="withdrawn")["proposals"][0]["status"], "withdrawn")

    def test_f5_reload_is_journaled_as_reload_without_flash(self):
        window = self.window
        agent = Document.open(self.path)
        agent.rename("Retitled")
        agent.save_project(self.path)
        window.reload_document()
        self.assertEqual(window.document.module.title, "Retitled")
        entries = self.call("changes")["entries"]
        self.assertEqual([(entry["kind"], entry["author"]) for entry in entries], [("reload", "file")])
        self.assertFalse(self.model.flashed())


if __name__ == "__main__":
    unittest.main()
