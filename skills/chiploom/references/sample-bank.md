# Build a local sample bank from a module selection

Use this workflow when asked to reproduce the reference-to-bank process. Run from
the ChipLoom checkout with its Python interpreter. Replace example source paths
with the user's selection; do not fetch unrelated music or reuse developer-only IDs.

## Select sources

Accept an explicit list of MOD files, a ZIP of MODs, or a folder the user asks you to
curate. Inventory that collection without changing it. If choosing for a musical
brief, look for complementary percussion, bass and melodic sounds. Read-only
`analyze` reports can help inspect construction and loops, but counts do not prove
that a sample sounds good. Audition before settling on a palette.

Record the exact chosen paths in a local JSON list, for example
`exports/bank-build/selection.json`:

```json
[
  "path/to/first.mod",
  "path/to/second.MOD"
]
```

Use JSON as data, never interpolate its contents into shell source. Resolve relative
paths from the checkout; absolute paths must refer to the host running the agent.
A ZIP import reads **all** its MOD members. For a subset, create a separate local
ZIP containing only the selected members using an archive API; never extract
untrusted member paths or overwrite the original archive.

## Extract and audit

For one MOD or a complete selected ZIP:

```sh
python -m tracker4agents samples extract path/to/selection.zip --library exports/sample_library
python -m tracker4agents samples audit --library exports/sample_library
```

For an arbitrary list, run `samples extract` once per chosen input with the same
`--library` path, or execute this equivalent Python workflow. Save it as
`exports/bank-build/build.py` and run `python exports/bank-build/build.py`:

```python
import json
from pathlib import Path
from tracker4agents.sample_library import SampleLibrary

selection = Path("exports/bank-build/selection.json")
sources = json.loads(selection.read_text(encoding="utf-8"))
if not isinstance(sources, list) or not sources or not all(
    isinstance(item, str) and item.strip() for item in sources
):
    raise ValueError("Expected a nonempty JSON list of source paths")
paths = list(dict.fromkeys(Path(item).resolve() for item in sources))
for source in paths:
    if not source.is_file() or source.suffix.lower() not in {".mod", ".zip"}:
        raise ValueError(f"Missing or unsupported input: {source}")

bank = SampleLibrary(Path("exports/sample_library"))
report = {"imports": [], "failures": []}
for source in paths:
    try:
        result = bank.extract(source)
    except (OSError, ValueError) as exc:
        report["failures"].append({"source": str(source), "error": str(exc)})
    else:
        report["imports"].append({"source": str(source), **result})
try:
    report["audit"] = bank.audit()
except (OSError, ValueError) as exc:
    report["audit"] = {"ok": False, "error": str(exc)}
report["ok"] = not report["failures"] and report["audit"]["ok"]
selection.with_name("report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(report, indent=2, ensure_ascii=False))
raise SystemExit(0 if report["ok"] else 2)
```

Each input is checked before its bank update. If a later input fails, earlier
successful imports remain; report that partial outcome. Do not claim the whole
selection succeeded or delete a partially built bank. Fix the input list and retry:
reimport preserves existing IDs, edited labels and playback variants.

Extraction preserves exact signed 8-bit PCM, loops, fine tune and volume. Exact PCM
duplicates share storage; differing playback settings keep distinct entries. IDs
and neutral names are generated automatically. `library.json` and `pcm/` are local
bank data; original labels and source fingerprints stay in `private/provenance.json`.
Never invent sample counts or claim every historical MOD layout is supported.
Inputs are bounded to 4 MiB per MOD, 512 ZIP members and 64 MiB expanded ZIP data.
An analyzable reference need not be editable in the strict four-channel profile.

## Refine names and roles by audition

```sh
python -m tracker4agents samples list --library exports/sample_library --compatible --limit 20
python -m tracker4agents samples list --library exports/sample_library --tag bass-candidate --compatible --limit 8
```

Paginate with `--offset` and `--limit`. Pick a returned ID; the ID below is only an
example. Preview at several useful notes, inspect its loop and fine tune, and use
concise neutral ASCII names (22 characters maximum). Categories are `cycle`,
`percussion`, `texture`, `effect`, `unclassified` and `silent`.

```sh
python -m tracker4agents samples inspect SMP-0001 --library exports/sample_library
python -m tracker4agents samples preview SMP-0001 --library exports/sample_library --note A-1 --output exports/bank-build/audition-low.wav
python -m tracker4agents samples preview SMP-0001 --library exports/sample_library --note C-2 --output exports/bank-build/audition-mid.wav
python -m tracker4agents samples edit SMP-0001 --library exports/sample_library --name "Warm Pulse" --category cycle --tag bass-candidate --tag warm
```

`--tag` on `edit` replaces the full tag list; include any existing tags worth keeping.
Automatic names and `*-candidate` roles are signal-based suggestions. Only call a
label audition-reviewed if someone actually listened. Rendering a WAV alone is not
listening. If playback is unavailable, keep provisional labels and offer the local
auditions or a catalog to the human. The optional catalog command is
`python tools/create_sample_catalog.py --library exports/sample_library --output exports/bank-catalog`
and requires a new output directory. Neither the catalog nor the bank is published.

## Make a small original MOD to test reuse

Create a blank project with `new`, select compatible samples from this bank, then use
repeated `samples add` calls (or `library_sample` patch operations):

```sh
python -m tracker4agents new --output exports/bank-test/blank.project.json --title "Bank test"
python -m tracker4agents samples add SMP-0001 --library exports/sample_library --project exports/bank-test/blank.project.json --output exports/bank-test/project.json
python -m tracker4agents validate exports/bank-test/project.json --report
```

Insertion only adds an instrument: write new notes/patterns in the returned slots
before exporting a short loop. Use the main skill's validation, MOD export and render
commands. Do not use `tools/create_library_demo.py` as a generic bank test: its
fixed palette expects the developer's private bank. A user's bank has its own IDs.

Report selected input count, successful/failed imports, total entries, unique PCM,
compatible/incompatible counts and the paths to the bank and test artifacts. Never
force-adapt incompatible sounds. Explain any explicitly chosen `--adapt` changes.
In the human window, choose the bank folder under the bottom **Sample library** tab;
search, filter, listen and add to a song there. The four tracker channels keep their
width. Bank data, source lists, provenance, reports and borrowed-sample test music
stay local; a skill folder contains instructions only, no reference PCM.
