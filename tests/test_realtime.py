"""Real-time libxmp engine: streaming blocks, seeking, reloading edits and channel mutes."""
from __future__ import annotations

from pathlib import Path
import unittest

from tracker4agents import project
from tracker4agents.document import Document
from tracker4agents.model import playback_plan
from tracker4agents.realtime import RealtimeError, XmpEngine, find_library

ROOT = Path(__file__).resolve().parents[1]


def peak(pcm: bytes) -> int:
    return max((abs(int.from_bytes(pcm[index:index + 2], "little", signed=True)) for index in range(0, len(pcm), 2)),
               default=0)


@unittest.skipUnless(find_library(), "libxmp is required for real-time playback tests.")
class RealtimeEngineTests(unittest.TestCase):
    def setUp(self):
        self.module = project.load(ROOT / "examples/pixel_rush.project.json")
        self.engine = XmpEngine()
        self.engine.load(self.module)

    def tearDown(self):
        self.engine.close()

    def test_blocks_have_the_requested_size_and_row_markers(self):
        pcm, markers = self.engine.render(4800)
        self.assertEqual(len(pcm), 4800 * 4)
        self.assertEqual({key: markers[0][key] for key in ("frame", "order", "row", "speed", "bpm")},
                         {"frame": 0, "order": 0, "row": 0, "speed": 6, "bpm": 160})
        # 160 BPM, speed 6: one row lasts 6 × 2.5 / 160 s = 4500 frames at 48 kHz.
        self.assertEqual([marker["frame"] for marker in markers[:2]], [0, 4500])
        self.assertGreater(peak(pcm), 1000)

    def test_seek_matches_the_playback_plan_for_every_order(self):
        plan = playback_plan(self.module)
        for order in range(len(self.module.orders)):
            self.engine.seek(order, 0)
            _, markers = self.engine.render(1200)
            expected = next(entry for entry in plan["timeline"] if entry["order"] == order)
            self.assertEqual((markers[0]["order"], markers[0]["row"], markers[0]["bpm"]),
                             (order, 0, expected["bpm"]))
        # Inside an order the tempo and the song time still match the plan (libxmp keeps neither on a row jump).
        self.engine.seek(2, 16)
        marker = self.engine.render(1200)[1][0]
        expected = next(entry for entry in plan["timeline"] if entry["order"] == 2 and entry["row"] == 16)
        self.assertEqual((marker["row"], marker["speed"], marker["bpm"], marker["seconds"]),
                         (16, expected["speed"], expected["bpm"], expected["seconds"]))
        self.assertEqual(self.engine.render(4500)[1][0]["row"], 17)

    def test_reload_keeps_position_and_plays_the_edit(self):
        self.engine.seek(3, 8)
        original, _ = self.engine.render(9000)
        self.engine.seek(3, 8)
        self.engine.render(100)
        document = Document(self.module)
        document.patch([{"op": "write", "pattern": self.module.orders[3], "channel": channel, "row": 8,
                          "cells": ["C-3 01 ..."] * 2} for channel in range(4)])
        self.engine.reload(document.module)
        edited, markers = self.engine.render(9000)
        self.assertEqual((markers[0]["order"], markers[0]["row"]), (3, 8))
        self.assertNotEqual(edited, original)

    def test_channel_mutes_apply_within_a_block(self):
        self.engine.set_audible((False, False, False, False))
        self.engine.render(4800)
        self.assertEqual(peak(self.engine.render(4800)[0]), 0)
        self.engine.set_audible((True, True, True, True))
        self.engine.render(4800)
        self.assertGreater(peak(self.engine.render(4800)[0]), 1000)

    def test_without_loop_playback_finishes(self):
        self.engine.loop = False
        self.engine.seek(len(self.module.orders) - 1, 60)
        blocks = 0
        while self.engine.render(4800)[0]:
            blocks += 1
            self.assertLess(blocks, 20)
        self.assertTrue(self.engine.finished)

    def test_rendering_is_much_faster_than_real_time(self):
        import time
        start = time.perf_counter()
        for _ in range(50):  # Five seconds of audio.
            self.engine.render(4800)
        self.assertLess(time.perf_counter() - start, 1.0)


class RealtimeAvailabilityTests(unittest.TestCase):
    def test_missing_library_reports_a_clear_error(self):
        with self.assertRaisesRegex(RealtimeError, "could not be loaded"):
            XmpEngine(Path("missing-libxmp-for-test.dll"))


if __name__ == "__main__":
    unittest.main()
