from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

from tracker4agents import cli, project, synth_tools, xm
from tracker4agents.lint import RULES, lint
from tracker4agents.model import Module, Pattern, Sample, cell

ROOT = Path(__file__).resolve().parents[1]
TONE = (0, 0, 50, -50, 50, -50)


def xm_song(cells: dict, speed: int = 6, orders=(0,)) -> Module:
    """A four-channel XM with two pulse instruments and the given cells in pattern 0 (64 rows)."""
    module = xm.blank("Lint", channels=4, speed=speed)
    synth_tools.insert_recipe(module, "Pulse A", {"type": "wave", "shape": "pulse"}, slot=1, volume=40)
    synth_tools.insert_recipe(module, "Pulse B", {"type": "wave", "shape": "pulse", "duty": 0.25}, slot=2, volume=40)
    for (row, channel), value in cells.items():
        module.patterns[0].put(row, channel, value)
    module.orders = list(orders)
    return module


def x(note=None, sample=0, effect="000", volume=0):
    return cell(note, sample, effect, "xm", volume)


def codes(module: Module) -> list[tuple[str, int, int]]:
    return [(item["code"], item["row"], item["channel"]) for item in lint(module)["findings"]]


class LintRuleTests(unittest.TestCase):
    def test_sample_offset_and_finetune_need_a_note(self):
        found = codes(xm_song({(0, 0): x("C-4", 1), (4, 0): x(effect="904"), (8, 0): x("C-4", 1, "904"),
                               (12, 0): x(effect="E54"), (16, 0): x("C-4", 1, "E54")}))
        self.assertIn(("offset_without_note", 4, 0), found)
        self.assertIn(("finetune_without_note", 12, 0), found)
        self.assertNotIn(("offset_without_note", 8, 0), found)
        self.assertNotIn(("finetune_without_note", 16, 0), found)

    def test_an_offset_past_the_end_of_the_sample(self):
        module = xm_song({(0, 0): x("C-4", 1, "9FF"), (8, 0): x("C-4", 1, "900")})
        frames = len(module.samples[0].pcm)
        self.assertLess(frames, 0xFF * 256)
        item = next(item for item in lint(module)["findings"] if item["code"] == "offset_past_end")
        self.assertEqual((item["row"], item["frames"]), (0, frames))
        repeated = next(item for item in lint(module)["findings"] if item["code"] == "offset_past_end" and item["row"] == 8)
        self.assertIn("repeated from memory", repeated["message"])   # 900 reuses the previous offset, FF

    def test_an_xm_instrument_number_without_a_note(self):
        found = codes(xm_song({(0, 0): x("C-4", 1), (4, 0): x(None, 1), (8, 0): x(None, 2), (12, 0): x("C-4", 2),
                               (16, 0): x(None, 2), (20, 0): x("===", 1)}))
        self.assertIn(("instrument_without_note", 8, 0), found)      # another instrument: the sample stays
        self.assertNotIn(("instrument_without_note", 4, 0), found)   # the same one: a volume reset, on purpose
        self.assertNotIn(("instrument_without_note", 16, 0), found)
        self.assertNotIn(("instrument_without_note", 20, 0), found)  # a key off is not a missing note

    def test_xm_retrigger_volume_and_k00(self):
        found = codes(xm_song({(0, 0): x("C-4", 1, "R21", 0x30), (4, 0): x("C-4", 1, "R01", 0x30),
                               (8, 0): x("C-4", 1, "R21"), (12, 0): x(effect="K00"), (16, 0): x(effect="K02")}))
        self.assertIn(("retrig_volume_ignored", 0, 0), found)
        self.assertNotIn(("retrig_volume_ignored", 4, 0), found)    # no volume change asked
        self.assertNotIn(("retrig_volume_ignored", 8, 0), found)    # no volume column
        self.assertIn(("key_off_k00", 12, 0), found)
        self.assertNotIn(("key_off_k00", 16, 0), found)

    def test_slides_with_both_nibbles(self):
        found = codes(xm_song({(0, 0): x("C-4", 1, "A12"), (4, 0): x(effect="A10"), (8, 1): x(effect="H21"),
                               (12, 2): x(effect="P44")}))
        self.assertIn(("slide_both_nibbles", 0, 0), found)
        self.assertNotIn(("slide_both_nibbles", 4, 0), found)
        self.assertIn(("slide_both_nibbles", 8, 1), found)
        self.assertIn(("slide_both_nibbles", 12, 2), found)

    def test_tick_effects_beyond_the_row(self):
        found = codes(xm_song({(0, 0): x("C-4", 1, "EC4"), (4, 0): x("C-4", 1, "EC2"), (8, 0): x("C-4", 1, "ED3"),
                               (12, 0): x("C-4", 1, "E93")}, speed=3))
        self.assertIn(("tick_effect_after_row", 0, 0), found)
        self.assertNotIn(("tick_effect_after_row", 4, 0), found)
        self.assertIn(("tick_effect_after_row", 8, 0), found)
        self.assertIn(("tick_effect_after_row", 12, 0), found)

    def test_portamento_before_any_note(self):
        found = codes(xm_song({(0, 1): x(effect="305"), (4, 1): x("C-4", 1), (8, 1): x("E-4", 0, "305"),
                               (12, 2): x(volume=0xF2)}))
        self.assertIn(("portamento_without_note", 0, 1), found)
        self.assertNotIn(("portamento_without_note", 8, 1), found)
        self.assertIn(("portamento_without_note", 12, 2), found)

    def test_xm_effect_memory(self):
        found = codes(xm_song({(0, 0): x("C-4", 1, "A00"), (4, 0): x(effect="A02"), (8, 0): x(effect="A00"),
                               (0, 1): x("C-4", 1, "502"), (4, 1): x(effect="A00"),
                               (0, 2): x("C-4", 1, "E10"), (4, 2): x(effect="X20"), (8, 2): x(effect="X24"),
                               (12, 2): x(effect="X20"), (16, 2): x(effect="100")}))
        self.assertIn(("effect_memory_empty", 0, 0), found)       # nothing to repeat yet
        self.assertNotIn(("effect_memory_empty", 8, 0), found)    # repeats A02
        self.assertNotIn(("effect_memory_empty", 4, 1), found)    # 5xy shares the volume-slide value with Axy
        self.assertIn(("effect_memory_empty", 0, 2), found)
        self.assertIn(("effect_memory_empty", 4, 2), found)
        self.assertNotIn(("effect_memory_empty", 12, 2), found)   # repeats X24
        self.assertIn(("effect_memory_empty", 16, 2), found)      # 1xx has its own slot
        self.assertNotIn("zero_parameter", [code for code, _, _ in found])

    def test_mod_effect_memory_and_zero_parameters(self):
        cells = {(0, 0): cell("C-2", 1, "A00"), (4, 0): cell(None, 0, "100"), (8, 0): cell(None, 0, "500"),
                 (0, 1): cell("C-2", 1, "300"), (4, 1): cell("E-2", 1, "305"), (8, 1): cell("G-2", 1, "300"),
                 (12, 1): cell(None, 0, "E10")}
        pattern = Pattern()
        for (row, channel), value in cells.items():
            pattern.put(row, channel, value)
        found = codes(Module("Mod", [Sample("A", TONE)], [pattern], [0]))
        self.assertIn(("zero_parameter", 0, 0), found)
        self.assertIn(("zero_parameter", 4, 0), found)
        self.assertNotIn(("zero_parameter", 8, 0), found)         # 500 continues the portamento: not inert
        self.assertIn(("effect_memory_empty", 0, 1), found)
        self.assertNotIn(("effect_memory_empty", 8, 1), found)    # 300 repeats 305
        self.assertIn(("zero_parameter", 12, 1), found)

    def test_a_held_arpeggio_and_a_struck_one(self):
        held = {(0, 0): x("A-4", 1, "037")}
        held.update({(row, 0): x(effect="037") for row in range(1, 64)})
        item = next(item for item in lint(xm_song(held))["findings"] if item["code"] == "held_arpeggio")
        self.assertEqual((item["row"], item["rows"], item["seconds"]), (0, 64, 7.68))
        struck = {}
        for row in range(0, 64, 4):
            struck.update({(row, 0): x("A-4", 1, "037", 0x30), (row + 1, 0): x(effect="037"),
                           (row + 2, 0): x(effect="037"), (row + 3, 0): x(effect="037", volume=0x10)})
        self.assertTrue(lint(xm_song(struck))["clean"])

    def test_a_cell_played_twice_is_listed_once(self):
        result = lint(xm_song({(0, 0): x("C-4", 1), (4, 0): x(effect="E54")}, orders=(0, 0)))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["findings"][0]["times_played"], 2)

    def test_mod_rules_and_xm_only_rules(self):
        cells = {(0, 0): cell("C-2", 1), (4, 0): cell(None, 0, "904"), (8, 0): cell(None, 2), (12, 0): cell(None, 0, "A12")}
        pattern = Pattern()
        for (row, channel), value in cells.items():
            pattern.put(row, channel, value)
        found = codes(Module("Mod", [Sample("A", TONE), Sample("B", TONE)], [pattern], [0]))
        self.assertIn(("offset_without_note", 4, 0), found)
        self.assertIn(("slide_both_nibbles", 12, 0), found)
        self.assertNotIn("instrument_without_note", [code for code, _, _ in found])   # a MOD sample swap

    def test_every_finding_names_a_documented_rule(self):
        result = lint(xm_song({(0, 0): x(effect="904"), (4, 0): x(effect="K00")}))
        self.assertEqual(set(result["rules"]), set(RULES))
        for item in result["findings"]:
            self.assertIn(item["code"], RULES)
            self.assertEqual(item["kind"], RULES[item["code"]][0])
            self.assertIsInstance(item["cell"], str)
            self.assertTrue(item["message"])


class ShippedSongsLintTests(unittest.TestCase):
    def test_the_published_songs_are_clean(self):
        for path in [*sorted((ROOT / "docs/listen/media").glob("*.project.json")),
                     *sorted((ROOT / "examples").glob("*.json"))]:
            with self.subTest(path=path.name):
                result = lint(project.load(path))
                self.assertTrue(result["clean"], result["counts"])


class LintCliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, json.loads(out.getvalue()) if out.getvalue() else None

    def test_lint_strict_and_validate_report(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "song.json"
            project.write_json(source, project.to_dict(xm_song({(0, 0): x(effect="904")})))
            code, result = self.run_cli("lint", str(source))
            self.assertEqual((code, result["clean"], result["counts"]), (0, False, {"offset_without_note": 1}))
            code, result = self.run_cli("lint", str(source), "--strict")
            self.assertEqual(code, 1)
            code, result = self.run_cli("validate", str(source), "--report")
            self.assertEqual((code, result["ok"], result["lint"]["count"]), (0, True, 1))


if __name__ == "__main__":
    unittest.main()
