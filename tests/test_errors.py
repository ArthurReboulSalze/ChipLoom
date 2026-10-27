from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker4agents import demo, mod, project
from tracker4agents.errors import diagnostic_payload, english_message, error_code, error_payload
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell, validate

ROOT = Path(__file__).resolve().parents[1]
FRENCH_MARKERS = ("é", "è", "à", "ê", "ç", " le ", " la ", " des ", "attendu", "voie")


class ErrorCodeTests(unittest.TestCase):
    def test_explicit_code_wins_over_message_table(self):
        self.assertEqual(error_code(ValidationError("Note inconnue", "CUSTOM")), "CUSTOM")

    def test_message_table_classifies_codeless_core_text(self):
        cases = {
            "Note inconnue 'X'": "NOTE_UNKNOWN",
            "Pattern 0: période 5 hors des 36 notes du profil.": "NOTE_RANGE",
            "Un effet doit contenir trois chiffres hexadécimaux": "EFFECT_FORMAT",
            "Pattern 0: cellule (0, 0) définie deux fois": "CELL_DUPLICATE",
            "Projet: champs inconnus ['x']": "UNKNOWN_FIELD",
            "FFmpeg est requis pour la copie MP3 optionnelle.": "FFMPEG_MISSING",
            "Le rendu a dépassé sa limite de temps et a été interrompu.": "RENDER_TIMEOUT",
            "Reference input exceeds the analysis size limit.": "FILE_TOO_LARGE",
            "Le rendu audio doit avoir un chemin distinct du module source.": "OUTPUT_PATH",
        }
        for message, code in cases.items():
            with self.subTest(message=message):
                self.assertEqual(error_code(ValidationError(message)), code)

    def test_fallbacks_by_exception_type(self):
        self.assertEqual(error_code(ValidationError("nothing known")), "VALIDATION")
        self.assertEqual(error_code(FileNotFoundError(2, "No such file")), "IO_ERROR")
        self.assertEqual(error_code(RuntimeError("boom")), "RUNTIME_ERROR")
        self.assertEqual(error_code(ValueError("boom")), "INVALID_VALUE")
        self.assertEqual(error_code(json.JSONDecodeError("Expecting value", "", 0)), "JSON_SYNTAX")

    def test_core_raise_sites_carry_explicit_codes(self):
        base = project.to_dict(demo.create(), layout="events")

        def failure(mutate):
            data = copy.deepcopy(base)
            mutate(data)
            with self.assertRaises(ValidationError) as caught:
                project.from_dict(data)
            return caught.exception

        def events(data):
            return data["patterns"][0]["events"]

        cases = {
            "NOTE_UNKNOWN": lambda d: events(d)[0].update(note="X-9"),
            "EFFECT_FORMAT": lambda d: events(d)[0].update(effect="ZZZ"),
            "EFFECT_UNSUPPORTED": lambda d: events(d)[0].update(effect="E30"),
            "EFFECT_PARAM": lambda d: events(d)[0].update(effect="C99"),
            "FLOW": lambda d: events(d)[0].update(effect="B99"),
            "TIMING": lambda d: events(d)[0].update(effect="F00"),
            "CELL_DUPLICATE": lambda d: events(d).append(dict(events(d)[0])),
            "UNKNOWN_FIELD": lambda d: d.update(extra=1),
            "SCHEMA": lambda d: d.update(schema="nope"),
            "TEXT_ASCII": lambda d: d.update(title="é"),
            "TEXT_LENGTH": lambda d: d.update(title="x" * 21),
            "ORDERS": lambda d: d.update(orders=[0, 99]),
            "SAMPLE_SLOT": lambda d: d.update(samples=[]),
            "SAMPLE_REF": lambda d: events(d)[0].update(sample=31),
            "INTEGER_RANGE": lambda d: events(d)[0].update(row=64),
        }
        for code, mutate in cases.items():
            with self.subTest(code=code):
                error = failure(mutate)
                self.assertEqual(error.code, code, str(error))
                self.assertEqual(error_code(error), code)

    def test_sample_and_mod_codes(self):
        def sample_error(**changes):
            sample = Sample("S", (0, 0, 1, 2), **changes)
            with self.assertRaises(ValidationError) as caught:
                validate(Module("T", [sample], [Pattern()], [0]))
            return caught.exception.code

        self.assertEqual(sample_error(loop_start=1, loop_length=2), "SAMPLE_LOOP")
        self.assertEqual(sample_error(loop_start=0, loop_length=2), "SAMPLE_LOOP")
        bad = Module("T", [Sample("S", (0, 0, 1))], [Pattern()], [0])
        with self.assertRaises(ValidationError) as caught:
            validate(bad)
        self.assertEqual(caught.exception.code, "SAMPLE_LENGTH")
        bad.samples[0].pcm = (0, 0, 1, 300)
        with self.assertRaises(ValidationError) as caught:
            validate(bad)
        self.assertEqual(caught.exception.code, "SAMPLE_PCM")
        with self.assertRaises(ValidationError) as caught:
            mod.decode(b"short")
        self.assertEqual(caught.exception.code, "MOD_FORMAT")
        with self.assertRaises(ValidationError) as caught:
            cell("H-9")
        self.assertEqual(caught.exception.code, "NOTE_UNKNOWN")


