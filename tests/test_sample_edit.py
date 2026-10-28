"""Sample editing on copies: loop, trim, gain, fade, drawn PCM, level matching, provenance and the helpers."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import wave

from tracker4agents import audio, loudness, mod, project, sample_tools, synth
from tracker4agents.cli import main
from tracker4agents.document import Document
from tracker4agents.errors import error_code
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell, validate
from tracker4agents.patch import OPERATIONS, apply_ops, merge_modules
from tracker4agents.sample_source import SampleSourceError

ROOT = Path(__file__).resolve().parents[1]
CYCLE = (0, 40, 80, 120, 80, 40, 0, -40, -80, -120, -80, -40) * 4  # 48 bytes, a looped wave
HIT = (0, 0) + tuple(range(-60, 60, 3))  # 42 bytes, a one-shot with the two leading zero bytes


def song(source: str | None = None) -> Module:
    pattern = Pattern("A")
    pattern.put(0, 0, cell("C-2", 1))
    samples = [Sample("Cycle", CYCLE, 40, 0, 0, len(CYCLE)), Sample("Hit", HIT, 50, 0, 0, 0),
               synth.from_recipe("Kick", {"type": "kick", "duration": 0.05}, 55)]
    module = Module("Edit", samples, [pattern], [0])
    if source:
        module.metadata["sample_source"] = source
    return module


def code_of(test: unittest.TestCase, ops: list[dict], module: Module | None = None, kind=ValidationError) -> str:
    with test.assertRaises(kind) as caught:
        apply_ops(module or song(), ops)
    return error_code(caught.exception)


def run(*argv, cwd: Path | None = None):
    out, err = io.StringIO(), io.StringIO()
    previous = Path.cwd()
    if cwd:
        os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(item) for item in argv])
    finally:
        os.chdir(previous)
    return code, json.loads(out.getvalue()) if out.getvalue() else None, json.loads(err.getvalue()) if err.getvalue() else None


class LoopTests(unittest.TestCase):
    def test_set_loop_and_report_the_seam(self):
        module = song()
        result = apply_ops(module, [{"op": "sample_loop", "slot": 2, "loop_start": 4, "loop_length": 16}])[0]
        sample = module.samples[1]
        self.assertEqual((sample.loop_start, sample.loop_length), (4, 16))
        self.assertEqual(sample.pcm, HIT)
        self.assertEqual(result["seam_jump"], abs(HIT[19] - HIT[4]))
        self.assertTrue(result["changed"])

    def test_loop_validation_codes(self):
        for loop in ({"loop_start": 1, "loop_length": 8}, {"loop_start": 0, "loop_length": 6 + 1},
                     {"loop_start": 0, "loop_length": 2}, {"loop_start": 40, "loop_length": 8},
                     {"loop_start": 4, "loop_length": 0}, {"loop_start": 0, "loop_length": 1000}):
            self.assertEqual(code_of(self, [{"op": "sample_loop", "slot": 2, **loop}]), "SAMPLE_LOOP", loop)
        self.assertEqual(code_of(self, [{"op": "sample_loop", "slot": 9, "loop_start": 0, "loop_length": 0}]),
                         "SAMPLE_SLOT")
        self.assertEqual(code_of(self, [{"op": "sample_loop", "slot": 1, "loop_start": 0}]), "PATCH_FIELD")

    def test_removing_a_loop_needs_the_leading_zero_bytes_or_adapt(self):
        self.assertEqual(code_of(self, [{"op": "sample_loop", "slot": 1, "loop_start": 0, "loop_length": 0}]),
                         "SAMPLE_LOOP")
        module = song()
        result = apply_ops(module, [{"op": "sample_loop", "slot": 1, "loop_start": 0, "loop_length": 0,
                                     "adapt": True}])[0]
        sample = module.samples[0]
        self.assertEqual(result["adaptations"], ["prepend-two-zero-bytes"])
        self.assertEqual(sample.pcm, (0, 0) + CYCLE)  # the original PCM, byte for byte, after two zeros
        self.assertEqual(sample.loop_length, 0)
        validate(module)
        # A one-shot that already starts with zeros needs no adaptation.
        module = song()
        module.samples[0] = Sample("Zeros", (0, 0) + CYCLE[2:], 40, 0, 0, 0)
        self.assertEqual(apply_ops(module, [{"op": "sample_loop", "slot": 1, "loop_start": 0,
                                             "loop_length": 0}])[0]["adaptations"], [])

    def test_same_loop_is_a_no_op_that_keeps_the_recipe(self):
        module = song()
        kick = module.samples[2]
        result = apply_ops(module, [{"op": "sample_loop", "slot": 3, "loop_start": 0, "loop_length": 0}])[0]
        self.assertFalse(result["changed"])
        self.assertIsNotNone(module.samples[2].recipe)
        self.assertNotIn("sample_sources", module.metadata)
        self.assertEqual(module.samples[2], kick)


class TrimTests(unittest.TestCase):
    def test_trim_keeps_the_bytes_and_moves_the_loop(self):
        module = song()
        module.samples[0] = Sample("Cycle", CYCLE, 40, 0, 8, 24)
        result = apply_ops(module, [{"op": "sample_trim", "slot": 1, "start": 4, "end": 44}])[0]
        sample = module.samples[0]
        self.assertEqual(sample.pcm, CYCLE[4:44])
        self.assertEqual((sample.loop_start, sample.loop_length), (4, 24))
        self.assertEqual((result["bytes_before"], result["bytes"]), (48, 40))

    def test_trim_into_a_loop_is_refused_unless_adjusted(self):
        module = song()
        module.samples[0] = Sample("Cycle", CYCLE, 40, 0, 8, 24)  # loop is bytes 8..32
        self.assertEqual(code_of(self, [{"op": "sample_trim", "slot": 1, "end": 20}], module), "SAMPLE_LOOP")
        self.assertEqual(code_of(self, [{"op": "sample_trim", "slot": 1, "start": 10}], module), "SAMPLE_LOOP")
        result = apply_ops(module, [{"op": "sample_trim", "slot": 1, "start": 0, "end": 20, "adjust_loop": True}])[0]
        self.assertEqual((module.samples[0].loop_start, module.samples[0].loop_length), (8, 12))
        self.assertEqual(result["adaptations"], ["loop-shortened"])
        # Only a sliver of the loop left: the loop goes, so the sample needs its leading zeros.
        again = song()
        again.samples[0] = Sample("Cycle", CYCLE, 40, 0, 8, 24)
        self.assertEqual(code_of(self, [{"op": "sample_trim", "slot": 1, "start": 0, "end": 10,
                                         "adjust_loop": True}], again), "SAMPLE_LOOP")
        apply_ops(again, [{"op": "sample_trim", "slot": 1, "start": 0, "end": 10, "adjust_loop": True,
                           "adapt": True}])
        self.assertEqual((again.samples[0].loop_length, again.samples[0].pcm), (0, (0, 0) + CYCLE[:10]))

    def test_one_shot_trim_needs_zero_lead_or_adapt(self):
        self.assertEqual(code_of(self, [{"op": "sample_trim", "slot": 2, "start": 10}]), "SAMPLE_LOOP")
        module = song()
        apply_ops(module, [{"op": "sample_trim", "slot": 2, "start": 10, "adapt": True}])
        self.assertEqual(module.samples[1].pcm, (0, 0) + HIT[10:])
        validate(module)
        # Cutting only the end keeps the leading zeros.
        module = song()
        apply_ops(module, [{"op": "sample_trim", "slot": 2, "end": 20}])
        self.assertEqual(module.samples[1].pcm, HIT[:20])

    def test_trim_range_errors(self):
        for fields in ({"start": 1}, {"end": 21}, {"start": 20, "end": 22}, {"start": 30, "end": 10}, {"end": 100},
                       {"start": -2}):
            self.assertEqual(code_of(self, [{"op": "sample_trim", "slot": 2, **fields}]), "SAMPLE_LENGTH", fields)
        self.assertEqual(code_of(self, [{"op": "sample_trim", "slot": 2}]), "PATCH_FIELD")


class GainTests(unittest.TestCase):
    def test_gain_scales_rounds_and_reports(self):
        module = song()
        module.samples[1] = Sample("S", (0, 0, 10, -10, 22, -22), 40, 0, 0, 0)
        result = apply_ops(module, [{"op": "sample_gain", "slot": 2, "db": -6.0206}])[0]
        self.assertEqual(module.samples[1].pcm, (0, 0, 5, -5, 11, -11))
        self.assertEqual((result["peak_before"], result["peak_after"], result["clipped"]), (22, 11, 0))
        module = song()
        apply_ops(module, [{"op": "sample_gain", "slot": 1, "db": -6.0206}])
        self.assertEqual(module.samples[0].pcm[:5], (0, 20, 40, 60, 40))
        self.assertEqual(module.samples[0].loop_length, len(CYCLE))

    def test_gain_that_would_clip_is_refused_with_the_headroom(self):
        with self.assertRaises(ValidationError) as caught:
            apply_ops(song(), [{"op": "sample_gain", "slot": 1, "db": 6}])
        self.assertEqual(caught.exception.code, "SAMPLE_CLIP")
        self.assertIn("+0.492", str(caught.exception))  # 127/120: the clean headroom
        self.assertEqual(sample_tools.headroom_db(CYCLE), 0.492)

    def test_allow_clip_clamps_and_counts(self):
        module = song()
        result = apply_ops(module, [{"op": "sample_gain", "slot": 1, "db": 6, "allow_clip": True}])[0]
        self.assertEqual(result["clipped"], 24)  # six bytes beyond +-63 per 12-byte cycle, four cycles
        self.assertEqual(max(module.samples[0].pcm), 127)
        self.assertEqual(min(module.samples[0].pcm), -128)
        self.assertEqual(module.metadata["sample_sources"]["1"]["edits"][-1], {"op": "sample_gain", "db": 6.0,
                                                                                 "clipped": 24})

    def test_zero_gain_changes_nothing(self):
        module = song()
        result = apply_ops(module, [{"op": "sample_gain", "slot": 3, "db": 0}])[0]
        self.assertFalse(result["changed"])
        self.assertIsNotNone(module.samples[2].recipe)

    def test_bad_values(self):
        for db in (100, float("nan"), "3", True):
            self.assertEqual(code_of(self, [{"op": "sample_gain", "slot": 1, "db": db}]), "PATCH_FIELD")
        self.assertEqual(code_of(self, [{"op": "sample_gain", "slot": 1, "db": 1, "allow_clip": "yes"}]),
                         "PATCH_FIELD")


class FadeTests(unittest.TestCase):
    def test_fades_ramp_linearly_and_keep_zero_lead(self):
        module = song()
        apply_ops(module, [{"op": "sample_fade", "slot": 2, "fade_in": 10, "fade_out": 8}])
        pcm = module.samples[1].pcm
        self.assertEqual(pcm[:2], (0, 0))
        self.assertEqual(pcm[10:34], HIT[10:34])
        self.assertEqual(pcm[-1], 0)
        self.assertEqual(pcm[3], round(HIT[3] * 3 / 10))
        self.assertEqual(pcm[-2], round(HIT[-2] * 1 / 8))
        validate(module)

    def test_loop_protection(self):
        module = song()  # the cycle loops over the whole sample
        self.assertEqual(code_of(self, [{"op": "sample_fade", "slot": 1, "fade_in": 8}]), "SAMPLE_LOOP")
        self.assertEqual(code_of(self, [{"op": "sample_fade", "slot": 1, "fade_out": 8}]), "SAMPLE_LOOP")
        result = apply_ops(module, [{"op": "sample_fade", "slot": 1, "fade_in": 8, "allow_loop": True}])[0]
        self.assertTrue(result["touches_loop"])
        # A fade fully outside the loop is fine.
        module.samples[0] = Sample("Cycle", CYCLE, 40, 0, 12, 24)
        self.assertFalse(apply_ops(module, [{"op": "sample_fade", "slot": 1, "fade_in": 12,
                                             "fade_out": 12}])[0]["touches_loop"])

    def test_fade_range_errors(self):
        self.assertEqual(code_of(self, [{"op": "sample_fade", "slot": 2}]), "PATCH_FIELD")
        self.assertEqual(code_of(self, [{"op": "sample_fade", "slot": 2, "fade_in": 30, "fade_out": 30}]),
                         "PATCH_FIELD")
        self.assertEqual(code_of(self, [{"op": "sample_fade", "slot": 2, "fade_in": -1}]), "INTEGER_RANGE")


class SetPcmTests(unittest.TestCase):
    def test_drawn_wave_into_the_next_slot_and_back_out_as_a_project(self):
        pcm = sample_tools.draw_to_pcm([0, 1, 0, -1], cycles=8, frequency=130.8)
        self.assertEqual(pcm, synth.from_recipe("x", {"type": "draw", "points": [0, 1, 0, -1], "cycles": 8,
                                                      "frequency": 130.8}).pcm)
        module = song()
        result = apply_ops(module, [{"op": "sample_set_pcm", "slot": 4, "name": "Hand wave", "volume": 33,
                                     **sample_tools.pcm_fields(pcm)}])[0]
        self.assertEqual(result["slot"], 4)
        sample = module.samples[3]
        self.assertEqual((sample.name, sample.pcm, sample.volume, sample.loop_length), ("Hand wave", pcm, 33, len(pcm)))
        self.assertEqual(module.metadata["sample_sources"]["4"]["origin"], "drawn")
        again = project.from_dict(project.to_dict(module))
        self.assertEqual(mod.encode(again), mod.encode(module))

    def test_hash_and_slot_rules(self):
        pcm = sample_tools.draw_to_pcm([0, 1, 0, -1])
        fields = sample_tools.pcm_fields(pcm)
        self.assertEqual(code_of(self, [{"op": "sample_set_pcm", "slot": 4, **fields, "pcm_sha256": "0" * 64}]),
                         "SAMPLE_PCM_HASH")
        self.assertEqual(code_of(self, [{"op": "sample_set_pcm", "slot": 5, **fields}]), "SAMPLE_SLOT")
        self.assertEqual(code_of(self, [{"op": "sample_set_pcm", "slot": 1, **fields}]), "SAMPLE_SLOT")  # occupied
        self.assertEqual(code_of(self, [{"op": "sample_set_pcm", "slot": 4, **fields, "pcm_base64": "!!"}]),
                         "SAMPLE_PCM")
        module = song()
        apply_ops(module, [{"op": "sample_set_pcm", "slot": 1, "replace": True, **fields}])
        self.assertEqual(module.samples[0].name, "Cycle")  # the name is kept when replacing
        self.assertEqual(module.samples[0].volume, 40)

    def test_one_shot_pcm_needs_its_zero_lead(self):
        raw = sample_tools.pcm_fields(CYCLE, 0, 0)
        self.assertEqual(code_of(self, [{"op": "sample_set_pcm", "slot": 4, **raw}]), "SAMPLE_LOOP")
        module = song()
        apply_ops(module, [{"op": "sample_set_pcm", "slot": 4, "adapt": True, **raw}])
        self.assertEqual(module.samples[3].pcm, (0, 0) + CYCLE)

    def test_drawn_pcm_follows_the_sample_source_rules(self):
        fields = sample_tools.pcm_fields(sample_tools.draw_to_pcm([0, 1, 0, -1]))
        for declared in ("library", "synthesized"):
            self.assertEqual(code_of(self, [{"op": "sample_set_pcm", "slot": 4, **fields}], song(declared),
                                     SampleSourceError), "SAMPLE_SOURCE")
        for declared in ("mixed", None):
            apply_ops(song(declared), [{"op": "sample_set_pcm", "slot": 4, **fields}])


class ProvenanceTests(unittest.TestCase):
    def test_editing_a_recipe_sample_drops_the_recipe_and_records_it(self):
        module = song()
        recipe = dict(module.samples[2].recipe)
        result = apply_ops(module, [{"op": "sample_gain", "slot": 3, "db": -3}, {"op": "sample_fade", "slot": 3,
                                                                                  "fade_out": 10}])
        self.assertTrue(result[0]["recipe_dropped"])
        self.assertIsNone(module.samples[2].recipe)
        entry = module.metadata["sample_sources"]["3"]
        self.assertEqual((entry["origin"], entry["derived_from"], entry["recipe"]), ("derived", "recipe", recipe))
        self.assertEqual(entry["recipe_type"], "kick")
        self.assertEqual(entry["edit_count"], 2)
        self.assertEqual([item["op"] for item in entry["edits"]], ["sample_gain", "sample_fade"])
        # The project keeps embedding the edited bytes and rebuilds the same MOD.
        data = project.to_dict(module)
        self.assertNotIn("recipe", data["samples"][2])
        self.assertEqual(mod.encode(project.from_dict(data)), mod.encode(module))

    def test_library_samples_keep_their_id_and_gain_an_edited_flag(self):
        module = song("library")
        module.samples[2] = Sample("Lib", HIT, 40, 0, 0, 0)
        module.metadata["sample_sources"] = {"3": {"library_id": "SMP-0007", "origin": "module-extracted",
                                                   "adaptations": []}}
        apply_ops(module, [{"op": "sample_gain", "slot": 3, "db": -2}])
        entry = module.metadata["sample_sources"]["3"]
        self.assertEqual((entry["library_id"], entry["edited"], entry["edit_count"]), ("SMP-0007", True, 1))
        self.assertIsNone(sample_tools.guard_edit(module, module.samples[2], 3))

    def test_plain_embedded_pcm_gets_an_origin(self):
        module = song()
        apply_ops(module, [{"op": "sample_gain", "slot": 1, "db": -1}])
        self.assertEqual(module.metadata["sample_sources"]["1"]["origin"], "embedded-pcm")

    def test_recorded_edits_are_capped(self):
        module = song()
        ops = [{"op": "sample_gain", "slot": 1, "db": -0.5 if index % 2 else 0.4, "allow_clip": True}
               for index in range(20)]
        apply_ops(module, ops)
        entry = module.metadata["sample_sources"]["1"]
        self.assertEqual((len(entry["edits"]), entry["edit_count"]), (sample_tools.MAX_RECORDED_EDITS, 20))

    def test_a_synthesized_project_refuses_edits_that_would_drop_a_recipe(self):
        module = song("synthesized")
        module.samples[:2] = [synth.from_recipe("A", {"type": "kick"}), synth.from_recipe("B", {"type": "hat"})]
        for op in ({"op": "sample_gain", "slot": 1, "db": -1}, {"op": "sample_trim", "slot": 1, "end": 100},
                   {"op": "sample_loop", "slot": 1, "loop_start": 0, "loop_length": 100},
                   {"op": "sample_fade", "slot": 1, "fade_in": 10}):
            self.assertEqual(code_of(self, [op], module, SampleSourceError), "SAMPLE_SOURCE", op)
        self.assertIsNotNone(module.samples[0].recipe)

    def test_all_or_nothing_through_a_document(self):
        document = Document(song())
        before = project.to_dict(document.module)
        with self.assertRaises(ValidationError):
            document.patch([{"op": "sample_gain", "slot": 1, "db": -1}, {"op": "sample_gain", "slot": 1, "db": 30}])
        self.assertEqual(project.to_dict(document.module), before)
        self.assertTrue(document.patch([{"op": "sample_gain", "slot": 1, "db": -1}])["changed"])
        self.assertIn("sample_sources", document.module.metadata)
        document.undo()
        self.assertEqual(project.to_dict(document.module), before)

    def test_unknown_fields_and_every_operation_is_registered(self):
        names = {"sample_loop", "sample_trim", "sample_gain", "sample_fade", "sample_set_pcm", "sample_match_level",
                 "apply_instrument"}
        self.assertTrue(names <= set(OPERATIONS))
        self.assertEqual(code_of(self, [{"op": "sample_gain", "slot": 1, "db": 1, "colour": 2}]), "UNKNOWN_FIELD")
        self.assertEqual(code_of(self, [{"op": "sample_gain", "db": 1}]), "PATCH_FIELD")

    def test_merge_carries_the_provenance_of_a_merged_slot(self):
        base = song()
        mine, theirs = song(), song()
        apply_ops(mine, [{"op": "sample_gain", "slot": 3, "db": -3}])
        apply_ops(theirs, [{"op": "set", "pattern": 0, "row": 8, "channel": 1, "cell": "E-2 01 ..."}])
        merged, conflicts = merge_modules(base, mine, theirs)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged.samples[2].pcm, mine.samples[2].pcm)
        self.assertEqual(merged.metadata["sample_sources"]["3"]["derived_from"], "recipe")


class MatchLevelTests(unittest.TestCase):
    def test_a_loud_sample_gets_a_lower_volume_and_keeps_its_pcm(self):
        module = song()
        module.samples[0] = Sample("Loud", (127, -128) * 24, 64, 0, 0, 48)
        result = apply_ops(module, [{"op": "sample_match_level", "slot": 1, "role": "bass"}])[0]
        self.assertEqual(module.samples[0].pcm, (127, -128) * 24)
        self.assertLess(module.samples[0].volume, 64)
        self.assertLess(abs(result["deviation_db"]), 0.6)
        self.assertEqual(result["method"], "volume")
        self.assertEqual(result["target_db"], loudness.target_db("bass"))
        self.assertNotIn("sample_sources", module.metadata)  # PCM untouched: nothing to record

    def test_a_quiet_sample_gets_clean_gain(self):
        module = song()
        module.samples[1] = Sample("Quiet", (0, 0) + (3, -3) * 20, 64, 0, 0, 0)
        result = apply_ops(module, [{"op": "sample_match_level", "slot": 2, "role": "snare"}])[0]
        self.assertEqual(result["method"], "volume+gain")
        self.assertGreater(result["gain_db"], 20)
        self.assertLessEqual(max(map(abs, module.samples[1].pcm)), 128)
        self.assertEqual(module.metadata["sample_sources"]["2"]["edits"][0]["op"], "sample_match_level")
        self.assertLess(abs(result["deviation_db"]), 1.5)
        validate(module)

    def test_gain_is_limited_by_the_peak_not_clipped(self):
        module = song()
        module.samples[1] = Sample("Spike", (0, 0, 4) + (0,) * 38 + (-4,), 64, 0, 0, 0)  # peak 4, almost silent
        result = apply_ops(module, [{"op": "sample_match_level", "slot": 2, "role": "kick"}])[0]
        self.assertLessEqual(max(map(abs, module.samples[1].pcm)), 127)
        self.assertTrue(result["limited_by_peak"])
        self.assertEqual(module.samples[1].volume, 64)

    def test_a_recipe_sample_stays_a_recipe(self):
        module = song()
        result = apply_ops(module, [{"op": "sample_match_level", "slot": 3, "role": "kick"}])[0]
        sample = module.samples[2]
        self.assertEqual(result["method"], "recipe")
        self.assertIsNotNone(sample.recipe)
        self.assertEqual(project.from_dict(project.to_dict(module)).samples[2].pcm, sample.pcm)
        # ... which also makes it fine in a synthesized project.
        module = song("synthesized")
        apply_ops(module, [{"op": "sample_match_level", "slot": 3}])

    def test_role_and_bank_errors(self):
        self.assertEqual(code_of(self, [{"op": "sample_match_level", "slot": 1, "role": "tuba"}]), "RECIPE_INVALID")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(code_of(self, [{"op": "sample_match_level", "slot": 1, "library": folder}]),
                             "SAMPLE_LIBRARY")
        self.assertEqual(code_of(self, [{"op": "sample_match_level", "slot": 9}]), "SAMPLE_SLOT")


class HelperTests(unittest.TestCase):
    def test_waveform_summary(self):
        pcm = tuple(range(-8, 8))
        self.assertEqual(sample_tools.waveform_summary(pcm, 4), [(-8, -5), (-4, -1), (0, 3), (4, 7)])
        self.assertEqual(len(sample_tools.waveform_summary(pcm, 100)), 16)  # one bucket per byte at most
        self.assertEqual(sample_tools.waveform_summary(bytes([255, 1, 128, 127]), 2), [(-1, 1), (-128, 127)])
        self.assertEqual(sample_tools.waveform_summary(pcm, 1), [(-8, 7)])
        with self.assertRaises(ValidationError):
            sample_tools.waveform_summary(pcm, 0)

    def test_preview_recipe_matches_the_audio_module(self):
        recipe = {"type": "wave", "shape": "triangle", "frequency": 130.81}
        wav, facts = sample_tools.preview_recipe(recipe, "C-2", 0.25, 50, 2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.wav"
            audio.audition_sample(synth.from_recipe("Preview", recipe, 50, 2), path, "C-2", 0.25)
            self.assertEqual(path.read_bytes(), wav)
        with wave.open(io.BytesIO(wav)) as reader:
            self.assertEqual((reader.getnchannels(), reader.getframerate(), reader.getnframes()), (1, 44100, 11025))
        self.assertEqual(facts["sample"]["type"], "wave")
        self.assertEqual(facts["loudness"]["role"], "bass")
        self.assertGreater(facts["audio"]["peak"], 0.1)
        self.assertEqual(facts["audio"]["clipped_samples"], 0)
        with self.assertRaises(ValidationError):
            sample_tools.preview_recipe(recipe, "H-9")
        with self.assertRaises(ValidationError):
            sample_tools.preview_recipe({"type": "nope"})

    def test_recipe_schema_default_recipes_are_valid(self):
        schema = sample_tools.recipe_schema()
        self.assertEqual({item["type"] for item in schema["types"]},
                         {item["type"] for item in synth.recipe_types()})
        for entry in schema["types"]:
            sample = synth.from_recipe("Form", entry["default_recipe"])
            self.assertTrue(sample.pcm, entry["type"])
        json.dumps(schema)  # a pure JSON document
        self.assertEqual(schema["limits"]["max_bytes"], 65_534)

    def test_pcm_fields_round_trip(self):
        fields = sample_tools.pcm_fields(CYCLE)
        self.assertEqual((fields["loop_start"], fields["loop_length"]), (0, len(CYCLE)))
        self.assertEqual(project._pcm_from_base64(fields, "x"), CYCLE)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.dir = Path(self.folder.name)
        project.write_json(self.dir / "song.json", project.to_dict(song()))

    def tearDown(self):
        self.folder.cleanup()

    def test_edit_applies_flags_in_a_fixed_order_and_reports(self):
        code, out, err = run("sample", "edit", self.dir / "song.json", "--slot", 2, "--trim", 0, 30, "--fade", 0, 6,
                             "--gain", -1.5, "--output", self.dir / "out.json")
        self.assertEqual((code, err), (0, None), err)
        self.assertEqual(out["results"][2]["db"], -1.5)
        self.assertEqual(out["sample"]["bytes"], 30)
        self.assertEqual(out["sample"]["provenance"]["origin"], "embedded-pcm")
        edited = project.load(self.dir / "out.json").samples[1]
        self.assertEqual(len(edited.pcm), 30)
        original = project.load(self.dir / "song.json").samples[1]
        self.assertEqual(original.pcm, HIT)  # the source project is never touched

    def test_edit_errors_are_structured(self):
        code, _, err = run("sample", "edit", self.dir / "song.json", "--slot", 2, "--gain", 40,
                           "--output", self.dir / "out.json")
        self.assertEqual((code, err["code"]), (2, "SAMPLE_CLIP"))
        self.assertFalse((self.dir / "out.json").exists())
        code, _, err = run("sample", "edit", self.dir / "song.json", "--slot", 2, "--output", self.dir / "out.json")
        self.assertEqual((code, err["code"]), (2, "PATCH_FIELD"))
        code, _, err = run("sample", "edit", self.dir / "song.json", "--slot", 2, "--gain", 1,
                           "--output", self.dir / "song.json")
        self.assertEqual((code, err["code"]), (2, "OUTPUT_PATH"))

    def test_loop_flags(self):
        code, out, err = run("sample", "edit", self.dir / "song.json", "--slot", 2, "--loop", 4, 16,
                             "--output", self.dir / "a.json")
        self.assertEqual((code, out["sample"]["loop_length"]), (0, 16), err)
        code, out, err = run("sample", "edit", self.dir / "song.json", "--slot", 1, "--no-loop", "--adapt",
                             "--output", self.dir / "b.json")
        self.assertEqual((code, out["sample"]["bytes"], out["sample"]["looped"]), (0, 50, False), err)

    def test_draw_and_waveform_and_schema(self):
        code, out, err = run("sample", "draw", self.dir / "song.json", "--slot", 4, "--points", "[0, 1, 0, -1]",
                             "--cycles", 8, "--name", "Hand", "--output", self.dir / "drawn.json")
        self.assertEqual((code, out["sample"]["name"], out["sample"]["looped"]), (0, "Hand", True), err)
        code, out, err = run("sample", "draw", self.dir / "song.json", "--slot", 4, "--points", "[0, 1, 0, -1]",
                             "--as-recipe", "--output", self.dir / "recipe.json")
        self.assertEqual((code, out["sample"]["recipe"]), (0, True), err)
        code, out, err = run("sample", "waveform", self.dir / "drawn.json", "--slot", 4, "--buckets", 16)
        self.assertEqual((code, out["bucket_count"], len(out["buckets"][0])), (0, 16, 2), err)
        code, out, err = run("sample", "waveform", "--recipe", '{"type": "kick"}', "--buckets", 8)
        self.assertEqual((code, out["bucket_count"]), (0, 8), err)
        code, out, err = run("sample", "schema")
        self.assertEqual((code, "wave" in [item["type"] for item in out["types"]]), (0, True), err)
        code, _, err = run("sample", "draw", self.dir / "song.json", "--slot", 4, "--points", "[0, 1]",
                           "--output", self.dir / "bad.json")
        self.assertEqual((code, err["code"]), (2, "RECIPE_INVALID"))


if __name__ == "__main__":
    unittest.main()
