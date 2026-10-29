from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker4agents import mod, project, synth, xm
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell, playback_plan
from tracker4agents.report import (
    KK_MAJOR, KK_MINOR, PITCH_CLASS_NAMES, add_feedback, analyze, estimate_key, loudness_reference,
)
from tracker4agents.sample_library import SampleLibrary

ROOT = Path(__file__).resolve().parents[1]
TONE = (0, 0, 50, -50, 50, -50)


def samples(count: int = 2) -> list[Sample]:
    return [Sample(f"Tone {index}", TONE) for index in range(1, count + 1)]


def pattern(*cells: tuple[int, int, object]) -> Pattern:
    result = Pattern()
    for row, channel, value in cells:
        result.put(row, channel, value)
    return result


def tiny_module() -> Module:
    """Four rows at speed 6 / 125 BPM = 0.12 s each; D00 on row 3 ends the pattern."""
    return Module("Tiny", samples(), [pattern(
        (0, 0, cell("C-2", 1)), (1, 0, cell("E-2", 1)), (2, 1, cell("C-3", 1)), (3, 3, cell(None, 0, "D00")),
    )], [0])


class AnalyzeTinyModuleTests(unittest.TestCase):
    def setUp(self):
        self.report = analyze(tiny_module())
        self.channels = {entry["channel"]: entry for entry in self.report["channels"]}

    def test_timing(self):
        timing = self.report["timing"]
        self.assertEqual(timing["rows_played"], 4)
        self.assertAlmostEqual(timing["duration_seconds"], 0.48)
        self.assertEqual(timing["loop_start_seconds"], 0.0)
        self.assertAlmostEqual(timing["loop_seconds"], 0.48)
        self.assertEqual((timing["bpm_min"], timing["bpm_max"], timing["speed_min"], timing["speed_max"]), (125, 125, 6, 6))
        self.assertEqual(timing["tempo_changes"]["count"], 0)

    def test_channel_zero(self):
        one = self.channels[0]
        self.assertEqual(one["note_ons"], 2)
        self.assertAlmostEqual(one["notes_per_second"], 2 / 0.48, places=5)
        self.assertEqual(one["density"], 0.5)
        self.assertEqual((one["lowest_note"], one["highest_note"], one["range_semitones"]), ("C-2", "E-2", 4))
        self.assertEqual(one["samples_used"], [1])
        self.assertEqual(one["longest_gap_without_note"]["rows"], 2)
        self.assertAlmostEqual(one["longest_gap_without_note"]["seconds"], 0.24)

    def test_channel_one_gap_is_the_first_longest_run(self):
        two = self.channels[1]
        self.assertEqual((two["note_ons"], two["lowest_note"], two["range_semitones"]), (1, "C-3", 0))
        self.assertEqual(two["longest_gap_without_note"]["rows"], 2)
        self.assertEqual(two["longest_gap_without_note"]["start_played_row"], 0)

    def test_silent_channels_and_effects(self):
        three, four = self.channels[2], self.channels[3]
        self.assertEqual((three["note_ons"], three["lowest_note"], three["range_semitones"]), (0, None, None))
        self.assertEqual(three["longest_gap_without_note"]["rows"], 4)
        self.assertEqual(four["effects"], {"D": 1})

    def test_global_measurements(self):
        overall = self.report["global"]
        self.assertEqual(overall["note_starts"], 3)
        self.assertEqual(overall["rows_with_note_start"], 3)
        self.assertEqual(overall["rows_without_note_start"]["total_rows"], 1)
        self.assertEqual(overall["rows_without_note_start"]["longest"]["rows"], 1)
        self.assertEqual(overall["pitch_classes"]["C"], 2)
        self.assertEqual(overall["pitch_classes"]["E"], 1)
        self.assertEqual(sum(overall["pitch_classes"].values()), 3)

    def test_key_is_unavailable_for_too_few_notes(self):
        key = self.report["global"]["key_estimate"]
        self.assertFalse(key["available"])
        self.assertTrue(key["is_estimate"])

    def test_sample_usage_and_warnings_are_factual(self):
        usage = self.report["samples"]
        self.assertEqual(usage["never_played_slots"], [2])
        self.assertEqual(usage["slots"][0]["note_ons"], 3)
        self.assertEqual(usage["slots"][0]["channels"], [0, 1])
        codes = {(item["code"], item.get("channel", item.get("slot"))) for item in self.report["warnings"]
                 if item["code"] != "sample_level_off_reference"}  # level warnings are tested in test_synth_mode
        self.assertEqual(codes, {("channel_never_plays", 2), ("channel_never_plays", 3), ("sample_never_played", 2)})
        self.assertIn("Channel 2 starts no note", " ".join(item["message"] for item in self.report["warnings"]))
        self.assertEqual([entry["channel"] for entry in self.report["channels"]], [0, 1, 2, 3])

    def test_json_serializable_and_deterministic(self):
        json.dumps(self.report, allow_nan=False)
        self.assertEqual(self.report, analyze(tiny_module()))