class PayloadTests(unittest.TestCase):
    def test_payload_has_code_english_message_and_french_original(self):
        with self.assertRaises(ValidationError) as caught:
            cell("C-1", effect="12")
        payload = error_payload(caught.exception)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error"], "ValidationError")
        self.assertEqual(payload["code"], "EFFECT_FORMAT")
        self.assertEqual(payload["message"], english_message(caught.exception))
        self.assertIn("hexadecimal", payload["message"])
        self.assertIn("hexadécimaux", payload["message_fr"])

    def test_message_fr_is_omitted_when_text_is_already_english(self):
        payload = error_payload(ValidationError("Sample slot is occupied; --replace is required."))
        self.assertEqual(payload["code"], "SAMPLE_SLOT")
        self.assertNotIn("message_fr", payload)

    def test_agent_facing_messages_are_english(self):
        base = project.to_dict(demo.create(), layout="events")
        def first(d):
            return d["patterns"][0]["events"]

        for mutate in (lambda d: first(d)[0].update(note="X-9"), lambda d: first(d)[0].update(effect="B99"),
                       lambda d: first(d).append(dict(first(d)[0])), lambda d: d.update(title="é"),
                       lambda d: d.update(orders=[0, 99]), lambda d: first(d)[0].update(foo=1)):
            data = copy.deepcopy(base)
            mutate(data)
            with self.assertRaises(ValidationError) as caught:
                project.from_dict(data)
            message = error_payload(caught.exception)["message"]
            with self.subTest(message=message):
                self.assertFalse(any(marker in message.lower() for marker in FRENCH_MARKERS), message)


class CliErrorTests(unittest.TestCase):
    def invoke(self, *args: str):
        return subprocess.run([sys.executable, "-m", "tracker4agents", *args], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_failures_emit_structured_stderr_with_exit_code_two(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            broken, missing = directory / "broken.json", directory / "missing.json"
            broken.write_text("{nope", encoding="utf-8")
            expected = {broken: "JSON_SYNTAX", missing: "IO_ERROR"}
            for source, code in expected.items():
                result = self.invoke("inspect", str(source))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                payload = json.loads(result.stderr)
                self.assertEqual((payload["ok"], payload["code"]), (False, code))
                self.assertTrue(payload["message"])

    def test_validate_report_entries_have_code_path_and_english_message(self):
        data = project.to_dict(demo.create(), layout="events")
        data["title"] = "é"
        data["patterns"][0]["events"][0]["note"] = "X-9"
        data["patterns"][0]["events"].append(dict(data["patterns"][0]["events"][1]))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "bad.json"
            project.write_json(source, data)
            result = self.invoke("validate", str(source), "--report")
            self.assertEqual(result.returncode, 2)
            payload = json.loads(result.stderr)
            self.assertEqual(payload["code"], "PROJECT_INVALID")
            self.assertEqual(payload["error_count"], len(payload["errors"]))
            by_path = {entry["path"]: entry for entry in payload["errors"]}
            self.assertEqual(by_path["title"]["code"], "TEXT_ASCII")
            self.assertEqual(by_path["patterns[0].events[0]"]["code"], "NOTE_UNKNOWN")
            duplicate = by_path[f"patterns[0].events[{len(data['patterns'][0]['events']) - 1}]"]
            self.assertEqual(duplicate["code"], "CELL_DUPLICATE")
            for entry in payload["errors"]:
                self.assertEqual(set(entry) - {"message_fr"}, {"path", "code", "message"})
                self.assertIn("message_fr", entry)
                self.assertNotEqual(entry["message"], entry["message_fr"])

    def test_diagnostic_payload_keeps_english_only_entries_without_french_copy(self):
        entry = diagnostic_payload({"path": "schema", "code": "SCHEMA", "message": "Expected schema x."})
        self.assertEqual(entry, {"path": "schema", "code": "SCHEMA", "message": "Expected schema x."})


if __name__ == "__main__":
    unittest.main()
