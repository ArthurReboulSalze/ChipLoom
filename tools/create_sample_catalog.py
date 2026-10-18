"""Create a local neutral-name listening catalog; reference data stays local."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker4agents import project
from tracker4agents.sample_library import DEFAULT_LIBRARY, SampleLibrary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--output", type=Path, default=Path("exports/sample_catalog"))
    args = parser.parse_args()
    try:
        bank, output = SampleLibrary(args.library), args.output.resolve()
        if output.exists() or output.is_relative_to(bank.path):
            raise ValueError("Catalog requires a new output directory outside the bank.")
        entries = bank.search(limit=500)["samples"]
        if bank.search(limit=1)["total"] > 500:
            raise ValueError("This listening catalog supports at most 500 entries.")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".sample-catalog-", dir=output.parent) as temporary:
            folder = Path(temporary) / "catalog"
            folder.mkdir()
            cards = []
            for entry in entries:
                info = bank.get(entry["id"])
                raw = (bank.path / info["pcm"]).read_bytes()
                values = [value if value < 128 else value - 256 for value in raw]
                # A peak envelope keeps short transients visible in long samples.
                width = min(256, len(values))
                points = []
                for index in range(width):
                    block = values[index * len(values) // width:(index + 1) * len(values) // width]
                    value = max(block, key=abs)
                    points.append(f"{index * 300 / max(1, width - 1):.2f},{40 - value * .28:.2f}")
                filename = f"samples/{entry['id']}.wav"
                preview = bank.audition(entry["id"], folder / filename, note="C-2", seconds=.8)
                status = "Ready for MOD" if entry["compatible"] else "MOD adaptation required"
                tags = " · ".join(entry["tags"])
                cards.append(f'<article id="{entry["id"]}"><small>{entry["id"]} · {escape(entry["category"])}</small>'
                    f'<h2>{escape(entry["name"])}</h2><svg viewBox="0 0 300 80" aria-label="Waveform">'
                    f'<path d="M0 40H300" stroke="#35405c"/><polyline points="{" ".join(points)}" '
                    'fill="none" stroke="#91e8cd" stroke-width="1.4"/></svg>'
                    f'<p>{entry["bytes"]} bytes · loop {entry["loop_start"]}+{entry["loop_length"]} · '
                    f'fine tune {entry["finetune"]} · volume {entry["volume"]}</p>'
                    f'<p>{escape(tags)}</p><audio controls preload="none" src="{filename}"></audio>'
                    f'<small>{status}</small></article>')
            page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ChipLoom · Sample Library</title>
<style>body{margin:0;background:#101525;color:#e8f0ff;font:15px system-ui}header,main{max-width:1240px;margin:auto;padding:24px}
h1{font-size:32px;margin-bottom:8px}header p{color:#b8c7e0;max-width:850px;line-height:1.5}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;padding-top:0}
article{background:#1a2338;border:1px solid #35405c;border-radius:12px;padding:18px}h2{font-size:19px;margin:8px 0}
small{color:#92c9ff}article p{color:#bac8dd;font-size:12px;line-height:1.5}svg,audio{width:100%;display:block}
audio{margin:15px 0}a{color:#91e8cd}article:target{outline:2px solid #91e8cd}</style>
<header><h1>ChipLoom · Sample Library</h1><p>COUNT neutral sample entries. Original PCM, loop, fine tune and volume.
Auditions play at tracker C-2, without pattern effects. Use Ctrl+F to find a name, ID or tag.
Categories describe signal-based suggestions and can be edited through the agent tools.</p>
<p>This is a local listening catalog. The JSON project and exported MOD embed their own samples.</p></header><main>CARDS</main></html>'''
            page = page.replace("COUNT", str(len(entries))).replace("CARDS", "\n".join(cards))
            project.atomic_bytes(folder / "index.html", page.encode("utf-8"))
            project.write_json(folder / "catalog.json", {"schema": "chiploom.sample-catalog.v1", "samples": entries})
            folder.rename(output)
        print(json.dumps({"ok": True, "entries": len(entries), "catalog": str(output / "index.html")}, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
