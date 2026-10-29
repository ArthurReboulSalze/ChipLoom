"""How a module uses its samples: roles from evidence, channel layout and structure, never notes."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from tracker4agents import project
from tracker4agents.model import Module, Pattern, Sample, cell
from tracker4agents.usage import _name_hint, study

ROOT = Path(__file__).resolve().parents[1]
CYCLE = (0, 60, 90, 60, 0, -60, -90, -60) * 4                     # a short looped cycle (32 frames)
NOISE = (0, 0) + tuple(((index * 7919) % 211) - 105 for index in range(398))  # a short noisy one-shot


def song() -> Module:
    """Slot 1: a hat struck on every eighth; slot 2: a low melodic loop (bass); slot 3: arpeggiated chords."""
    samples = [Sample("", NOISE, 40), Sample("", CYCLE, 50, 0, 0, len(CYCLE)), Sample("", CYCLE, 40, 0, 0, len(CYCLE))]
    first, second = Pattern(), Pattern()
    bass = ("C-1", "E-1", "G-1", "A-1", "F-1", "D-1", "B-1", "C#1")
    for row in range(0, 64, 4):
        first.put(row, 0, cell("C-2", 1))
        second.put(row, 0, cell("C-2", 1))
        second.put(row, 1, cell(bass[(row // 4) % len(bass)], 2))
    for row in range(0, 64, 8):
        second.put(row, 2, cell("A-2", 3, "037"))
    return Module("Usage", samples, [first, second], [0, 1, 1])


class RoleTests(unittest.TestCase):
    def test_roles_come_from_the_song_and_the_sound(self):
        result = study(song())
        roles = {entry["slot"]: entry["role"] for entry in result["slots"]}
        self.assertEqual(roles, {1: "hat", 2: "bass", 3: "chord"})
        self.assertEqual(result["channel_layout"], ["hat", "bass", "chord", None])
        for entry in result["slots"]:
            self.assertIn(entry["confidence"], ("high", "medium", "low"))
            self.assertTrue(entry["evidence"])

    def test_a_name_keyword_counts_but_the_name_is_not_kept(self):
        module = song()
        module.samples[1] = Sample("my funky slap bass 2", CYCLE, 50, 0, 0, len(CYCLE))
        result = study(module)
        slot = next(entry for entry in result["slots"] if entry["slot"] == 2)
        self.assertEqual(slot["name_hint"], "bass")
        self.assertNotIn("funky", json.dumps(result))
        self.assertEqual(_name_hint("BD 909"), "kick")
        self.assertEqual(_name_hint("hihat closed"), "hat")
        self.assertIsNone(_name_hint("untitled"))

    def test_structure_keeps_sections_not_notes(self):
        result = study(song())
        structure = result["structure"]
        self.assertEqual(structure["order_patterns"], [0, 1, 1])
        self.assertEqual([(section["start_order"], section["orders"], section["active_channels"])
                          for section in structure["sections"]], [(0, 1, [0]), (1, 2, [0, 1, 2])])
        self.assertEqual(structure["channel_entry_order"], {0: 0, 1: 1, 2: 1, 3: None})
        text = json.dumps(result)
        for note in ("C-1", "E-1", "A-2", "037"):
            self.assertNotIn(note, text)

    def test_the_published_demos_get_their_obvious_roles(self):
        copper = study(project.load(ROOT / "docs/listen/media/copper_skies.project.json"))
        roles = {entry["slot"]: entry["role"] for entry in copper["slots"]}
        self.assertEqual((roles[1], roles[7], roles[9], roles[11]), ("kick", "bass", "chord", "lead"))
        self.assertEqual(copper["channel_layout"][2], "bass")
        pixel = study(project.load(ROOT / "docs/listen/media/pixel_rush.project.json"))
        self.assertEqual(pixel["channel_layout"][1:], ["bass", "chord", "lead"])


if __name__ == "__main__":
    unittest.main()