class AnalyzeStructureTests(unittest.TestCase):
    def test_tempo_changes_use_the_state_after_the_row(self):
        module = Module("Tempo", samples(1), [pattern(
            (0, 2, cell(None, 0, "F03")), (0, 3, cell(None, 0, "F96")), (3, 1, cell(None, 0, "D00")),
        )], [0])
        timing = analyze(module)["timing"]
        self.assertEqual(timing["rows_played"], 4)
        self.assertAlmostEqual(timing["duration_seconds"], 4 * 3 * 2.5 / 150)
        self.assertEqual((timing["speed_min"], timing["bpm_max"]), (3, 150))
        self.assertEqual(timing["tempo_changes"]["count"], 1)
        self.assertEqual(timing["tempo_changes"]["events"][0]["bpm"], 150)

    def test_long_silence_warning_uses_seconds(self):
        # One 64-row pattern is 7.68 s with a single note on row 0: 63 rows (7.56 s) follow it.
        module = Module("Quiet", samples(1), [pattern((0, 0, cell("C-2", 1)))], [0])
        report = analyze(module)
        longest = report["global"]["rows_without_note_start"]["longest"]
        self.assertEqual(longest["rows"], 63)
        self.assertAlmostEqual(longest["seconds"], 7.56)
        self.assertIn("long_stretch_without_note", [item["code"] for item in report["warnings"]])

    def test_repeated_blocks_and_gaps_inside_a_channel(self):
        module = Module("Blocks", samples(1), [pattern(
            (0, 0, cell("C-2", 1)), (4, 0, cell("C-2", 1)), (7, 3, cell(None, 0, "D00")),
        )], [0])
        blocks = analyze(module)["repetition"]["blocks"]
        first = blocks["4"]["channels"][0]
        self.assertEqual({key: first[key] for key in ("total", "empty", "non_empty", "distinct")},
                         {"total": 2, "empty": 0, "non_empty": 2, "distinct": 1})
        self.assertEqual(first["repeated_fraction"], 0.5)
        self.assertEqual(blocks["8"]["channels"][0]["distinct"], 1)
        self.assertEqual(blocks["16"]["channels"][0]["total"], 0)
        self.assertIsNone(blocks["16"]["channels"][0]["repeated_fraction"])
        silent = blocks["4"]["channels"][1]
        self.assertEqual((silent["total"], silent["empty"], silent["non_empty"]), (2, 2, 0))
        self.assertEqual(blocks["4"]["all_channels"]["distinct"], 2)

    def test_identical_patterns_and_reused_orders(self):
        def song(note: str, rows_after: int = 3):
            return pattern((0, 0, cell(note, 1)), (rows_after, 3, cell(None, 0, "D00")))
        module = Module("Reuse", samples(1), [song("C-2"), song("C-2"), song("G-2")], [0, 1, 1, 2])
        repetition = analyze(module)["repetition"]
        self.assertEqual(repetition["identical_pattern_groups"], [[0, 1]])
        self.assertEqual(repetition["order_slots_played"], 4)
        self.assertEqual(repetition["distinct_pattern_contents_played"], 2)
        self.assertEqual(repetition["order_slots_reusing_earlier_pattern"], 2)
        self.assertEqual(repetition["patterns_never_played"], [])

    def test_pattern_that_playback_never_reaches_is_listed(self):
        def song():
            return pattern((0, 0, cell("C-2", 1)), (3, 3, cell(None, 0, "D00")))
        module = Module("Skip", samples(1), [song(), pattern((0, 0, cell("D-2", 1))), song()], [0, 2])
        report = analyze(module)
        self.assertEqual(report["repetition"]["patterns_never_played"], [1])
        self.assertIn("pattern_never_played", [item["code"] for item in report["warnings"]])

    def test_note_without_sample_and_portamento_targets(self):
        module = Module("Sticky", samples(1), [pattern(
            (0, 0, cell("C-2", 0)), (1, 0, cell("D-2", 1)), (2, 0, cell("E-2", 0)),
            (3, 0, cell("G-2", 0, "300")), (3, 3, cell(None, 0, "D00")),
        )], [0])
        one = analyze(module)["channels"][0]
        self.assertEqual(one["note_ons"], 3)  # The tone-portamento target is not a note start.
        self.assertEqual(one["portamento_targets"], 1)
        self.assertEqual(one["notes_without_sample"], 1)  # Only the first note precedes any sample number.
        self.assertEqual(one["samples_used"], [1])
        self.assertEqual(one["effects"]["3"], 1)

    def test_a_held_arpeggio_is_flagged_and_a_struck_one_is_not(self):
        # 64 rows at speed 6 / 125 BPM = 7.68 s; one note held under 037 for the whole pattern
        held = [(0, 0, cell("A-2", 1, "037"))] + [(row, 0, cell(None, 0, "037")) for row in range(1, 64)]
        report = analyze(Module("Held", samples(1), [pattern(*held)], [0]))
        run = report["channels"][0]["held_arpeggios"]
        self.assertEqual(run["count"], 1)
        self.assertEqual((run["longest"]["start_played_row"], run["longest"]["rows"]), (0, 64))
        self.assertAlmostEqual(run["longest"]["seconds"], 7.68)
        warning = next(item for item in report["warnings"] if item["code"] == "held_arpeggio")
        self.assertEqual((warning["channel"], warning["count"]), (0, 1))
        # the same chord struck every four rows (three rows of arpeggio, then a C00 cut) is not flagged
        struck = []
        for row in range(0, 64, 4):
            struck += [(row, 0, cell("A-2", 1, "037")), (row + 1, 0, cell(None, 0, "037")),
                       (row + 2, 0, cell(None, 0, "037")), (row + 3, 0, cell(None, 0, "C00"))]
        report = analyze(Module("Struck", samples(1), [pattern(*struck)], [0]))
        self.assertEqual(report["channels"][0]["held_arpeggios"], {"count": 0, "longest": None})
        self.assertNotIn("held_arpeggio", [item["code"] for item in report["warnings"]])

    def test_extended_effects_are_counted_separately(self):
        module = Module("Ext", samples(1), [pattern((0, 0, cell("C-2", 1, "E51")), (3, 3, cell(None, 0, "D00")))], [0])
        one = analyze(module)["channels"][0]
        self.assertEqual(one["effects"], {"E": 1})
        self.assertEqual(one["extended_effects"], {"E5": 1})


