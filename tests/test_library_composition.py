"""The current composition workflow must use bank PCM without synthesizing it."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker4agents import mod, project
from tracker4agents.model import Module, Pattern, Sample, playback_plan
from tracker4agents.sample_library import SampleLibrary
from tools.create_library_demo import PALETTE, STEM, compose

ROOT = Path(__file__).resolve().parents[1]


class LibraryCompositionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="library composition ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Generated fixtures are not reference assets. Give every entry a distinct
        # payload/settings pair, then assign the selected palette's neutral IDs.
        samples = [Sample(f"Fixture hit {i}", (0, 0, 70 - i * 5, -60 + i * 7, 0, 0), 40)
                   for i in range(3)]
        for index in range(7):
            size = 112 if index == 0 else 28
            values = tuple(round(90 * math.sin(math.tau * i / size) +
                                 index * 2 * math.sin(2 * math.tau * i / size)) for i in range(size))
            samples.append(Sample(f"Fixture cycle {index}", values, 60 - index, 0, 0, size))
        source = self.root / "fixture.mod"
        source.write_bytes(mod.encode(Module("Fixture", samples, [Pattern()], [0])))
        self.bank = SampleLibrary(self.root / "bank")
        self.bank.extract(source)
        manifest = project.read_json(self.bank.path / "library.json")
        self.assertEqual(len(manifest["samples"]), len(PALETTE))
        for entry, sample_id in zip(manifest["samples"], PALETTE):
            entry["id"] = sample_id
        project.write_json(self.bank.path / "library.json", manifest)

    def test_composition_preserves_every_library_sample_and_is_a_valid_32_second_mod(self):
        module = compose(self.bank)
        self.assertEqual(module.metadata["sample_policy"], "library-only")
        self.assertEqual(module.metadata["sample_palette"]["newly_created"], 0)
        self.assertEqual(len(module.samples), len(PALETTE))
        for slot, (sample, sample_id) in enumerate(zip(module.samples, PALETTE), 1):
            self.assertIsNone(sample.recipe)
            self.assertEqual(sample, self.bank.sample(sample_id)[0])
            self.assertEqual(module.metadata["sample_sources"][str(slot)]["library_id"], sample_id)
        payload = mod.encode(project.from_dict(project.to_dict(module)))
        self.assertEqual(mod.encode(mod.decode(payload)), payload)
        self.assertEqual(playback_plan(module)["duration_seconds"], 32)

    def test_missing_library_entry_fails_instead_of_creating_a_replacement(self):
        manifest = project.read_json(self.bank.path / "library.json")
        manifest["samples"] = manifest["samples"][:-1]
        project.write_json(self.bank.path / "library.json", manifest)
        with self.assertRaisesRegex(ValueError, "Unknown library sample"):
            compose(self.bank)

    def test_cli_builds_self_contained_library_only_mod_without_audio_dependencies(self):
        output = self.root / "composition"
        result = subprocess.run([sys.executable, "tools/create_library_demo.py", "--library", str(self.bank.path),
                                 "--output", str(output), "--no-audio"], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["checks"]["all_samples_from_library"])
        self.bank.path.rename(self.root / "moved bank")
        saved = project.load(output / f"{STEM}.project.json")
        self.assertEqual(mod.encode(saved), (output / f"{STEM}.mod").read_bytes())


if __name__ == "__main__":
    unittest.main()
