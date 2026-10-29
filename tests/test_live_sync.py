"""`chiploom live sync`: a project file pushed into a running session as undoable patches."""

from __future__ import annotations

import argparse
import copy
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tracker4agents import live_cli, live_sync, project
from tracker4agents.convert import mod_to_xm
from tracker4agents.document import Document
from tracker4agents.errors import error_payload
from tracker4agents.live import LiveClient, LiveConflict, LiveServer, LiveSession
from tracker4agents.model import ValidationError
from tracker4agents.patch import apply_ops

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "pixel_rush.project.json"


def put(row: int, channel: int, text: str, pattern: int = 0) -> dict:
    return {"op": "set", "pattern": pattern, "row": row, "channel": channel, "cell": text}


class Base(unittest.TestCase):
    source = EXAMPLE

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.dir = Path(self._directory.name)
        environment = mock.patch.dict(os.environ, {"CHIPLOOM_HOME": str(self.dir / "home")})
        environment.start()
        self.addCleanup(environment.stop)
        self.project = self.dir / "song.project.json"
        self.write_source()
        self.document = Document.open(self.project)
        self.session = LiveSession(self.document)
        self.server = LiveServer(self.session, kind="headless").start()
        self.addCleanup(self.server.stop)
        self.client = LiveClient(self.server.url, self.server.token)
        self.parser = argparse.ArgumentParser(prog="chiploom")
        live_cli.add_parser(self.parser.add_subparsers(dest="command", required=True))

    def write_source(self) -> None:
        shutil.copyfile(self.source, self.project)

    def run_cli(self, *argv):
        return live_cli.run(self.parser.parse_args(["live", *argv]))

    def variant(self, ops: list[dict], edit=None, name: str = "regenerated.project.json", recipes: bool = True) -> Path:
        """A copy of the session's project with `ops` applied (and `edit(module)`), as a script would write it."""
        module = project.load(self.project)
        if ops:
            apply_ops(module, ops)
        if edit:
            edit(module)
        path = self.dir / name
        project.write_json(path, project.to_dict(module, recipes=recipes))
        return path


