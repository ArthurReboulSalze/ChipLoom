from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker4agents import demo, mod, project
from tracker4agents.model import Module, Pattern, Sample, ValidationError

ROOT = Path(__file__).resolve().parents[1]
PIXEL_RUSH = ROOT / "examples" / "pixel_rush.project.json"


class SchemaV2Tests(unittest.TestCase):
    def test_default_schema_is_v2_and_v1_is_kept(self):
        self.assertEqual(project.SCHEMA, "tracker4agents.project.v2")
        self.assertEqual(project.SCHEMA_V1, "tracker4agents.project.v1")
        module = demo.create()
        self.assertEqual(project.to_dict(module)["schema"], project.SCHEMA_V2)
        self.assertEqual(project.to_dict(module, schema=1)["schema"], project.SCHEMA_V1)
        with self.assertRaises(ValidationError) as caught:
            project.to_dict(module, schema=3)
        self.assertEqual(caught.exception.code, "SCHEMA")

    def test_v2_sample_is_base64_of_raw_signed_bytes_with_sha256(self):
        sample = Sample("Raw", (0, 0, 127, -128, -1, 5), volume=33, finetune=-2, loop_start=2, loop_length=4)
        module = Module("T", [sample, Sample("Empty", ())], [Pattern()], [0])
        first, second = project.to_dict(module)["samples"]
        raw = bytes((0, 0, 127, 128, 255, 5))
        self.assertEqual(first, {
            "name": "Raw", "volume": 33, "finetune": -2, "pcm_base64": base64.b64encode(raw).decode(),
            "pcm_sha256": hashlib.sha256(raw).hexdigest(), "loop_start": 2, "loop_length": 4})
        self.assertEqual(second["pcm_base64"], "")
        self.assertEqual(second["pcm_sha256"], hashlib.sha256(b"").hexdigest())
        loaded = project.from_dict(project.to_dict(module)).samples
        self.assertEqual(loaded[0].pcm, sample.pcm)
        self.assertEqual(loaded[1].pcm, ())

    def test_v1_output_is_exactly_the_original_shape(self):
        module = demo.create()
        v1 = project.to_dict(module, recipes=False, schema=1)
        self.assertEqual(v1["schema"], "tracker4agents.project.v1")
        for entry in v1["samples"]:
            self.assertEqual(set(entry), {"name", "volume", "finetune", "pcm", "loop_start", "loop_length"})
            self.assertIsInstance(entry["pcm"], list)
        self.assertEqual(mod.encode(project.from_dict(v1)), mod.encode(module))

    def test_recipes_stay_recipes_in_v2_unless_flattened(self):
        module = demo.create()
        kept = project.to_dict(module)["samples"]
        self.assertTrue(all("recipe" in entry and "pcm_base64" not in entry for entry in kept))
        flat = project.to_dict(module, recipes=False)["samples"]
        self.assertTrue(all("recipe" not in entry and "pcm_base64" in entry for entry in flat))
        self.assertEqual(mod.encode(project.from_dict(project.to_dict(module, recipes=False))), mod.encode(module))

    def test_corrupt_or_missing_hash_and_bad_base64_are_rejected(self):
        module = Module("T", [Sample("S", (0, 0, 9, 8))], [Pattern()], [0])
        base = project.to_dict(module)

        def code_for(mutate):
            data = copy.deepcopy(base)
            mutate(data["samples"][0])
            with self.assertRaises(ValidationError) as caught:
                project.from_dict(data)
            return caught.exception.code

        self.assertEqual(code_for(lambda s: s.update(pcm_base64=base64.b64encode(b"\0\0\7\7").decode())),
                         "SAMPLE_PCM_HASH")
        self.assertEqual(code_for(lambda s: s.update(pcm_sha256="0" * 64)), "SAMPLE_PCM_HASH")
        self.assertEqual(code_for(lambda s: s.pop("pcm_sha256")), "SAMPLE_PCM_HASH")
        self.assertEqual(code_for(lambda s: s.update(pcm_base64="not base64!")), "SAMPLE_PCM")
        self.assertEqual(code_for(lambda s: s.update(pcm_base64=12)), "SAMPLE_PCM")
        self.assertEqual(code_for(lambda s: s.update(pcm_base64="A" * 90_000)), "SAMPLE_PCM")
        # The hash is case-insensitive hex; an uppercase digest still verifies.
        data = copy.deepcopy(base)
        data["samples"][0]["pcm_sha256"] = data["samples"][0]["pcm_sha256"].upper()
        self.assertEqual(project.from_dict(data).samples[0].pcm, (0, 0, 9, 8))

    def test_pcm_list_and_pcm_base64_are_not_interchangeable_between_versions(self):
        module = Module("T", [Sample("S", (0, 0, 9, 8))], [Pattern()], [0])
        v2, v1 = project.to_dict(module), project.to_dict(module, schema=1)
        v2["samples"][0]["pcm"] = [0, 0, 9, 8]
        v1["samples"][0].update(pcm_base64="AAAJCA==", pcm_sha256="0" * 64)
        v2_wrong, v1_wrong = copy.deepcopy(v2), copy.deepcopy(v1)
        v2_wrong["schema"], v1_wrong["schema"] = project.SCHEMA_V2, project.SCHEMA_V1
        for data in (v2_wrong, v1_wrong):
            with self.assertRaises(ValidationError) as caught:
                project.from_dict(data)
            self.assertEqual(caught.exception.code, "UNKNOWN_FIELD")
        recipe_and_pcm = project.to_dict(demo.create())
        recipe_and_pcm["samples"][0].update(pcm_base64="", pcm_sha256="")
        with self.assertRaises(ValidationError) as caught:
            project.from_dict(recipe_and_pcm)
        self.assertEqual(caught.exception.code, "RECIPE_INVALID")

    def test_diagnose_supports_both_schemas(self):
        module = Module("T", [Sample("S", (0, 0, 9, 8))], [Pattern()], [0])
        for schema in (1, 2):
            data = project.to_dict(module, schema=schema)
            self.assertEqual(project.diagnose(data), [])
        broken = project.to_dict(module)
        broken["samples"][0]["pcm_sha256"] = "0" * 64
        errors = project.diagnose(broken)
        self.assertEqual([(entry["path"], entry["code"]) for entry in errors],
                         [("samples[0]", "SAMPLE_PCM_HASH")])
        old = project.to_dict(module, schema=1)
        old["samples"][0]["pcm"] = [0, 0, 1000, 0]
        errors = project.diagnose(old)
        self.assertEqual([(entry["path"], entry["code"]) for entry in errors], [("samples[0]", "SAMPLE_PCM")])
        wrong = project.to_dict(module, layout="events")
        wrong["schema"] = "tracker4agents.project.v9"
        self.assertEqual({entry["code"] for entry in project.diagnose(wrong)}, {"SCHEMA"})
        self.assertTrue(all(set(entry) == {"path", "code", "message"} for entry in project.diagnose(wrong)))

    def test_diagnose_stays_read_only(self):
        data = project.to_dict(demo.create(), layout="events")
        data["patterns"][0]["events"][0]["note"] = "X-9"
        before = json.dumps(data, sort_keys=True)
        self.assertTrue(project.diagnose(data))
        self.assertEqual(json.dumps(data, sort_keys=True), before)


