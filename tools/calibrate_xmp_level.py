"""Measure libxmp's level against libopenmpt for every format and channel count.

    python tools/calibrate_xmp_level.py [--channels 2-32]

Each case is one pulse note repeated on channel 0 of an otherwise empty song (centred in an XM, the
default MOD panning in a MOD), rendered for two seconds by both engines. The script prints, per channel
count, the remaining gap (libxmp minus libopenmpt, RMS dB) with the current table and the master volume
that would close it; paste the suggested tuples into `LEVEL_TO_OPENMPT` in tracker4agents/_xmp_worker.py.
It needs FFmpeg with libopenmpt and the libxmp library from tools/setup_reference.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker4agents import formats, synth_tools, xm  # noqa: E402
from tracker4agents._xmp_worker import master_volume  # noqa: E402
from tracker4agents.audio import render  # noqa: E402
from tracker4agents.model import Pattern, cell  # noqa: E402


def probe(fmt: str, channels: int):
    if fmt == "xm":
        module = xm.blank("Level probe", channels=channels)
        synth_tools.insert_recipe(module, "Pulse", {"type": "wave", "shape": "pulse"}, slot=1, volume=64)
        note = "C-4"
    else:
        module, _ = synth_tools.palette("Level probe", channels=channels)
        module.patterns, module.orders, note = [Pattern("Probe", {}, 64)], [0], "C-2"
    for row in range(0, 64, 8):
        module.patterns[0].put(row, 0, cell(note, 1, "000", fmt))
    return module


def gap(module, folder: Path) -> float:
    source = folder / f"probe{formats.extension(module)}"
    source.write_bytes(formats.encode(module))
    levels = {engine: render(source, folder / f"{engine}.wav", engine=engine, seconds=2)["audio"]["rms_dbfs"]
              for engine in ("openmpt", "xmp")}
    return levels["xmp"] - levels["openmpt"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--channels", default="2-32", help="a range such as 2-32 or one count")
    args = parser.parse_args()
    low, _, high = args.channels.partition("-")
    counts = range(int(low), int(high or low) + 1)
    rows, suggested = [], {"mod": [], "xm": []}
    with tempfile.TemporaryDirectory() as folder:
        for channels in counts:
            row = {"channels": channels}
            for fmt in ("mod", "xm"):
                volume = master_volume(fmt, channels)
                remaining = gap(probe(fmt, channels), Path(folder))
                best = min(200, max(1, round(volume * 10 ** (-remaining / 20))))
                row[fmt] = {"volume": volume, "gap_db": round(remaining, 2), "suggested": best}
                suggested[fmt].append(best)
            rows.append(row)
            print(json.dumps(row), flush=True)
    print(json.dumps({"suggested": suggested}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
