"""Articulation norms: durations and proportions measured on reference modules, never notes or patterns."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest
import zipfile

from tracker4agents import cli, formats, xm
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell
from tracker4agents.norms import measure, norms

ROOT = Path(__file__).resolve().parents[1]
LOOP = (0, 40, 80, 40, 0, -40, -80, -40) * 4


def mod_song() -> Module:
    """Channel 0: an arpeggio struck every 4 rows (3 rows of 037, then a C00 cut); channel 1: one held note."""
    pattern = Pattern()
    for row in range(0, 64, 4):
        pattern.put(row, 0, cell("A-2", 1, "037"))
        pattern.put(row + 1, 0, cell(None, 0, "037"))
        pattern.put(row + 2, 0, cell(None, 0, "037"))
        pattern.put(row + 3, 0, cell(None, 0, "C00"))
    pattern.put(0, 1, cell("C-2", 1))
    return Module("Norms", [Sample("Loop", LOOP, 64, 0, 0, len(LOOP))], [pattern], [0])


class MeasureTests(unittest.TestCase):
    def test_runs_notes_and_endings_of_a_struck_arpeggio(self):
        result = measure(mod_song())
        self.assertEqual(set(result["arpeggio_run_rows"]), {3})              # every hit keeps 037 for three rows
        self.assertEqual(len(result["arpeggio_run_rows"]), 16)
        self.assertEqual(set(result["arpeggio_run_ticks"]), {18})            # 3 rows at speed 6
        self.assertAlmostEqual(result["arpeggio_run_seconds"][0], 0.36, places=3)
        self.assertEqual(result["note_endings"]["cut"], round(16 / 17, 4))   # 16 cut hits, the held note ends with the song
        held = max(result["note_seconds"])
        self.assertAlmostEqual(held, 7.68, places=2)
        arpeggio_channel = result["channel_measures"][0]
        self.assertEqual(arpeggio_channel["arpeggio_note_share"], 1.0)
        self.assertEqual(result["channel_measures"][1]["arpeggio_note_share"], 0.0)

    def test_nothing_identifies_the_notes(self):
        text = json.dumps(measure(mod_song()))
        for note in ("A-2", "C-2", "037"):
            self.assertNotIn(note, text)

    def test_xm_key_offs_end_notes(self):
        module = xm.blank("Norms XM", channels=2)
        module.samples[0] = Sample("Loop", LOOP, 64, 0, 0, len(LOOP))
        module.patterns[0].put(0, 0, cell("C-4", 1, "000", "xm"))
        module.patterns[0].put(8, 0, cell("===", 0, "000", "xm"))
        result = measure(module)
        self.assertEqual(result["note_endings"]["key_off"], 1.0)
        self.assertAlmostEqual(result["note_seconds"][0], 8 * 6 * 2.5 / 125, places=3)


class AggregateTests(unittest.TestCase):
    def test_files_folders_and_zips_are_read_and_unreadable_ones_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "one.mod").write_bytes(formats.encode(mod_song()))
            (folder / "broken.mod").write_bytes(b"not a module")
            with zipfile.ZipFile(folder / "set.zip", "w") as archive:
                archive.writestr("inside/two.mod", formats.encode(mod_song()))
                archive.writestr("readme.txt", "ignored")
            result = norms([folder], details=True)
            self.assertEqual(result["modules"]["measured"], 2)
            self.assertEqual(sum(result["modules"]["skipped"].values()), 1)
            self.assertEqual(result["arpeggio"]["run_rows"]["p50"], 3)
            self.assertEqual([item["file"] for item in result["details"]], ["one.mod", "set.zip/inside/two.mod"])
            published = norms([folder])
            self.assertNotIn("details", published)
            self.assertNotIn("one.mod", json.dumps(published))                # the aggregate names no file
            with self.assertRaises(ValidationError):
                norms([folder / "missing"])

    def test_the_published_demos_measure_and_the_cli_writes_json(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "norms.json"
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["norms", str(ROOT / "docs/listen/media"), "--output", str(output)])
            self.assertEqual(code, 0, err.getvalue())
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(written["modules"]["formats"], {"xm": 1, "mod": 2})
            for key in ("arpeggio", "notes", "channels", "tempo"):
                self.assertIn(key, written)


if __name__ == "__main__":
    unittest.main()
