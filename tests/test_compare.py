from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from tracker4agents import audio, mod, project
from tracker4agents.compare import create_comparison
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell

ROOT = Path(__file__).resolve().parents[1]
SINE = tuple(round(100 * math.sin(math.tau * index / 64)) for index in range(64))


def tone_module(title: str, notes: tuple[str, ...]) -> Module:
    """Eight rows (0.96 s). A looped sine plays the given notes on rows 0, 2, 4, 6."""
    pattern = Pattern()
    for row, note in zip((0, 2, 4, 6), notes):
        pattern.put(row, 0, cell(note, 1))
    pattern.put(7, 3, cell(None, 0, "D00"))
    return Module(title, [Sample("Sine", SINE, 64, loop_length=64)], [pattern], [0])


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fake_render(source, output, engine="openmpt", seconds=None, **kwargs):
    """Writes a short 48 kHz stereo tone; records the requested excerpt length."""
    fake_render.calls.append({"source": Path(source).name, "seconds": seconds})
    frames = 4800
    with wave.open(str(output), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        data = b"".join(struct.pack("<hh", value, value) for value in
                        (round(8000 * math.sin(index / 20)) for index in range(frames)))
        stream.writeframes(data)
    return {"engine": "fake", "version": "0", "requested_seconds": seconds, "output": str(output),
            "source_sha256": audio.sha256(Path(source)), "audio": audio.analyze_wav(Path(output))}


fake_render.calls = []


class ComparisonFixtureCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="compare ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.alpha = tone_module("Tone Alpha", ("C-2", "E-2", "G-2", "C-3"))
        self.beta = tone_module("Tone Beta", ("D-2", "F-2", "A-2", "D-3"))
        self.first = self.sources / "alpha.project.json"
        self.second = self.sources / "beta.mod"
        project.write_json(self.first, project.to_dict(self.alpha))
        self.second.write_bytes(mod.encode(self.beta))
        self.labels = ("Alpha draft", "Beta draft")
        fake_render.calls.clear()


class MockedAudioComparisonTests(ComparisonFixtureCase):
    def build(self, name="out", show_answer=True, **kwargs):
        with patch("tracker4agents.compare.audio.render", side_effect=fake_render):
            return create_comparison(self.first, self.second, self.root / name, labels=self.labels,
                                     show_answer=show_answer, **kwargs)

    def test_bundle_layout_and_return_value(self):
        result = self.build(seed=3)
        out = self.root / "out"
        self.assertTrue(result["ok"])
        self.assertEqual(Path(result["page"]).resolve(), (out / "index.html").resolve())
        self.assertEqual(sorted(path.name for path in out.iterdir()),
                         ["answer_key.json", "comparison.json", "index.html", "x.mod", "x.wav", "y.mod", "y.wav"])
        self.assertEqual(set(result["answer_key"]), {"x", "y", "labels"})
        self.assertEqual({result["answer_key"]["x"], result["answer_key"]["y"]}, {"first", "second"})
        self.assertFalse(list(self.root.glob(".chiploom-compare-*")))

    def test_answer_key_is_written_to_a_file_not_returned_by_default(self):
        result = self.build(seed=3, show_answer=False)
        out = (self.root / "out").resolve()
        self.assertNotIn("answer_key", result)
        for secret in ("first", "second", "Alpha draft", "Beta draft"):
            self.assertNotIn(f'"{secret}"', json.dumps(result), secret)
        self.assertEqual(Path(result["answer_key_file"]), out / "answer_key.json")
        key = json.loads((out / "answer_key.json").read_text(encoding="utf-8"))
        full = json.loads((out / "comparison.json").read_text(encoding="utf-8"))["answer_key"]
        self.assertEqual({"x": key["x"], "y": key["y"]}, full)
        self.assertEqual(set(key["labels"].values()), set(self.labels))
        self.assertEqual(self.build("again", seed=3)["answer_key"]["x"], key["x"])

    def test_cli_prints_the_key_only_with_show_answer(self):
        from tracker4agents import cli
        import contextlib
        import io
        for flag, name in (([], "cli-hidden"), (["--show-answer"], "cli-shown")):
            stream = io.StringIO()
            with patch("tracker4agents.compare.audio.render", side_effect=fake_render),                     contextlib.redirect_stdout(stream):
                code = cli.main(["compare", str(self.first), str(self.second), "--output", str(self.root / name),
                                 "--seed", "2", *flag])
            self.assertEqual(code, 0)
            result = json.loads(stream.getvalue())
            self.assertEqual("answer_key" in result, bool(flag))
            self.assertTrue(Path(result["answer_key_file"]).is_file())

    def test_xm_inputs_keep_their_extension(self):
        from tracker4agents import formats
        from tracker4agents.convert import mod_to_xm
        xm_path = self.sources / "beta.xm"
        xm_path.write_bytes(formats.encode(mod_to_xm(self.beta)[0]))
        with patch("tracker4agents.compare.audio.render", side_effect=fake_render):
            result = create_comparison(self.first, xm_path, self.root / "xm", seed=1, show_answer=True)
        out = self.root / "xm"
        xm_side = "x" if result["answer_key"]["x"] == "second" else "y"
        mod_side = "y" if xm_side == "x" else "x"
        self.assertEqual(Path(result[xm_side]["mod"]), out / f"{xm_side}.xm")
        self.assertEqual(Path(result[mod_side]["mod"]), out / f"{mod_side}.mod")
        self.assertTrue(Path(result[xm_side]["mod"]).is_file())
        self.assertTrue(Path(result[mod_side]["mod"]).is_file())

    def test_seed_makes_the_mapping_deterministic_and_both_orders_occur(self):
        keys = {}
        for seed in range(12):
            name = f"seed{seed}"
            keys[seed] = self.build(name, seed=seed)["answer_key"]
            again = self.build(f"{name}-again", seed=seed)["answer_key"]
            self.assertEqual(keys[seed], again)
        self.assertEqual({key["x"] for key in keys.values()}, {"first", "second"})

    def test_answer_key_matches_the_exported_modules(self):
        result = self.build(seed=1)
        out = self.root / "out"
        key = json.loads((out / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(key["answer_key"], {"x": result["answer_key"]["x"], "y": result["answer_key"]["y"]})
        expected = {"first": mod.encode(self.alpha), "second": mod.encode(self.beta)}
        for side in ("x", "y"):
            self.assertEqual((out / f"{side}.mod").read_bytes(), expected[key["answer_key"][side]])
            self.assertEqual(key["versions"][side]["mod_sha256"], sha(out / f"{side}.mod"))
        self.assertEqual(key["labels"], {"first": "Alpha draft", "second": "Beta draft"})
        self.assertIn("not judgments", key["versions"]["x"]["report"]["scope"])

    def test_page_hides_the_answer_until_reveal(self):
        self.build(seed=5)
        page = (self.root / "out" / "index.html").read_text(encoding="utf-8")
        for secret in ("Alpha draft", "Beta draft", "Tone Alpha", "Tone Beta", "alpha.project", "beta.mod",
                       '"answer_key"', '"mapping"', "alpha", "beta"):
            self.assertNotIn(secret, page, secret)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        self.assertNotRegex(page, r"<script[^>]+src=")
        self.assertNotRegex(page, r"<link[^>]+(stylesheet|href=\"http)")
        blob = re.search(r'<script id="answer" type="text/plain">([A-Za-z0-9+/=]+)</script>', page).group(1)
        secret = json.loads(base64.b64decode(blob).decode("utf-8"))
        key = json.loads((self.root / "out" / "comparison.json").read_text(encoding="utf-8"))["answer_key"]
        self.assertEqual({secret["x"]["version"], secret["y"]["version"]}, {"first", "second"})
        self.assertEqual(secret["x"]["version"], key["x"])
        self.assertEqual({secret["x"]["label"], secret["y"]["label"]}, set(self.labels))
        self.assertTrue(any(row["key"] == "ch0_notes" and row["channel"] == 0 for row in secret["metrics"]))

    def test_page_features_and_languages(self):
        self.build("english", seed=2)
        self.build("french", seed=2, language="fr")
        english = (self.root / "english" / "index.html").read_text(encoding="utf-8")
        french = (self.root / "french" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="en"', english)
        self.assertIn('<html lang="fr"', french)
        self.assertIn("Submit and reveal", english)
        self.assertIn("Valider et révéler", french)
        for needle in ('id="player-x"', 'id="player-y"', 'value="x"', 'value="y"', 'value="none"',
                       "r-melody-x", "r-groove-y", "r-palette-x", "r-arrangement-y", 'id="comment"',
                       "new Blob", "localStorage", "chiploom.comparison-result.v1"):
            self.assertIn(needle, english, needle)
        # Both languages ship in every page so the listener can switch.
        self.assertIn("Valider et r\\u00e9v\\u00e9ler", english)
        for sentence in ("Download result JSON",):
            self.assertIn(sentence, english)

    def test_inline_script_is_syntactically_valid(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js unavailable")
        self.build(seed=2)
        page = (self.root / "out" / "index.html").read_text(encoding="utf-8")
        script = re.findall(r"<script>(.*?)</script>", page, re.S)[-1]
        path = self.root / "page.js"
        path.write_text(script, encoding="utf-8")
        check = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)

    def test_excerpt_seconds_are_forwarded_and_shown(self):
        self.build(seed=1, seconds=0.5)
        self.assertEqual([call["seconds"] for call in fake_render.calls], [0.5, 0.5])
        page = (self.root / "out" / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-seconds="0.5"', page)

    def test_sources_are_never_modified(self):
        before = {path.name: sha(path) for path in self.sources.iterdir()}
        self.build(seed=1)
        # Also when the bundle is placed beside the sources.
        with patch("tracker4agents.compare.audio.render", side_effect=fake_render):
            create_comparison(self.first, self.second, self.sources / "compare", labels=self.labels, seed=1)
        self.assertEqual({path.name: sha(path) for path in self.sources.iterdir() if path.is_file()}, before)

    def test_output_must_be_new_or_empty(self):
        existing = self.root / "existing"
        existing.mkdir()
        (existing / "keep.txt").write_text("precious", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.build("existing", seed=1)
        self.assertEqual((existing / "keep.txt").read_text(encoding="utf-8"), "precious")
        self.assertEqual(fake_render.calls, [])
        empty = self.root / "empty"
        empty.mkdir()
        self.build("empty", seed=1)
        self.assertTrue((empty / "index.html").is_file())
        file_path = self.root / "a_file"
        file_path.write_text("x", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.build("a_file", seed=1)
        with self.assertRaises(ValidationError):  # The sources' own directory is not empty.
            with patch("tracker4agents.compare.audio.render", side_effect=fake_render):
                create_comparison(self.first, self.second, self.sources)

    def test_failed_render_leaves_nothing_behind(self):
        def failing(source, output, *args, **kwargs):
            if Path(source).name == "y.mod":
                raise audio.RenderError("boom")
            return fake_render(source, output, *args, **kwargs)
        with patch("tracker4agents.compare.audio.render", side_effect=failing):
            with self.assertRaises(audio.RenderError):
                create_comparison(self.first, self.second, self.root / "broken", seed=1)
        self.assertFalse((self.root / "broken").exists())
        self.assertFalse(list(self.root.glob(".chiploom-compare-*")))

    def test_input_validation(self):
        bad = [dict(language="de"), dict(seconds=0), dict(seconds=121), dict(seconds=float("nan")),
               dict(labels=("Same", "Same")), dict(labels=("", "B")), dict(labels=("only one",))]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                with patch("tracker4agents.compare.audio.render", side_effect=fake_render):
                    create_comparison(self.first, self.second, self.root / "bad", **kwargs)
        with self.assertRaises(ValidationError):
            create_comparison(self.first, self.first, self.root / "bad")
        self.assertFalse((self.root / "bad").exists())

    def test_default_labels_come_from_file_names(self):
        with patch("tracker4agents.compare.audio.render", side_effect=fake_render):
            result = create_comparison(self.first, self.second, self.root / "named", seed=4, show_answer=True)
        self.assertEqual(set(result["answer_key"]["labels"].values()), {"alpha", "beta"})

    def test_cycle_longer_than_the_render_limit_is_refused_unless_an_excerpt_is_requested(self):
        long_pattern = Pattern()
        long_pattern.put(0, 0, cell("C-2", 1))
        long = Module("Long", [Sample("Sine", SINE, 64, loop_length=64)], [long_pattern], [0] * 16)
        long_path = self.sources / "long.mod"
        long_path.write_bytes(mod.encode(long))
        with self.assertRaises(ValidationError) as caught, patch("tracker4agents.compare.audio.render", side_effect=fake_render):
            create_comparison(long_path, self.second, self.root / "long")
        self.assertIn("seconds", str(caught.exception))
        self.assertFalse((self.root / "long").exists())
        self.assertEqual(fake_render.calls, [])
        with patch("tracker4agents.compare.audio.render", side_effect=fake_render):
            create_comparison(long_path, self.second, self.root / "long", seconds=2.0)
        self.assertEqual([call["seconds"] for call in fake_render.calls], [2.0, 2.0])


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg indisponible")
class RealAudioComparisonTests(ComparisonFixtureCase):
    def test_real_render_and_mp3_copies(self):
        result = create_comparison(self.first, self.second, self.root / "real", mp3=True,
                                   labels=self.labels, seed=7, language="fr")
        out = self.root / "real"
        for side in ("x", "y"):
            metrics = audio.analyze_wav(out / f"{side}.wav")
            self.assertAlmostEqual(metrics["duration_seconds"], 0.96, places=2)
            self.assertGreater(metrics["peak"], 0.01)
            self.assertGreater((out / f"{side}.mp3").stat().st_size, 500)
            self.assertEqual(result[side]["mp3"], str(out / f"{side}.mp3"))
        key = json.loads((out / "comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(key["versions"]["x"]["render"]["audio"]["sha256"], sha(out / "x.wav"))
        self.assertIsNotNone(key["versions"]["y"]["optional_mp3"])
        self.assertNotIn("output", key["versions"]["y"]["optional_mp3"])
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Alpha draft", page)
        # Different notes mean different rendered audio.
        self.assertNotEqual(sha(out / "x.wav"), sha(out / "y.wav"))

    def test_example_project_against_a_variant(self):
        example = ROOT / "examples" / "pixel_rush.project.json"
        variant = project.load(example)
        variant.metadata = {**variant.metadata, "note": "variant"}
        variant_path = self.sources / "pixel_variant.project.json"
        project.write_json(variant_path, project.to_dict(variant))
        before = sha(example)
        result = create_comparison(example, variant_path, self.root / "pixel", seconds=3.0, seed=2)
        self.assertEqual(sha(example), before)
        self.assertAlmostEqual(audio.analyze_wav(self.root / "pixel" / "x.wav")["duration_seconds"], 3.0, places=2)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