class KeyEstimateTests(unittest.TestCase):
    def rotated(self, profile, tonic):
        return [round(profile[(pitch - tonic) % 12] * 100) for pitch in range(12)]

    def test_exact_profiles_are_recognised_in_every_transposition(self):
        names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        for tonic in range(12):
            for mode, profile in (("major", KK_MAJOR), ("minor", KK_MINOR)):
                with self.subTest(tonic=tonic, mode=mode):
                    key = estimate_key(self.rotated(profile, tonic))
                    self.assertEqual(key["key"], f"{names[tonic]} {mode}")
                    self.assertGreater(key["correlation"], 0.999)
                    self.assertGreater(key["margin"], 0.0)
                    self.assertTrue(key["is_estimate"])
                    self.assertIn("period labels", key["caveat"])

    def test_relative_key_runner_up_caps_confidence(self):
        # Am-F-C-G as equal note counts: C major and A minor are nearly tied, so high is not claimed.
        histogram = [0] * 12
        for chord in ((9, 0, 4), (5, 9, 0), (0, 4, 7), (7, 11, 2)):
            for pitch in chord:
                histogram[pitch] += 4
        histogram[9] += 3
        key = estimate_key(histogram)
        self.assertTrue(key["runner_up_is_relative"])
        self.assertEqual({key["key"], key["runner_up"]["key"]}, {"C major", "A minor"})
        self.assertLess(key["margin"], 0.20)
        self.assertNotEqual(key["confidence"], "high")
        self.assertIn("relative", key["confidence_rule"])

    def test_flat_histogram_is_refused_not_guessed(self):
        self.assertFalse(estimate_key([5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])["available"])

    def test_bad_histogram_size(self):
        with self.assertRaises(ValidationError):
            estimate_key([1, 2, 3])


class ExampleProjectTests(unittest.TestCase):
    def test_pixel_rush_report_matches_the_playback_plan(self):
        module = project.load(ROOT / "examples" / "pixel_rush.project.json")
        report = analyze(module)
        plan = playback_plan(module)
        self.assertEqual(report["timing"]["rows_played"], len(plan["timeline"]))
        self.assertEqual(report["timing"]["duration_seconds"], plan["duration_seconds"])
        self.assertEqual(report["global"]["note_starts"], sum(entry["note_ons"] for entry in report["channels"]))
        self.assertEqual(sum(report["global"]["pitch_classes"].values()), report["global"]["note_starts"])
        self.assertTrue(report["global"]["key_estimate"]["available"])
        json.dumps(report, allow_nan=False)
        self.assertEqual(report, analyze(module))
        self.assertIn("not judgments", report["scope"])


KICK = Sample("Kick", (0, 0) + (90, -90, 60, -60, 30, -30) * 20, 48)
LEAD = Sample("Lead", (0, 0) + (50, 50, -50, -50) * 8, 40, 0, 2, 32)
MELODY = ("A-2", "C-3", "E-3", "A-2", "B-2", "C-3", "E-3", "A-2", "G-2", "A-2", "C-3", "E-3", "D-3", "C-3", "B-2", "A-2")


def drums_and_melody(drum: Sample = KICK) -> Module:
    """A drum slot hit at C-2 on every other row and an A minor melody on a looped lead."""
    result = Pattern()
    for row in range(0, 64, 2):
        result.put(row, 0, cell("C-2", 1))
    for index, note in enumerate(MELODY):
        result.put(index * 4, 1, cell(note, 2))
    return Module("Key", [drum, LEAD], [result], [0])


