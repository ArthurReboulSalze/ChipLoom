from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import urlparse

from tracker4agents import live, live_cli, mod, project
from tracker4agents.document import Document
from tracker4agents.live import LiveClient, LiveConflict, LiveServer, LiveSession
from tracker4agents.model import ValidationError

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "pixel_rush.project.json"


def put(row: int, channel: int, text: str, pattern: int = 0) -> dict:
    return {"op": "set", "pattern": pattern, "row": row, "channel": channel, "cell": text}


class Base(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.dir = Path(self._directory.name)
        self.home = self.dir / "home"
        environment = mock.patch.dict(os.environ, {"CHIPLOOM_HOME": str(self.home)})
        environment.start()
        self.addCleanup(environment.stop)
        self.project = self.dir / "song.project.json"
        shutil.copyfile(EXAMPLE, self.project)
        self.document = Document.open(self.project)
        self.events: list[tuple[str, dict]] = []
        self.session = LiveSession(self.document, on_event=lambda kind, payload: self.events.append((kind, payload)))

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]


class SessionTests(Base):
    def test_patch_is_journaled_and_emitted(self):
        result = self.session.apply_patch([put(1, 0, "C-2 01 ...")], label="Kick on row 1")
        self.assertTrue(result["changed"])
        self.assertEqual(result["revision"], 1)
        self.assertEqual(self.document.module.patterns[0].get(1, 0).text(), "C-2 01 000")
        changes = self.session.changes()
        self.assertEqual(changes["revision"], 1)
        entry = changes["entries"][0]
        self.assertEqual((entry["author"], entry["label"], entry["kind"]), ("agent", "Kick on row 1", "patch"))
        self.assertEqual(entry["diff"]["cells"][0]["after"], "C-2 01 ...")
        self.assertTrue(entry["summary"])
        self.assertNotIn("_keys", entry)
        json.dumps(changes)  # fully serializable
        self.assertEqual(changes["summary"]["agent"]["entries"], 1)
        self.assertEqual(changes["summary"]["human"]["entries"], 0)
        self.assertEqual(self.kinds(), ["change"])
        # No-op patches are not journaled; invalid ones change nothing.
        self.assertFalse(self.session.apply_patch([put(1, 0, "C-2 01 ...")])["changed"])
        with self.assertRaises(ValidationError):
            self.session.apply_patch([put(2, 0, "C-2 01 ..."), put(99, 0, "C-2 01 ...")])
        self.assertEqual(self.session.revision, 1)
        self.assertEqual(self.document.module.patterns[0].get(2, 0).text(), "--- 00 000")

    def test_patch_accepts_wrapped_document_form(self):
        result = self.session.apply_patch({"ops": [put(1, 0, "C-2 01 ...")], "label": "Wrapped", "base_revision": 0})
        self.assertTrue(result["changed"])
        self.assertEqual(self.session.changes()["entries"][0]["label"], "Wrapped")

    def test_sync_journals_direct_human_edits_undo_and_redo(self):
        self.assertIsNone(self.session.sync())
        self.document.replace_cell(0, 1, 0, project.from_dict(project.to_dict(self.document.module)).patterns[0].get(0, 0))
        entry = self.session.sync()
        self.assertEqual((entry["author"], entry["label"], entry["revision"]), ("human", "Edit", 1))
        self.assertIsNone(self.session.sync())
        self.document.undo()
        undo = self.session.sync(label="Undo")
        self.assertEqual((undo["author"], undo["label"]), ("human", "Undo"))
        self.assertEqual(undo["diff"]["cells"][0]["after"], "--- -- ...")
        self.document.redo()
        self.assertEqual(self.session.sync(label="Redo")["revision"], 3)
        self.assertEqual(self.session.changes(since=1)["summary"]["human"]["entries"], 2)
        self.assertEqual(self.session.changes(author="agent")["entries"], [])

    def test_unreported_direct_edits_are_noticed_on_the_next_call(self):
        self.document.patch([put(1, 0, "D-2 01 ...")], "Direct")
        changes = self.session.changes()
        self.assertEqual([entry["author"] for entry in changes["entries"]], ["human"])

    def test_conflict_with_a_human_edit_since_base_revision(self):
        base = self.session.revision
        self.document.patch([put(1, 0, "E-2 01 ...")], "Human edit")
        self.session.sync()
        with self.assertRaises(LiveConflict) as caught:
            self.session.apply_patch([put(1, 0, "G-2 01 ..."), put(2, 0, "G-2 01 ...")], base_revision=base)
        exc = caught.exception
        self.assertEqual(exc.code, "LIVE_CONFLICT")
        self.assertIsInstance(exc, ValidationError)
        self.assertEqual(len(exc.conflicts), 1)
        conflict = exc.conflicts[0]
        self.assertEqual((conflict["unit"], conflict["pattern"], conflict["row"], conflict["channel"]), ("cell", 0, 1, 0))
        self.assertEqual((conflict["current"], conflict["yours"], conflict["author"]), ("E-2 01 ...", "G-2 01 ...", "human"))
        # Atomic: the non-overlapping cell of the refused patch was not written either.
        self.assertEqual(self.document.module.patterns[0].get(2, 0).text(), "--- 00 000")
        # A different cell with the same stale base is fine, and so is the current revision.
        self.assertTrue(self.session.apply_patch([put(2, 0, "G-2 01 ...")], base_revision=base)["changed"])
        self.assertTrue(self.session.apply_patch([put(1, 0, "G-2 01 ...")], base_revision=self.session.revision)["changed"])

    def test_own_edits_never_conflict_but_other_agents_do(self):
        base = self.session.revision
        self.session.apply_patch([put(1, 0, "E-2 01 ...")], author="agent")
        self.assertTrue(self.session.apply_patch([put(1, 0, "G-2 01 ...")], author="agent", base_revision=base)["changed"])
        with self.assertRaises(LiveConflict):
            self.session.apply_patch([put(1, 0, "A-2 01 ...")], author="helper", base_revision=base)

    def test_structure_and_title_conflicts_and_bad_base(self):
        base = self.session.revision
        self.document.patch([{"op": "title", "title": "Human title"}], "Title")
        self.session.sync()
        with self.assertRaises(LiveConflict) as caught:
            self.session.apply_patch([{"op": "title", "title": "Agent title"}], base_revision=base)
        self.assertEqual(caught.exception.conflicts[0]["unit"], "title")
        self.assertEqual(caught.exception.conflicts[0]["current"], "Human title")
        for bad in (-1, 99, "1", True):
            with self.assertRaises(ValidationError) as invalid:
                self.session.apply_patch([put(3, 0, "C-2 01 ...")], base_revision=bad)
            self.assertEqual(invalid.exception.code, "LIVE_BASE")

    def test_opening_another_file_conflicts_with_older_bases(self):
        base = self.session.revision
        other = Document(mod.decode(mod.encode(self.document.module)))
        self.session.reset(other, label="Open")
        self.assertEqual(self.session.changes()["entries"][-1]["kind"], "open")
        with self.assertRaises(LiveConflict) as caught:
            self.session.apply_patch([put(3, 0, "C-2 01 ...")], base_revision=base)
        self.assertEqual(caught.exception.conflicts[0]["unit"], "document")
        self.assertIn("reset", self.kinds())

    def test_reload_of_the_same_path_journals_the_net_diff(self):
        self.project.write_text(self.project.read_text(encoding="utf-8").replace(
            self.document.module.title, "Reloaded title", 1), encoding="utf-8")
        entry = self.session.reset(Document.open(self.project), label="Reload")
        self.assertEqual((entry["kind"], entry["author"]), ("reload", "human"))
        self.assertEqual(entry["diff"]["title"]["after"], "Reloaded title")
        self.assertIsNone(self.session.reset(Document.open(self.project)))  # nothing new

    def test_journal_is_bounded_and_reports_the_gap(self):
        with mock.patch.object(live, "JOURNAL_LIMIT", 5):
            for index in range(8):
                self.session.apply_patch([put(index, 0, "C-2 01 ...")])
        changes = self.session.changes(since=0)
        self.assertEqual(len(changes["entries"]), 5)
        self.assertIn("gap", changes)
        with self.assertRaises(LiveConflict) as caught:
            self.session.apply_patch([put(20, 0, "C-2 01 ...")], base_revision=0)
        self.assertEqual(caught.exception.conflicts[0]["unit"], "history")

    def test_proposals_accept_and_reject(self):
        first = self.session.propose([put(1, 0, "C-2 01 ...")], label="Add kick")
        self.assertEqual((first["id"], first["status"], first["author"]), ("p1", "pending", "agent"))
        self.assertEqual(self.document.module.patterns[0].get(1, 0).text(), "--- 00 000")  # nothing applied
        self.assertEqual([item["id"] for item in self.session.proposals()], ["p1"])
        preview = self.session.proposal_preview("p1")
        self.assertEqual(preview.patterns[0].get(1, 0).text(), "C-2 01 000")
        self.assertEqual(self.document.module.patterns[0].get(1, 0).text(), "--- 00 000")
        accepted = self.session.accept("p1", author="human")
        self.assertTrue(accepted["changed"])
        entry = self.session.changes()["entries"][-1]
        self.assertEqual((entry["author"], entry["kind"], entry["accepted_by"], entry["proposal"]),
                         ("agent", "accept", "human", "p1"))
        self.assertEqual(self.session.proposals(), [])
        self.assertEqual(self.session.proposals("accepted")[0]["status"], "accepted")
        with self.assertRaises(ValidationError) as again:
            self.session.accept("p1")
        self.assertEqual(again.exception.code, "LIVE_PROPOSAL")
        second = self.session.propose([put(2, 0, "D-2 01 ...")])
        rejected = self.session.reject(second["id"], reason="not now")
        self.assertEqual((rejected["status"], rejected["closed_by"], rejected["reason"]), ("rejected", "human", "not now"))
        third = self.session.propose([put(3, 0, "E-2 01 ...")])
        self.assertEqual(self.session.withdraw(third["id"])["status"], "withdrawn")
        self.assertEqual([item[1]["action"] for item in self.events if item[0] == "proposal"],
                         ["created", "accepted", "created", "rejected", "created", "withdrawn"])
        with self.assertRaises(ValidationError):
            self.session.propose([put(99, 0, "C-2 01 ...")])
        with self.assertRaises(ValidationError):
            self.session.propose([put(1, 0, "C-2 01 ...")])  # already there: nothing to propose

    def test_accepting_a_stale_proposal_detects_the_owner_edit(self):
        proposal = self.session.propose([put(1, 0, "G-2 01 ..."), put(2, 0, "G-2 01 ...")])
        self.document.patch([put(1, 0, "E-2 01 ...")], "Owner")
        self.session.sync()
        self.assertTrue(self.session.proposals()[0]["stale"])
        with self.assertRaises(LiveConflict):
            self.session.accept(proposal["id"])
        self.assertEqual(self.session.proposals()[0]["status"], "pending")
        self.assertEqual(self.document.module.patterns[0].get(2, 0).text(), "--- 00 000")
        self.session.accept(proposal["id"], force=True)
        self.assertEqual(self.document.module.patterns[0].get(1, 0).text(), "G-2 01 000")

    def test_takes_are_validated(self):
        mod_path = self.dir / "take.mod"
        self.document.export_mod(mod_path)
        project_take = self.session.add_take(self.project, "Original")
        mod_take = self.session.add_take(mod_path, "As MOD", author="helper")
        self.assertEqual((project_take["id"], mod_take["id"]), ("t1", "t2"))
        self.assertEqual(mod_take["author"], "helper")
        self.assertGreater(mod_take["duration_seconds"], 1)
        self.assertEqual(len(mod_take["sha256"]), 64)
        self.assertEqual(self.session.takes(), [project_take, mod_take])
        self.assertEqual(self.kinds().count("take"), 2)
        broken = self.dir / "broken.project.json"
        broken.write_text("{\"schema\": \"nope\"}", encoding="utf-8")
        for path in (broken, self.dir / "missing.mod", self.dir / "notes.txt"):
            if path.name == "notes.txt":
                path.write_text("x", encoding="utf-8")
            with self.assertRaises((ValidationError, ValueError)):
                self.session.add_take(path, "bad")
        (self.dir / "truncated.mod").write_bytes(b"MOD")
        with self.assertRaises(ValidationError):
            self.session.add_take(self.dir / "truncated.mod", "bad")
        self.assertEqual(len(self.session.takes()), 2)

    def test_requests_without_a_window(self):
        for kind in ("play", "stop"):
            with self.assertRaises(ValidationError) as caught:
                self.session.request(kind)
            self.assertEqual(caught.exception.code, "LIVE_NO_WINDOW")
        take = self.session.add_take(self.project, "Original")
        self.assertEqual(self.session.request_open(take=take["id"]), {"handled": False})
        self.assertEqual(self.session.request_open(path=self.project), {"handled": False})
        self.assertEqual(self.session.request("select", {"pattern": 1, "row": 4, "channel": 2, "rows": 2}),
                         {"handled": False})
        self.assertEqual(self.session.context()["selection"],
                         {"pattern": 1, "row": 4, "channel": 2, "rows": 2, "channels": 1})
        with self.assertRaises(ValidationError):
            self.session.request("select", {"pattern": 99, "row": 0, "channel": 0})
        with self.assertRaises(ValidationError):
            self.session.request_open(take="t9")
        with self.assertRaises(ValidationError):
            self.session.request_open()
        with self.assertRaises(ValidationError):
            self.session.request("explode")
        self.assertFalse(self.session.context()["window"])

    def test_handlers_receive_requests(self):
        seen = []
        self.session.set_handler("play", lambda payload: seen.append(payload) or {"position": 0})
        self.session.set_handler("open", lambda payload: seen.append(payload))
        self.assertEqual(self.session.request("play", {"order": 2}), {"handled": True, "position": 0})
        take = self.session.add_take(self.project, "Original")
        self.assertEqual(self.session.request_open(take=take["id"])["handled"], True)
        self.assertEqual(seen[0], {"order": 2})
        self.assertEqual((seen[1]["take"], seen[1]["path"]), ("t1", str(self.project.resolve())))
        self.assertIn(("request", {"kind": "play", "payload": {"order": 2}, "handled": True}), self.events)
        self.assertTrue(self.session.context()["window"])
        with self.assertRaises(ValidationError):
            self.session.request("play", {"order": 999})
        self.session.set_handler("play", None)
        with self.assertRaises(ValidationError):
            self.session.request("play")

    def test_context_and_score(self):
        self.session.update_context(order=1, pattern=1, row=7, channel=2, playing=True, position_seconds=3.5,
                                    selection={"pattern": 1, "row": 7, "rows": 2, "channel": 2, "channels": 1},
                                    language="fr")
        context = self.session.context()
        self.assertEqual((context["order"], context["row"], context["playing"], context["language"]), (1, 7, True, "fr"))
        self.assertEqual(context["title"], self.document.module.title)
        self.assertEqual(context["path"], str(self.project.resolve()))
        self.assertEqual((context["revision"], context["document_revision"], context["dirty"]), (0, 0, False))
        self.assertEqual(context["orders"], list(self.document.module.orders))
        self.assertEqual(context["pattern_count"], len(self.document.module.patterns))
        self.session.update_context(playing=None)
        self.assertNotIn("playing", self.session.context())
        with self.assertRaises(ValidationError):
            self.session.update_context(unknown=1)
        self.session.apply_patch([put(1, 0, "C-2 01 ...")])
        self.assertTrue(self.session.context()["dirty"])
        self.assertEqual(self.session.context()["last_change"]["author"], "agent")
        overview = self.session.score()
        self.assertEqual(overview["revision"], 1)
        self.assertEqual(len(overview["patterns"]), len(self.document.module.patterns))
        self.assertEqual({"slot", "name", "volume", "finetune", "length", "sha256", "library_id"} - set(overview["samples"][0]), set())
        grid = self.session.score(pattern=0, start=0, rows=4)
        self.assertEqual(len(grid["lines"]), 4)
        self.assertIn("C-2 01 ...", grid["lines"][1])
        self.assertEqual(self.session.score(pattern=0, start=60, rows=64)["rows"], 4)
        with self.assertRaises(ValidationError):
            self.session.score(pattern=99)

    def test_save_goes_through_the_document(self):
        self.session.apply_patch([put(1, 0, "C-2 01 ...")])
        saved = self.session.save()
        self.assertEqual(saved["path"], str(self.project.resolve()))
        self.assertFalse(saved["dirty"])
        self.assertEqual(project.load(self.project).patterns[0].get(1, 0).text(), "C-2 01 000")
        copy = self.session.save(self.dir / "copy.project.json")
        self.assertTrue(Path(copy["path"]).is_file())
        with self.assertRaises(ValidationError) as caught:
            self.session.save(self.dir / "copy.mod")
        self.assertEqual(caught.exception.code, "LIVE_SAVE_PATH")
        self.assertIn("saved", self.kinds())
        headless = LiveSession(Document(mod.decode(mod.encode(self.document.module))))
        with self.assertRaises(ValidationError):
            headless.save()

    def test_dispatcher_wraps_each_public_call_once(self):
        calls = []

        def dispatcher(fn):
            calls.append(threading.current_thread().name)
            return fn()

        session = LiveSession(self.document, dispatcher=dispatcher)
        session.apply_patch([put(1, 0, "C-2 01 ...")])      # nested helpers must not dispatch again
        session.accept(session.propose([put(2, 0, "D-2 01 ...")])["id"])
        self.assertEqual(len(calls), 3)

    def test_a_failing_listener_does_not_break_edits(self):
        def broken(kind, payload):
            raise RuntimeError("ui bug")

        self.session.add_listener(broken)
        self.assertTrue(self.session.apply_patch([put(1, 0, "C-2 01 ...")])["changed"])

    def test_concurrent_patches_are_serialized(self):
        errors = []

        def work(start):
            try:
                for row in range(start, start + 8):
                    self.session.apply_patch([put(row, 3, "C-2 01 ...", pattern=1)])
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(index * 8,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.session.revision, 32)


