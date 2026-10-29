"""Songs made only with created samples: waves, recipe insertion, palette, sample_source, loudness."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
import wave

from tracker4agents import loudness, mod, project, sample_source, synth, synth_tools, xm
from tracker4agents.cli import main
from tracker4agents.document import Document
from tracker4agents.errors import error_code
from tracker4agents.model import SAMPLE_RATE, Module, Pattern, Sample, ValidationError, cell
from tracker4agents.patch import apply_ops
from tracker4agents.report import analyze
from tracker4agents.sample_library import SampleLibrary

ROOT = Path(__file__).resolve().parents[1]

# MOD bytes exported before the wave recipe existed: created-sample projects must still build the same files.
GOLDEN_MODS = {
    "docs/listen/media/pixel_rush.project.json": "1ce068afb51e239fb090ff8b1cf3adca9ab96991d12bad6c618573d873516281",
    "docs/listen/media/voltage_odyssey_v2.project.json": "a4822a56be18d66145dac91706a096e6efbfcfa97b9e5a392c3d79f128234197",
    "examples/first_light.project.json": "4c14e4bbd515f4aeefdbc3fb978ed18b75f6f92365dcf24d925e048572913b19",
    "examples/pixel_rush.project.json": "1ce068afb51e239fb090ff8b1cf3adca9ab96991d12bad6c618573d873516281",
}


def run(*argv: str, cwd: Path | None = None) -> tuple[int, dict | None, dict | None]:
    """Run the CLI in-process: (exit code, stdout JSON, stderr JSON)."""
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


def crossings(pcm: tuple[int, ...]) -> int:
    positive = [value >= 0 for value in pcm]
    return sum(positive[index] != positive[index - 1] for index in range(len(pcm)))


def empty_module() -> Module:
    return Module("Test", [Sample("", (), 0, 0, 0, 0)], [Pattern("Pattern 00")], [0])


class WaveTests(unittest.TestCase):
    def test_shapes_loop_whole_sample_with_valid_pcm(self):
        for shape in ("pulse", "triangle", "saw", "sine"):
            for frequency in (65.4, 130.812783, 261.625565, 523.25):
                with self.subTest(shape=shape, frequency=frequency):
                    sample = synth.from_recipe("w", {"type": "wave", "shape": shape, "frequency": frequency})
                    self.assertEqual((sample.loop_start, sample.loop_length), (0, len(sample.pcm)))
                    self.assertEqual(len(sample.pcm) % 2, 0)
                    self.assertTrue(all(-128 <= value <= 127 for value in sample.pcm))
                    self.assertEqual(max(map(abs, sample.pcm)), round(0.88 * 127))
                    self.assertLess(abs(sum(sample.pcm)) / len(sample.pcm), 1.0)  # no DC offset
                    from tracker4agents.model import validate_sample
                    validate_sample(sample)

    def test_tuning_zero_crossings_per_cycle_and_cents(self):
        for shape in ("pulse", "triangle", "saw", "sine"):
            for frequency in (65.4, 130.812783, 261.625565, 440.0, 1000.0):
                with self.subTest(shape=shape, frequency=frequency):
                    sample = synth.from_recipe("w", {"type": "wave", "shape": shape, "frequency": frequency,
                                                     "duty": 0.5} if shape == "pulse" else
                                               {"type": "wave", "shape": shape, "frequency": frequency})
                    cycles = crossings(sample.pcm) / 2
                    heard = SAMPLE_RATE * cycles / len(sample.pcm)
                    self.assertLess(abs(synth.cents(heard, frequency)), 6, (cycles, heard))
                    facts = synth.recipe_facts(sample)
                    self.assertEqual(facts["cycles"], cycles)
                    self.assertLess(abs(facts["tuning_cents"]), 6)

    def test_auto_cycles_are_within_two_cents_when_possible_and_explicit_cycles_are_kept(self):
        auto = synth.from_recipe("w", {"type": "wave", "shape": "sine", "frequency": 130.812783})
        self.assertLessEqual(abs(synth.recipe_facts(auto)["tuning_cents"]), synth.AUTO_TUNING_CENTS)
        fixed = synth.from_recipe("w", {"type": "wave", "shape": "triangle", "frequency": 130.812783, "cycles": 1})
        self.assertEqual(synth.recipe_facts(fixed)["cycles"], 1)
        self.assertEqual(len(fixed.pcm), 64)

    def test_pulse_duty_changes_shape_and_noise_is_deterministic(self):
        narrow = synth.from_recipe("w", {"type": "wave", "shape": "pulse", "duty": 0.125, "cycles": 1, "frequency": 130.8})
        wide = synth.from_recipe("w", {"type": "wave", "shape": "pulse", "duty": 0.5, "cycles": 1, "frequency": 130.8})
        high = lambda sample: sum(value > 0 for value in sample.pcm) / len(sample.pcm)  # noqa: E731
        self.assertLess(high(narrow), 0.25)
        self.assertAlmostEqual(high(wide), 0.5, delta=0.05)
        recipe = {"type": "wave", "shape": "noise", "seed": 7, "length": 512, "smooth": 0.5}
        first, second = synth.from_recipe("n", recipe), synth.from_recipe("n", recipe)
        self.assertEqual(first.pcm, second.pcm)
        self.assertNotEqual(first.pcm, synth.from_recipe("n", {**recipe, "seed": 8}).pcm)
        self.assertEqual((len(first.pcm), first.loop_length), (512, 512))
        binary = synth.from_recipe("n", {"type": "wave", "shape": "noise", "binary": True, "length": 128})
        self.assertEqual(len(set(binary.pcm)), 2)

    def test_parameter_validation_uses_recipe_invalid(self):
        wave_recipe = {"type": "wave", "shape": "pulse"}
        invalid = [
            {"type": "wave"}, {"type": "wave", "shape": "organ"},
            {**wave_recipe, "duty": 0.01}, {**wave_recipe, "duty": 0.99}, {**wave_recipe, "duty": "a"},
            {**wave_recipe, "cycles": 0}, {**wave_recipe, "cycles": 65}, {**wave_recipe, "cycles": 1.5},
            {**wave_recipe, "cycles": True}, {**wave_recipe, "frequency": 20}, {**wave_recipe, "frequency": 2500},
            {**wave_recipe, "frequency": float("nan")}, {**wave_recipe, "peak": 0}, {**wave_recipe, "peak": 1.2},
            {**wave_recipe, "length": 100}, {"type": "wave", "shape": "triangle", "duty": 0.5},
            {"type": "wave", "shape": "noise", "frequency": 100}, {"type": "wave", "shape": "noise", "length": 63},
            {"type": "wave", "shape": "noise", "length": 101}, {"type": "wave", "shape": "noise", "smooth": 1},
            {"type": "wave", "shape": "noise", "seed": -1}, {"type": "wave", "shape": "noise", "binary": 1},
            {"type": "wave", "shape": "noise", "binary": True, "smooth": 0.3},
            {"type": "draw", "points": [0, 1, 0, -1], "drive": 0.5}, {"type": "kick", "drive": 2},
        ]
        for recipe in invalid:
            with self.subTest(recipe=recipe), self.assertRaises(ValidationError) as caught:
                synth.from_recipe("x", recipe)
            self.assertEqual(error_code(caught.exception), "RECIPE_INVALID")

    def test_existing_recipes_build_identical_mod_files(self):
        for name, digest in GOLDEN_MODS.items():
            with self.subTest(project=name):
                self.assertEqual(hashlib.sha256(mod.encode(project.load(ROOT / name))).hexdigest(), digest)
        for name in ("pixel_rush", "voltage_odyssey_v2"):
            built = mod.encode(project.load(ROOT / "docs/listen/media" / f"{name}.project.json"))
            self.assertEqual(built, (ROOT / "docs/listen/media" / f"{name}.mod").read_bytes())
        copper = project.load(ROOT / "docs/listen/media/copper_skies.project.json")   # the synthesized XM demo
        self.assertEqual(copper.metadata["sample_source"], "synthesized")
        self.assertTrue(all(sample.recipe for sample in copper.samples))
        self.assertEqual(xm.encode(copper), (ROOT / "docs/listen/media/copper_skies.xm").read_bytes())

    def test_recipe_catalog_names_only_accepted_parameters(self):
        types = {item["type"]: item for item in synth.recipe_types()}
        self.assertEqual(set(types), {"wave", "kick", "snare", "hat", "kick_hat", "snare_hat", "pluck", "draw"})
        for kind, item in types.items():
            for name, details in item["parameters"].items():
                self.assertIn("kind", details)
                self.assertIn(name, {"shape", "frequency", "cycles", "duty", "length", "smooth", "binary", "seed", "peak",
                                     "duration", "points", "drive"}, kind)
        sample = synth.from_recipe("p", {"type": "kick", "drive": 0.3})
        self.assertTrue(sample.pcm)
        self.assertNotEqual(sample.pcm, synth.from_recipe("p", {"type": "kick"}).pcm)


class LoudnessTests(unittest.TestCase):
    def test_full_scale_square_vs_half_scale_differs_by_six_db(self):
        full = Sample("f", (100, -100) * 8, 64, 0, 0, 16)
        half = Sample("h", (50, -50) * 8, 64, 0, 0, 16)
        difference = loudness.measure(full)["loudness_db"] - loudness.measure(half)["loudness_db"]
        self.assertAlmostEqual(difference, 6.02, delta=0.02)
        quiet = loudness.measure(full, 32)["loudness_db"]
        self.assertAlmostEqual(loudness.measure(full)["loudness_db"] - quiet, 6.02, delta=0.02)
        self.assertAlmostEqual(loudness.measure(Sample("m", (127, -127) * 8, 64, 0, 0, 16))["loudness_db"], -0.07, delta=0.05)
        self.assertEqual(loudness.measure(Sample("z", (0, 0) * 8, 64, 0, 0, 16))["loudness_db"], loudness.FLOOR_DB)

    def test_one_shot_measures_only_its_audible_part(self):
        body = (0, 0) + (60, -60) * 31
        padded = Sample("p", body + (0,) * 2000, 64)
        self.assertEqual(loudness.audible_region(padded)[1], len(body) if len(body) % 64 == 0 else
                         math.ceil(len(body) / 64) * 64)
        self.assertAlmostEqual(loudness.measure(padded)["loudness_db"], loudness.measure(Sample("b", body, 64))["loudness_db"],
                               delta=0.6)

    def fixture_bank(self, root: Path) -> SampleLibrary:
        pulse = Sample("a", (50, -50) * 8, 64, 0, 0, 16)
        hit = Sample("b", (0, 0) + tuple((90 if index % 2 else -90) for index in range(298)), 64)
        module = Module("t", [pulse, hit], [Pattern(cells={(0, 0): cell("C-2", 1)})], [0])
        source = root / "ref.mod"
        source.write_bytes(mod.encode(module))
        bank = SampleLibrary(root / "bank")
        bank.extract(source)
        return bank

    def test_reference_from_a_small_bank_is_aggregate_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            bank = self.fixture_bank(Path(temporary))
            reference = loudness.reference_from_library(bank)
            self.assertEqual(reference["groups"]["bass"]["count"], 1)
            self.assertEqual(reference["groups"]["percussion"]["count"], 1)
            self.assertAlmostEqual(reference["groups"]["bass"]["median_db"], -8.17, delta=0.05)
            self.assertAlmostEqual(reference["groups"]["percussion"]["median_db"], -3.06, delta=0.1)
            text = json.dumps(reference)
            self.assertNotIn("SMP-", text)
            resolved = synth_tools.resolve_reference("library", bank.path)
            self.assertEqual(resolved["source"], "library")
            self.assertEqual(resolved["groups"]["lead"]["median_db"], loudness.DEFAULT_REFERENCE_DB["lead"]["p50"])

    def test_percussion_roles_aim_at_their_own_quartile_of_the_bank(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            hits = [Sample(f"h{amp}", (0, 0) + tuple((amp if index % 2 else -amp) for index in range(298)), 64)
                    for amp in (10, 20, 40, 80, 120)]
            (root / "ref.mod").write_bytes(mod.encode(Module("t", hits, [Pattern(cells={(0, 0): cell("C-2", 1)})], [0])))
            bank = SampleLibrary(root / "bank")
            bank.extract(root / "ref.mod")
            reference = loudness.reference_from_library(bank)
            group = reference["groups"]["percussion"]
            self.assertEqual(group["count"], 5)
            self.assertLess(group["p25_db"], group["p50_db"])
            self.assertLess(group["p50_db"], group["p75_db"])
            self.assertEqual(group["median_db"], group["p50_db"])
            # amplitudes 10..120 give about -22, -16, -10, -4 and -0.5 dB; the quartiles are the 2nd and 4th.
            self.assertAlmostEqual(group["p25_db"], -16.0, delta=0.6)
            self.assertAlmostEqual(group["p75_db"], -4.0, delta=0.6)
            resolved = synth_tools.resolve_reference("library", bank.path)
            self.assertEqual(loudness.target_db("kick", resolved), group["p75_db"])
            self.assertEqual(loudness.target_db("snare", resolved), group["p50_db"])
            self.assertEqual(loudness.target_db("hat", resolved), group["p25_db"])
            code, out, _ = run("synth", "levels", "--library", bank.path)
            self.assertEqual(out["groups"]["percussion"]["p75_db"], group["p75_db"])
            self.assertEqual(out["role_targets_db"]["hat"], group["p25_db"])
            self.assertNotIn("SMP-", json.dumps(out))
            _, info = synth_tools.palette("T", "default", resolved)
            by_name = {entry["name"]: entry for entry in info["slots"]}
            self.assertGreater(by_name["Kick"]["target_db"], by_name["Snare"]["target_db"])
            self.assertGreater(by_name["Snare"]["target_db"], by_name["Hat"]["target_db"])
            self.assertEqual(by_name["Kick+hat"]["target_db"], group["p75_db"])
            self.assertEqual(by_name["Snare+hat"]["target_db"], group["p50_db"])

    def test_fallback_without_a_bank_uses_fixed_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, out, _ = run("synth", "levels", cwd=Path(temporary))
            self.assertEqual(code, 0)
            self.assertEqual(out["source"], "defaults")
            self.assertEqual({group: value["p50_db"] for group, value in out["groups"].items()},
                             {group: value["p50"] for group, value in loudness.DEFAULT_REFERENCE_DB.items()})
            targets = out["role_targets_db"]
            self.assertGreater(targets["kick"], targets["snare"])
            self.assertGreater(targets["snare"], targets["hat"])
            self.assertEqual(targets["kick"], loudness.DEFAULT_REFERENCE_DB["percussion"]["p75"])
            self.assertEqual(targets["hat"], loudness.DEFAULT_REFERENCE_DB["percussion"]["p25"])
            self.assertEqual((targets["bass"], targets["lead"], targets["chord"], targets["texture"]),
                             (-7.3, -9.9, -9.9, -2.8))
            code, _, err = run("synth", "levels", "--library", Path(temporary) / "missing")
            self.assertEqual((code, err["code"]), (2, "SAMPLE_LIBRARY"))

    def test_palette_lands_within_tolerance_of_every_target(self):
        for source, reference in (("defaults", synth_tools.resolve_reference("defaults")),):
            module, info = synth_tools.palette("Test", "default", reference)
            for entry in info["slots"]:
                with self.subTest(slot=entry["name"]):
                    self.assertAlmostEqual(entry["measured_db"], entry["target_db"], delta=1.5)
                    self.assertEqual(loudness.measure(module.samples[entry["slot"] - 1])["loudness_db"], entry["measured_db"])

    def test_palette_matches_a_fixture_bank_and_no_match_keeps_hand_set_levels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bank = self.fixture_bank(root)
            code, out, _ = run("synth", "palette", "--output", root / "m.json", "--match-library", bank.path)
            self.assertEqual((code, out["reference"]), (0, "library"))
            roles = {entry["role"]: entry for entry in out["slots"]}
            self.assertAlmostEqual(roles["bass"]["target_db"], -8.17, delta=0.05)
            self.assertAlmostEqual(roles["bass"]["measured_db"], roles["bass"]["target_db"], delta=1.5)
            code, plain, _ = run("synth", "palette", "--output", root / "n.json", "--no-match")
            self.assertEqual(code, 0)
            for entry in plain["slots"]:
                self.assertEqual(entry["volume"], entry["hand_set_volume"])
                self.assertIsNone(entry["target_db"])
            self.assertEqual([item[2] for item in synth_tools.PALETTE],
                             [item.volume for item in project.load(root / "n.json").samples[:13]])
            code, _, err = run("synth", "palette", "--output", root / "n.json", "--no-match")
            self.assertEqual((code, err["code"]), (2, "OUTPUT_PATH"))

    def test_add_matches_by_role_or_keeps_an_explicit_volume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project.write_json(root / "p.json", project.to_dict(empty_module()))
            recipe = json.dumps({"type": "wave", "shape": "triangle", "frequency": 130.812783})
            code, matched, _ = run("synth", "add", root / "p.json", "--recipe", recipe, "--name", "Bass",
                                   "--output", root / "a.json", cwd=root)
            self.assertEqual((code, matched["role"], matched["reference"]), (0, "bass", "defaults"))
            self.assertAlmostEqual(matched["loudness"]["measured_db"], matched["loudness"]["target_db"], delta=1.5)
            code, plain, _ = run("synth", "add", root / "p.json", "--recipe", recipe, "--name", "Bass",
                                 "--output", root / "b.json", "--no-match")
            self.assertEqual((plain["loudness"]["volume"], plain["loudness"]["measured_db"]),
                             (40, plain["loudness"]["unmatched_db"]))
            code, explicit, _ = run("synth", "add", root / "p.json", "--recipe", recipe, "--name", "Bass",
                                    "--output", root / "c.json", "--volume", "20", "--role", "lead")
            self.assertEqual((explicit["loudness"]["volume"], explicit["role"]), (20, "lead"))
            self.assertEqual(project.load(root / "c.json").samples[0].volume, 20)

    def test_report_lists_loudness_and_flags_samples_far_from_the_reference(self):
        module = Module("t", [Sample("quiet", (6, -6) * 8, 64, 0, 0, 16, None),
                              Sample("ok", (60, -60) * 8, 64, 0, 0, 16, None)],
                        [Pattern(cells={(0, 0): cell("C-2", 1), (1, 1): cell("C-2", 2)})], [0])
        report = analyze(module)
        slots = {entry["slot"]: entry for entry in report["samples"]["slots"]}
        self.assertEqual(slots[1]["group"], "lead")
        self.assertLess(slots[1]["deviation_db"], -6)
        flagged = [item["slot"] for item in report["warnings"] if item["code"] == "sample_level_off_reference"]
        self.assertEqual(flagged, [1])
        self.assertEqual(report["samples"]["sources"], {"recipe": 0, "embedded_pcm": 2, "declared": None})
        self.assertEqual(slots[2]["source"], "embedded_pcm")


class RecipeSampleOperationTests(unittest.TestCase):
    RECIPE = {"type": "wave", "shape": "pulse", "duty": 0.25}

    def test_first_free_slot_explicit_slot_and_metadata(self):
        module = empty_module()
        module.metadata["sample_sources"] = {"1": {"library_id": "SMP-0001"}}  # stale entry of an emptied slot
        first = apply_ops(module, [{"op": "recipe_sample", "name": "A", "recipe": self.RECIPE, "volume": 33}])[0]
        self.assertEqual((first["slot"], module.samples[0].volume, module.samples[0].recipe), (1, 33, self.RECIPE))
        self.assertEqual(module.metadata["sample_sources"]["1"]["origin"], "synthesized")
        second = apply_ops(module, [{"op": "recipe_sample", "name": "B", "recipe": {"type": "kick"}}])[0]
        self.assertEqual((second["slot"], second["role"]), (2, "kick"))
        self.assertEqual(len(module.samples), 2)
        apply_ops(module, [{"op": "recipe_sample", "name": "C", "recipe": self.RECIPE, "slot": 3, "finetune": 2,
                            "match": "none"}])
        self.assertEqual((module.samples[2].volume, module.samples[2].finetune), (40, 2))
        module.patterns[0].put(0, 0, cell("C-2", 4))  # a free slot referenced by a cell is not reused
        module.samples.append(Sample("", (), 0, 0, 0, 0))
        self.assertEqual(apply_ops(module, [{"op": "recipe_sample", "name": "D", "recipe": self.RECIPE}])[0]["slot"], 5)

    def test_occupied_slots_gaps_and_bad_fields_are_refused(self):
        module = empty_module()
        apply_ops(module, [{"op": "recipe_sample", "name": "A", "recipe": self.RECIPE}])
        cases = [
            ({"slot": 1}, "SAMPLE_SLOT"), ({"slot": 5}, "SAMPLE_SLOT"), ({"slot": 32}, "SAMPLE_SLOT"),
            ({"replace": "yes"}, "PATCH_FIELD"), ({"role": "piano"}, "RECIPE_INVALID"),
            ({"volume": 65}, "INTEGER_RANGE"), ({"match": "bank"}, "PATCH_FIELD"), ({"library": "x"}, "PATCH_FIELD"),
            ({"match": "library"}, "PATCH_FIELD"), ({"colour": 1}, "UNKNOWN_FIELD"),
        ]
        for extra, code in cases:
            with self.subTest(extra=extra), self.assertRaises(ValidationError) as caught:
                apply_ops(module, [{"op": "recipe_sample", "name": "B", "recipe": self.RECIPE, **extra}])
            self.assertEqual(error_code(caught.exception), code)
        with self.assertRaises(ValidationError) as caught:
            apply_ops(module, [{"op": "recipe_sample", "name": "B", "recipe": {"type": "wave", "shape": "x"}}])
        self.assertEqual(error_code(caught.exception), "RECIPE_INVALID")
        apply_ops(module, [{"op": "recipe_sample", "name": "B", "recipe": {"type": "kick"}, "slot": 1, "replace": True}])
        self.assertEqual((module.samples[0].name, len(module.samples)), ("B", 1))

    def test_document_patch_is_undoable_and_all_or_nothing(self):
        document = Document(empty_module())
        result = document.patch([{"op": "recipe_sample", "name": "A", "recipe": self.RECIPE}], "add")
        self.assertTrue(result["changed"])
        self.assertTrue(document.module.samples[0].pcm)
        self.assertTrue(document.undo())
        self.assertFalse(document.module.samples[0].pcm)
        with self.assertRaises(ValidationError):
            document.patch([{"op": "recipe_sample", "name": "A", "recipe": self.RECIPE},
                            {"op": "recipe_sample", "name": "B", "recipe": self.RECIPE, "slot": 9}])
        self.assertFalse(document.module.samples[0].pcm)

    def test_matching_from_a_bank_through_the_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            bank = LoudnessTests().fixture_bank(Path(temporary))
            module = empty_module()
            info = apply_ops(module, [{"op": "recipe_sample", "name": "A", "recipe": self.RECIPE, "match": "library",
                                       "library": str(bank.path), "role": "bass"}])[0]
            self.assertEqual(info["loudness"]["reference"], "library")
            self.assertAlmostEqual(info["loudness"]["measured_db"], -8.17, delta=1.5)
            with self.assertRaises(ValidationError) as caught:
                apply_ops(module, [{"op": "recipe_sample", "name": "A", "recipe": self.RECIPE, "match": "library",
                                    "library": str(Path(temporary) / "none"), "slot": 2}])
            self.assertEqual(error_code(caught.exception), "SAMPLE_LIBRARY")


class SampleSourceTests(unittest.TestCase):
    def synthesized(self) -> Module:
        module, _ = synth_tools.palette("Test", "default", None)
        return module

    def library_like(self) -> Module:
        return Module("Lib", [Sample("PCM", (50, -50) * 8, 40, 0, 0, 16)], [Pattern()], [0])

    def test_palette_is_valid_declared_and_explained(self):
        module, info = synth_tools.palette("My Palette", "default", None)
        self.assertEqual(module.metadata["sample_source"], "synthesized")
        self.assertEqual(len(module.patterns), 1)
        self.assertFalse(module.patterns[0].cells)
        self.assertEqual([entry["slot"] for entry in info["slots"]], list(range(1, 14)))
        self.assertTrue(all(sample.recipe for sample in module.samples))
        self.assertEqual(module.metadata["palette"]["roles"]["1"], "kick: Kick")
        for sample in module.samples:
            self.assertLessEqual(len(sample.name), 22)
        self.assertEqual(mod.encode(project.from_dict(project.to_dict(module))), mod.encode(module))
        self.assertEqual({entry["role"] for entry in info["slots"]},
                         {"kick", "snare", "hat", "bass", "lead", "chord", "texture"})
        for entry in info["slots"]:
            if entry["tuning_cents"] is not None:
                self.assertLess(abs(entry["tuning_cents"]), 2.5)

    def test_validate_flag_works_both_ways(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            synthesized, library = root / "s.json", root / "l.json"
            project.write_json(synthesized, project.to_dict(self.synthesized()))
            project.write_json(library, project.to_dict(self.library_like()))
            self.assertEqual(run("validate", synthesized, "--sample-source", "synthesized")[0], 0)
            code, _, err = run("validate", library, "--sample-source", "synthesized")
            self.assertEqual((code, err["code"]), (2, "SAMPLE_SOURCE"))
            self.assertEqual(err["violations"][0]["slot"], 1)
            self.assertIn("1", err["message"])
            self.assertEqual(run("validate", library, "--sample-source", "library")[0], 0)
            code, _, err = run("validate", synthesized, "--sample-source", "library")
            self.assertEqual(err["code"], "SAMPLE_SOURCE")
            self.assertEqual(len(err["violations"]), 14)  # the declaration plus all 13 recipe slots
            code, out, _ = run("validate", synthesized)
            self.assertEqual(out["sample_source"]["checked"], "synthesized")

    def test_declared_source_is_checked_without_the_flag_and_in_the_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = self.synthesized()
            module.samples[2] = Sample("Borrowed", (40, -40) * 8, 40, 0, 0, 16)
            path = root / "bad.json"
            project.write_json(path, project.to_dict(module))
            code, _, err = run("validate", path)
            self.assertEqual((code, err["code"], err["violations"][0]["slot"]), (2, "SAMPLE_SOURCE", 3))
            code, _, err = run("validate", path, "--report")
            self.assertEqual((code, err["code"]), (2, "PROJECT_INVALID"))
            self.assertEqual([(item["code"], item["path"]) for item in err["errors"]], [("SAMPLE_SOURCE", "samples[2]")])
            module.metadata["sample_source"] = "mixed"
            project.write_json(path, project.to_dict(module))
            self.assertEqual(run("validate", path, "--report")[0], 0)
            module.metadata["sample_source"] = "analog"
            project.write_json(path, project.to_dict(module))
            self.assertEqual(run("validate", path)[2]["code"], "SAMPLE_SOURCE")

    def test_modes_are_not_mixed_unless_the_project_says_so(self):
        library_project = self.library_like()
        library_project.metadata["sample_source"] = "library"
        with self.assertRaises(ValidationError) as caught:
            apply_ops(library_project, [{"op": "recipe_sample", "name": "A", "recipe": {"type": "kick"}}])
        self.assertEqual(error_code(caught.exception), "SAMPLE_SOURCE")
        library_project.metadata["sample_source"] = "mixed"
        apply_ops(library_project, [{"op": "recipe_sample", "name": "A", "recipe": {"type": "kick"}}])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "ref.mod"
            source.write_bytes(mod.encode(Module("t", [Sample("a", (50, -50) * 8, 64, 0, 0, 16)],
                                                 [Pattern(cells={(0, 0): cell("C-2", 1)})], [0])))
            bank = SampleLibrary(root / "bank")
            bank.extract(source)
            target = self.synthesized()
            with self.assertRaises(ValidationError) as caught:
                bank.insert(target, "SMP-0001")
            self.assertEqual(error_code(caught.exception), "SAMPLE_SOURCE")
            with self.assertRaises(ValidationError) as caught:
                apply_ops(target, [{"op": "library_sample", "library": str(bank.path), "id": "SMP-0001"}])
            self.assertEqual(error_code(caught.exception), "SAMPLE_SOURCE")
            project.write_json(root / "s.json", project.to_dict(target))
            code, _, err = run("samples", "add", "SMP-0001", "--library", bank.path, "--project", root / "s.json",
                               "--output", root / "o.json")
            self.assertEqual((code, err["code"]), (2, "SAMPLE_SOURCE"))
            self.assertFalse((root / "o.json").exists())
            bank.insert(self.library_like(), "SMP-0001")  # an undeclared project still accepts a library sample

    def test_report_counts_sources(self):
        module = self.synthesized()
        module.samples.append(Sample("PCM", (50, -50) * 8, 40, 0, 0, 16))
        counts = analyze(module)["samples"]["sources"]
        self.assertEqual((counts["recipe"], counts["embedded_pcm"], counts["declared"]), (13, 1, "synthesized"))
        self.assertEqual(sample_source.counts(module)["embedded_pcm_slots"], [14])


class CliContractTests(unittest.TestCase):
    def test_types_and_preview_and_add_contracts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, out, _ = run("synth", "types")
            self.assertEqual(code, 0)
            wave_type = next(item for item in out["types"] if item["type"] == "wave")
            self.assertEqual(wave_type["parameters"]["duty"]["min"], 0.05)
            self.assertEqual(wave_type["parameters"]["shape"]["choices"], list(synth.WAVE_SHAPES))
            self.assertTrue(all(item["purpose"] for item in out["types"]))
            recipe = json.dumps({"type": "wave", "shape": "saw", "frequency": 130.812783})
            code, out, _ = run("synth", "preview", "--recipe", recipe, "--output", root / "p.wav",
                               "--note", "C-2", "--seconds", "0.5", "--role", "bass")
            self.assertEqual(code, 0)
            with wave.open(str(root / "p.wav")) as reader:
                self.assertEqual((reader.getnchannels(), reader.getframerate(), reader.getnframes()), (1, 44100, 22050))
            self.assertLess(abs(out["sample"]["tuning_cents"]), 2.5)
            self.assertEqual(out["loudness"]["group"], "bass")
            self.assertIn("rms_dbfs", out["audio"])
            (root / "recipe.json").write_text(recipe, encoding="utf-8")
            self.assertEqual(run("synth", "preview", "--recipe", f"@{root / 'recipe.json'}", "--output", root / "q.wav")[0], 0)
            code, _, err = run("synth", "preview", "--recipe", '{"type": "wave", "shape": "saw", "cycles": 99}',
                               "--output", root / "r.wav")
            self.assertEqual((code, err["code"]), (2, "RECIPE_INVALID"))
            self.assertFalse((root / "r.wav").exists())
            code, _, err = run("synth", "preview", "--recipe", "{nope", "--output", root / "r.wav")
            self.assertEqual(err["code"], "RECIPE_INVALID")
            code, _, err = run("synth", "preview", "--recipe", recipe, "--output", root / "r.mp3")
            self.assertEqual(err["code"], "OUTPUT_PATH")

    def test_add_refuses_occupied_slots_same_output_and_writes_a_new_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            code, _, _ = run("synth", "palette", "--output", root / "p.json", "--title", "T", "--no-match")
            self.assertEqual(code, 0)
            kick = '{"type": "kick", "seed": 5}'
            code, _, err = run("synth", "add", root / "p.json", "--recipe", kick, "--name", "K2", "--slot", "1",
                               "--output", root / "o.json", "--no-match")
            self.assertEqual((code, err["code"]), (2, "SAMPLE_SLOT"))
            code, _, err = run("synth", "add", root / "p.json", "--recipe", kick, "--name", "K2",
                               "--output", root / "p.json", "--no-match")
            self.assertEqual(err["code"], "OUTPUT_PATH")
            code, out, _ = run("synth", "add", root / "p.json", "--recipe", kick, "--name", "K2", "--slot", "1",
                               "--replace", "--output", root / "o.json", "--no-match", "--volume", "50", "--finetune", "-2")
            self.assertEqual((code, out["slot"]), (0, 1))
            replaced = project.load(root / "o.json").samples[0]
            self.assertEqual((replaced.name, replaced.volume, replaced.finetune, replaced.recipe), ("K2", 50, -2, json.loads(kick)))
            code, out, _ = run("synth", "add", root / "p.json", "--recipe", kick, "--name", "K3", "--output", root / "n.json",
                               "--no-match")
            self.assertEqual(out["slot"], 14)
            self.assertEqual(project.load(root / "p.json").samples[0].name, "Kick")  # the input is untouched

    def test_synthesized_demo_flow_exports_a_mod(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run("synth", "palette", "--output", root / "p.json", "--no-match")
            ops = [{"op": "set", "pattern": 0, "row": row, "channel": channel, "cell": f"{note} {slot:02X} ..."}
                   for row, channel, note, slot in ((0, 0, "C-2", 4), (4, 0, "C-2", 5), (0, 1, "A-1", 6), (0, 3, "E-3", 9))]
            code, _, _ = run("patch", root / "p.json", "--output", root / "s.json", "--op", json.dumps(ops))
            self.assertEqual(code, 0)
            self.assertEqual(run("validate", root / "s.json", "--sample-source", "synthesized", "--report")[0], 0)
            self.assertEqual(run("export", root / "s.json", "--output", root / "s.mod")[0], 0)
            self.assertEqual(mod.read(root / "s.mod").samples[3].pcm, project.load(root / "s.json").samples[3].pcm)


if __name__ == "__main__":
    unittest.main()