class PercussionKeyTests(unittest.TestCase):
    """Drums written at C-2 must not pull every song towards C major."""

    def histogram(self, counts: dict) -> list[int]:
        return [counts[name] for name in PITCH_CLASS_NAMES]

    def test_percussion_note_starts_are_left_out_of_the_key(self):
        report = analyze(drums_and_melody())
        overall = report["global"]
        key = overall["key_estimate"]
        self.assertEqual(estimate_key(self.histogram(overall["pitch_classes"]))["key"], "C major")  # drums counted
        self.assertEqual(key["key"], "A minor")
        excluded = key["percussion_excluded"]
        self.assertEqual(excluded["note_starts"], 32)
        self.assertEqual([(item["slot"], item["role"], item["role_source"], item["note_starts"])
                          for item in excluded["slots"]], [(1, "percussion", "heuristic", 32)])
        self.assertEqual(sum(key["pitch_classes_counted"].values()), len(MELODY))
        self.assertEqual(key["notes_counted"], len(MELODY))
        self.assertEqual(sum(overall["pitch_classes"].values()), overall["note_starts"])  # full histogram kept
        self.assertIn("percussion", key["caveat"])

    def test_role_sources_in_order(self):
        recorded = drums_and_melody(Sample("Thud", LEAD.pcm, 40, 0, 2, 32))  # looped: the heuristic says lead
        self.assertEqual(analyze(recorded)["global"]["key_estimate"]["percussion_excluded"]["note_starts"], 0)
        recorded.metadata["sample_sources"] = {"1": {"role": "kick"}}
        slots = analyze(recorded)["global"]["key_estimate"]["percussion_excluded"]["slots"]
        self.assertEqual([(item["role"], item["role_source"]) for item in slots], [("kick", "recorded")])
        recipe = drums_and_melody(synth.from_recipe("Kick", {"type": "kick"}))
        slots = analyze(recipe)["global"]["key_estimate"]["percussion_excluded"]["slots"]
        self.assertEqual([(item["role"], item["role_source"]) for item in slots], [("kick", "recipe")])
        # A recorded role wins over the one-shot heuristic: a one-shot pluck is not percussion.
        pluck = drums_and_melody()
        pluck.metadata["sample_sources"] = {"1": {"role": "lead"}}
        report = analyze(pluck)
        self.assertEqual(report["global"]["key_estimate"]["percussion_excluded"]["note_starts"], 0)
        self.assertEqual(report["samples"]["slots"][0]["role_source"], "recorded")

    def test_library_id_uses_the_bank_category_when_a_bank_is_the_reference(self):
        import random
        with tempfile.TemporaryDirectory(prefix="chiploom key bank ") as folder:
            rng = random.Random(1)
            noise = Sample("noise", (0, 0) + tuple(int(100 * (1 - i / 3000) * rng.uniform(-1, 1))
                                                   for i in range(3000)), 40)
            source = Path(folder) / "bank source.mod"
            source.write_bytes(mod.encode(Module("t", [noise], [pattern((0, 0, cell("C-2", 1)))], [0])))
            bank = Path(folder) / "bank"
            SampleLibrary(bank).extract(source)
            module = drums_and_melody(Sample("Looped hit", LEAD.pcm, 40, 0, 2, 32))
            module.metadata["sample_sources"] = {"1": {"library_id": "SMP-0001", "origin": "module-extracted"}}
            without = analyze(module)
            self.assertEqual(without["samples"]["slots"][0]["role_source"], "heuristic")
            self.assertEqual(without["global"]["key_estimate"]["percussion_excluded"]["note_starts"], 0)
            report = analyze(module, loudness_reference(module, bank))
            entry = report["samples"]["slots"][0]
            self.assertEqual((entry["library_id"], entry["role"], entry["role_source"], entry["group"]),
                             ("SMP-0001", "percussion", "library", "percussion"))
            self.assertEqual(report["global"]["key_estimate"]["percussion_excluded"]["slots"][0]["role_source"],
                             "library")
            self.assertEqual(report["global"]["key_estimate"]["key"], "A minor")


class SampleSwitchingTests(unittest.TestCase):
    """A cell with a sample number and no note switches the sound mid-note: that slot is played."""

    def test_sample_changes_count_and_never_played_only_for_unreferenced_slots(self):
        module = Module("Switch", [LEAD, Sample("Lead B", LEAD.pcm, 40, 0, 2, 32), Sample("Unused", LEAD.pcm)],
                        [pattern((0, 0, cell("C-2", 1)), (2, 0, cell(None, 2)), (4, 0, cell(None, 1)),
                                 (6, 0, cell(None, 2)), (8, 0, cell("E-2", 0)))], [0])
        report = analyze(module)
        slots = {entry["slot"]: entry for entry in report["samples"]["slots"]}
        self.assertEqual((slots[1]["note_ons"], slots[1]["sample_changes"]), (1, 1))
        # The E-2 on row 8 has no sample number: it plays slot 2, selected on row 6.
        self.assertEqual((slots[2]["note_ons"], slots[2]["sample_changes"]), (1, 2))
        self.assertEqual(slots[2]["channels"], [0])
        self.assertEqual((slots[3]["note_ons"], slots[3]["sample_changes"]), (0, 0))
        self.assertEqual(report["samples"]["never_played_slots"], [3])
        self.assertEqual([item["slot"] for item in report["warnings"] if item["code"] == "sample_never_played"], [3])
        self.assertEqual(report["channels"][0]["samples_used"], [1, 2])

    def test_slot_used_only_by_switching_is_not_flagged(self):
        module = Module("Switch", [LEAD, Sample("Lead B", LEAD.pcm, 40, 0, 2, 32)],
                        [pattern((0, 0, cell("C-2", 1)), (2, 0, cell(None, 2)), (4, 0, cell(None, 1)))], [0])
        report = analyze(module)
        self.assertEqual(report["samples"]["never_played_slots"], [])
        self.assertEqual(report["samples"]["slots"][1]["note_ons"], 0)
        self.assertEqual(report["samples"]["slots"][1]["sample_changes"], 1)
        self.assertNotIn("sample_never_played", [item["code"] for item in report["warnings"]])