class SyncTests(Base):
    CHANGES = [put(3, 1, "C-2 01 ..."), put(5, 2, "E-2 02 C20", pattern=2), put(9, 2, "E-2 02 C20", pattern=2),
               {"op": "set_orders", "orders": [0, 1, 2, 3, 4, 1, 5, 6, 1]}, {"op": "sample", "slot": 3, "volume": 30}]

    def test_full_read_matches_the_session(self):
        revision, module = live_sync.read_session(self.client)
        self.assertEqual(revision, 0)
        self.assertEqual(live_sync.mismatches(self.document.module, module), [])
        self.assertEqual([sample.recipe for sample in module.samples], [s.recipe for s in self.document.module.samples])

    def test_sync_sends_one_patch_per_pattern_and_verifies(self):
        target = self.variant(self.CHANGES)
        result = self.run_cli("sync", str(target), "--label", "Regen")
        self.assertTrue(result["ok"])
        self.assertFalse(result["unchanged"])
        self.assertTrue(result["verified"], result.get("mismatches"))
        self.assertEqual(result["revision_before"], 0)
        names = [pattern.name for pattern in self.document.module.patterns]
        self.assertEqual([(item["label"], item["pattern"]) for item in result["patches"]],
                         [("Regen: samples", None), ("Regen: structure", None),
                          (f"Regen: {names[0]}", 0), (f"Regen: {names[2]}", 2)])
        self.assertEqual([item["revision"] for item in result["patches"]], [1, 2, 3, 4])
        self.assertEqual(result["revision_after"], 4)
        self.assertEqual(result["not_synced"], [])
        module = self.document.module
        self.assertEqual(module.orders, [0, 1, 2, 3, 4, 1, 5, 6, 1])
        self.assertEqual(module.samples[2].volume, 30)
        self.assertEqual(module.patterns[2].get(9, 2).text(), "E-2 02 C20")
        # Each pattern is its own journal entry (one undo step in the window), written by the agent.
        entries = self.session.changes()["entries"]
        self.assertEqual([entry["author"] for entry in entries], ["agent"] * 4)
        self.assertEqual({entry["diff"]["cells"][0]["pattern"] for entry in entries[2:]}, {0, 2})
        self.assertTrue(self.run_cli("sync", str(target))["unchanged"])

    def test_dry_run_sends_nothing(self):
        target = self.variant(self.CHANGES)
        result = self.run_cli("sync", str(target), "--dry-run")
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.session.revision, 0)
        self.assertEqual(result["revision_after"], 0)
        ops = [op for item in result["patches"] for op in item["ops"]]
        self.assertIn({"op": "sample", "slot": 3, "volume": 30}, ops)
        self.assertIn({"op": "set_orders", "orders": [0, 1, 2, 3, 4, 1, 5, 6, 1]}, ops)
        self.assertIn({"op": "write", "pattern": 0, "row": 3, "channel": 1, "cells": ["C-2 01 ..."]}, ops)
        self.assertEqual([item["op_count"] for item in result["patches"]], [1, 1, 1, 1])

    def test_identical_project_is_unchanged(self):
        result = self.run_cli("sync", str(self.project))
        self.assertTrue(result["unchanged"])
        self.assertEqual((result["patches"], result["not_synced"]), ([], []))
        self.assertEqual(self.session.revision, 0)

    def test_patterns_added_removed_and_cleared(self):
        added = self.variant([{"op": "add_pattern", "copy_of": 1, "name": "Coda", "insert_order": "end"},
                              {"op": "clear", "pattern": 1, "rows": 64, "channel": 3}, {"op": "title", "title": "PR 2"}])
        planned = self.run_cli("sync", str(added), "--dry-run")["patches"]
        self.assertIn({"op": "add_pattern", "name": "Coda", "insert_order": None, "copy_of": 1}, planned[0]["ops"])
        self.assertEqual(planned[1]["ops"], [{"op": "clear", "pattern": 1, "row": 0, "rows": 64, "channel": 3}])
        self.assertEqual(len(planned), 2)
        result = self.run_cli("sync", str(added))
        self.assertTrue(result["verified"], result.get("mismatches"))
        self.assertEqual(self.document.module.patterns[-1].name, "Coda")
        self.assertEqual(self.document.module.title, "PR 2")
        back = live_sync.plan(project.load(self.project), self.document.module)["patches"]
        self.assertIn({"op": "remove_pattern", "pattern": 7}, back[0]["ops"])
        self.assertTrue(self.run_cli("sync", str(self.project))["verified"])
        self.assertEqual(len(self.document.module.patterns), 7)

    def test_invalid_intermediate_step_falls_back_to_one_patch(self):
        # The session ends on a jump to order 7; the project drops an order and jumps to 5 instead.
        self.session.apply_patch([put(63, 0, "--- 00 B07", pattern=6)])
        target = self.variant([{"op": "set_orders", "orders": [0, 1, 2, 3, 4, 5, 6]}, put(63, 0, "--- 00 B05", pattern=6)])
        result = self.run_cli("sync", str(target))
        self.assertTrue(result["verified"], result.get("mismatches"))
        self.assertEqual([item["label"] for item in result["patches"]], ["Sync: whole song"])
        self.assertEqual(self.document.module.orders, [0, 1, 2, 3, 4, 5, 6])

    def test_changed_recipe_is_regenerated(self):
        def louder_kick(module):
            module.samples[0].recipe = {**module.samples[0].recipe, "seed": 1}
            module.samples[0] = project.from_dict(project.to_dict(module)).samples[0]

        result = self.run_cli("sync", str(self.variant([], louder_kick)))
        self.assertTrue(result["verified"], result.get("mismatches"))
        self.assertEqual(self.document.module.samples[0].recipe["seed"], 1)
        self.assertEqual(result["patches"][0]["label"], "Sync: samples")
        # The inserted recipe writes its provenance record, which the project does not carry.
        self.assertEqual([item["what"] for item in result["not_synced"]], ["metadata.sample_sources"])

    def test_pcm_edit_without_recipe_or_library_id_is_not_synced(self):
        def edit(module):
            sample = module.samples[0]
            module.samples[0] = type(sample)(sample.name, tuple(-value for value in sample.pcm), sample.volume)

        result = self.run_cli("sync", str(self.variant([], edit, recipes=False)), "--dry-run")
        self.assertTrue(result["unchanged"])
        self.assertEqual([(item["what"], item["slot"]) for item in result["not_synced"]], [("sample 1", 1)])

    def test_concurrent_edit_after_the_read_stops_the_sync(self):
        target = self.variant(self.CHANGES)
        real_call, sent = self.client.call, []

        def owner_edits_between_patches(method, **params):
            if method == "patch" and not sent:
                # The owner types into pattern 0 right after the agent read the score.
                self.document.patch([put(3, 1, "G-2 04 ...")], "Owner")
                self.session.sync()
            if method == "patch":
                sent.append(params["label"])
            return real_call(method, **params)

        with mock.patch.object(self.client, "call", side_effect=owner_edits_between_patches):
            with self.assertRaises(LiveConflict) as caught:
                live_sync.sync(self.client, target, label="Regen")
        report = caught.exception.sync
        names = [pattern.name for pattern in self.document.module.patterns]
        self.assertEqual([item["label"] for item in report["applied"]], ["Regen: samples", "Regen: structure"])
        self.assertEqual(report["failed"]["label"], f"Regen: {names[0]}")
        self.assertEqual(report["not_applied"], [{"label": f"Regen: {names[2]}", "pattern": 2}])
        self.assertEqual(self.document.module.patterns[0].get(3, 1).text(), "G-2 04 000")  # the owner's edit stays
        payload = error_payload(caught.exception)
        self.assertEqual(payload["code"], "LIVE_CONFLICT")
        self.assertEqual(payload["conflicts"][0]["unit"], "cell")
        self.assertEqual(payload["sync"]["revision_before"], 0)

    def test_format_mismatch_is_refused(self):
        module, _ = mod_to_xm(project.load(self.project))
        path = self.dir / "song.xm.project.json"
        project.write_json(path, project.to_dict(module, recipes=False))
        with self.assertRaises(ValidationError) as caught:
            self.run_cli("sync", str(path))
        self.assertEqual(caught.exception.code, "LIVE_SYNC_FORMAT")


