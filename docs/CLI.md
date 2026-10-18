# ChipLoom command reference

Use `chiploom` after editable installation, or `python -m tracker4agents` from the checkout. The examples below use the module form to make the chosen interpreter explicit.

| Command | Input | Result |
| --- | --- | --- |
| `demo` | Built-in song and seed | Reproduces an original example, MOD and project; optional renders |
| `inspect` | Strict MOD or JSON | Structured summary; optional 64-row pattern |
| `validate` | Strict MOD or JSON | Playback plan, duration warnings; `--report` collects independent JSON errors |
| `estimate` | Order count, speed, BPM, rows | Constant-timing duration estimate without a source file |
| `import` | Strict MOD | JSON with PCM; no inferred synthesis recipes |
| `export` | JSON project | Real self-contained MOD |
| `render` | Strict MOD | WAV from the actual MOD; optional MP3 |
| `preview` | Strict MOD or JSON | New portable HTML/media directory |
| `analyze` | Reference MOD or ZIP | Read-only aggregate report; broader than editable profile |
| `samples` | Local sample bank, reference MOD/ZIP or project | Extract, search, inspect, audition, edit labels, insert and audit |
| `gui` | Optional MOD or JSON | Native human window, optional dependency required |

## Common commands

```sh
python -m tracker4agents --version
python -m tracker4agents demo --song first-light --output exports/first-light --no-audio
python -m tracker4agents demo --song pixel-rush --mp3
python -m tracker4agents inspect examples/pixel_rush.project.json --pattern 0
python -m tracker4agents validate examples/pixel_rush.project.json
python -m tracker4agents export examples/pixel_rush.project.json --output exports/custom.mod
python -m tracker4agents import exports/custom.mod --output exports/imported.project.json
python -m tracker4agents render exports/custom.mod --output exports/custom.wav --mp3-output exports/custom.mp3
python -m tracker4agents preview exports/custom.mod --output exports/custom-review --mp3 --language fr
python -m tracker4agents analyze path/to/modules.zip --output exports/study.json --probe
python -m tracker4agents gui examples/pixel_rush.project.json
```

`preview --output` is a **new directory**, not an HTML filename. It renders one complete supported cycle and creates `preview.html`, `module.mod`, `module.project.json`, `module.wav`, `validation.json`, sample WAVs, and optionally `module.mp3`. It publishes the directory only after successful completion. The HTML player loops from the module's computed restart time after the first pass.

`analyze --output` is a JSON filename. `--probe` adds ffprobe/libopenmpt duration estimates. Without that flag, analysis uses only the standard library. Per-file failures appear under `analysis_error`; successful entries remain in the report. A report with any failed file returns exit code 2. `editable_in_current_profile: false` is a compatibility fact, not an analysis failure. Archives are limited to 512 entries and 64 MiB expanded; each MOD is limited to 4 MiB.

`render` supports `--engine openmpt|xmp`, `--seconds` (greater than 0, at most 120), `--sample-rate` (8000–96000), `--ffmpeg` and `--xmp-library`. `preview` also accepts `--ffmpeg`. XMP requires the optional separately built reference library.

`gui --state-dir PATH` chooses a session/cache folder. `gui --no-restore` skips the previous file and uses a built-in example when no input is supplied. Language and theme are selected in the window and stored there.

## Response contract

Successful non-GUI operations emit JSON to stdout. Runtime, input and rendering failures emit `{"ok": false, "error": "...", "message": "..."}` to stderr with code 2. Normal argument-parser errors, help and version are text. Some core diagnostics retain their original French wording; scripts should use exit status and structured fields, not parse a translated sentence.

The analysis command returns a compact report location and count to stdout, with detailed per-file facts in its output JSON. Rendering validates the MOD before launching a decoder. Export validates before replacing its destination. Source and output must differ for import, export and analysis.

## Output ownership

Export, import, render and analysis may replace the explicitly requested output file after validation. Preview refuses an existing output directory. Demo output is reproducible generated content and may be refreshed in its designated directory. Always choose output paths separate from user-supplied references.

Generated files can contain the project's user-authored metadata and music. Review a bundle before publishing it. ChipLoom does not upload it automatically.

## Local sample library

The library is optional and uses only the standard library. Its default location is
`exports/sample_library`, relative to the working directory. Every subcommand accepts
`--library PATH` after the subcommand. Library data and its private provenance stay local.

```sh
python -m tracker4agents samples extract path/to/selection.zip --library exports/sample_library
python -m tracker4agents samples audit
python -m tracker4agents samples list --category cycle --tag bass-candidate --compatible --limit 10
python -m tracker4agents samples list --query smooth --offset 0 --limit 10
python -m tracker4agents samples inspect SMP-0001
python -m tracker4agents samples preview SMP-0001 --note C-2 --seconds 1 --output exports/auditions/pulse.wav
python -m tracker4agents samples edit SMP-0001 --name "Warm Pulse" --category cycle --tag bass-candidate --tag warm
python -m tracker4agents samples add SMP-0001 --project exports/song/project.json --output exports/song/with-pulse.project.json
```

`extract` accepts the same bounded 31-sample layouts as structural analysis, including
the supplied two-channel references. Unsupported patterns/restart bytes do not prevent
reading their samples. It validates all layouts before updating a bank; malformed or
unsupported layouts fail rather than producing a partial import. Archive paths are never
extracted. Limits are 512 members, 64 MiB expanded ZIP data and 4 MiB per MOD.

