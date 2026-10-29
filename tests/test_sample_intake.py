"""Managing a bank one sample at a time: active bank, slots of a song, WAV files, tuning and its corrections."""
from __future__ import annotations

import io
import json
import math
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from tracker4agents import cli, mod, project, sample_intake, xm
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell
from tracker4agents.sample_library import SampleLibrary

SQUARE = (60,) * 32 + (-60,) * 32   # one 64-frame cycle


def run(*argv: str) -> dict:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return json.loads(out.getvalue() or err.getvalue()) | {"exit": code}


def tuned_song() -> Module:
    """An XM whose bass sample is written a semitone sharp of its lead (relative note +1)."""
    module = xm.blank("Tuned", channels=4, metadata={"sample_source": "library"})
    module.samples = [Sample("lead", SQUARE, 64, 0, 0, 64), Sample("bass", SQUARE, 64, 0, 0, 64, relative_note=-23)]
    for row in range(0, 64, 4):
        module.patterns[0].put(row, 0, cell(("C-5", "E-5", "G-5", "A-5", "D-5")[row // 4 % 5], 1, fmt="xm"))
        module.patterns[0].put(row, 1, cell(("C-4", "F-4", "G-4", "A-4", "E-4")[row // 4 % 5], 2, fmt="xm"))
    return module


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.saved = {key: os.environ.get(key) for key in ("CHIPLOOM_HOME", "CHIPLOOM_BANK")}
        os.environ["CHIPLOOM_HOME"] = str(self.folder / "home")
        os.environ.pop("CHIPLOOM_BANK", None)
        self.bank = SampleLibrary(self.folder / "bank")

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_the_active_bank_is_shared_and_remembered(self):
        result = run("samples", "bank", "--new", str(self.folder / "mine"))
        self.assertTrue(result["ok"])
        self.assertEqual(Path(sample_intake.active_library()), (self.folder / "mine").resolve())
        self.assertEqual(run("samples", "bank")["entries"], 0)
        other = self.folder / "other"
        sample_intake.set_active_library(other)
        self.assertEqual(sample_intake.recent_libraries()[:2], [str(other.resolve()), str((self.folder / "mine").resolve())])
        os.environ["CHIPLOOM_BANK"] = str(self.folder / "env")
        self.assertEqual(sample_intake.active_library(), (self.folder / "env").resolve())
        (self.folder / "busy").mkdir()
        (self.folder / "busy" / "file.txt").write_text("x")
        with self.assertRaises(ValidationError):
            sample_intake.set_active_library(self.folder / "busy")

    def test_a_song_slot_enters_the_bank_with_the_owners_labels_once(self):
        song = tuned_song()
        listing = sample_intake.song_slots(song, self.bank)
        self.assertEqual([row["slot"] for row in listing["slots"]], [1, 2])
        self.assertEqual(listing["slots"][1]["tuning"]["written_c_sounds"], "C#")
        result = sample_intake.add_from_song(self.bank, song, 2, "tuned.xm", name="Fat bass", role="bass",
                                             tags=["warm"])
        entry = result["entry"]
        self.assertTrue(result["created"])
        self.assertEqual((entry["name"], entry["role"], entry["role_source"]), ("Fat bass", "bass", "owner"))
        self.assertEqual(entry["source"], {"file": "tuned.xm", "slot": 2, "name": "bass"})
        self.assertIn("warm", entry["tags"])
        self.assertEqual((entry["format_origin"], entry["relative_note"]), ("xm", -23))
        again = sample_intake.add_from_song(self.bank, song, 2, "tuned.xm")
        self.assertFalse(again["created"])
        self.assertEqual(again["id"], entry["id"])
        self.assertEqual(sample_intake.song_slots(song, self.bank)["slots"][1]["in_bank"], entry["id"])
        scored = sample_intake.add_from_song(self.bank, song, 1, "tuned.xm")["entry"]
        self.assertEqual((scored["name"], scored["role_source"]), ("lead", "song"))

    def test_a_wav_becomes_an_xm_sample_playing_at_its_own_rate(self):
        path = self.folder / "tone.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            handle.writeframes(b"".join(struct.pack("<hh", int(9000 * math.sin(2 * math.pi * 440 * i / 22050)),
                                                    -int(9000 * math.sin(2 * math.pi * 440 * i / 22050)) // 3)
                                        for i in range(2205)))
        result = run("samples", "import-wav", str(path), "--library", str(self.bank.path), "--role", "lead",
                     "--loop-length", "2200")
        entry = result["entry"]
        self.assertEqual((entry["bits"], entry["loop_length"], entry["name"], entry["role"]), (16, 2200, "tone", "lead"))
        rate = 8363 * 2 ** ((entry["relative_note"] * 128 + entry["finetune"]) / 1536)
        self.assertAlmostEqual(rate, 22050, delta=22050 * 0.001)
        self.assertEqual(result["tuning"]["written_c_sounds"], "A")
        with self.assertRaises(ValidationError):
            sample_intake.read_wav(self.folder / "tone.wav", loop_start=2000, loop_length=500)

    def test_a_tuning_correction_is_kept_and_applied_on_insertion(self):
        entry = sample_intake.add_from_song(self.bank, tuned_song(), 1, "tuned.xm")["entry"]
        self.bank.edit(entry["id"], retune={"semitones": 12, "cents": 20})
        self.assertEqual(self.bank.get(entry["id"])["retune"], {"semitones": 12, "cents": 20})
        blank = xm.blank("Into", channels=4, metadata={"sample_source": "library"})
        module, info = self.bank.insert(blank, entry["id"])
        self.assertEqual((module.samples[0].relative_note, module.samples[0].finetune), (12, 26))
        self.assertEqual(info["retune"]["transpose_notes"], 0)
        mod_song = Module("Into", [Sample("", ())], [Pattern()], [0], metadata={"sample_source": "library"})
        module, info = self.bank.insert(mod_song, entry["id"], adapt=True)
        self.assertEqual(info["retune"]["transpose_notes"], 12)       # a MOD sample cannot hold the octave
        self.bank.edit(entry["id"], retune={"semitones": 0, "cents": 0})
        self.assertIsNone(self.bank.get(entry["id"])["retune"])
        with self.assertRaises(ValidationError):
            self.bank.edit(entry["id"], retune={"semitones": 60, "cents": 0})

    def test_a_palette_with_a_bass_tuned_a_semitone_off_is_found_and_retuned(self):
        source = self.folder / "tuned.xm"
        source.write_bytes(xm.encode(tuned_song()))
        self.bank.extract(source)
        blank = self.folder / "blank.json"
        project.write_json(blank, project.to_dict(xm.blank("Blank", channels=4, metadata={"sample_source": "library"})))
        result = run("samples", "use-palette", "PAL-0001", str(blank), "--output", str(self.folder / "out.json"),
                     "--library", str(self.bank.path), "--retune")
        tuning = result["tuning"]
        self.assertFalse(tuning["consistent"])
        off = [row for row in tuning["entries"] if not row["in_tune"]]
        self.assertEqual(len(off), 1)
        self.assertEqual(off[0]["retune_relative_note"], -1)
        out = project.load(self.folder / "out.json")
        retuned = result["retuned"][0]
        self.assertEqual(out.samples[retuned["slot"] - 1].relative_note, -24)
        again = sample_intake.song_slots(out)["slots"]
        self.assertEqual({row["tuning"]["written_c_sounds"] for row in again}, {"C"})

    def test_relabel_gives_older_entries_their_source_names(self):
        source = self.folder / "song.mod"
        song = Module("Song", [Sample("warm pulse", SQUARE, 40, 0, 0, 64)], [Pattern()], [0])
        song.patterns[0].put(0, 0, cell("C-2", 1))
        source.write_bytes(mod.encode(song))
        self.bank.extract(source)
        manifest = project.read_json(self.bank.path / "library.json")   # an entry from before readable names
        manifest["samples"][0]["name"] = "Cycle Pulse 01"
        manifest["samples"][0].pop("source")
        project.write_json(self.bank.path / "library.json", manifest)
        result = sample_intake.relabel(self.bank)
        self.assertEqual((result["renamed"], result["sources_added"]), (1, 1))
        self.assertEqual(self.bank.get("SMP-0001")["name"], "warm pulse")
        self.bank.edit("SMP-0001", name="Mine")
        self.assertEqual(sample_intake.relabel(self.bank)["renamed"], 0)


if __name__ == "__main__":
    unittest.main()
