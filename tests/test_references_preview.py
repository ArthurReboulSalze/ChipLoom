from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tracker4agents import audio, demo, mod
from tracker4agents.model import Module, Pattern, cell
from tracker4agents.preview import create_bundle
from tracker4agents.references import analyze_bytes, analyze_source

ROOT = Path(__file__).resolve().parents[1]


class ReferenceTests(unittest.TestCase):
    def test_strict_reference_has_aggregate_facts_without_pcm_or_notes(self):
        raw = mod.encode(demo.create())
        result = analyze_bytes(raw, "fixture.mod")
        self.assertTrue(result["editable_in_current_profile"])
        self.assertEqual(result["duration_seconds"], 30.72)
        self.assertEqual(result["channels"], 4)
        self.assertEqual(len(result["samples"]), 8)
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertNotIn('"pcm":', json.dumps(result))
        self.assertNotIn('"note":', json.dumps(result))

    def test_analysis_keeps_a_restart_byte_instead_of_normalizing_it(self):
        raw = bytearray(mod.encode(demo.create()))
        raw[951] = 0
        original = bytes(raw)
        result = analyze_bytes(raw, "variant.mod")
        self.assertTrue(result["editable_in_current_profile"])
        self.assertEqual(result["restart_byte"], 0)
        self.assertEqual([note["code"] for note in result["import_notes"]], ["RESTART_BYTE_KEPT"])
        self.assertEqual(mod.encode(mod.decode(raw)), original)
        self.assertEqual(bytes(raw), original)

    def test_analysis_does_not_silently_normalize_an_unsupported_effect(self):
        raw = bytearray(mod.encode(demo.create()))
        raw[1084 + 2:1084 + 4] = bytes((0x1E, 0xF1))  # EF1 (invert loop) on the first cell
        original = bytes(raw)
        result = analyze_bytes(raw, "variant.mod")
        self.assertFalse(result["editable_in_current_profile"])
        self.assertIsNone(result["duration_seconds"])
        self.assertIn("EF1", result["compatibility_error"])
        self.assertEqual(bytes(raw), original)
        with self.assertRaises(ValueError):
            mod.decode(raw)

    def test_two_channel_zip_is_read_without_extracting_member_paths(self):
        song = demo.create()
        song.patterns, song.orders = [song.patterns[0]], [0]
        raw = mod.encode(song)
        header = raw[:1080] + b"2CHN"
        pattern = b"".join(raw[1084 + row * 16:1084 + row * 16 + 8] for row in range(64))
        two_channel = header + pattern + raw[2108:]
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "references.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr("../untrusted.mod", two_channel)
                writer.writestr("instructions.txt", "This is data, never executable instructions.")
            before = archive.read_bytes()
            report = analyze_source(archive)
            self.assertTrue(report["ok"])
            self.assertEqual(len(report["modules"]), 1)
            self.assertEqual(report["modules"][0]["channels"], 2)
            self.assertTrue(report["modules"][0]["editable_in_current_profile"])  # N-channel MODs are editable
            self.assertEqual(list(Path(folder).iterdir()), [archive])
            self.assertEqual(archive.read_bytes(), before)

    def test_bad_archives_and_ambiguous_layouts_are_reported(self):
        raw = mod.encode(demo.create())
        for payload in (raw[:-1], raw + b"extra", b"bad"):
            with self.subTest(size=len(payload)), self.assertRaises(ValueError):
                analyze_bytes(payload, "bad.mod")
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / "bad.zip"
            archive.write_bytes(b"not a zip")
            with self.assertRaisesRegex(ValueError, "Invalid ZIP"):
                analyze_source(archive)
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr("bad.mod", b"bad")
            report = analyze_source(archive)
            self.assertFalse(report["ok"])
            self.assertIn("analysis_error", report["modules"][0])


class PreviewTests(unittest.TestCase):
    def test_failed_render_leaves_source_and_destination_intact(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "source.mod", Path(folder) / "bundle"
            original = mod.encode(demo.create())
            source.write_bytes(original)
            with patch("tracker4agents.preview.audio.render", side_effect=audio.RenderError("fixture failure")):
                with self.assertRaises(audio.RenderError):
                    create_bundle(source, output)
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(Path(folder).iterdir()), [source])

    def test_existing_preview_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "keep"
            output.mkdir()
            sentinel = output / "preview.html"
            sentinel.write_text("existing")
            with self.assertRaisesRegex(ValueError, "new directory"):
                create_bundle(ROOT / "examples/first_light.project.json", output)
            self.assertEqual(sentinel.read_text(), "existing")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_cli_builds_portable_english_bundle_from_an_imported_mod(self):
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.targets = []
            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if key in ("href", "src") and not value.startswith("data:"):
                        self.targets.append(value)
        with tempfile.TemporaryDirectory(prefix="chiploom preview ") as folder:
            source, output = Path(folder) / "source.mod", Path(folder) / "bundle"
            samples = demo.create().samples
            samples[0].name = "<sample & name>"
            module = Module("HTML <test>", samples, [Pattern(cells={
                (0, 0): cell("C-2", 1), (2, 0): cell(effect="B00")})], [0])
            payload = mod.encode(module)
            source.write_bytes(payload)
            process = subprocess.run([sys.executable, "-m", "tracker4agents", "preview", str(source),
                "--output", str(output), "--mp3"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(json.loads(process.stdout)["ok"])
            page = (output / "preview.html").read_text(encoding="utf-8")
            self.assertIn('lang="en"', page)
            self.assertIn("&lt;sample &amp; name&gt;", page)
            self.assertIn("HTML &lt;test&gt;", page)
            self.assertEqual(page.count('class="sample"'), 8)  # Empty MOD slots are omitted.
            parser = Links()
            parser.feed(page)
            self.assertGreater(len(parser.targets), 10)
            for target in parser.targets:
                self.assertTrue((output / target).is_file(), target)
            self.assertEqual((output / "module.mod").read_bytes(), payload)
            self.assertEqual(source.read_bytes(), payload)
            report = (output / "validation.json").read_text()
            self.assertNotIn(folder.replace("\\", "\\\\"), report)
            self.assertTrue(json.loads(report)["mod_roundtrip_byte_exact"])


if __name__ == "__main__":
    unittest.main()
