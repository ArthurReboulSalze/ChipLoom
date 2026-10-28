"""Pocket Signals V2: original notes using only the owner's local sample bank.

The neutral IDs refer to the selected local bank, never to source filenames.
No reference PCM or music is embedded in this script.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker4agents import audio, mod, project
from tracker4agents.model import Module, Pattern, Sample, cell, playback_plan, validate
from tracker4agents.review import write_preview
from tracker4agents.sample_library import DEFAULT_LIBRARY, SampleLibrary

PALETTE = ["SMP-0078", "SMP-0079", "SMP-0077", "SMP-0080",
           "SMP-0081", "SMP-0082", "SMP-0083", "SMP-0084", "SMP-0085", "SMP-0086"]
STEM = "pocket_signals_v2"


def compose(bank: SampleLibrary) -> Module:
    module = Module("Pocket Signals V2", [Sample("empty", ())], [Pattern()], [0])
    # One reference palette: percussion plus a 112-byte bass cycle and 28-byte
    # melodic cycles, all fine tune 0. They share pitch classes two octaves apart.
    for index, sample_id in enumerate(PALETTE, 1):
        module, _ = bank.insert(module, sample_id)
        expected_loop = 112 if index == 4 else 28 if index >= 5 else 0
        sample = module.samples[index - 1]
        if sample.loop_length != expected_loop or sample.finetune:
            raise ValueError("This demo needs the selected bank's percussion, 112-byte bass and 28-byte melodic cycles.")
    roots = ["E-2", "C-2", "A-2", "B-2"]
    chord_roots = ["E-1", "C-1", "A-1", "B-1"]
    fifths = ["B-2", "G-2", "E-3", "F#3"]
    # Each event is (row in the bar, note, length). Rests and a recurring rhythm
    # make the hook recognizable; the last bar uses the leading note D#.
    theme = [
        [(0, "B-2", 2), (3, "G-2", 1), (4, "E-2", 3), (8, "G-2", 2), (10, "B-2", 3), (14, "F#2", 2)],
        [(0, "G-2", 3), (4, "E-2", 2), (6, "G-2", 2), (8, "C-3", 4), (13, "B-2", 1), (14, "G-2", 2)],
        [(0, "A-2", 2), (3, "C-3", 1), (4, "E-3", 3), (8, "D-3", 2), (10, "C-3", 3), (14, "B-2", 2)],
        [(0, "F#2", 3), (4, "D#3", 3), (8, "B-2", 4), (13, "D#3", 1), (14, "F#3", 2)],
    ]
    answer = [
        [(0, "E-3", 3), (4, "D-3", 2), (6, "B-2", 2), (8, "G-2", 3), (12, "B-2", 2), (14, "E-3", 2)],
        [(0, "E-3", 4), (4, "G-3", 3), (8, "E-3", 2), (10, "D-3", 2), (12, "C-3", 4)],
        [(0, "E-3", 2), (3, "C-3", 1), (4, "A-2", 3), (8, "C-3", 2), (10, "E-3", 3), (14, "F#3", 2)],
        [(0, "D#3", 4), (4, "F#3", 2), (6, "E-3", 2), (8, "D#3", 2), (10, "C-3", 2), (12, "B-2", 2), (14, "D#3", 2)],
    ]
    patterns = []
    for section in range(5):
        pattern = Pattern(name=["Tune the receiver", "Pocket theme", "Answering phrase", "A little space", "Theme returns"][section])
        for bar in range(4):
            start = bar * 16
            sparse = section == 3 or section == 0 and bar < 2
            for step in range(0, 16, 2):
                row = start + step
                if step in (0, 8) and (not sparse or step == 0):
                    pattern.put(row, 0, cell("C-1", 1, "C28"))
                elif step in (4, 12) and (not sparse or step == 12):
                    pattern.put(row, 0, cell("C-2", 2, "C1C" if step == 4 else "C21"))
                else:
                    pattern.put(row, 0, cell("C-3", 3, "C1A" if step % 4 else "C22"))
            if section in (2, 4) and bar == 3:
                for step, volume in ((13, 20), (14, 25), (15, 30)):
                    pattern.put(start + step, 0, cell("C-2", 2, f"C{volume:02X}"))
            for step in ((0, 8) if sparse else (0, 3, 6, 8, 11, 14)):
                bass_note = fifths[bar] if step in (6, 14) else roots[bar]
                pattern.put(start + step, 1, cell(bass_note, 4, "C23" if step in (0, 8) else "C1B"))
                pattern.put(start + min(15, step + (4 if sparse else 2)), 1, cell(effect="C00"))
            if not (section == 3 and bar < 2):
                for step in range(0, 16, 4):
                    pattern.put(start + step, 2, cell(chord_roots[bar], 8, "C0E"))
                    pattern.put(start + step + 1, 2, cell(effect="047" if bar in (1, 3) else "037"))
                    pattern.put(start + step + 2, 2, cell(effect="A01"))
                    pattern.put(start + step + 3, 2, cell(effect="C00"))
            if section == 0 and bar < 2:
                continue
            phrase = answer[bar] if section == 2 else theme[bar]
            for index, (step, note, length) in enumerate(phrase):
                if section == 3 and index not in (0, len(phrase) - 1):
                    continue
                row = start + step
                sample = 5 if step in (0, 8) else 6 + index % 5
                volume = 35 if step in (0, 8) else 29
                if section == 3:
                    volume = 24
                pattern.put(row, 3, cell(note, sample, f"C{volume:02X}"))
                if length >= 3:
                    pattern.put(row + 1, 3, cell(effect="413"))
                    pattern.put(row + length - 1, 3, cell(effect="C18"))
                # Place cuts only inside this bar; the next bar's note retriggers.
                if step + length < 16:
                    pattern.put(row + length, 3, cell(effect="C00"))
        patterns.append(pattern)
    patterns[0].put(0, 0, cell("C-1", 1, "F06"))
    patterns[0].put(0, 1, cell("E-2", 4, "F96"))
    patterns[0].put(0, 3, cell(effect="E01"))
    patterns[-1].put(63, 0, cell(effect="B00"))
    patterns[-1].put(63, 3, cell(effect="C00"))
    module.patterns, module.orders = patterns, list(range(5))
    module.metadata.update({
        "description": "Original 32-second four-channel composition using ten unchanged samples from the local library.",
        "display_description": "Ten samples from the library, a coherent palette and a new theme in call and response.",
        "arrangement": "Short introduction, theme, answer, breather and return. Only samples from the library; the notes and the arrangement are new.",
        "channel_names": ["Drums", "Bass", "Arpeggio", "Lead"],
        "timing": {"mode": "PAL CIA", "speed": 6, "bpm": 150},
        "sample_palette": {"imported": len(PALETTE), "newly_created": 0},
        "sample_policy": "library-only",
    })
    validate(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--output", type=Path, default=Path("exports/pocket_signals_v2"))
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--mp3", action="store_true")
    parser.add_argument("--with-xmp", action="store_true")
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        if output.exists():
            raise ValueError("Demo output must be a new directory.")
        if args.no_audio and (args.mp3 or args.with_xmp):
            raise ValueError("MP3 and XMP require audio rendering.")
        module = compose(SampleLibrary(args.library))
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".library-demo-", dir=output.parent) as temporary:
            folder = Path(temporary) / "demo"
            folder.mkdir()
            source = folder / f"{STEM}.project.json"
            project.write_json(source, project.to_dict(module))
            payload = mod.encode(project.load(source))
            module_path = folder / f"{STEM}.mod"
            project.atomic_bytes(module_path, payload)
            checks = {"mod_roundtrip_byte_exact": mod.encode(mod.read(module_path)) == payload,
                      "project_rebuild_byte_exact": mod.encode(project.load(source)) == payload,
                      "all_samples_from_library": len(module.samples) == len(PALETTE) and all(
                          sample == SampleLibrary(args.library).sample(sample_id)[0]
                          for sample, sample_id in zip(module.samples, PALETTE)),
                      "no_synthesis_recipes": all(sample.recipe is None for sample in module.samples)}
            renders = {}
            for index, sample in enumerate(module.samples, 1):
                audio.sample_preview(sample, folder / "samples" / f"{index:02d}.wav")
            if not args.no_audio:
                engines = ["openmpt", "xmp"] if args.with_xmp else ["openmpt"]
                for engine in engines:
                    filename = f"{STEM}.wav" if engine == "openmpt" else f"{STEM}.xmp.wav"
                    render = audio.render(module_path, folder / filename, engine=engine)
                    render["output"] = filename
                    renders[engine] = render
                    checks[f"{engine}_audible"] = render["audio"]["peak"] > .01
                    checks[f"{engine}_no_clipping"] = render["audio"]["clipped_samples"] == 0
                    checks[f"{engine}_full_cycle"] = abs(render["audio"]["duration_seconds"] - 32) < 1 / 48000
                if args.mp3:
                    audio.export_mp3(folder / f"{STEM}.wav", folder / f"{STEM}.mp3")
                write_preview(module, folder / "preview.html", f"{STEM}.wav", "validation.json",
                              f"{STEM}.mp3" if args.mp3 else None, language="fr")
            report = {"ok": all(checks.values()), "checks": checks, "renders": renders,
                      "duration_seconds": playback_plan(module)["duration_seconds"],
                      "not_validated": ["human listening", "physical audio output"]}
            project.write_json(folder / "validation.json", report)
            if not report["ok"]:
                raise ValueError("A demo audio or export check failed.")
            folder.rename(output)
        print(json.dumps({"ok": True, "output": str(output), "duration_seconds": 32,
                          "mod": str(output / f"{STEM}.mod"), "checks": checks}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