class LevelReachTests(unittest.TestCase):
    def test_unreachable_reference_says_limited_by_peak(self):
        quiet = Sample("Spiky", (0, 0) + (127, 4, -128, -4) + (0, 0, 0, 0) * 7, 64, 0, 2, 32)  # full peak, low RMS
        module = Module("Reach", [quiet], [pattern((0, 0, cell("C-2", 1)))], [0])
        module.metadata["sample_sources"] = {"1": {"role": "texture"}}
        report = analyze(module)
        entry = report["samples"]["slots"][0]
        self.assertTrue(entry["limited_by_peak"])
        self.assertLess(entry["reachable_db"], entry["reference_db"])
        warning = next(item for item in report["warnings"] if item["code"] == "sample_level_off_reference")
        self.assertTrue(warning["limited_by_peak"])
        self.assertIn("limited by peak", warning["message"])

    def test_a_quiet_sample_with_room_is_not_limited(self):
        soft = Sample("Soft lead", LEAD.pcm, 8, 0, 2, 32)
        module = Module("Reach", [soft], [pattern((0, 0, cell("C-2", 1)))], [0])
        module.metadata["sample_sources"] = {"1": {"role": "lead"}}
        report = analyze(module)
        entry = report["samples"]["slots"][0]
        self.assertFalse(entry["limited_by_peak"])
        warning = next(item for item in report["warnings"] if item["code"] == "sample_level_off_reference")
        self.assertNotIn("limited_by_peak", warning)


