from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from tracker4agents import project
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell, playback_plan
from tracker4agents.report import KK_MAJOR, KK_MINOR, add_feedback, analyze, estimate_key

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

    def test_channel_one(self):
        one = self.channels[1]
        self.assertEqual(one["note_ons"], 2)
        self.assertAlmostEqual(one["notes_per_second"], 2 / 0.48, places=5)
        self.assertEqual(one["density"], 0.5)
        self.assertEqual((one["lowest_note"], one["highest_note"], one["range_semitones"]), ("C-2", "E-2", 4))
        self.assertEqual(one["samples_used"], [1])
        self.assertEqual(one["longest_gap_without_note"]["rows"], 2)
        self.assertAlmostEqual(one["longest_gap_without_note"]["seconds"], 0.24)

    def test_channel_two_gap_is_the_first_longest_run(self):
        two = self.channels[2]
        self.assertEqual((two["note_ons"], two["lowest_note"], two["range_semitones"]), (1, "C-3", 0))
        self.assertEqual(two["longest_gap_without_note"]["rows"], 2)
        self.assertEqual(two["longest_gap_without_note"]["start_played_row"], 0)

    def test_silent_channels_and_effects(self):
        three, four = self.channels[3], self.channels[4]
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
        self.assertEqual(usage["slots"][0]["channels"], [1, 2])
        codes = {(item["code"], item.get("channel", item.get("slot"))) for item in self.report["warnings"]}
        self.assertEqual(codes, {("channel_never_plays", 3), ("channel_never_plays", 4), ("sample_never_played", 2)})

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


if __name__ == "__main__":
    unittest.main()