class ExamplesAndMigrationTests(unittest.TestCase):
    def test_shipped_v1_files_still_load(self):
        for path in sorted((ROOT / "examples").glob("*.json")) + sorted((ROOT / "docs" / "listen" / "media").glob("*.project.json")):
            with self.subTest(path=path.name):
                data = project.read_json(path)
                if path.name == "copper_skies.project.json":   # the XM demo is written as schema v2
                    self.assertEqual(data["schema"], project.SCHEMA_V2)
                    self.assertEqual(project.diagnose(data), [])
                    continue
                self.assertEqual(data["schema"], project.SCHEMA_V1)
                self.assertEqual(project.diagnose(data), [])
                mod.encode(project.from_dict(data))

    def test_mod_export_is_byte_identical_after_v1_to_v2_round_trip(self):
        v1 = project.load(PIXEL_RUSH)
        expected = mod.encode(v1)
        v2_data = project.to_dict(v1)
        self.assertEqual(v2_data["schema"], project.SCHEMA_V2)
        self.assertEqual(mod.encode(project.from_dict(v2_data)), expected)
        flat = project.to_dict(v1, recipes=False)
        self.assertEqual(mod.encode(project.from_dict(flat)), expected)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pixel_rush.v2.json"
            project.write_json(path, flat)
            self.assertEqual(mod.encode(project.load(path)), expected)

    def test_voltage_odyssey_shrinks_in_v2(self):
        source = ROOT / "docs" / "listen" / "media" / "voltage_odyssey_v2.project.json"
        module = project.load(source)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "voltage.v2.json"
            project.write_json(target, project.to_dict(module))
            self.assertLess(target.stat().st_size, source.stat().st_size)
            self.assertEqual(mod.encode(project.load(target)), mod.encode(module))