The manifest `library.json` contains stable `SMP-0001` IDs, neutral names, PCM digests,
playback settings, measured features and editable labels. `pcm/` holds exact signed
8-bit bytes, with one file per distinct payload. Different loop, volume or fine-tune
settings remain separate entries. Original filenames, titles, sample labels and source
fingerprints exist only in `private/provenance.json`; ordinary search/inspect results
do not include them. A generated `.gitignore` excludes bank contents from Git.

Reimport preserves IDs, user-edited names/tags and playback variants. Only one writer
may update a bank at a time. A stale `.write.lock` left by a terminated process must be
removed only after checking that no writer is running. The manifest is replaced last;
an interrupted update can leave unreferenced PCM files, never a partially written PCM
or manifest. Automatic multi-process editing is not supported.

Categories are `cycle`, `percussion`, `texture`, `effect`, `unclassified` and `silent`.
Roles such as `bass-candidate` are heuristic suggestions, not a listening verdict.
`list` supports all requested `--tag` filters, case-insensitive query words, pagination
and `--compatible`. `inspect` returns the complete entry and checks the stored PCM.
`audit` verifies every referenced payload and recomputes compatibility with the current
MOD profile. It does not rewrite imported sounds.

`preview` produces a mono 44.1 kHz PCM16 WAV for a tracker note C-1 through B-3, with
0.05–5 seconds duration. It honors volume, loop and fine tune, using nearest-neighbor
sampling and a fine-tune frequency approximation. It is an audition without pattern
effects, not a reference MOD replay or an estimate of the original recording rate.
Preview output must be outside the bank. Invalid loops or volumes are rejected.

`add` outputs a complete editable JSON project, embedding PCM and settings. Output must
differ from input and be outside the bank. Without `--slot`, it uses an unreferenced empty
slot or appends a slot. Occupied slots require explicit `--slot N --replace`; MOD has at
most 31 slots. No existing notes or sample numbers are shifted. A bank is not needed to
reopen that JSON or play its exported MOD.

`--adapt` explicitly permits two limited changes on an inserted copy of a one-shot:
clear an inactive loop start, and prepend two zero bytes when required by the strict
MOD profile. Original PCM is retained, and the project records the adaptations. Oversized
samples, invalid active loops and other unsupported settings still fail validation.

For a local listening catalog and the original test composition using the selected bank:

```sh
python tools/create_sample_catalog.py --library exports/sample_library --output exports/sample_catalog
python tools/create_library_demo.py --library exports/sample_library --output exports/pocket_signals_v2 --mp3 --with-xmp
```

Both tools require a new output directory. The catalog contains neutral names and raw
auditions; the current demo, Pocket Signals V2, uses ten selected bank IDs exclusively,
with new notes and arrangement. It checks that every embedded sample equals its library
entry. This demo requires the developer's private bank: it is not a generic composer
for an arbitrary bank. For a user's own module list, use the reproducible
[skill workflow](../skills/chiploom/references/sample-bank.md), discover that bank's
IDs and write a new test score. New sample synthesis is deferred in the current composition workflow.
`--with-xmp` needs the optional libxmp setup; omit it
for libopenmpt alone. `--no-audio` builds the MOD/project without external decoders.

The optional native window exposes the same bank in its bottom **Sample library**
tab. Search and auditions run without changing the score. Insertion goes through
`Document.insert_library_sample`, so the change is undoable and embeds PCM in the
project. The GUI remembers its selected bank folder; the CLI's default path remains
relative to the working directory. The human can choose a different folder without
changing any CLI configuration. See [the French desktop guide](USAGE_FR.md#bibliothèque-de-samples-dans-la-fenêtre).

## Planning and diagnostics (v0.5.0)

```sh
python -m tracker4agents estimate --orders 18 --speed 6 --bpm 125
python -m tracker4agents validate examples/pixel_rush.project.json --report
python -m tracker4agents render docs/listen/media/voltage_odyssey_v2.mod --from-order 6 --seconds 10 --output exports/drop.wav
```

`estimate` accepts `--orders` 1–128, `--rows` 1–64 (default 64), `--speed` 1–31 (default 6) and `--bpm` 33–255 (default 125), all decimal integers. It returns seconds per order, total duration, assumptions and warnings. It assumes constant timing and no jumps or early breaks.

`inspect` and successful `validate` responses now include `warnings: []`. A duration over 120 seconds adds a warning while retaining `ok: true`: render bounds do not make a MOD invalid.

For JSON, `validate --report` collects independent structural errors as `errors: [{"path": "...", "message": "..."}]` plus `error_count`. On failure it uses stderr / exit 2, retaining the normal error envelope; success uses stdout / exit 0 and an empty error array. One primary error per field/sample/event and additional collisions are reported. Dependent timing checks run only after the score is structurally valid. Unparseable JSON or MOD data returns the usual single decoding error. No source is modified.

`render --from-order N` selects the first reached entry into zero-based order N. It decodes the prefix to retain state, then cuts at the nominal playback-plan timestamp. Small native replay timing differences remain possible. Both engines support it. Preroll must be at most 600 seconds; output is still limited to 120 seconds. If `--seconds` is absent, render the remainder of the first cycle. The response includes `from_order` (null when omitted) and `start_seconds`; excerpt trace timestamps are relative to the output, while order/row indices remain those of the original MOD.
