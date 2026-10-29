"""Comments attached to places in the score: document storage, live session, agent and browser APIs, CLI."""
from __future__ import annotations

import argparse
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tracker4agents import cli, comments, live_cli, project
from tracker4agents.document import Document
from tracker4agents.live import API, LiveClient, LiveServer, LiveSession
from tracker4agents.model import ValidationError, cell
from tracker4agents.web import api as web_api

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "pixel_rush.project.json"
PLACE = {"pattern": 1, "row": 0, "rows": 4, "channel": 2, "channels": 2}


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        self.project = self.dir / "song.project.json"
        shutil.copyfile(EXAMPLE, self.project)
        self.document = Document.open(self.project)
        self.events = []
        self.session = LiveSession(self.document, on_event=lambda kind, payload: self.events.append((kind, payload)))


class CommentModelTests(Base):
    def test_a_comment_keeps_its_place_and_the_cells_it_pointed_at(self):
        comment = self.session.add_comment("Track 3 drags here", PLACE, "human")
        self.assertEqual((comment["id"], comment["status"], comment["author"]), ("c1", "open", "human"))
        self.assertEqual(comment["place"], PLACE)
        self.assertEqual(len(comment["cells"]), 4)
        self.assertEqual(len(comment["cells"][0].split(" | ")), 3)    # the row number and two channels
        whole = self.session.add_comment("The intro is too long", None, "human")
        self.assertEqual((whole["id"], whole["place"], whole["cells"]), ("c2", None, []))

    def test_places_and_texts_are_checked(self):
        for place in ({"pattern": 99}, {"pattern": 0, "row": 64}, {"pattern": 0, "channel": 3, "channels": 2},
                      {"row": 0}, {"pattern": 0, "colour": 1}, "pattern 0"):
            with self.subTest(place=place), self.assertRaises(ValidationError) as caught:
                self.session.add_comment("x", place, "human")
            self.assertEqual(caught.exception.code, "COMMENT_INVALID")
        for text in ("", "   ", "x" * 1001, 3):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                self.session.add_comment(text, None, "human")

    def test_reply_resolve_reopen_and_the_journal(self):
        comment = self.session.add_comment("Too busy", PLACE, "human")
        self.session.reply_comment(comment["id"], "I thinned the hats", "agent")
        resolved = self.session.resolve_comment(comment["id"], "agent", "Done, listen again")
        self.assertEqual((resolved["status"], resolved["resolved_by"]), ("resolved", "agent"))
        self.assertEqual([item["text"] for item in resolved["replies"]], ["I thinned the hats", "Done, listen again"])
        with self.assertRaises(ValidationError):
            self.session.resolve_comment(comment["id"], "agent")          # already resolved
        reopened = self.session.resolve_comment(comment["id"], "human", reopen=True)
        self.assertEqual((reopened["status"], reopened["resolved_by"]), ("open", None))
        entries = [entry for entry in self.session.changes(0)["entries"] if entry["kind"] == "comment"]
        self.assertEqual([entry["action"] for entry in entries], ["created", "replied", "resolved", "reopened"])
        self.assertTrue(all(entry["comment"] == "c1" and entry["place"] == PLACE for entry in entries))
        self.assertEqual([payload["action"] for kind, payload in self.events if kind == "comment"],
                         ["created", "replied", "resolved", "reopened"])
        self.assertEqual(self.session.context()["open_comments"], 1)
        self.assertEqual([item["id"] for item in self.session.comments("open")], ["c1"])
        self.assertEqual(self.session.comments("resolved"), [])

    def test_comments_are_saved_with_the_project_and_survive_undo(self):
        self.assertFalse(self.document.dirty)
        self.session.add_comment("Keep this fill", PLACE, "human")
        self.assertTrue(self.document.dirty)                  # a new comment is an unsaved change
        self.document.apply("Edit", lambda module: module.patterns[0].put(0, 0, cell("C-2", 1)))
        self.document.undo()
        self.assertEqual(len(self.document.comments), 1)       # undoing a note never removes a comment
        self.document.save_project(self.project)
        self.assertFalse(self.document.dirty)
        saved = json.loads(self.project.read_text(encoding="utf-8"))
        self.assertEqual(saved["metadata"]["comments"][0]["text"], "Keep this fill")
        reopened = Document.open(self.project)
        self.assertEqual([item["id"] for item in reopened.comments], ["c1"])
        self.assertNotIn("comments", reopened.module.metadata)   # kept beside the module, not in its history
        self.assertFalse(reopened.dirty)
        self.assertEqual(project.load(self.project).metadata["comments"][0]["place"], PLACE)

    def test_malformed_stored_comments_are_refused(self):
        module = project.load(self.project)
        module.metadata["comments"] = [{"id": "c1", "text": "x", "status": "maybe"}]
        with self.assertRaises(ValidationError) as caught:
            Document(module)
        self.assertEqual(caught.exception.code, "COMMENT_INVALID")

    def test_the_oldest_resolved_comments_go_first_past_the_limit(self):
        with mock.patch.object(comments, "COMMENT_LIMIT", 3):
            first = self.session.add_comment("one", None, "human")
            self.session.resolve_comment(first["id"], "agent")
            for text in ("two", "three", "four"):
                self.session.add_comment(text, None, "human")
        self.assertEqual([item["text"] for item in self.session.comments("all")], ["two", "three", "four"])


