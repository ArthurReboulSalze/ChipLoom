"""The sample bank with XM sources: 16-bit and ping-pong entries, roles, palettes, adapt rules, privacy."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tracker4agents import cli, mod, project, xm
from tracker4agents.model import Module, Pattern, Sample, cell, validate
from tracker4agents.sample_library import SampleLibrary, adapt_for_mod, mod_adaptations

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = {"title": "PRIVATE xm title", "file": "PRIVATE song.xm", "bass": "PRIVATE fat bass", "hat": "PRIVATE hh",
           "dropped": "PRIVATE hh open", "chord": "PRIVATE arp"}
BASS = tuple(20000 if index % 64 < 32 else -20000 for index in range(256))          # 16-bit pulse, 4 cycles
HAT = (0, 0) + tuple(((index * 7919) % 211) - 105 for index in range(298))             # 300-frame noise
OPEN_HAT = (0, 0) + tuple(((index * 104729) % 199) - 99 for index in range(498))      # 500-frame noise, never played
CHORD = tuple(((index * 37) % 64) - 32 for index in range(64))                        # bright 8-bit cycle


def _instrument(name: str, samples: list[dict], keymap: bytes, sustain: bool = False) -> bytes:
    """One XM instrument block: the 263-byte header, the sample headers, then every sample's delta PCM."""
    head = bytearray(struct.pack("<I", 263) + name.encode("ascii").ljust(22, b"\0") + b"\0")
    head += struct.pack("<H", len(samples)) + struct.pack("<I", 40) + keymap.ljust(96, b"\0")
    points = [(0, 64), (10, 48), (40, 32)] if sustain else []
    envelope = b"".join(struct.pack("<HH", x, y) for x, y in points).ljust(48, b"\0")
    head += envelope + bytes(48) + bytes((len(points), 0, 1, 0, 0, 0, 0, 0, 3 if sustain else 0, 0, 0, 0, 0, 0))
    head += struct.pack("<H", 0) + bytes(22)
    pcm = bytearray()
    for item in samples:
        bits = item.get("bits", 8)
        step = bits // 8
        kind = {"none": 0, "forward": 1, "pingpong": 2}[item.get("loop", "none")] | (16 if bits == 16 else 0)
        head += struct.pack("<IIIBbBBbB", len(item["pcm"]) * step, item.get("loop_start", 0) * step,
                            item.get("loop_length", 0) * step, item.get("volume", 64), item.get("finetune", 0), kind,
                            item.get("panning", 128), item.get("relative_note", 0), 0)
        head += item["name"].encode("ascii").ljust(22, b"\0")
        pcm += xm._delta(item["pcm"], bits)
    return bytes(head) + bytes(pcm)