class ServerTests(Base):
    def setUp(self):
        super().setUp()
        self.server = LiveServer(self.session, kind="headless").start()
        self.addCleanup(self.server.stop)
        self.client = LiveClient(self.server.url, self.server.token)

    def raw(self, method="POST", path="/v1/status", body=b"{}", token="default", headers=None):
        target = urlparse(self.server.url)
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=10)
        values = {"Content-Length": str(len(body)), **(headers or {})}
        if token == "default":
            token = self.server.token
        if token is not None:
            values["Authorization"] = f"Bearer {token}"
        try:
            connection.request(method, path, body, values)
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def test_authentication(self):
        status, body = self.raw(token=None)
        self.assertEqual((status, body["code"], body["ok"]), (401, "LIVE_AUTH", False))
        self.assertEqual(self.raw(token="wrong" * 8)[0], 401)
        self.assertEqual(self.raw(token="")[0], 401)
        self.assertEqual(self.raw(token=None, headers={"Authorization": self.server.token})[0], 401)
        self.assertEqual(self.raw()[0], 200)
        self.assertEqual(self.raw(headers={"Origin": "http://evil.example"})[0], 403)
        with self.assertRaises(ValidationError) as caught:
            LiveClient(self.server.url, "x" * 64).call("status")
        self.assertEqual(caught.exception.code, "LIVE_AUTH")
        self.assertEqual(len(self.server.token), 64)
        self.assertNotEqual(self.server.token, LiveServer(self.session).token)

    def test_http_contract(self):
        self.assertEqual(self.raw(path="/v1/nothing")[1]["code"], "LIVE_UNKNOWN_METHOD")
        self.assertEqual(self.raw(path="/v1/nothing")[0], 404)
        self.assertEqual(self.raw(path="/other")[0], 404)
        self.assertEqual(self.raw(method="GET", path="/v1/status", body=b"")[0], 405)
        self.assertEqual(self.raw(body=b"[1]")[0], 400)
        self.assertEqual(self.raw(body=b"not json")[0], 400)
        status, body = self.raw(path="/v1/score", body=b'{"bogus": 1}')
        self.assertEqual((status, body["code"]), (422, "LIVE_PARAMS"))
        status, body = self.raw(path="/v1/patch", body=json.dumps({"ops": [put(99, 0, "C-2 01 ...")]}).encode())
        self.assertEqual(status, 422)
        self.assertFalse(body["ok"])
        self.assertIn("code", body)
        status, body = self.raw(path="/v1/play")
        self.assertEqual((status, body["code"]), (503, "LIVE_NO_WINDOW"))
        status, body = self.raw(path="/v1/patch", body=json.dumps({"ops": [put(3, 0, "C-2 01 ...")], "author": "human"}).encode())
        self.assertEqual((status, body["code"]), (422, "LIVE_AUTHOR"))

    def test_body_size_limit(self):
        status, body = self.raw(body=b" " * (live.MAX_BODY + 1))
        self.assertEqual((status, body["code"]), (413, "LIVE_TOO_LARGE"))
        padding = json.dumps({"label": "x" * 1_000_000}).encode()
        self.assertEqual(self.raw(path="/v1/changes", body=padding)[0], 422)  # accepted size, unknown parameter
        # An unauthenticated oversized request is refused as unauthenticated and the server stays healthy.
        self.assertEqual(self.raw(token=None, body=b" " * (live.MAX_BODY + 10))[0], 401)
        self.assertEqual(self.raw()[0], 200)

    def test_only_loopback_hosts(self):
        for host in ("0.0.0.0", "192.168.1.20", "example.com", "", "::"):
            with self.assertRaises(ValidationError) as caught:
                LiveServer(self.session, host=host)
            self.assertEqual(caught.exception.code, "LIVE_HOST")
        self.assertEqual(urlparse(self.server.url).hostname, "127.0.0.1")
        with LiveServer(self.session, host="localhost", home=self.dir / "other") as other:
            self.assertTrue(other.url.startswith("http://127.0.0.1:"))

    def test_discovery_file_lifecycle(self):
        files = sorted((self.home / "live").glob("*.json"))
        self.assertEqual([file.name for file in files], [f"{os.getpid()}.json"])
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual((data["url"], data["token"], data["kind"]), (self.server.url, self.server.token, "headless"))
        self.assertEqual(data["path"], str(self.project.resolve()))
        self.assertEqual(data["title"], self.document.module.title)
        self.assertTrue(data["started"].endswith("Z"))
        if os.name != "nt":
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual([item["url"] for item in live.discover()], [self.server.url])
        # A second server in the same process gets its own file; the newest comes first.
        second = LiveServer(self.session, kind="desktop").start()
        self.assertEqual(len(list((self.home / "live").glob("*.json"))), 2)
        found = live.discover()
        self.assertEqual([item["url"] for item in found], [second.url, self.server.url])
        self.assertEqual(LiveClient.discover().url, second.url)
        self.assertEqual(LiveClient.discover(session=self.server.url).url, self.server.url)
        self.assertEqual(LiveClient.discover(session=str(os.getpid())).url, second.url)
        second.stop()
        self.assertEqual(len(list((self.home / "live").glob("*.json"))), 1)
        self.server.stop()
        self.assertEqual(list((self.home / "live").glob("*.json")), [])
        with self.assertRaises(ValidationError) as caught:
            LiveClient.discover()
        self.assertEqual(caught.exception.code, "LIVE_NOT_RUNNING")
        with self.assertRaises(ValidationError) as down:
            self.client.call("status")
        self.assertEqual(down.exception.code, "LIVE_NOT_RUNNING")

    def test_stale_discovery_files_are_cleaned(self):
        directory = self.home / "live"
        stale = directory / "2147483646.json"
        stale.write_text(json.dumps({"pid": 2147483646, "url": "http://127.0.0.1:9", "token": "t", "started": "2000"}))
        junk = directory / "junk.json"
        junk.write_text("not json")
        refused = directory / f"{os.getpid()}-1.json"  # alive pid but nothing listens there
        refused.write_text(json.dumps({"pid": os.getpid(), "url": "http://127.0.0.1:1", "token": "t", "started": "2001"}))
        self.assertEqual([item["url"] for item in live.discover()], [self.server.url])
        self.assertFalse(stale.exists() or junk.exists() or refused.exists())
        self.assertTrue(live.pid_alive(os.getpid()))
        self.assertFalse(live.pid_alive(2147483646))
        self.assertFalse(live.pid_alive(0))

    def test_discovery_follows_the_opened_file(self):
        copy = self.dir / "other.project.json"
        shutil.copyfile(EXAMPLE, copy)
        self.session.reset(Document.open(copy))
        data = json.loads(next((self.home / "live").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(data["path"], str(copy.resolve()))

    def test_client_round_trip(self):
        ping = self.client.call("ping")
        self.assertEqual((ping["ok"], ping["pid"], ping["revision"]), (True, os.getpid(), 0))
        status = self.client.call("status")
        self.assertEqual(status["title"], self.document.module.title)
        self.assertTrue(status["ok"])
        overview = self.client.call("score")
        self.assertEqual(overview["revision"], 0)
        grid = self.client.call("score", pattern=0, start=0, rows=2)
        self.assertEqual(len(grid["lines"]), 2)

        result = self.client.call("patch", ops=[put(1, 0, "C-2 01 ...")], label="Kick", base_revision=0)
        self.assertEqual((result["changed"], result["revision"]), (True, 1))
        self.assertEqual(self.document.module.patterns[0].get(1, 0).text(), "C-2 01 000")
        self.assertTrue(self.document.dirty)

        # The owner edits a cell in the window; the agent sees it and is refused on overlap.
        self.document.patch([put(2, 0, "E-2 02 ...")], "Owner edit")
        self.session.sync()
        changes = self.client.call("changes", since=1)
        self.assertEqual([(entry["author"], entry["revision"]) for entry in changes["entries"]], [("human", 2)])
        self.assertEqual(changes["summary"]["human"]["entries"], 1)
        with self.assertRaises(LiveConflict) as caught:
            self.client.call("patch", ops=[put(2, 0, "A-2 01 ...")], base_revision=1)
        self.assertEqual(caught.exception.conflicts[0]["current"], "E-2 02 ...")
        self.assertEqual(caught.exception.revision, 2)
        self.assertEqual(self.client.call("patch", ops=[put(2, 0, "A-2 01 ...")], base_revision=2)["revision"], 3)

        proposal = self.client.call("patch", ops=[put(5, 0, "C-2 01 ...")], propose=True, label="Idea")["proposal"]
        self.assertEqual(self.client.call("proposals")["proposals"][0]["id"], proposal["id"])
        self.assertNotEqual(self.document.module.patterns[0].get(5, 0).text(), "C-2 01 000")
        self.assertEqual(self.client.call("withdraw", id=proposal["id"])["proposal"]["status"], "withdrawn")
        self.assertEqual(self.client.call("proposals")["proposals"], [])
        with self.assertRaises(ValidationError) as unknown:
            self.client.call("withdraw", id="p99")
        self.assertEqual(unknown.exception.code, "LIVE_PROPOSAL")

        take = self.client.call("take", path=str(self.project), label="Start")["take"]
        self.assertEqual(self.client.call("takes")["takes"][0]["id"], take["id"])
        self.assertEqual(self.client.call("open", take=take["id"])["handled"], False)
        for method in ("play", "stop"):
            with self.assertRaises(ValidationError) as headless:
                self.client.call(method)
            self.assertEqual(headless.exception.code, "LIVE_NO_WINDOW")
        selected = self.client.call("select", pattern=1, row=3, channel=1)
        self.assertEqual(selected["handled"], False)
        self.assertEqual(self.client.call("status")["selection"]["row"], 3)

        saved = self.client.call("save", path=str(self.dir / "out.project.json"))
        # Another path writes a copy: the session keeps its own (still unsaved) file.
        self.assertEqual((saved["copy"], saved["dirty"]), (True, True))
        self.assertEqual(self.document.path, self.project.resolve())
        self.assertEqual(self.client.call("save")["dirty"], False)
        self.assertEqual(project.load(self.dir / "out.project.json").patterns[0].get(1, 0).text(), "C-2 01 000")
        with self.assertRaises(ValidationError) as unknown_method:
            self.client.call("explode")
        self.assertEqual(unknown_method.exception.code, "LIVE_UNKNOWN_METHOD")

    def test_window_requests_reach_registered_handlers_over_http(self):
        self.session.set_handler("play", lambda payload: {"started": True, "order": payload.get("order", 0)})
        self.assertEqual(self.client.call("play", order=2), {"ok": True, "handled": True, "started": True, "order": 2})


class CliTests(Base):
    def setUp(self):
        super().setUp()
        self.server = LiveServer(self.session).start()
        self.addCleanup(self.server.stop)
        self.parser = argparse.ArgumentParser(prog="chiploom")
        live_cli.add_parser(self.parser.add_subparsers(dest="command", required=True))

    def run_cli(self, *argv):
        return live_cli.run(self.parser.parse_args(["live", *argv]))

    def test_sessions_hide_tokens_and_status_reads_the_window(self):
        sessions = self.run_cli("sessions")["sessions"]
        self.assertEqual([item["url"] for item in sessions], [self.server.url])
        self.assertNotIn("token", sessions[0])
        self.assertEqual(self.run_cli("status")["title"], self.document.module.title)
        self.assertEqual(self.run_cli("--session", str(os.getpid()), "status")["revision"], 0)
        self.assertEqual(self.run_cli("status", "--session", self.server.url)["revision"], 0)
        with self.assertRaises(ValidationError) as caught:
            self.run_cli("status", "--session", "1")
        self.assertEqual(caught.exception.code, "LIVE_NOT_RUNNING")

    def test_patch_changes_proposals_and_conflicts(self):
        result = self.run_cli("patch", "--op", json.dumps(put(1, 0, "C-2 01 ...")), "--label", "CLI kick", "--base", "0")
        self.assertEqual(result["revision"], 1)
        ops = self.dir / "ops.json"
        ops.write_text(json.dumps({"ops": [put(2, 0, "D-2 01 ..."), put(3, 0, "E-2 01 ...")], "label": "From file",
                                   "base_revision": 1}), encoding="utf-8")
        self.assertEqual(self.run_cli("patch", "--ops", str(ops))["revision"], 2)
        self.assertEqual(self.run_cli("changes", "--since", "1")["entries"][0]["label"], "From file")
        self.document.patch([put(1, 0, "G-2 01 ...")], "Owner")
        self.session.sync()
        with self.assertRaises(LiveConflict):
            self.run_cli("patch", "--op", json.dumps(put(1, 0, "A-2 01 ...")), "--base", "0")
        proposed = self.run_cli("patch", "--op", json.dumps(put(8, 1, "C-2 01 ...")), "--propose", "--author", "bard")
        self.assertEqual(proposed["proposal"]["author"], "bard")
        self.assertEqual(self.run_cli("proposals")["proposals"][0]["id"], proposed["proposal"]["id"])
        self.assertEqual(self.run_cli("withdraw", proposed["proposal"]["id"])["proposal"]["status"], "withdrawn")
        with self.assertRaises(ValidationError) as bad:
            self.run_cli("patch", "--op", "{broken")
        self.assertEqual(bad.exception.code, "PATCH_FORMAT")

    def test_score_take_open_select_play_save(self):
        self.assertIn("lines", self.run_cli("score", "--pattern", "0", "--row", "2", "--rows", "3"))
        self.assertEqual(len(self.run_cli("score", "--pattern", "0", "--row", "2", "--rows", "3")["lines"]), 3)
        self.assertIn("samples", self.run_cli("score"))
        take = self.run_cli("take", str(self.project), "--label", "Start")["take"]
        self.assertEqual(self.run_cli("takes")["takes"][0]["label"], "Start")
        self.assertEqual(self.run_cli("open", "--take", take["id"])["handled"], False)
        self.assertEqual(self.run_cli("open", str(self.project))["handled"], False)
        with self.assertRaises(ValidationError):
            self.run_cli("open")
        self.assertEqual(self.run_cli("select", "--pattern", "1", "--row", "2", "--channel", "3")["handled"], False)
        with self.assertRaises(ValidationError) as headless:
            self.run_cli("play", "--order", "1")
        self.assertEqual(headless.exception.code, "LIVE_NO_WINDOW")
        self.assertEqual(self.run_cli("save", "--output", str(self.dir / "cli.project.json"))["dirty"], False)

    def test_serve_hosts_a_headless_session_until_stopped(self):
        stop, announced, outcome = threading.Event(), [], {}
        args = self.parser.parse_args(["live", "serve", str(self.project), "--port", "0"])
        worker = threading.Thread(target=lambda: outcome.update(live_cli.run(args, stop, announced.append)))
        worker.start()
        try:
            for _ in range(100):
                if announced:
                    break
                threading.Event().wait(0.05)
            self.assertTrue(announced, "serve did not announce itself")
            info = announced[0]
            self.assertEqual((info["event"], info["kind"], info["pid"]), ("listening", "headless", os.getpid()))
            self.assertNotIn("token", info)
            client = LiveClient.discover(session=info["url"])
            self.assertEqual(client.call("patch", ops=[put(1, 0, "C-2 01 ...")])["changed"], True)
        finally:
            stop.set()
            worker.join(10)
        self.assertEqual((outcome["event"], outcome["revision"], outcome["dirty"]), ("stopped", 1, True))
        self.assertEqual([item["url"] for item in live.discover()], [self.server.url])


if __name__ == "__main__":
    unittest.main()