class CommentApiTests(Base):
    def test_agent_api_cannot_write_as_the_owner(self):
        result = API["comment"](self.session, {"text": "Listen to bar 3", "place": PLACE})
        self.assertEqual(result["comment"]["author"], "agent")
        with self.assertRaises(ValidationError) as caught:
            API["comment"](self.session, {"text": "x", "author": "human"})
        self.assertEqual(caught.exception.code, "LIVE_AUTHOR")
        reply = API["reply"](self.session, {"id": "c1", "text": "ok"})["comment"]
        self.assertEqual(reply["replies"][-1]["author"], "agent")
        resolved = API["resolve"](self.session, {"id": "c1", "text": "fixed"})["comment"]
        self.assertEqual(resolved["status"], "resolved")
        with self.assertRaises(ValidationError):
            API["resolve"](self.session, {"id": "c1", "reopen": "yes"})
        self.assertEqual(len(API["comments"](self.session, {"status": "all"})["comments"]), 1)

    def test_browser_comments_are_the_owners(self):
        call = web_api.Call(session=self.session, server=None, device={}, listener="local")
        created = web_api.WEB_API["comment"](call, {"text": "From the tablet", "place": PLACE})["comment"]
        self.assertEqual(created["author"], web_api.WEB_AUTHOR)
        web_api.WEB_API["reply"](call, {"id": created["id"], "text": "still too loud"})
        web_api.WEB_API["resolve"](call, {"id": created["id"]})
        listed = web_api.WEB_API["comments"](call, {"status": "resolved"})["comments"]
        self.assertEqual((listed[0]["resolved_by"], listed[0]["replies"][0]["author"]),
                         (web_api.WEB_AUTHOR, web_api.WEB_AUTHOR))
        with self.assertRaises(ValidationError):
            web_api.WEB_API["comment"](call, {"text": "x", "author": "agent"})


class CommentCliTests(Base):
    def setUp(self):
        super().setUp()
        environment = mock.patch.dict(os.environ, {"CHIPLOOM_HOME": str(self.dir / "home")})
        environment.start()
        self.addCleanup(environment.stop)
        self.server = LiveServer(self.session, kind="headless").start()
        self.addCleanup(self.server.stop)
        self.parser = argparse.ArgumentParser(prog="chiploom")
        live_cli.add_parser(self.parser.add_subparsers(dest="command", required=True))

    def live(self, *argv):
        return live_cli.run(self.parser.parse_args(["live", *argv]))

    def test_live_comment_commands(self):
        self.session.add_comment("The bass is too low", PLACE, "human")
        listed = self.live("comments")["comments"]
        self.assertEqual((listed[0]["id"], listed[0]["place"]), ("c1", PLACE))
        self.live("reply", "c1", "Raised it an octave")
        self.live("resolve", "c1", "--text", "Listen from order 2")
        self.assertEqual(self.live("comments")["comments"], [])
        done = self.live("comments", "--status", "resolved")["comments"][0]
        self.assertEqual([item["text"] for item in done["replies"]], ["Raised it an octave", "Listen from order 2"])
        added = self.live("comment", "Check this fill", "--pattern", "0", "--row", "56", "--rows", "8",
                          "--channel", "0")["comment"]
        self.assertEqual(added["place"], {"pattern": 0, "row": 56, "rows": 8, "channel": 0, "channels": 1})
        self.assertEqual(self.live("comment", "Whole song note")["comment"]["place"], None)
        self.assertEqual(self.live("status")["open_comments"], 2)
        client = LiveClient(self.server.url, self.server.token)
        self.assertEqual(len(client.call("comments", status="all")["comments"]), 3)


class FeedbackPlaceTests(unittest.TestCase):
    def test_feedback_can_be_tied_to_a_block(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "fb.project.json"
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["feedback", str(EXAMPLE), "--text", "Arp too dense", "--output", str(output),
                                 "--pattern", "1", "--rows", "16", "--channel", "2"])
            self.assertEqual(code, 0, err.getvalue())
            entry = json.loads(out.getvalue())["feedback"]
            self.assertEqual(entry["place"], {"pattern": 1, "row": 0, "rows": 16, "channel": 2, "channels": 1})
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = cli.main(["feedback", str(EXAMPLE), "--text", "x", "--output", str(Path(folder) / "bad.json"),
                                 "--pattern", "1", "--channel", "9"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