class LoudnessReferenceTests(unittest.TestCase):
    """`report` uses the default sample bank whenever it exists and says which reference it used."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chiploom report reference ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.default = self.root / "exports" / "sample_library"

    def build_bank(self, path: Path) -> None:
        pulse = Sample("pulse", (60, 60, -60, -60) * 8, 40, 0, 0, 32)
        source = self.root / "bank source.mod"
        source.write_bytes(mod.encode(Module("t", [pulse], [pattern((0, 0, cell("C-2", 1)))], [0])))
        SampleLibrary(path).extract(source)

    def module(self, mode: str | None) -> Module:
        module = tiny_module()
        if mode == "declared":
            module.metadata["sample_source"] = "library"
        elif mode == "ids":
            module.metadata["sample_sources"] = {"1": {"library_id": "SMP-0001", "origin": "module-extracted"}}
        return module

    def test_the_default_bank_is_used_whenever_it_exists(self):
        self.build_bank(self.default)
        for mode in ("declared", "ids", None, "synthesized"):
            with self.subTest(mode=mode):
                module = self.module(mode)
                if mode == "synthesized":
                    module.metadata["sample_source"] = "synthesized"
                info = analyze(module, loudness_reference(module, default=self.default))["samples"]["loudness_reference"]
                self.assertEqual((info["source"], info["selection"], info["path"]),
                                 ("library", "automatic", str(self.default.resolve())))
                self.assertIn("default sample bank exists", info["reason"])

    def test_defaults_without_a_bank(self):
        for mode in ("declared", None):
            module = self.module(mode)
            info = analyze(module, loudness_reference(module, default=self.default))["samples"]["loudness_reference"]
            self.assertEqual((info["source"], info["path"], info["selection"]), ("defaults", None, "automatic"))
            self.assertIn("no sample bank", info["reason"])
        self.assertEqual(analyze(self.module(None))["samples"]["loudness_reference"]["selection"], "default")

    def test_same_rule_as_sample_match_level(self):
        from unittest import mock
        from tracker4agents.patch import apply_ops
        self.build_bank(self.default)
        module = self.module(None)
        module.samples[0] = Sample("Lead", LEAD.pcm, 64, 0, 2, 32)
        with mock.patch("tracker4agents.sample_library.DEFAULT_LIBRARY", self.default):
            result = apply_ops(module, [{"op": "sample_match_level", "slot": 1, "role": "lead"}])[0]
            info = analyze(module, loudness_reference(module))["samples"]
        self.assertEqual((result["reference"], result["reference_path"]), ("library", str(self.default.resolve())))
        self.assertEqual(info["loudness_reference"]["path"], result["reference_path"])
        self.assertEqual(info["slots"][0]["reference_db"], result["target_db"])
        self.assertEqual((info["slots"][0]["role"], info["slots"][0]["role_source"]), ("lead", "recorded"))

    def test_explicit_library_overrides_and_must_exist(self):
        other = self.root / "other bank"
        self.build_bank(other)
        plain = self.module(None)
        info = analyze(plain, loudness_reference(plain, other))["samples"]["loudness_reference"]
        self.assertEqual((info["source"], info["selection"], info["path"]), ("library", "explicit", str(other.resolve())))
        with self.assertRaises(ValidationError):
            loudness_reference(plain, self.root / "missing")

    def test_cli_report_falls_back_to_the_bank_under_the_working_directory(self):
        self.build_bank(self.default)
        source = self.root / "song.json"
        project.write_json(source, project.to_dict(self.module("declared")))
        environment = {**os.environ, "PYTHONPATH": str(ROOT)}
        result = subprocess.run([sys.executable, "-m", "tracker4agents", "report", str(source)], cwd=self.root,
                                capture_output=True, text=True, encoding="utf-8", timeout=60, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads(result.stdout)["samples"]["loudness_reference"]
        self.assertEqual((info["source"], info["selection"]), ("library", "automatic"))


class FeedbackTests(unittest.TestCase):
    NOW = datetime(2026, 10, 27, 9, 30, 15, 999, tzinfo=timezone.utc)

    def test_adds_a_record_to_a_copy(self):
        module = tiny_module()
        updated = add_feedback(module, "  The bass feels thin.  ", rating=3, version_label="v2", now=self.NOW)
        self.assertNotIn("feedback", module.metadata)
        self.assertIsNot(updated, module)
        self.assertEqual(updated.metadata["feedback"], [{
            "text": "The bass feels thin.", "rating": 3, "source": "owner", "version": "v2",
            "recorded_at": "2026-10-27T09:30:15Z"}])

    def test_appends_without_touching_earlier_entries(self):
        first = add_feedback(tiny_module(), "one", now=self.NOW)
        second = add_feedback(first, "two", rating=5, source="agent", now=self.NOW)
        self.assertEqual([item["text"] for item in second.metadata["feedback"]], ["one", "two"])
        self.assertEqual(len(first.metadata["feedback"]), 1)
        self.assertIsNone(second.metadata["feedback"][0]["rating"])
        self.assertIsNone(second.metadata["feedback"][0]["version"])

    def test_default_timestamp_is_utc_iso8601(self):
        stamp = add_feedback(tiny_module(), "ok").metadata["feedback"][0]["recorded_at"]
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_validation(self):
        module = tiny_module()
        bad_calls = [
            dict(text=""), dict(text="   "), dict(text="x" * 2001), dict(text=None),
            dict(text="ok", rating=0), dict(text="ok", rating=6), dict(text="ok", rating=True),
            dict(text="ok", rating=3.5), dict(text="ok", source=""), dict(text="ok", version_label=""),
            dict(text="bad \x00 text"),
        ]
        for kwargs in bad_calls:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                add_feedback(module, **kwargs)
        add_feedback(module, "x" * 2000)  # The limit itself is accepted.
        module.metadata["feedback"] = "broken"
        with self.assertRaises(ValidationError):
            add_feedback(module, "ok")

    def test_feedback_survives_a_project_round_trip(self):
        updated = add_feedback(tiny_module(), "Keep the intro.", rating=4, now=self.NOW)
        restored = project.from_dict(json.loads(json.dumps(project.to_dict(updated))))
        self.assertEqual(restored.metadata["feedback"], updated.metadata["feedback"])


ROW = 0.12  # seconds per row at speed 6 / 125 BPM
SONG = 3 * 64 * ROW  # orders [0, 1, 1]: 23.04 s


def held_song(sample: Sample, *cells: tuple[int, int, object], channels: int = 4) -> Module:
    """Pattern 0 holds `cells`, then an empty pattern played twice: 23.04 s in all."""
    return Module("Held", [sample], [pattern(*cells), Pattern()], [0, 1, 1], channels=channels)


def codes(report: dict, code: str) -> list[dict]:
    return [item for item in report["warnings"] if item["code"] == code]


class SoundingTests(unittest.TestCase):
    """When each channel is heard: note starts, cuts, key offs and one-shot lengths along the timeline."""

    def test_a_held_looped_note_never_rests_and_a_struck_one_does(self):
        report = analyze(held_song(LEAD, (0, 0, cell("C-2", 1))))
        sounding = report["channels"][0]["sounding"]
        self.assertAlmostEqual(report["timing"]["duration_seconds"], SONG)
        self.assertEqual(sounding["fraction"], 1.0)
        self.assertAlmostEqual(sounding["longest_run_seconds"], SONG)
        self.assertEqual((sounding["longest_run"]["start_played_row"], sounding["longest_run"]["rows"],
                          sounding["longest_run"]["percussion_only"], sounding["rests"]), (0, 192, False, 0))
        warning = codes(report, "channel_never_rests")
        self.assertEqual([(item["channel"], item["seconds"]) for item in warning], [(0, round(SONG, 6))])
        self.assertIn("23.04 s", warning[0]["message"])
        self.assertIn("16 s", warning[0]["message"])
        # the same looped sample struck every 8 rows, with C00 four rows after each note
        struck = []
        for row in range(0, 64, 8):
            struck += [(row, 0, cell("C-2", 1)), (row + 4, 0, cell(None, 0, "C00"))]
        report = analyze(Module("Struck", [LEAD], [pattern(*struck)] * 3, [0, 1, 2]))
        sounding = report["channels"][0]["sounding"]
        self.assertAlmostEqual(sounding["longest_run_seconds"], 4 * ROW)
        self.assertAlmostEqual(sounding["fraction"], 0.5)
        self.assertEqual(sounding["rests"], 24)
        self.assertEqual(codes(report, "channel_never_rests"), [])

    def test_cuts_and_volume_bring_a_voice_back(self):
        # ECx cuts at tick x; a later Cxx brings back a looped voice that is still playing
        report = analyze(Module("Cut", [LEAD], [pattern((0, 0, cell("C-2", 1, "EC3")), (4, 0, cell(None, 0, "C20")),
                                                         (8, 0, cell(None, 0, "D00")))], [0]))
        sounding = report["channels"][0]["sounding"]
        self.assertAlmostEqual(sounding["seconds"], 0.06 + 5 * ROW)  # half of row 0, then rows 4 to 8
        self.assertEqual(sounding["rests"], 1)

    def test_a_one_shot_stops_when_it_runs_out(self):
        blip = Sample("Blip", (0, 0) + (60, -60) * 499)  # 1000 frames, unlooped
        blip_song = Module("Blip", [blip], [pattern((0, 0, cell("C-2", 1)), (32, 0, cell("C-3", 1)),
                                                    (63, 3, cell(None, 0, "D00")))], [0])
        sounding = analyze(blip_song)["channels"][0]["sounding"]
        at_c2 = 1000 / (3_546_895 / 428)  # 0.1207 s at period 428
        self.assertAlmostEqual(sounding["seconds"], at_c2 + at_c2 / 2, places=4)  # C-3 plays twice as fast
        self.assertAlmostEqual(sounding["longest_run_seconds"], at_c2, places=5)
        self.assertEqual((sounding["longest_run"]["rows"], sounding["rests"]), (2, 2))
        self.assertTrue(sounding["longest_run"]["percussion_only"])  # one-shot PCM: percussion by heuristic

    def test_percussion_one_shots_never_count_as_a_channel_that_never_rests(self):
        crash = Sample("Crash", (0, 0) + (60, -60) * 29_999)  # 60000 frames: 7.2 s at C-2, struck every 4 rows
        hits = pattern(*[(row, 0, cell("C-2", 1)) for row in range(0, 64, 4)])
        report = analyze(Module("Crash", [crash], [hits] * 3, [0, 1, 2]))
        sounding = report["channels"][0]["sounding"]
        self.assertGreater(sounding["longest_run_seconds"], 16)
        self.assertTrue(sounding["longest_run"]["percussion_only"])
        self.assertIsNone(sounding["longest_non_percussion_run"])
        self.assertEqual(codes(report, "channel_never_rests"), [])
        # the same sample recorded as a pad counts
        song = Module("Crash", [crash], [hits] * 3, [0, 1, 2])
        song.metadata["sample_sources"] = {"1": {"role": "texture"}}
        self.assertEqual(len(codes(analyze(song), "channel_never_rests")), 1)

    def test_crowded_sustain(self):
        report = analyze(held_song(LEAD, *[(0, channel, cell("C-2", 1)) for channel in range(4)]))
        sustain = report["global"]["sustain"]
        self.assertEqual((sustain["threshold_channels"], sustain["start_played_row"], sustain["rows"]), (4, 0, 192))
        self.assertAlmostEqual(sustain["longest_seconds"], SONG)
        warning = codes(report, "crowded_sustain")
        self.assertEqual(len(warning), 1)
        self.assertIn("4 of 4 channels", warning[0]["message"])
        # three channels held, one struck: never four at once for long
        cells = [(0, channel, cell("C-2", 1)) for channel in range(3)]
        cells += [(row, 3, cell("C-2", 1, "EC3")) for row in range(0, 64, 4)]
        report = analyze(held_song(LEAD, *cells))
        self.assertAlmostEqual(report["global"]["sustain"]["longest_seconds"], 0.06)
        self.assertEqual(codes(report, "crowded_sustain"), [])
        # eight channels need max(4, ceil(0.6 x 8)) = 5 of them
        self.assertEqual(analyze(held_song(LEAD, channels=8))["global"]["sustain"]["threshold_channels"], 5)

    def test_xm_key_off_and_an_envelope_that_falls_to_zero(self):
        module = xm.blank("Keys", 4)
        module.samples = [dataclasses.replace(LEAD, name="Pad"), dataclasses.replace(LEAD, name="Pluck")]
        module.metadata["xm"]["instruments"] = {"2": {"volume_envelope": {"points": [[0, 64], [30, 0]], "type": 1}}}
        for row, channel, value in ((0, 0, cell("C-4", 1, fmt="xm")), (8, 0, cell("===", fmt="xm")),
                                    (0, 1, cell("C-4", 2, fmt="xm")), (63, 3, cell(None, 0, "D00", fmt="xm"))):
            module.patterns[0].put(row, channel, value)
        channels = analyze(module)["channels"]
        self.assertAlmostEqual(channels[0]["sounding"]["seconds"], 8 * ROW)
        self.assertAlmostEqual(channels[1]["sounding"]["seconds"], 30 * 2.5 / 125)  # 30 ticks


class SoundingPitchTests(unittest.TestCase):
    """Heard fundamentals: the slot's pitch at its reference note, moved by the note, relative note and finetune."""

    def bass_song(self, relative_note: int) -> Module:
        module = xm.blank("Bass", 4)
        bass = synth.from_recipe("Bass", {"type": "wave", "shape": "pulse", "frequency": 130.8})
        module.samples = [dataclasses.replace(bass, relative_note=relative_note)]
        module.patterns[0].put(0, 0, cell("C-3", 1, fmt="xm"))
        return module

    def test_a_recipe_bass_two_octaves_down_is_too_low(self):
        report = analyze(self.bass_song(-24))
        slot = report["samples"]["slots"][0]["pitch"]
        self.assertEqual((slot["estimated"], slot["method"], slot["reference_note"]), (True, "recipe", "C-4"))
        # 130.8 Hz at 8287 Hz (C-2 finetune 0) is 132.0 Hz at XM C-4 (8363 Hz); -24 then C-3: three octaves down
        self.assertAlmostEqual(slot["hz_at_reference"], 130.8 * 8363 / 8287 / 4, delta=0.2)
        lowest = report["channels"][0]["pitch"]["lowest"]
        self.assertEqual((lowest["note"], lowest["slot"]), ("C-3", 1))
        self.assertAlmostEqual(lowest["hz"], 130.8 * 8363 / 8287 / 8, delta=0.1)
        warning = codes(report, "pitch_too_low")
        self.assertEqual([(item["channel"], item["note"], item["slot"]) for item in warning], [(0, "C-3", 1)])
        self.assertIn("below 40 Hz", warning[0]["message"])

    def test_a_normal_recipe_bass_is_not_flagged(self):
        report = analyze(self.bass_song(0))
        self.assertAlmostEqual(report["channels"][0]["pitch"]["highest"]["hz"], 130.8 * 8363 / 8287 / 2, delta=0.2)
        self.assertEqual(codes(report, "pitch_too_low") + codes(report, "pitch_too_high"), [])

    def test_mod_estimate_finetune_and_too_high(self):
        # LEAD loops 8 cycles in 32 frames: 8287 / 4 = 2071.8 Hz at C-2, raised by finetune 4 (half a semitone)
        lead = dataclasses.replace(LEAD, finetune=4)
        report = analyze(Module("Lead", [lead], [pattern((0, 0, cell("C-1", 1)), (4, 0, cell("C-3", 1)))], [0]))
        slot = report["samples"]["slots"][0]["pitch"]
        self.assertEqual((slot["method"], slot["reference_note"]), ("estimate", "C-2"))
        self.assertAlmostEqual(slot["hz_at_reference"], 3_546_895 / 428 / 4 * 2 ** (4 / 96), delta=0.5)
        pitch = report["channels"][0]["pitch"]
        self.assertEqual((pitch["lowest"]["note"], pitch["highest"]["note"], pitch["note_starts_measured"]),
                         ("C-1", "C-3", 2))
        self.assertEqual([item["note"] for item in codes(report, "pitch_too_high")], ["C-3"])
        self.assertEqual(codes(report, "pitch_too_low"), [])

    def test_percussion_and_noise_are_left_out(self):
        report = analyze(drums_and_melody())
        self.assertIsNone(report["channels"][0]["pitch"]["lowest"])  # the kick channel
        self.assertEqual(report["samples"]["slots"][0]["pitch"]["reason"], "percussion slot: not measured")
        noise = synth.from_recipe("Wind", {"type": "wave", "shape": "noise"})
        report = analyze(Module("Wind", [noise], [pattern((0, 0, cell("C-2", 1)))], [0]))
        self.assertEqual(report["channels"][0]["pitch"]["note_starts_without_estimate"], 1)
        self.assertEqual(report["samples"]["slots"][0]["pitch"]["estimated"], False)


class PublishedSongTests(unittest.TestCase):
    NEW_CODES = ("channel_never_rests", "crowded_sustain", "pitch_too_low", "pitch_too_high")
    SONGS = ("docs/listen/media/copper_skies.project.json", "docs/listen/media/pixel_rush.project.json",
             "docs/listen/media/voltage_odyssey_v2.project.json", "examples/first_light.project.json",
             "examples/pixel_rush.project.json")

    def test_published_songs_raise_no_time_or_pitch_warning(self):
        for name in self.SONGS:
            with self.subTest(name):
                report = analyze(project.load(ROOT / name))
                found = [item for item in report["warnings"] if item["code"] in self.NEW_CODES]
                if "copper_skies" in name:
                    # Its pulse bass (channel 2) and two legato leads (5, 6) really play without a rest for 25-66 s
                    # (looped samples, sustained envelopes, no key off or cut); only that flag is accepted here.
                    found = [item for item in found if item["code"] != "channel_never_rests"]
                self.assertEqual(found, [])
                json.dumps(report, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
