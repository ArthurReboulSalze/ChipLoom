"""Comments with a place in the window: the Comment action on a grid selection, the corner markers and their
tooltips, the COMMENTS column of the Agent tab (Go to, Reply, Resolve, Reopen, Show resolved), an agent's
replies through the live server, save and reopen, the same actions without a live session, French strings.

Offscreen, on temporary projects (rendered playback). The text dialog is replaced by a stub.
"""
from __future__ import annotations

import importlib
import shutil
import unittest

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from tracker4agents.desktop_comments import COMMENTS_ROLE
    from tracker4agents.desktop_layout import SHORTCUTS
except ModuleNotFoundError:
    QApplication = None

from tracker4agents.document import Document
from tracker4agents.i18n import FR
from tracker4agents.live import LiveClient
from tracker4agents.model import ValidationError

PACKAGE = __package__ + "." if __package__ else ""
base = importlib.import_module(PACKAGE + "test_desktop_08")


@unittest.skipUnless(QApplication is not None and shutil.which("ffmpeg"), "PySide6 and FFmpeg required")
class DesktopCommentTests(base.WindowCase):
    def setUp(self):
        super().setUp()
        self.panel = self.window.comment_panel
        self.typed = []   # texts the stubbed dialog returns, in order
        self.panel.ask_text = lambda title, prompt: self.typed.pop(0) if self.typed else None

    def comment_block(self, text="Track 2 drags here", row=0, rows=4, channel=1, channels=2):
        self.window.show_pattern(0)
        self.table.select_block(row, rows, channel, channels)
        self.table.setFocus()
        self.typed.append(text)
        QTest.keyClick(self.table, Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier)   # the shortcut, from the grid
        self.app.processEvents()
        return self.window.document.comments[-1]

    def marks(self, row, channel):
        return self.model.data(self.model.index(row, self.model.column_of(channel, "effect")), COMMENTS_ROLE)

    def select_comment(self, comment_id):
        for index in range(self.panel.list.count()):
            if self.panel.list.item(index).data(Qt.ItemDataRole.UserRole) == comment_id:
                self.panel.list.setCurrentRow(index)
                return
        self.fail(f"{comment_id} is not listed")

    def test_comment_on_a_selection_marks_its_cells_and_lists_it_in_the_agent_tab(self):
        window = self.window
        comment = self.comment_block()
        self.assertEqual(comment["place"], {"pattern": 0, "row": 0, "rows": 4, "channel": 1, "channels": 2})
        self.assertEqual((comment["author"], comment["status"], comment["text"]), ("human", "open", "Track 2 drags here"))
        self.assertEqual(comment["cells"][0].split(" | ")[0], "00")
        self.assertEqual(self.marks(0, 1), [comment["id"]])
        self.assertEqual(self.marks(3, 2), [comment["id"]])
        self.assertEqual(self.marks(4, 1), [])
        self.assertEqual(self.marks(0, 0), [])
        tip = self.model.data(self.model.index(2, self.model.column_of(2)), Qt.ItemDataRole.ToolTipRole)
        self.assertIn("Track 2 drags here", tip)
        self.assertIn("Double-click to edit", tip)
        self.assertNotIn("drags", self.model.data(self.model.index(5, 0), Qt.ItemDataRole.ToolTipRole))
        # The marker is painted in the accent colour at the top-right corner of a covered channel.
        column = self.model.column_of(1, "effect")
        x = self.table.columnViewportPosition(column) + self.table.columnWidth(column) - 4
        y = self.table.rowViewportPosition(1) + 3
        image = self.table.viewport().grab().toImage()
        self.assertEqual(image.pixelColor(x, y).name(), QColor(window.palette_colors["accent"]).name())
        # Listed in the Agent tab with its place in the grid's notation; the project is unsaved.
        self.assertEqual(self.panel.list.count(), 1)
        text = self.panel.list.item(0).text()
        self.assertIn("Pattern 00 · rows 00-03 · channels 2-3", text)
        self.assertIn("c1 · human", text)
        self.assertEqual(self.panel.header.text(), "COMMENTS · 1 open")
        self.assertTrue(window.document.dirty)
        self.assertTrue(window.windowTitle().startswith("* "))
        self.assertEqual(window.live.session.comments()[0]["id"], comment["id"])
        self.assertIn("Comment added", window.statusBar().currentMessage())
        # A whole-song comment has no place and no marker; Go to has nowhere to go.
        song = self.panel.comment_song(text="The ending is too long")
        self.assertIsNone(song["place"])
        self.select_comment(song["id"])
        self.assertIn("Whole song", self.panel.list.currentItem().text())
        self.assertFalse(self.panel.go_button.isEnabled())
        self.assertEqual(self.panel.header.text(), "COMMENTS · 2 open")

    def test_the_agent_tab_says_where_to_write_and_what_the_agent_did(self):
        window, panel, agent = self.window, self.panel, self.window.agent_panel
        self.assertIn("Write to your agent", panel.compose.placeholderText())
        self.assertIn("No message yet", panel.list.hint())
        self.assertIn("No proposal yet", agent.proposal_list.hint())
        self.assertIn("No take yet", agent.take_list.hint())
        self.assertIn("read only", agent.details.placeholderText())
        agent.refresh()
        self.assertIn("nothing yet", agent.activity.text())
        # Typed in the box with cells selected: a comment on that block.
        window.show_pattern(0)
        self.table.select_block(4, 2, 0, 1)
        panel.update_target()
        self.assertIn("rows 04-05", panel.target.text())
        panel.compose.setText("Make this bar breathe")
        QTest.keyClick(panel.compose, Qt.Key.Key_Return)
        comment = window.document.comments[-1]
        self.assertEqual((comment["text"], comment["place"]["row"], comment["place"]["rows"]), ("Make this bar breathe", 4, 2))
        self.assertEqual(panel.compose.text(), "")
        # Unticked: the whole song.
        panel.at_selection.setChecked(False)
        self.assertIn("Whole song", panel.target.text())
        panel.compose.setText("Shorter intro please")
        panel.send_compose()
        self.assertIsNone(window.document.comments[-1]["place"])
        panel.compose.setText("   ")
        self.assertIsNone(panel.send_compose())
        # An agent's edit shows on the activity line.
        session = window.live.session
        session.apply_patch([{"op": "title", "title": "Agent title"}], author="agent-test", label="Retitle the song")
        self.app.processEvents()
        agent.refresh()
        self.assertIn("Retitle the song", agent.activity.text())
        self.assertIn("agent-test", agent.activity.text())

    def test_go_to_reply_resolve_and_reopen(self):
        window, panel = self.window, self.panel
        comment = self.comment_block(row=2, rows=3, channel=0, channels=1)
        window.show_pattern(1)
        self.table.clearSelection()
        self.select_comment(comment["id"])
        self.assertTrue(panel.go_to())
        self.assertEqual(self.model.pattern, 0)
        self.assertEqual(self.table.selection_block(), (2, 3, 0, 1))
        self.typed.append("And it clips")
        panel.reply_selected()
        self.assertEqual(window.document.comments[0]["replies"][-1]["text"], "And it clips")
        self.assertIn("» human", panel.list.currentItem().text())
        panel.resolve_button.click()
        self.assertEqual(window.document.comments[0]["status"], "resolved")
        self.assertEqual(window.document.comments[0]["resolved_by"], "human")
        self.assertEqual(panel.list.count(), 0)            # resolved ones are hidden...
        self.assertEqual(self.marks(2, 0), [])              # ...and lose their marker
        self.assertEqual(panel.header.text(), "COMMENTS")
        panel.show_resolved.setChecked(True)
        self.assertEqual(panel.list.count(), 1)
        self.select_comment(comment["id"])
        self.assertIn("Resolved by human", panel.list.currentItem().text())
        self.assertEqual(panel.resolve_button.text(), "Reopen")
        panel.resolve_selected()
        self.assertEqual(window.document.comments[0]["status"], "open")
        self.assertEqual(panel.resolve_button.text(), "Resolve")
        self.assertEqual(self.marks(2, 0), [comment["id"]])
        kinds = [entry.get("action") for entry in window.live.session.changes()["entries"] if entry["kind"] == "comment"]
        self.assertEqual(kinds, ["created", "replied", "resolved", "reopened"])
        # An empty reply is refused with a message, and nothing changes.
        self.assertIsNone(panel.reply_selected(text="   "))
        self.assertIn("Comment not saved", window.statusBar().currentMessage())
        self.assertEqual(len(window.document.comments[0]["replies"]), 1)

    def test_agent_replies_comments_and_resolves_through_the_session(self):
        window, panel = self.window, self.panel
        comment = self.comment_block()
        client = LiveClient.discover(home=self.home)

        def call(method, **params):
            future = self.pool.submit(client.call, method, **params)
            self.wait_until(future.done, 30)
            return future.result()

        call("reply", id=comment["id"], text="Moved it to the eighth grid", author="hermes")
        self.wait_until(lambda: "Moved it" in panel.list.item(0).text())
        self.assertIn("hermes replied to c1", window.statusBar().currentMessage())
        call("comment", text="Listen from here", place={"pattern": 0, "row": 8, "rows": 2, "channel": 3, "channels": 1},
             author="hermes")
        self.wait_until(lambda: panel.list.count() == 2)
        self.assertEqual(self.marks(9, 3), ["c2"])
        self.assertFalse(window.debounce.isActive())   # a comment changes no cell: no new rendering
        call("resolve", id=comment["id"], text="Done", author="hermes")
        self.wait_until(lambda: panel.list.count() == 1)
        self.assertEqual(self.marks(0, 1), [])
        self.assertIn("hermes resolved c1", window.statusBar().currentMessage())
        self.assertEqual(panel.header.text(), "COMMENTS · 1 open")

    def test_comments_survive_save_and_reopen(self):
        window = self.window
        comment = self.comment_block(text="Keep me")
        window.save_project()
        self.assertFalse(window.document.dirty)
        self.assertTrue(window.open_document(self.path, ask=False))
        self.assertEqual([item["text"] for item in window.document.comments], ["Keep me"])
        self.assertEqual(self.panel.list.count(), 1)
        self.assertEqual(self.marks(1, 2), [comment["id"]])
        self.assertIs(window.live.session.document, window.document)
        self.assertEqual(window.live.session.comments()[0]["text"], "Keep me")
        # A file without comments clears the list and the markers.
        other = self.directory / "other.project.json"
        Document(base.song("Other")).save_project(other)
        self.assertTrue(window.open_document(other, ask=False))
        self.assertEqual(self.panel.list.count(), 0)
        self.assertEqual(self.marks(1, 2), [])

    def test_without_a_live_session_the_same_actions_work_on_the_document(self):
        window, panel = self.window, self.panel
        session, window.live.session = window.live.session, None
        try:
            self.assertIsNone(panel.store.session)
            comment = self.comment_block(text="Offline note")
            self.assertEqual(comment["place"]["channels"], 2)
            self.assertEqual(self.marks(0, 2), ["c1"])
            self.select_comment("c1")
            panel.reply_selected(text="Seen")
            panel.resolve_selected()
            self.assertEqual(window.document.comments[0]["status"], "resolved")
            self.assertEqual([reply["text"] for reply in window.document.comments[0]["replies"]], ["Seen"])
            self.assertEqual(panel.list.count(), 0)
            with self.assertRaises(ValidationError):   # the session's rule on the document path too
                panel.store.resolve("c1")
            panel.show_resolved.setChecked(True)
            self.select_comment("c1")
            panel.resolve_selected()
            self.assertEqual(window.document.comments[0]["status"], "open")
            self.assertTrue(window.document.dirty)
            self.assertEqual(session.comments()[0]["replies"][0]["text"], "Seen")   # the same list
        finally:
            window.live.session = session

    def test_grid_context_menu_and_agent_menu_offer_the_comment_actions(self):
        window = self.window
        self.assertEqual(self.table.contextMenuPolicy(), Qt.ContextMenuPolicy.CustomContextMenu)
        menu = self.panel.grid_menu()
        seen = menu.actions()
        menu.deleteLater()
        self.assertIn(window.comment_action, seen)
        self.assertIn(window.song_comment_action, seen)
        self.assertIn(window.copy_action, seen)
        self.assertEqual(window.comment_action.shortcut().toString(), "Ctrl+M")
        self.assertIn(("Ctrl+M", "Comment on the selected cells (listed in the Agent tab)"), SHORTCUTS)
        self.typed.append("From the menu")
        self.table.select_block(5, 1, 0, 1)
        window.comment_action.trigger()
        self.assertEqual(window.document.comments[-1]["place"], {"pattern": 0, "row": 5, "rows": 1, "channel": 0,
                                                                  "channels": 1})
        self.assertIn("Pattern 00 · row 05 · channel 1", self.panel.list.item(0).text())
        self.typed.append(None)
        self.assertIsNone(self.panel.comment_song())   # a cancelled dialog writes nothing
        self.assertEqual(len(window.document.comments), 1)

    def test_french_strings(self):
        window, panel = self.window, self.panel
        self.comment_block()
        window.set_language("fr")
        try:
            self.assertEqual(panel.header.text(), "COMMENTAIRES · 1 ouvert(s)")
            self.assertEqual(panel.go_button.text(), "Aller à")
            self.assertEqual(panel.show_resolved.text(), "Afficher les résolus")
            self.assertEqual(window.comment_action.text(), "Commenter la sélection…")
            self.assertIn("Pattern 00 · lignes 00-03 · voies 2-3", panel.list.item(0).text())
            tip = self.model.data(self.model.index(1, self.model.column_of(1)), Qt.ItemDataRole.ToolTipRole)
            self.assertTrue(tip.startswith("Commentaires ici :"))
        finally:
            window.set_language("en")
        for source in ("Show resolved", "Go to", "Reply", "Resolve", "Reopen", "Whole song",
                       "Comment on the selection…", "Comment on the whole song…", "Comment not saved: {detail}",
                       "{author} replied to {id}: {snippet}", "{author} resolved {id}", "Comment {id} reopened",
                       "What should your agent look at here?", "Your reply", "Select a cell or a block first.",
                       "Comment on the selected cells (listed in the Agent tab)", "Ctrl+M in the grid: comment on the selected cells · double-click: go to the place"):
            self.assertIn(source, FR)


if __name__ == "__main__":
    unittest.main()
