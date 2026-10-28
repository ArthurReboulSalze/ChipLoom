"""Instruments: validation, the instrument folder, capturing from a song, applying with the patch operation, the CLI."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from tracker4agents import instruments, mod, project, sample_tools, synth
from tracker4agents.cli import main
from tracker4agents.document import Document
from tracker4agents.errors import error_code
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell, validate
from tracker4agents.patch import apply_ops, pattern_grid
from tracker4agents.sample_library import SampleLibrary
from tracker4agents.sample_source import SampleSourceError

WAVE = (0, 40, 80, 120, 80, 40, 0, -40, -80, -120, -80, -40) * 4
PLUCK = {"name": "Pluck bass", "role": "bass", "tags": ["pluck", "bass"], "volume": 44,
         "phrase": ["000", "C30", "C20", "C10"],
         "sample": {"kind": "recipe", "recipe": {"type": "wave", "shape": "triangle", "frequency": 130.81}}}


def song(source: str | None = None) -> Module:
    module = Module("Inst", [Sample("Pulse", WAVE, 40, 0, 0, len(WAVE))], [Pattern("A")], [0])
    if source:
        module.metadata["sample_source"] = source
    return module


def apply(module: Module, **fields) -> dict:
    op = {"op": "apply_instrument", "pattern": 0, "channel": 1, "row": 4, "note": "C-2", "instrument": PLUCK}
    return apply_ops(module, [{**op, **fields}])[0]


def grid(module: Module, row: int, channel: int = 1) -> str:
    return pattern_grid(module, 0, row, 1)[0].split(" | ")[1 + channel]


def code_of(test: unittest.TestCase, module: Module, kind=ValidationError, **fields) -> str:
    with test.assertRaises(kind) as caught:
        apply(module, **fields)
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


class ValidationTests(unittest.TestCase):
    def test_a_valid_instrument_is_normalized(self):
        data = instruments.normalize({**PLUCK, "phrase": ["...", "c30", " 047 ", "---"], "tags": ["b", "a", "a"]})
        self.assertEqual(data["phrase"], ["000", "C30", "047", "000"])
        self.assertEqual(data["tags"], ["a", "b"])
        self.assertEqual((data["schema"], data["finetune"]), (instruments.SCHEMA, 0))
        self.assertEqual(instruments.normalize({"name": "X", "sample": PLUCK["sample"]})["volume"], 40)

    def test_phrase_errors(self):
        for phrase in (["F06"], ["B00"], ["D10"], ["80A"], ["C65"], ["C2"], ["zzz"], [20], ["000"] * 33, "C20"):
            with self.assertRaises(ValidationError, msg=phrase) as caught:
                instruments.normalize({**PLUCK, "phrase": phrase})
            self.assertEqual(caught.exception.code, "INSTRUMENT_INVALID", phrase)
        self.assertEqual(len(instruments.normalize({**PLUCK, "phrase": ["000"] * 32})["phrase"]), 32)

    def test_other_field_errors(self):
        cases = [({"volume": 65}, "INSTRUMENT_INVALID"), ({"finetune": 8}, "INSTRUMENT_INVALID"),
                 ({"name": ""}, "INSTRUMENT_INVALID"), ({"name": "x" * 23}, "INSTRUMENT_INVALID"),
                 ({"name": "Café"}, "INSTRUMENT_INVALID"), ({"role": "tuba"}, "INSTRUMENT_INVALID"),
                 ({"tags": ["Bad Tag"]}, "INSTRUMENT_INVALID"), ({"id": "X-1"}, "INSTRUMENT_INVALID"),
                 ({"colour": 1}, "UNKNOWN_FIELD"), ({"schema": "other"}, "INSTRUMENT_INVALID"),
                 ({"sample": {"kind": "wave"}}, "INSTRUMENT_INVALID"),
                 ({"sample": {"kind": "library", "library_id": "nope"}}, "INSTRUMENT_INVALID"),
                 ({"sample": {"kind": "recipe", "recipe": {"type": "nope"}}}, "RECIPE_INVALID"),
                 ({"sample": {"kind": "recipe", "recipe": {"type": "kick"}, "x": 1}}, "INSTRUMENT_INVALID")]
        for change, code in cases:
            with self.assertRaises(ValidationError, msg=change) as caught:
                instruments.normalize({**PLUCK, **change})
            self.assertEqual(error_code(caught.exception), code, change)
        pcm = sample_tools.pcm_fields(WAVE)
        good = {"kind": "pcm", **pcm}
        self.assertEqual(instruments.normalize({**PLUCK, "sample": good})["sample"]["loop_length"], len(WAVE))
        with self.assertRaises(ValidationError) as caught:
            instruments.normalize({**PLUCK, "sample": {**good, "pcm_sha256": "0" * 64}})
        self.assertEqual(caught.exception.code, "SAMPLE_PCM_HASH")
        with self.assertRaises(ValidationError):
            instruments.normalize({**PLUCK, "sample": {**good, "origin": {"colour": 1}}})


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = instruments.InstrumentLibrary(Path(self.temporary.name) / "instruments")

    def tearDown(self):
        self.temporary.cleanup()

    def test_save_show_list_delete(self):
        first = self.folder.save(PLUCK)
        second = self.folder.save({**PLUCK, "name": "Kick", "role": "kick", "tags": ["drum"],
                                   "sample": {"kind": "recipe", "recipe": {"type": "kick"}}})
        self.assertEqual((first["id"], second["id"]), ("INS-0001", "INS-0002"))
        self.assertEqual(self.folder.get("INS-0001"), first)
        listing = self.folder.list()
        self.assertEqual([item["id"] for item in listing["instruments"]], ["INS-0001", "INS-0002"])
        self.assertEqual(listing["instruments"][0]["sample"]["recipe"]["shape"], "triangle")
        self.assertEqual(self.folder.list(query="kick")["total"], 1)
        self.assertEqual(self.folder.list(tags=["drum"])["instruments"][0]["name"], "Kick")
        self.assertEqual(self.folder.list(role="bass")["total"], 1)
        self.assertEqual(self.folder.list(query="nothing")["total"], 0)
        self.assertEqual(self.folder.list(limit=1, offset=1)["instruments"][0]["id"], "INS-0002")
        self.assertEqual(self.folder.delete("INS-0001")["deleted"], "INS-0001")
        self.assertEqual(self.folder.save(PLUCK)["id"], "INS-0003")  # ids are not recycled below the highest
        with self.assertRaises(ValidationError) as caught:
            self.folder.get("INS-0001")
        self.assertEqual(caught.exception.code, "INSTRUMENT_NOT_FOUND")

    def test_ids_and_replacement(self):
        saved = self.folder.save({**PLUCK, "id": "INS-0042"})
        self.assertEqual(saved["id"], "INS-0042")
        with self.assertRaises(ValidationError) as caught:
            self.folder.save({**PLUCK, "id": "INS-0042"})
        self.assertEqual(caught.exception.code, "INSTRUMENT_EXISTS")
        replaced = self.folder.save({**PLUCK, "id": "INS-0042", "name": "Renamed"}, replace=True)
        self.assertEqual(self.folder.get("INS-0042")["name"], replaced["name"])
        self.assertEqual(self.folder.save(PLUCK)["id"], "INS-0043")
        for bad in ("../x", "INS-1", "nope", 5):
            with self.assertRaises(ValidationError) as caught:
                self.folder.get(bad)
            self.assertEqual(caught.exception.code, "INSTRUMENT_NOT_FOUND")

    def test_a_damaged_file_is_reported_not_fatal(self):
        self.folder.save(PLUCK)
        (self.folder.path / "INS-0009.json").write_text("{not json", encoding="utf-8")
        listing = self.folder.list()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["invalid"][0]["id"], "INS-0009")

    def test_the_default_folder_is_ignored_by_git(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(instruments.DEFAULT_LIBRARY, Path("exports/instruments"))
        self.assertIn("exports/", (root / ".gitignore").read_text(encoding="utf-8").splitlines())


class ApplyTests(unittest.TestCase):
    def test_note_phrase_and_sample(self):
        module = song()
        result = apply(module)
        self.assertEqual((result["slot"], result["slot_reused"], result["rows_written"], result["stopped"]),
                         (2, False, [4, 5, 6, 7], "phrase_end"))
        self.assertEqual([grid(module, row) for row in range(4, 9)],
                         ["C-2 02 ...", "--- -- C30", "--- -- C20", "--- -- C10", "--- -- ..."])
        sample = module.samples[1]
        self.assertEqual((sample.name, sample.volume, sample.finetune), ("Pluck bass", 44, 0))
        self.assertEqual(sample.recipe["shape"], "triangle")
        self.assertEqual(module.metadata["sample_sources"]["2"]["origin"], "synthesized")
        validate(module)

    def test_phrase_stops_at_the_next_note_length_and_pattern_end(self):
        module = song()
        module.patterns[0].put(6, 1, cell("E-2", 1))
        result = apply(module)
        self.assertEqual((result["rows_written"], result["stopped"]), ([4, 5], "next_note"))
        self.assertEqual(grid(module, 6), "E-2 01 ...")
        module = song()
        result = apply(module, length=2)
        self.assertEqual((result["rows_written"], result["stopped"]), ([4, 5], "length"))
        self.assertEqual(grid(module, 6), "--- -- ...")
        module = song()
        result = apply(module, row=62)
        self.assertEqual((result["rows_written"], result["stopped"]), ([62, 63], "end_of_pattern"))
        module = song()
        self.assertEqual(apply(module, length=40)["rows_written"], [4, 5, 6, 7])  # never past the phrase

    def test_other_channels_and_samples_in_between_are_left_alone(self):
        module = song()
        module.patterns[0].put(5, 0, cell("G-2", 1))
        module.patterns[0].put(6, 1, cell(None, 1, "000"))  # a sample change without a note
        apply(module)
        self.assertEqual(grid(module, 5, 0), "G-2 01 ...")
        self.assertEqual(grid(module, 6), "--- 01 C20")

    def test_existing_effects_are_kept_unless_overwrite(self):
        module = song()
        module.patterns[0].put(5, 1, cell(None, 0, "A03"))
        module.patterns[0].put(6, 1, cell(None, 0, "F06"))
        result = apply(module)
        self.assertEqual([item["row"] for item in result["skipped"]], [5, 6])
        self.assertEqual((grid(module, 5), grid(module, 6), grid(module, 7)), ("--- -- A03", "--- -- F06", "--- -- C10"))
        result = apply(module, overwrite=True)
        self.assertEqual((grid(module, 5), grid(module, 6)), ("--- -- C30", "--- -- F06"))  # timing is never replaced
        self.assertEqual([item["row"] for item in result["skipped"]], [6])
        self.assertIn("never replaced", result["skipped"][0]["reason"])

    def test_a_zero_phrase_row_never_clears_an_effect(self):
        module = song()
        module.patterns[0].put(4, 1, cell("C-3", 1, "F06"))
        apply(module)
        self.assertEqual(grid(module, 4), "C-2 02 F06")

    def test_an_identical_sample_is_reused_and_a_different_one_is_not(self):
        module = song()
        apply(module)
        again = apply(module, row=16)
        self.assertEqual((again["slot"], again["slot_reused"], len(module.samples)), (2, True, 2))
        louder = {**PLUCK, "volume": 50}
        other = apply(module, row=24, instrument=louder)
        self.assertEqual((other["slot"], other["slot_reused"], len(module.samples)), (3, False, 3))
        # Explicit slot: reused when identical, replace needed when another sound sits there.
        self.assertTrue(apply(module, row=32, slot=2)["slot_reused"])
        self.assertEqual(code_of(self, module, row=40, slot=1), "SAMPLE_SLOT")
        apply(module, row=40, slot=1, replace=True)
        self.assertEqual(module.samples[0].name, "Pluck bass")
        self.assertEqual(code_of(self, song(), slot=5), "SAMPLE_SLOT")

    def test_free_slots_are_reused_before_the_song_grows(self):
        module = song()
        module.samples.append(Sample("", (), 0, 0, 0, 0))
        self.assertEqual(apply(module)["slot"], 2)
        full = Module("Full", [Sample(f"S{index}", WAVE, 40, 0, 0, len(WAVE)) for index in range(31)],
                      [Pattern()], [0])
        self.assertEqual(code_of(self, full), "SAMPLE_SLOT")

    def test_argument_errors(self):
        self.assertEqual(code_of(self, song(), note="H-2"), "NOTE_UNKNOWN")
        self.assertEqual(code_of(self, song(), note="---"), "NOTE_UNKNOWN")
        self.assertEqual(code_of(self, song(), note=None), "NOTE_UNKNOWN")
        self.assertEqual(code_of(self, song(), row=64), "INTEGER_RANGE")
        self.assertEqual(code_of(self, song(), channel=4), "INTEGER_RANGE")
        self.assertEqual(code_of(self, song(), pattern=3), "INTEGER_RANGE")
        self.assertEqual(code_of(self, song(), length=0), "INTEGER_RANGE")
        self.assertEqual(code_of(self, song(), instrument="INS-0001", instruments="/nonexistent/folder"),
                         "INSTRUMENT_NOT_FOUND")
        self.assertEqual(code_of(self, song(), instrument=5), "PATCH_FIELD")
        self.assertEqual(code_of(self, song(), instrument={"name": "x"}), "INSTRUMENT_INVALID")
        self.assertEqual(code_of(self, song(), colour=1), "UNKNOWN_FIELD")
        with self.assertRaises(ValidationError) as caught:
            apply_ops(song(), [{"op": "apply_instrument", "pattern": 0, "channel": 1, "row": 4, "note": "C-2"}])
        self.assertEqual(caught.exception.code, "PATCH_FIELD")

    def test_lowercase_notes_are_accepted(self):
        module = song()
        apply(module, note="g#2")
        self.assertEqual(grid(module, 4), "G#2 02 ...")

    def test_stored_instruments_apply_by_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            saved = instruments.InstrumentLibrary(temporary).save(PLUCK)
            module = song()
            result = apply(module, instrument=saved["id"], instruments=temporary)
            self.assertEqual(result["instrument"], "INS-0001")
            self.assertEqual(module.metadata["sample_sources"]["2"]["instrument"], "INS-0001")

    def test_one_undoable_transaction_through_a_document(self):
        document = Document(song())
        before = project.to_dict(document.module)
        self.assertTrue(document.patch([{"op": "apply_instrument", "pattern": 0, "channel": 1, "row": 4,
                                         "note": "C-2", "instrument": PLUCK}])["changed"])
        self.assertEqual(len(document.module.samples), 2)
        document.undo()
        self.assertEqual(project.to_dict(document.module), before)
        with self.assertRaises(ValidationError):  # the second operation fails: the first is not kept either
            document.patch([{"op": "apply_instrument", "pattern": 0, "channel": 1, "row": 4, "note": "C-2",
                             "instrument": PLUCK}, {"op": "apply_instrument", "pattern": 0, "channel": 9,
                                                    "row": 4, "note": "C-2", "instrument": PLUCK}])
        self.assertEqual(project.to_dict(document.module), before)


class SourceRuleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        reference = root / "ref.mod"
        reference.write_bytes(mod.encode(Module("t", [Sample("a", (50, -50) * 8, 64, 0, 0, 16)],
                                                [Pattern(cells={(0, 0): cell("C-2", 1)})], [0])))
        self.bank = SampleLibrary(root / "bank")
        self.bank.extract(reference)
        self.library_instrument = {"name": "Bank tone", "volume": 30,
                                   "sample": {"kind": "library", "library_id": "SMP-0001"}, "phrase": ["047"]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_library_instruments_insert_the_exact_pcm_and_record_the_id(self):
        module = song("library")
        result = apply(module, instrument=self.library_instrument, library=str(self.bank.path))
        sample = module.samples[1]
        self.assertEqual((sample.pcm, sample.volume, sample.name), ((50, -50) * 8, 30, "Bank tone"))
        self.assertEqual(module.metadata["sample_sources"]["2"]["library_id"], "SMP-0001")
        self.assertEqual(grid(module, 4), "C-2 02 047")
        self.assertEqual(result["stopped"], "phrase_end")
        # The song now holds the sample: no bank is needed to place the instrument again.
        again = apply(module, row=20, instrument=self.library_instrument, library="/nonexistent")
        self.assertTrue(again["slot_reused"])
        # A missing bank is a clear error when the song does not hold it.
        self.assertEqual(code_of(self, song(), instrument=self.library_instrument, library="/nonexistent"),
                         "SAMPLE_LIBRARY")

    def test_declared_sources_are_respected(self):
        self.assertEqual(code_of(self, song("library"), SampleSourceError), "SAMPLE_SOURCE")  # a recipe
        self.assertEqual(code_of(self, song("synthesized"), SampleSourceError, instrument=self.library_instrument,
                                 library=str(self.bank.path)), "SAMPLE_SOURCE")
        drawn = {**PLUCK, "sample": {"kind": "pcm", **sample_tools.pcm_fields(WAVE)}}
        for declared in ("library", "synthesized"):
            self.assertEqual(code_of(self, song(declared), SampleSourceError, instrument=drawn), "SAMPLE_SOURCE")
        apply(song("mixed"), instrument=drawn)
        apply(song(), instrument=drawn)
        # PCM that came from a library sample is still a library sample for a library project.
        edited = {**PLUCK, "sample": {"kind": "pcm", **sample_tools.pcm_fields(WAVE),
                                      "origin": {"library_id": "SMP-0001", "edited": True}}}
        module = song("library")
        apply(module, instrument=edited)
        entry = module.metadata["sample_sources"]["2"]
        self.assertEqual((entry["library_id"], entry["edited"]), ("SMP-0001", True))
        self.assertEqual(code_of(self, song("synthesized"), SampleSourceError, instrument=edited), "SAMPLE_SOURCE")


class CaptureTests(unittest.TestCase):
    def test_from_a_recipe_slot(self):
        module = song()
        apply(module)
        data = instruments.from_slot(module, 2, "Captured", ["000", "c20"], tags=["mine"])
        self.assertEqual((data["sample"]["kind"], data["role"], data["volume"]), ("recipe", "bass", 44))
        self.assertEqual(data["phrase"], ["000", "C20"])
        self.assertEqual(data["sample"]["recipe"], module.samples[1].recipe)

    def test_from_library_edited_and_plain_slots(self):
        module = song()
        module.metadata["sample_sources"] = {"1": {"library_id": "SMP-0003", "origin": "module-extracted"}}
        data = instruments.from_slot(module, 1, "Bank")
        self.assertEqual(data["sample"], {"kind": "library", "library_id": "SMP-0003"})
        apply_ops(module, [{"op": "sample_gain", "slot": 1, "db": -2}])
        data = instruments.from_slot(module, 1, "Bank edited")
        self.assertEqual(data["sample"]["kind"], "pcm")
        self.assertEqual(data["sample"]["origin"], {"library_id": "SMP-0003", "edited": True})
        self.assertEqual(instruments.from_slot(module, 1, "Forced", embed=True)["sample"]["kind"], "pcm")
        plain = instruments.from_slot(song(), 1, "Plain")
        self.assertNotIn("origin", plain["sample"])
        derived = song()
        derived.samples[0] = synth.from_recipe("K", {"type": "kick"})
        apply_ops(derived, [{"op": "sample_gain", "slot": 1, "db": -2}])
        origin = instruments.from_slot(derived, 1, "Derived")["sample"]["origin"]
        self.assertEqual(origin, {"derived_from": "recipe", "recipe_type": "kick"})
        with self.assertRaises(ValidationError):
            instruments.from_slot(module, 9, "Nothing")
        with self.assertRaises(ValidationError):
            instruments.from_slot(module, 1, "Bad", ["F06"])

    def test_a_captured_instrument_applies_back_to_the_same_song(self):
        module = song()
        module.samples[0].volume = 33
        data = instruments.from_slot(module, 1, "Pulse again", ["C20"])
        result = apply(module, instrument=data)
        self.assertEqual((result["slot"], result["slot_reused"]), (1, True))  # only the name differs: same sound
        self.assertEqual(len(module.samples), 1)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.dir = Path(self.temporary.name)
        self.folder = self.dir / "instruments"
        project.write_json(self.dir / "song.json", project.to_dict(song()))

    def tearDown(self):
        self.temporary.cleanup()

    def test_save_list_show_apply_delete(self):
        code, out, err = run("instruments", "save", "--name", "Pluck bass", "--recipe",
                             json.dumps(PLUCK["sample"]["recipe"]), "--phrase", "000, c30 C20,C10", "--role", "bass",
                             "--tag", "pluck", "--volume", 44, "--dir", self.folder)
        self.assertEqual((code, err), (0, None), err)
        self.assertEqual(out["instrument"]["id"], "INS-0001")
        self.assertEqual(out["instrument"]["phrase"], ["000", "C30", "C20", "C10"])
        code, out, _ = run("instruments", "list", "--dir", self.folder, "--query", "pluck")
        self.assertEqual((code, out["total"]), (0, 1))
        code, out, _ = run("instruments", "show", "INS-0001", "--dir", self.folder)
        self.assertEqual(out["instrument"]["sample"]["recipe"]["shape"], "triangle")
        code, out, err = run("instruments", "apply", self.dir / "song.json", "--output", self.dir / "out.json",
                             "--instrument", "INS-0001", "--pattern", 0, "--channel", 1, "--row", 4, "--note", "C-2",
                             "--dir", self.folder)
        self.assertEqual((code, err), (0, None), err)
        self.assertEqual((out["applied"]["slot"], out["applied"]["rows_written"]), (2, [4, 5, 6, 7]))
        self.assertTrue(out["changes"][0].startswith("P00 r04 ch1: --- -- ... → C-2 02 ..."))
        self.assertIn("sample 02 changed", out["changes"])
        applied = project.load(self.dir / "out.json")
        self.assertEqual(applied.patterns[0].get(5, 1).effect, "C30")
        self.assertEqual(len(project.load(self.dir / "song.json").samples), 1)  # the source is untouched
        code, out, _ = run("instruments", "delete", "INS-0001", "--dir", self.folder)
        self.assertEqual((code, out["deleted"]), (0, "INS-0001"))
        code, _, err = run("instruments", "show", "INS-0001", "--dir", self.folder)
        self.assertEqual((code, err["code"]), (2, "INSTRUMENT_NOT_FOUND"))

    def test_save_from_a_project_slot_and_inline_apply(self):
        code, out, err = run("instruments", "save", "--name", "Pulse tone", "--project", self.dir / "song.json",
                             "--slot", 1, "--phrase", '["C20", "000"]', "--dir", self.folder)
        self.assertEqual((code, err), (0, None), err)
        self.assertEqual(out["instrument"]["sample"]["kind"], "pcm")
        code, out, _ = run("instruments", "show", "INS-0001", "--dir", self.folder, "--full")
        self.assertIn("pcm_base64", out["instrument"]["sample"])
        code, out, err = run("instruments", "apply", self.dir / "song.json", "--output", self.dir / "inline.json",
                             "--inline", json.dumps(PLUCK), "--pattern", 0, "--channel", 0, "--row", 0,
                             "--note", "E-2", "--length", 2, "--dir", self.folder)
        self.assertEqual((code, out["applied"]["stopped"]), (0, "length"), err)

    def test_cli_errors(self):
        code, _, err = run("instruments", "save", "--name", "Bad", "--recipe", '{"type": "kick"}', "--phrase", "F06",
                           "--dir", self.folder)
        self.assertEqual((code, err["code"]), (2, "INSTRUMENT_INVALID"))
        self.assertFalse(self.folder.exists())
        code, _, err = run("instruments", "apply", self.dir / "song.json", "--output", self.dir / "o.json",
                           "--pattern", 0, "--channel", 1, "--row", 4, "--note", "C-2", "--dir", self.folder)
        self.assertEqual((code, err["code"]), (2, "PATCH_FIELD"))
        code, _, err = run("instruments", "save", "--name", "Whole", "--json", json.dumps(PLUCK), "--dir", self.folder)
        self.assertEqual(code, 0, err)
        code, _, err = run("instruments", "save", "--json", json.dumps(PLUCK), "--id", "INS-0001", "--dir", self.folder)
        self.assertEqual((code, err["code"]), (2, "INSTRUMENT_EXISTS"))
        code, out, _ = run("instruments", "save", "--json", json.dumps({**PLUCK, "name": "Renamed"}), "--id", "INS-0001",
                           "--replace", "--dir", self.folder)
        self.assertEqual((code, out["instrument"]["name"]), (0, "Renamed"))


if __name__ == "__main__":
    unittest.main()