class XmSyncTests(Base):
    def write_source(self) -> None:
        module, _ = mod_to_xm(project.load(EXAMPLE))
        project.write_json(self.project, project.to_dict(module, recipes=False))

    def test_envelope_is_reported_and_xm_fields_are_synced(self):
        def edit(module):
            module.metadata.setdefault("xm", {}).setdefault("instruments", {})["1"] = {
                "volume_envelope": {"points": [[0, 64], [10, 32], [20, 0]], "sustain": 1, "type": 3}}
            module.metadata["xm"]["default_bpm"] = 140
            module.samples[1].panning = 64
            module.patterns[1].rows = 32
            for key in [key for key in module.patterns[1].cells if key[0] >= 32]:
                del module.patterns[1].cells[key]

        target = self.variant([], edit, recipes=False)
        result = self.run_cli("sync", str(target))
        self.assertTrue(result["verified"], result.get("mismatches"))
        envelope = [item for item in result["not_synced"] if item["what"] == "XM instrument 1"]
        self.assertEqual(envelope[0]["fields"], ["volume_envelope"])
        module = self.document.module
        self.assertEqual((module.patterns[1].rows, module.samples[1].panning), (32, 64))
        self.assertEqual(module.metadata["xm"]["default_bpm"], 140)
        self.assertNotIn("1", module.metadata["xm"].get("instruments", {}))  # not sent: a reload takes it
        # Planned back towards the original file: the XM-only operations appear.
        ops =[op["op"] for item in live_sync.plan(project.load(self.project), copy.deepcopy(module))["patches"]
               for op in item["ops"]]
        self.assertIn("pattern_length", ops)
        self.assertIn("xm_header", ops)


if __name__ == "__main__":
    unittest.main()
