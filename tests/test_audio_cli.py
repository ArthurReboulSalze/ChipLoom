from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tracker4agents import audio, demo, mod, project
from tracker4agents.model import Module, Pattern, ValidationError, cell, playback_plan

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def invoke(self, *args: str):
        return subprocess.run([sys.executable, "-m", "tracker4agents", *args], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=20)

    def test_agent_can_edit_score_then_export_import_and_reexport(self):
        with tempfile.TemporaryDirectory(prefix="tracker agent ") as directory:
            directory = Path(directory)
            score = project.to_dict(demo.create(), layout="events")
            score["patterns"][0]["events"][3]["note"] = "G-2"
            source, output = directory / "score.json", directory / "score.mod"
            project.write_json(source, score)
            result = self.invoke("export", str(source), "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])
            imported = directory / "imported.json"
            result = self.invoke("import", str(output), "--output", str(imported))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(mod.encode(project.load(imported)), output.read_bytes())

    def test_bad_project_returns_json_and_keeps_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "bad.json", Path(directory) / "existing.mod"
            source.write_text('{"schema":"unknown"}', encoding="utf-8")
            output.write_bytes(b"original")
            result = self.invoke("export", str(source), "--output", str(output))
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stderr)["ok"])
            self.assertEqual(output.read_bytes(), b"original")

    def test_demo_can_build_without_external_audio_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke("demo", "--output", directory, "--no-audio")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(json.loads(result.stdout)["wav"])
            self.assertEqual(len(list((Path(directory) / "samples").glob("*.wav"))), 8)


class NativeAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="tracker audio ")
        cls.directory = Path(cls.temporary.name)
        cls.source = cls.directory / "test loop.mod"
        cls.module = demo.create()
        cls.source.write_bytes(mod.encode(cls.module))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_render_bounds_and_extensions_are_enforced(self):
        for seconds in (0, -1, 121, float("nan")):
            with self.subTest(seconds=seconds), self.assertRaises(ValidationError):
                audio.render(self.source, self.directory / "bad.wav", seconds=seconds)
        with self.assertRaises(ValidationError):
            audio.render(self.source, self.directory / "bad.mod", seconds=0.2)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg indisponible")
    def test_openmpt_decodes_actual_mod_and_optional_mp3(self):
        output = self.directory / "openmpt.wav"
        result = audio.render(self.source, output, seconds=0.96)
        self.assertEqual(result["audio"]["frames"], 46080)
        self.assertGreater(result["audio"]["peak"], 0.01)
        self.assertEqual(result["audio"]["clipped_samples"], 0)
        mp3 = self.directory / "optional.mp3"
        encoded = audio.export_mp3(output, mp3)
        self.assertGreater(encoded["bytes"], 1000)
        verify = subprocess.run([shutil.which("ffmpeg"), "-hide_banner", "-v", "error", "-i", str(mp3),
                                 "-f", "null", "-"], capture_output=True, text=True, timeout=20)
        self.assertEqual(verify.returncode, 0, verify.stderr)

    def test_xmp_replays_two_cycles_with_expected_order_timing(self):
        try:
            library = audio.default_xmp_library()
        except audio.RenderError as exc:
            self.skipTest(str(exc))
        plan = playback_plan(self.module)
        result = audio.render(self.source, self.directory / "xmp.wav", "xmp", plan["duration_seconds"] * 2,
                              xmp_library=library)
        self.assertEqual(result["version"], "4.7.3")
        self.assertEqual(result["mixer_type"], 1)  # Actual A500 mixer, not merely a requested flag.
        self.assertEqual(result["audio"]["frames"], 2_949_120)
        self.assertEqual(result["audio"]["clipped_samples"], 0)
        trace = result["trace"]
        self.assertEqual(len(trace), 512)
        for index, row in enumerate(trace):
            expected = plan["timeline"][index % 256]
            for key in ("order", "pattern", "row", "speed", "bpm"):
                self.assertEqual(row[key], expected[key])
            self.assertAlmostEqual(row["seconds"], expected["seconds"] + (index // 256) * 30.72, places=4)

    def test_xmp_confirms_tempo_speed_and_decimal_pattern_break(self):
        try:
            library = audio.default_xmp_library()
        except audio.RenderError as exc:
            self.skipTest(str(exc))
        first = Pattern(cells={(0, 0): cell("C-2", 4, "F03"), (0, 1): cell(effect="F64"),
                               (1, 0): cell(effect="D10")})
        second = Pattern(cells={(10, 0): cell(effect="B00")})
        module = Module("Timing fixture", self.module.samples, [first, second], [0, 1])
        source = self.directory / "tempo.mod"
        source.write_bytes(mod.encode(module))
        plan = playback_plan(module)
        result = audio.render(source, self.directory / "tempo.wav", "xmp", plan["duration_seconds"] * 2,
                              xmp_library=library)
        trace = result["trace"]
        self.assertEqual(len(trace), 6)
        for index, row in enumerate(trace):
            expected = plan["timeline"][index % 3]
            for key in ("order", "pattern", "row", "speed", "bpm"):
                self.assertEqual(row[key], expected[key])
            self.assertAlmostEqual(row["seconds"], expected["seconds"] + (index // 3) * 0.225, places=4)


if __name__ == "__main__":
    unittest.main()