class MigrateCliTests(unittest.TestCase):
    def invoke(self, *args: str):
        return subprocess.run([sys.executable, "-m", "tracker4agents", *args], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)

    def test_migrate_v1_project_to_v2_keeps_the_mod_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pixel_rush.v2.json"
            result = self.invoke("migrate", str(PIXEL_RUSH), "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual((report["ok"], report["source_schema"], report["schema"]),
                             (True, project.SCHEMA_V1, project.SCHEMA_V2))
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["schema"], project.SCHEMA_V2)
            expected = mod.encode(project.load(PIXEL_RUSH))
            self.assertEqual(mod.encode(project.load(output)), expected)
            self.assertEqual(report["mod_sha256"], hashlib.sha256(expected).hexdigest())
            self.assertEqual(report["output_bytes"], output.stat().st_size)
            # A second pass over a v2 file is accepted and idempotent.
            again = Path(directory) / "again.json"
            result = self.invoke("migrate", str(output), "--output", str(again))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["source_schema"], project.SCHEMA_V2)
            self.assertEqual(again.read_bytes(), output.read_bytes())

    def test_migrate_mod_writes_flattened_v2_and_import_also_writes_v2(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            payload = mod.encode(demo.create())
            source = directory / "song.mod"
            source.write_bytes(payload)
            migrated, imported = directory / "migrated.json", directory / "imported.json"
            result = self.invoke("migrate", str(source), "--output", str(migrated))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["source_schema"], "mod")
            result = self.invoke("import", str(source), "--output", str(imported))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["schema"], project.SCHEMA_V2)
            for path in (migrated, imported):
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], project.SCHEMA_V2)
                self.assertEqual(mod.encode(project.load(path)), payload)

    def test_migrate_refuses_to_overwrite_source_or_write_non_json(self):
        with tempfile.TemporaryDirectory() as directory:
            copy_path = Path(directory) / "copy.json"
            copy_path.write_bytes(PIXEL_RUSH.read_bytes())
            before = copy_path.read_bytes()
            result = self.invoke("migrate", str(copy_path), "--output", str(copy_path))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)["code"], "OUTPUT_PATH")
            result = self.invoke("migrate", str(copy_path), "--output", str(Path(directory) / "out.txt"))
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)["code"], "OUTPUT_PATH")
            self.assertEqual(copy_path.read_bytes(), before)

    def test_inspect_and_validate_accept_both_schemas(self):
        with tempfile.TemporaryDirectory() as directory:
            v2 = Path(directory) / "v2.json"
            project.write_json(v2, project.to_dict(project.load(PIXEL_RUSH), recipes=False))
            for source in (PIXEL_RUSH, v2):
                result = self.invoke("validate", str(source), "--report")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