def synthetic_xm() -> bytes:
    """Three instruments on four channels: a 16-bit ping-pong pulse played low and melodic (instrument 1), a
    two-sample hat instrument struck on one note (2; its second sample is never in the key map's main use),
    an arpeggiated bright loop (3). Channel 3 stays silent."""
    rows = 32
    pattern = bytearray()
    bass_notes = ("C-2", "E-2", "G-2", "A-2", "F-2", "D-2", "B-2", "C#2")
    for row in range(rows):
        for channel in range(4):
            value = cell(None, 0, "000", "xm")
            if channel == 0 and row % 4 == 0:
                value = cell(bass_notes[(row // 4) % len(bass_notes)], 1, "000", "xm")
            elif channel == 1 and row % 4 == 2:
                value = cell("C-5", 2, "000", "xm")
            elif channel == 2 and row % 8 == 0:
                value = cell("A-4" if row % 16 else "C-5", 3, "047", "xm")
            pattern += xm._pack_cell(value)
    header = bytearray(xm.MAGIC + PRIVATE["title"].encode("ascii").ljust(20, b"\0") + b"\x1a")
    header += b"FastTracker v2.00   " + struct.pack("<HIHHHHHHHH", 0x0104, 276, 2, 0, 4, 1, 3, 1, 6, 125)
    header += bytes(256)
    body = struct.pack("<IBHH", 9, 0, rows, len(pattern)) + bytes(pattern)
    body += _instrument(PRIVATE["bass"], [{"name": PRIVATE["bass"], "pcm": BASS, "bits": 16, "loop": "pingpong",
                                           "loop_start": 0, "loop_length": 64, "relative_note": -12, "finetune": -16,
                                           "panning": 96}], bytes(96), sustain=True)
    body += _instrument("hats", [{"name": PRIVATE["hat"], "pcm": HAT, "volume": 48},
                                 {"name": PRIVATE["dropped"], "pcm": OPEN_HAT, "volume": 40}],
                        bytes(86) + bytes([1] * 10))
    body += _instrument(PRIVATE["chord"], [{"name": PRIVATE["chord"], "pcm": CHORD, "loop": "forward", "loop_start": 0,
                                            "loop_length": 64, "volume": 50}], bytes(96))
    return bytes(header) + body


def synthetic_mod() -> bytes:
    kick = (0, 0) + tuple(round(100 * (1 - index / 1200)) * (1 if (index // 40) % 2 else -1) for index in range(1198))
    low = tuple(value for value in (60, 60, -60, -60) for _ in range(16))   # one 64-frame cycle: 129 Hz at C-2
    samples = [Sample("PRIVATE bd", kick, 64), Sample("PRIVATE bass", low, 50, 0, 0, 64)]
    pattern = Pattern()
    for row in range(0, 64, 8):
        pattern.put(row, 0, cell("C-2", 1))
        pattern.put(row + 4, 1, cell(("C-1", "G-1", "A-1", "F-1", "E-1", "D-1", "B-1", "C#1")[row // 8], 2))
    return mod.encode(Module("PRIVATE mod title", samples, [pattern], [0]))


def run_cli(*argv) -> tuple[int, dict]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = cli.main([str(value) for value in argv])
    return status, json.loads(stdout.getvalue() if status == 0 else stderr.getvalue())


class XmBankTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chiploom xm bank ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / "selection"
        (self.folder / "nested").mkdir(parents=True)
        self.source = self.folder / PRIVATE["file"]
        self.source.write_bytes(synthetic_xm())
        (self.folder / "nested" / "PRIVATE tune.mod").write_bytes(synthetic_mod())
        (self.folder / "PRIVATE impulse.xm").write_bytes(b"IMPM" + bytes(400))
        self.bank = SampleLibrary(self.root / "bank")

    def entries(self) -> dict[str, dict]:
        return {entry["id"]: entry for entry in project.read_json(self.bank.path / "library.json")["samples"]}

    def test_xm_entries_keep_bits_loop_mode_tuning_envelope_and_roles(self):
        result = self.bank.extract(self.source)
        self.assertEqual((result["modules"], result["refused"], result["sample_slots"], result["new_entries"]),
                         (1, {}, 4, 4))
        self.assertEqual((result["palettes"], result["palettes_new"], result["modules_without_palette"]), (1, 1, 0))
        entries = self.entries()
        bass = entries["SMP-0001"]
        self.assertEqual((bass["bits"], bass["loop_mode"], bass["loop_start"], bass["loop_length"]), (16, "pingpong", 0, 64))
        self.assertEqual((bass["relative_note"], bass["finetune"], bass["panning"], bass["format_origin"]), (-12, -16, 96, "xm"))
        self.assertEqual(bass["pcm"], f"pcm/{bass['pcm_sha256']}.pcm16")
        self.assertEqual(bass["bytes"], 512)
        self.assertEqual(bass["envelope"], {"volume_envelope": True, "sustained": True, "vibrato": False, "fadeout": 0})
        self.assertEqual(self.bank.read_sample("SMP-0001").pcm, BASS)
        self.assertEqual((bass["role"], bass["role_source"]), ("bass", "song"))
        self.assertFalse(bass["compatibility"]["compatible"])
        self.assertEqual(bass["compatibility"]["adapt"][:2], ["convert-16-bit-to-8-bit", "unfold-pingpong-loop"])
        hat, dropped, chord = entries["SMP-0002"], entries["SMP-0003"], entries["SMP-0004"]
        self.assertEqual((hat["role"], hat["bits"], hat["loop_mode"], hat["envelope"]["sustained"]), ("hat", 8, "forward", False))
        self.assertEqual((dropped["role_source"], dropped["role_occurrences"]), ("sound", 1))
        self.assertTrue(any("multi-sample" in line for line in dropped["role_evidence"]), dropped["role_evidence"])
        self.assertEqual(chord["role"], "chord")
        for entry in entries.values():
            self.assertIn(entry["role_confidence"], ("high", "medium", "low"))
        listed = self.bank.search(role="hat")
        self.assertEqual([item["id"] for item in listed["samples"]], ["SMP-0002", "SMP-0003"])
        self.assertEqual([item["id"] for item in self.bank.search(role="chord")["samples"]], ["SMP-0004"])
        self.assertEqual(self.bank.search(fmt="mod")["total"], 0)
        pitch = self.bank.inspect("SMP-0001")["pitch"]
        self.assertEqual((pitch["reference_note"], pitch["loop_cycles"]), ("C-4", 1))
        self.assertAlmostEqual(pitch["playback_rate_hz"], 8363 * 2 ** (-1 - 16 / 1536), places=1)

    def test_palette_names_no_file_and_the_bank_keeps_readable_sources(self):
        self.bank.extract(self.source)
        palettes = project.read_json(self.bank.path / "palettes.json")
        self.assertEqual(palettes["schema"], "chiploom.sample-palettes.v1")
        palette = palettes["palettes"][0]
        self.assertEqual((palette["id"], palette["format"], palette["channels"], palette["speed"], palette["bpm"]),
                         ("PAL-0001", "xm", 4, 6, 125))
        self.assertEqual(palette["summary"], "hat · bass · chord")
        played = {entry["id"]: entry for entry in palette["entries"] if entry["note_starts"]}
        self.assertEqual(set(played), {"SMP-0001", "SMP-0002", "SMP-0004"})
        self.assertEqual(played["SMP-0001"]["channels"], [0])
        self.assertEqual([item["role"] for item in palette["channel_layout"]], ["bass", "hat", "chord", None])
        self.assertEqual(palette["channel_layout"][0]["entries"], ["SMP-0001"])
        structure = palette["structure"]
        self.assertEqual((structure["orders"], structure["distinct_patterns"]), (2, 1))
        self.assertEqual(structure["sections"], [{"start_order": 0, "orders": 2, "seconds": 7.68, "active_channels": 3}])
        self.assertEqual(structure["channel_entry_order"], [0, 0, 0, None])
        self.assertNotIn("order_patterns", structure)
        palette_text = (self.bank.path / "palettes.json").read_text()
        self.assertNotIn("PRIVATE", palette_text)   # palettes hold counts and IDs, never file or sample names
        for note in ("C-2", "E-2", "C-5", "047"):
            self.assertNotIn(f'"{note}"', palette_text + (self.bank.path / "library.json").read_text())
        bass = self.bank.get("SMP-0001")
        self.assertEqual(bass["name"], PRIVATE["bass"][:22].rstrip())
        self.assertEqual((bass["source"]["file"], bass["source"]["slot"]), (PRIVATE["file"], 1))
        provenance = project.read_json(self.bank.path / "private/provenance.json")
        self.assertEqual(provenance["palettes"]["PAL-0001"]["filename"], PRIVATE["file"])
        self.assertEqual(provenance["palettes"]["PAL-0001"]["module_title"], PRIVATE["title"])
        names = {item["original_name"] for item in provenance["occurrences"].values()}
        self.assertEqual(names, {PRIVATE["bass"], PRIVATE["hat"], PRIVATE["dropped"], PRIVATE["chord"]})
        self.assertEqual(self.bank.palettes(role="bass")["total"], 1)
        self.assertEqual(self.bank.palettes(role="kick")["total"], 0)
        self.assertEqual(self.bank.palettes(fmt="mod")["total"], 0)
        self.assertEqual(self.bank.palette("PAL-0001")["id"], "PAL-0001")

    def test_reextraction_deduplicates_and_keeps_the_palette_id(self):
        first = self.bank.extract(self.source)
        again = self.bank.extract(self.source)
        self.assertEqual((first["new_entries"], again["new_entries"], again["palettes_new"], again["palettes"]), (4, 0, 0, 1))
        self.assertEqual(self.bank.get("SMP-0001")["source_occurrences"], 1)
        self.assertEqual(len(list((self.bank.path / "pcm").iterdir())), 4)

    def test_folder_extraction_counts_refusals_and_builds_mod_and_xm_palettes(self):
        result = self.bank.extract(self.folder)
        self.assertEqual((result["modules"], result["refused"], result["palettes"]), (2, {"IT_UNSUPPORTED": 1}, 2))
        self.assertEqual(result["entries"], 6)
        audit = self.bank.audit()
        self.assertEqual((audit["bits"], audit["format_origin"], audit["palettes"]), ({"8": 5, "16": 1}, {"xm": 4, "mod": 2}, 2))
        self.assertEqual(audit["loop_mode"], {"pingpong": 1, "one-shot": 3, "forward": 2})
        self.assertEqual(audit["roles"]["kick"], 1)
        listing = self.bank.palettes()
        self.assertEqual({row["format"] for row in listing["palettes"]}, {"mod", "xm"})
        mod_palette = next(row for row in listing["palettes"] if row["format"] == "mod")
        self.assertEqual(mod_palette["summary"], "kick · bass")
        self.assertNotIn("PRIVATE", (self.bank.path / "palettes.json").read_text())
        self.assertNotIn("nested", (self.bank.path / "palettes.json").read_text())
        with self.assertRaises(ValueError):
            self.bank.extract(self.folder / "PRIVATE impulse.xm")

    def test_mod_insertion_needs_adapt_and_keeps_the_bank_pcm(self):
        self.bank.extract(self.source)
        blank = Module("Test", [Sample("empty", ())], [Pattern()], [0], {"sample_source": "library"})
        with self.assertRaises(ValueError) as caught:
            self.bank.insert(blank, "SMP-0001")
        self.assertEqual(caught.exception.code, "SAMPLE_INCOMPATIBLE")
        self.assertIn("--adapt", str(caught.exception))
        self.assertIn("unfold-pingpong-loop", str(caught.exception))
        module, info = self.bank.insert(blank, "SMP-0001", adapt=True)
        inserted = module.samples[0]
        self.assertEqual((inserted.bits, inserted.loop_mode, inserted.loop_length, inserted.panning), (8, "forward", 128, 128))
        self.assertEqual((inserted.finetune, inserted.relative_note), (-1, 0))
        self.assertEqual(inserted.pcm[:2], (78, 78))
        self.assertEqual(len(inserted.pcm), 256 + 64)
        self.assertEqual(inserted.pcm[64:128], tuple(reversed(inserted.pcm[:64])))
        self.assertEqual(info["adaptations"][:3], ["convert-16-bit-to-8-bit", "unfold-pingpong-loop", "drop-panning"])
        self.assertTrue(info["adaptations"][3].startswith("map-xm-tuning"))
        self.assertIn("-12 semitones", info["adaptations"][3])
        self.assertEqual(info["role"], "bass")
        validate(module)
        mod.encode(module)
        self.assertEqual(self.bank.read_sample("SMP-0001").pcm, BASS)   # the bank keeps the 16-bit original
        self.bank.audit()
        odd = Sample("odd", (0, 0, 5, 6, 7), 64, 0, 1, 3, None, 8, "pingpong")
        self.assertEqual(mod_adaptations(odd), ["unfold-pingpong-loop", "align-to-even-bytes"])
        fixed, _ = adapt_for_mod(odd)
        validate(Module("t", [fixed], [Pattern()], [0]))

    def test_xm_insertion_keeps_the_sample_native(self):
        self.bank.extract(self.source)
        blank = xm.blank("Test", channels=4, metadata={"sample_source": "library"})
        module, info = self.bank.insert(blank, "SMP-0001")
        inserted = module.samples[0]
        self.assertEqual((inserted.bits, inserted.loop_mode, inserted.loop_length), (16, "pingpong", 64))
        self.assertEqual((inserted.finetune, inserted.relative_note, inserted.panning), (-16, -12, 96))
        self.assertEqual(inserted.pcm, BASS)
        self.assertTrue(info["xm"]["native"])
        self.assertEqual(info["adaptations"], [])
        payload = xm.encode(module)
        self.assertEqual(xm.decode(payload).samples[0], inserted)
        self.assertEqual(module.samples[0].name, self.bank.get("SMP-0001")["name"])

    def test_use_palette_fills_slots_in_role_order(self):
        self.bank.extract(self.folder)
        blank = xm.blank("Test", channels=4, metadata={"sample_source": "library"})
        xm_palette = next(row["id"] for row in self.bank.palettes()["palettes"] if row["format"] == "xm")
        module, info = self.bank.use_palette(xm_palette, blank)
        self.assertEqual([(item["slot"], item["role"]) for item in info["slot_map"]], [(1, "hat"), (2, "bass"), (3, "chord")])
        self.assertEqual(len(module.samples), 3)
        self.assertEqual(module.metadata["sample_sources"]["2"]["library_id"], info["slot_map"][1]["id"])
        self.assertEqual(info["channel_layout"][0], {"channel": 0, "role": "bass"})
        full, info = self.bank.use_palette(xm_palette, blank, include_unplayed=True)
        self.assertEqual(len(full.samples), 4)
        mod_blank = Module("Test", [Sample("empty", ())], [Pattern()], [0], {"sample_source": "library"})
        with self.assertRaises(ValueError):
            self.bank.use_palette(xm_palette, mod_blank)
        adapted, info = self.bank.use_palette(xm_palette, mod_blank, slots=[2, 1, 3], adapt=True)
        self.assertEqual([item["slot"] for item in info["slot_map"]], [2, 1, 3])
        self.assertEqual(len(adapted.samples), 3)
        self.assertEqual(info["slot_map"][1]["adaptations"][0], "convert-16-bit-to-8-bit")
        validate(adapted)
        mod.encode(adapted)
        for slots in ([1], [5, 3, 1]):
            with self.assertRaises(ValueError):
                self.bank.use_palette(xm_palette, mod_blank, slots=slots, adapt=True)
        with self.assertRaisesRegex(ValueError, "occupied"):
            self.bank.use_palette(xm_palette, adapted, slots=[1, 2, 3], adapt=True)

    def test_v1_manifest_is_migrated_and_old_entries_get_pcm_roles(self):
        self.bank.extract(self.folder / "nested" / "PRIVATE tune.mod")
        manifest = project.read_json(self.bank.path / "library.json")
        manifest["schema"] = "chiploom.sample-library.v1"
        for entry in manifest["samples"]:
            for key in ("format_origin", "bits", "loop_mode", "panning", "relative_note", "envelope", "role",
                        "role_confidence", "role_evidence", "role_occurrences", "role_source"):
                entry.pop(key)
        project.write_json(self.bank.path / "library.json", manifest)
        provenance = project.read_json(self.bank.path / "private/provenance.json")
        provenance.pop("palettes")
        for item in provenance["occurrences"].values():
            for key in ("role", "role_confidence", "role_evidence", "role_source", "note_starts"):
                item.pop(key)
        project.write_json(self.bank.path / "private/provenance.json", provenance)
        (self.bank.path / "palettes.json").unlink()
        entry = self.bank.get("SMP-0001")
        self.assertEqual((entry["bits"], entry["format_origin"], entry["role"]), (8, "mod", None))
        result = self.bank.extract(self.source)
        self.assertEqual(result["roles_from_pcm_alone"], 2)
        entry = self.bank.get("SMP-0001")
        self.assertEqual((entry["role"], entry["role_source"]), ("kick", "pcm"))
        self.assertIn("module unavailable", entry["role_evidence"][-1])
        self.assertEqual(project.read_json(self.bank.path / "library.json")["schema"], "chiploom.sample-library.v2")

    def test_cli_and_mcp_commands(self):
        status, result = run_cli("samples", "extract", self.folder, "--library", self.bank.path)
        self.assertEqual(status, 0, result)
        status, result = run_cli("samples", "list", "--library", self.bank.path, "--role", "bass", "--format", "xm")
        self.assertEqual((status, result["total"]), (0, 1))
        status, listing = run_cli("samples", "palettes", "--library", self.bank.path, "--role", "kick")
        self.assertEqual((status, listing["total"]), (0, 1))
        status, shown = run_cli("samples", "palette", listing["palettes"][0]["id"], "--library", self.bank.path)
        self.assertEqual((status, shown["palette"]["format"]), (0, "mod"))
        status, result = run_cli("new", "--output", self.root / "blank.json", "--format", "xm")
        self.assertEqual(status, 0, result)
        status, used = run_cli("samples", "use-palette", listing["palettes"][0]["id"], self.root / "blank.json",
                               "--library", self.bank.path, "--output", self.root / "palette.json")
        self.assertEqual(status, 0, used)
        self.assertEqual([item["role"] for item in used["slot_map"]], ["kick", "bass"])
        self.assertEqual(len(project.load(self.root / "palette.json").samples), 2)
        status, result = run_cli("samples", "palette", "PAL-0099", "--library", self.bank.path)
        self.assertEqual((status, result["code"]), (2, "SAMPLE_LIBRARY"))
        from tracker4agents.mcp_server import TOOLS
        tools = {tool["name"]: tool for tool in TOOLS}
        self.assertEqual(tools["samples_palettes"]["argv"]({"role": "bass", "format": "xm"}),
                         ["samples", "palettes", "--role", "bass", "--format", "xm"])
        self.assertEqual(tools["samples_palette"]["argv"]({"id": "PAL-0001"}), ["samples", "palette", "PAL-0001"])
        self.assertEqual(tools["samples_list"]["argv"]({"role": "kick"}), ["samples", "list", "--role", "kick"])
        self.assertTrue(tools["samples_palettes"]["annotations"]["readOnlyHint"])


if __name__ == "__main__":
    unittest.main()
