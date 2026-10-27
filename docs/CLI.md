# ChipLoom command reference

Use `chiploom` after editable installation, or `python -m tracker4agents` from the checkout. The examples below use the module form to make the chosen interpreter explicit.

| Command | Input | Result |
| --- | --- | --- |
| `demo` | Built-in song and seed | Reproduces an original example, MOD and project; optional renders |
| `inspect` | Strict MOD or JSON | Structured summary; optional pattern as rows or `--grid` tracker text |
| `validate` | Strict MOD or JSON | Playback plan, duration warnings; `--report` collects independent JSON errors with codes |
| `estimate` | Order count, speed, BPM, rows | Constant-timing duration estimate without a source file |
| `import` | Strict MOD | Schema v2 JSON with PCM; no inferred synthesis recipes |
| `migrate` | Project v1/v2 or MOD | Compact schema v2 project; the MOD it encodes is unchanged |
| `patch` | Project (or MOD) and a list of operations | New editable project; all operations apply or none does |
| `export` | JSON project | Real self-contained MOD |
| `render` | Strict MOD | WAV from the actual MOD; optional MP3 |
| `preview` | Strict MOD or JSON | New portable HTML/media directory |
| `analyze` | Reference MOD or ZIP | Read-only aggregate report; broader than editable profile |
| `report` | Project or MOD | Measurements of the played score: density, ranges, gaps, repetition, estimated key |
| `compare` | Two projects or MODs | New directory with a blind A/B listening page |
| `feedback` | Project | New project with the owner's listening feedback in its metadata |
| `live` | Running window or headless session | Compose together: read, patch, propose, announce takes, drive playback |
| `mcp` | MCP client on stdin/stdout | Model Context Protocol adapter over these commands |
| `samples` | Local sample bank, reference MOD/ZIP or project | Extract, search, inspect, audition, edit labels, insert and audit |
| `gui` | Optional MOD or JSON | Native human window, optional dependency required |

## Common commands

```sh
python -m tracker4agents --version
python -m tracker4agents demo --song first-light --output exports/first-light --no-audio
python -m tracker4agents demo --song pixel-rush --mp3
python -m tracker4agents inspect examples/pixel_rush.project.json --pattern 0 --grid --rows 8
python -m tracker4agents validate examples/pixel_rush.project.json
python -m tracker4agents patch examples/pixel_rush.project.json --output exports/variation.project.json --op '{"op": "transpose", "pattern": 1, "channel": 1, "semitones": 2}'
python -m tracker4agents export exports/variation.project.json --output exports/custom.mod
python -m tracker4agents report exports/variation.project.json
python -m tracker4agents migrate examples/pixel_rush.project.json --output exports/pixel_rush.v2.project.json
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

Successful non-GUI operations emit JSON to stdout. Runtime, input and rendering failures emit `{"ok": false, "error": "...", "code": "...", "message": "..."}` to stderr with exit status 2; see [Error contract and codes](#error-contract-and-codes). Normal argument-parser errors, help and version are text. Some core diagnostics retain their original French wording; scripts should use exit status and the `code` field, not parse a sentence.

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

For JSON, `validate --report` collects independent structural errors as `errors: [{"path": "...", "code": "...", "message": "..."}]` (plus `message_fr` when translated) and `error_count`. On failure it uses stderr / exit 2, retaining the normal error envelope; success uses stdout / exit 0 and an empty error array. One primary error per field/sample/event and additional collisions are reported. Dependent timing checks run only after the score is structurally valid. Unparseable JSON or MOD data returns the usual single decoding error. No source is modified.

`render --from-order N` selects the first reached entry into zero-based order N. It decodes the prefix to retain state, then cuts at the nominal playback-plan timestamp. Small native replay timing differences remain possible. Both engines support it. Preroll must be at most 600 seconds; output is still limited to 120 seconds. If `--seconds` is absent, render the remainder of the first cycle. The response includes `from_order` (null when omitted) and `start_seconds`; excerpt trace timestamps are relative to the output, while order/row indices remain those of the original MOD.

## Project files (schema v2)

New projects are written as `tracker4agents.project.v2`. Version 1 files still load and validate; `chiploom migrate` rewrites them. The score the file describes does not change: `migrate` refuses to write if the MOD encoded from the new file would differ from the old one.

```sh
python -m tracker4agents migrate old.project.json --output new.project.json
python -m tracker4agents migrate song.mod --output song.project.json
```

```json
{
  "ok": true,
  "source_schema": "tracker4agents.project.v1",
  "schema": "tracker4agents.project.v2",
  "source_bytes": 191941,
  "output_bytes": 33774,
  "mod_sha256": "1ce068af..."
}
```

`--output` must be a new `.json` path different from the source. On the included examples, `pixel_rush` goes from 192 KB (v1) to 34 KB, and `voltage_odyssey_v2` from 690 KB to 117 KB. A MOD source has no recipes, so its samples are stored as PCM.

What changed in v2:

- **Samples** store `pcm_base64` and `pcm_sha256` (plus `loop_start` and `loop_length`) instead of a list of integers, or carry a `recipe`. The hash is verified on load; a mismatch is rejected (`SAMPLE_PCM_HASH`), so a hand-edited payload is never silently accepted.
- **Patterns** are written as grid `rows`. Each key is a two-digit hexadecimal row `00`–`3F`; each value has four cells separated by `|`. A cell is `NOTE SS EEE`: note (`C-2`, `G#3`) or `---`, sample number in hexadecimal or `--`, effect in hexadecimal or `...`. Rows with no content are left out.

```json
{"name": "Boot", "rows": {
  "00": "C-2 04 F06 | E-1 06 FA0 | E-2 08 037 | E-2 0A E01",
  "01": "--- -- ... | --- -- A03 | --- -- 037 | --- 0B 412"
}}
```

- A pattern uses either `rows` or the sparse `events` layout (`{"row": 8, "channel": 3, "note": "E-3", "sample": 8, "effect": "C27"}`), never both. v2 reads both; v1 files only have `events`. New files are written with `rows`.
- Files are written compactly: one line per sample, per row and per event, so a Git diff shows which rows changed.

`inspect --pattern N --grid` prints the same grid text for any project or MOD, and works with `--row R --rows K` to show part of a pattern:

```sh
python -m tracker4agents inspect examples/pixel_rush.project.json --pattern 0 --grid --row 0 --rows 4
```

```json
"pattern": {
  "index": 0,
  "name": "Boot",
  "columns": "row | track 1 | track 2 | track 3 | track 4 (note sample effect)",
  "grid": [
    "00 | C-2 04 F06 | E-1 06 FA0 | E-2 08 037 | E-2 0A E01",
    "01 | --- -- ... | --- -- A03 | --- -- 037 | --- 0B 412",
    "02 | --- -- ... | --- -- C00 | --- -- 037 | --- -- 603",
    "03 | --- -- ... | E-1 06 C22 | --- -- C0E | --- -- C00"
  ]
}
```

`--grid`, `--row` and `--rows` need `--pattern N` (otherwise the command fails with `PATCH_FIELD`). Without `--grid`, `--pattern` keeps the earlier `rows`/`cells` shape. `import` also writes schema v2.

## Patch

`patch` applies a list of operations to a copy of a project and writes the result. The operations form **one transaction**: if any fails, or the final score does not validate, nothing is written. A failure names the operation, for example `ops[1] (set): …`. Patterns, orders, rows and channels are zero-based; sample slots are 1–31. Cells use the grid text above.

```sh
python -m tracker4agents patch exports/song/project.json --output exports/song/v2.project.json \
  --label "Lift lead" \
  --op '{"op": "set", "pattern": 0, "row": 4, "channel": 0, "cell": "E-2 04 C28"}' \
  --op '{"op": "write", "pattern": 0, "row": 8, "channel": 1, "cells": ["C-2 06 ...", "", "E-2 06 C20"], "step": 2}'

echo '[{"op": "transpose", "pattern": 0, "row": 0, "rows": 16, "channel": 1, "semitones": 12},
       {"op": "add_pattern", "copy_of": 0, "name": "Boot B"}]' \
  | python -m tracker4agents patch exports/song/v2.project.json --output exports/song/v3.project.json --ops -
```

| Option | Meaning |
| --- | --- |
| `SOURCE` | Project JSON, or a MOD (the result is still an editable `.json` project) |
| `--output PATH` | Edited `.json` project. Writing over the source needs `--in-place` |
| `--ops FILE` | JSON file with a list of operations; `-` reads standard input |
| `--op JSON` | One operation (or a list) as JSON; repeat for several. Give either `--ops` or `--op` |
| `--label TEXT` | Name for the change history (default `Patch`) |
| `--in-place` | Allow `--output` to be the source |

`--ops` also accepts a single operation object, or `{"ops": [...], "base_revision": N, "label": "..."}`. A patch holds at most 2000 operations. The result:

```json
{
  "ok": true,
  "output": "…/out1.json",
  "changed": true,
  "results": [{"op": "set"}, {"op": "write"}],
  "changes": [
    "P00 r04 ch1: C-2 05 C31 → E-2 04 C28",
    "P00 r08 ch2: E-1 06 C2B → C-2 06 ...",
    "P00 r0A ch2: B-1 06 C22 → --- -- ...",
    "P00 r0C ch2: E-1 06 C22 → E-2 06 C20"
  ],
  "cells_changed": 4,
  "duration_seconds": 48.0,
  "warnings": []
}
```

`changes` lists up to 40 lines (`P00 r04 ch1` is pattern 0, row `04`, channel 1 as displayed) and ends with a count when more cells changed; order, pattern-count, sample and title changes get their own lines. `results` has one entry per operation; `add_pattern` and `insert_order` report the new `pattern` and `order` index.

### Operations

Every operation is an object with an `"op"` and the fields below. Unknown fields are rejected (`UNKNOWN_FIELD`). A **block** is `row` (default 0), `rows`, `channel` (default 0) and `channels`; it must stay inside rows 0–63 and channels 0–3.

| `op` | Fields | Effect |
| --- | --- | --- |
| `set` | `pattern`, `row`, `channel`, then `cell` (`"E-2 04 C28"`) **or** any of `note`, `sample` (0–31), `effect` | Replace one cell. With `note`/`sample`/`effect`, fields you omit keep their current value; `note: "---"` or `effect: "..."` clears that part |
| `write` | `pattern`, `row` (default 0), `step` (default 1, 1–64), and either `cells` + `channel`, or `lines` | `cells`: consecutive cells down one channel, `step` rows apart. `lines`: whole grid rows across all four channels (`"C-2 04 C38 \| --- -- ... \| …"`, an optional `00 \|` row prefix is accepted); do not give `channel`. An empty string or `---` clears that cell |
| `clear` | `pattern` + block (`rows` and `channels` default 1) | Empty a block |
| `copy` | `pattern` + block (defaults 1 row, 1 channel), `to_pattern`, `to_row`, `to_channel` (default: same place) | Copy a block, possibly to another pattern |
| `move` | same fields as `copy` | Copy, then empty the source block |
| `transpose` | `pattern`, `semitones` (−35 to 35) + block | Shift notes only. Block defaults differ: from `row` to the end of the pattern, 1 channel. Leaving `C-1`–`B-3` fails (`NOTE_RANGE`) |
| `add_pattern` | optional `copy_of`, `name`, `insert_order` | Append a pattern (empty, or a copy), at most 64. It is also appended to the order list by default; `insert_order` is a position, `"end"` or `null` for none |
| `remove_pattern` | `pattern` | Delete a pattern that no order uses; later patterns are renumbered in the order list |
| `rename_pattern` | `pattern`, `name` (at most 64 characters) | Rename |
| `set_orders` | `orders` (list of pattern indices) | Replace the whole order list. The last stored pattern must appear in it |
| `insert_order` | `pattern`, optional `at` (default: end) | Insert one order |
| `remove_order` | `at` | Delete one order |
| `move_order` | `at`, `to` | Move one order |
| `title` | `title` | Set the module title (ASCII, validated) |
| `timing` | `bpm` (33–255), `speed` (1–31) | Write `Fxx` speed and BPM on the first played row. Needs two free effect columns there or existing `Fxx` effects, otherwise `TIMING`; other effects are never overwritten |
| `sample` | `slot` (1–31), optional `volume` (0–64), `finetune` (−8 to 7), `name` | Change a sample's playback settings or name. PCM is never touched |
| `library_sample` | `library`, `id`, optional `slot`, `replace`, `adapt` | Insert a library entry exactly like `samples add`: exact PCM, occupied slots need `slot` + `replace`, `adapt` only for the documented one-shot adaptation |

`timing`, `Fxx` effects and any order operation change the playback plan, so read `duration_seconds` and `warnings` in the result.

Errors in a patch use these codes: `PATCH_FORMAT` (not JSON, empty list, more than 2000 operations), `PATCH_OP` (unknown operation), `PATCH_FIELD` (missing, conflicting or wrongly typed field), `PATCH_CELL` (unreadable cell text), `PATCH_BOUNDS` (block or written rows past row 63 or channel 3), plus the score codes (`NOTE_UNKNOWN`, `NOTE_RANGE`, `ORDERS`, `PATTERNS`, `SAMPLE_SLOT`, …) when the edited score is invalid.

```json
{"ok": false, "error": "ValidationError", "code": "PATCH_OP",
 "message": "ops[0] (fly): unknown operation; use one of ['add_pattern', 'clear', 'copy', …]."}
```

## Measuring and comparing versions

### report

```sh
python -m tracker4agents report exports/song/project.json
```

`report` takes a project or MOD and prints `chiploom.report.v1` JSON. Everything in it is a **measurement of the symbolic score along its playback timeline** (first replay cycle, with repeated orders, jumps and tempo changes counted as played). It does not render audio and is not a quality verdict. The `scope` field says so in the output itself.

| Section | Contents |
| --- | --- |
| `timing` | Duration, loop start and length, rows and orders played, speed and BPM range, tempo changes |
| `channels` | Per channel: note starts, notes per second, density, lowest and highest note, range, samples used, effects used, portamento targets, longest gap without a note |
| `global` | Note starts, rows with and without a note start, pitch-class counts, and a `key_estimate` |
| `repetition` | Identical patterns, distinct pattern contents, patterns never played, repeated-block fractions for 4-, 8- and 16-row blocks |
| `samples` | Per slot: size, loop, volume, note starts, channels; empty and never-played slots |
| `warnings` | Duration and other warnings |

The key is the only estimate: a correlation with standard major and minor profiles, labelled `is_estimate: true` with a margin and a confidence level whose thresholds are heuristics chosen for this tool. Tracker note names are period labels and sample tuning is unknown, so the sounding pitch can differ from the written note. A "row without a note start" is not audible silence, because sustained or looped samples keep sounding.

### compare

```sh
python -m tracker4agents compare exports/song/v1.project.json exports/song/v2.project.json \
  --output exports/song-compare --seconds 20 --labels "Original" "Lift lead" --seed 7 --mp3 --language en
```

`compare` renders both versions and builds a **blind A/B page** in a new (or empty) directory: `index.html`, neutral-named `x.wav`/`y.wav` (plus `x.mod`, `y.mod` and optional MP3 copies) and `comparison.json`. Which version is X is random; `--seed` makes it repeatable. After the listener chooses a preference, optionally rates melody, groove, sound palette and arrangement, and submits, the page reveals the versions and shows per-version measurements.

| Option | Meaning |
| --- | --- |
| `FIRST`, `SECOND` | Two projects or MODs, different files |
| `--output DIR` | New or empty directory; it must not contain a source file |
| `--seconds S` | Render the same excerpt length (greater than 0, at most 120) from the start of both. Without it each version's full first cycle is rendered, and a cycle over 120 s is refused |
| `--labels A B` | Names shown after the reveal (default derived from the file names); they must differ |
| `--seed N` | Seed for the X/Y assignment |
| `--mp3`, `--ffmpeg`, `--language en\|fr` | MP3 copies, FFmpeg path, page language |

The result includes `answer_key` (also in `comparison.json`) and the paths. This is a **casual blind test, not secrecy**: the answer is in `comparison.json` and, base64-encoded, in the page source. **Loudness is not equalized**: a louder version tends to be preferred, so the page shows the measured peak and RMS of both renders after submission. An agent that reads `comparison.json` before the owner listens has spoiled the test.

### feedback

```sh
python -m tracker4agents feedback exports/song/v1.project.json --text "Bass is too busy in the second half" \
  --rating 3 --version v1 --output exports/song/v1-feedback.project.json
```

`feedback` copies a project to a **new** `.json` file with an entry appended to `metadata.feedback`: `{"text", "rating", "source", "version", "recorded_at"}`. `--rating` is an integer 1–5 and optional, `--source` defaults to `owner`, `--version` should match the label you gave the version you asked about. Text is limited to 2000 characters without control characters. Feedback is recorded, not interpreted; it does not change the score or any model.

## Live sessions

`live` lets an agent compose together with the owner. A **session** is a project open in the ChipLoom window, or hosted headless by `chiploom live serve`. The agent's commands talk to it through a localhost server, so edits appear in the window immediately, can be undone there, and are listed in a journal that records who made them.

- The server binds to loopback only (`127.0.0.1` or `::1`), requires a bearer token and refuses browser requests. Request bodies are limited to 2 MiB.
- Discovery: each running session writes `live/<pid>.json` (URL, token, file, title, kind) under `CHIPLOOM_HOME`. The default is `%LOCALAPPDATA%\ChipLoom` on Windows and `$XDG_STATE_HOME/chiploom` (or `~/.local/state/chiploom`) elsewhere. Stale files from dead processes are cleaned up. `live sessions` never prints the token.
- `--session PID_OR_URL` (before or after the subcommand) picks a session; the default is the newest.
- The author `human` is reserved for edits made in the window. An agent's `--author` (default `agent`) must be 1–32 letters, digits, space, `_`, `.` or `-`.
- `revision` counts journal entries from anyone. It is the number to remember and pass back as `--base`.

| Command | Purpose |
| --- | --- |
| `live sessions` | List running sessions: `pid`, `url`, `path`, `title`, `started`, `kind` (`desktop` or `headless`) |
| `live status` | `path`, `title`, `revision`, `dirty`, `orders`, `pattern_count`, `pending_proposals`, `takes`, `window` (is a window attached), `last_change`. A window also reports its cursor, selection and playback state |
| `live score [--pattern N --row R --rows K]` | Without `--pattern`, an overview (orders, duration, patterns with the orders that use them, samples with `library_id` when recorded). With it, grid `lines` |
| `live patch (--ops FILE\|- \| --op JSON …) [--base REV] [--label TEXT] [--propose] [--author NAME]` | Apply the operations from [Patch](#operations) to the open song as one undoable transaction; with `--propose`, only offer them |
| `live changes [--since REV] [--author NAME]` | Journal entries after `REV`, each with `revision`, `author`, `label`, `diff` and `summary`, plus a grouped `summary` for `human` and `agent` |
| `live proposals` | Pending proposals with `id`, `label`, `status`, `ops`, `diff`, `summary`, `stale` |
| `live withdraw ID` | Withdraw your own pending proposal |
| `live take PATH --label TEXT` | Announce a saved `.json` project or `.mod` as a take (id `t1`, `t2`, …) the owner can open from the window |
| `live takes` | List takes with title, duration, size and SHA-256 |
| `live open (PATH \| --take ID)` | Ask the window to open a file or a take |
| `live play [--order N]` / `live stop` | Start or stop playback in the window (`LIVE_NO_WINDOW` without a window) |
| `live select --pattern N --row R --channel C [--rows K --channels K]` | Move the window's selection to show a passage |
| `live save [--output PATH]` | Save the project JSON |
| `live serve SOURCE [--port N]` | Host a headless session on a project or MOD until Ctrl+C |

Applied patch result (shortened):

```json
{"ok": true, "changed": true, "results": [{"op": "set"}], "revision": 1, "document_revision": 1,
 "diff": {"cells": [{"pattern": 0, "row": 4, "channel": 0, "before": "C-2 05 C31", "after": "E-2 04 C28"}]},
 "summary": ["P00 r04 ch1: C-2 05 C31 → E-2 04 C28"]}
```

**Conflicts.** `--base REV` means "I last read the song at revision `REV`". If the patch touches a cell, a pattern name, a sample, the order structure or the title that someone with a *different author name* changed after `REV`, nothing is applied and the command fails with `LIVE_CONFLICT`. The error carries the new `revision` and one `conflicts` entry per contested unit:

```json
{"ok": false, "error": "LiveConflict", "code": "LIVE_CONFLICT",
 "message": "1 unit(s) were changed by agent since revision 0; read the changes, adapt the patch and resubmit with the new revision.",
 "conflicts": [{"unit": "cell", "author": "agent", "revision": 1, "label": "Soften intro",
                "pattern": 0, "row": 4, "channel": 0, "current": "E-2 04 C28", "yours": "G-2 04 C20"}],
 "revision": 1}
```

Non-overlapping edits pass even with an old `--base`. Without `--base`, **no conflict check happens** and the patch applies on top of whatever is there. A changed `base` outside the journal's memory (500 entries) also conflicts (`unit: "history"`); an opened different file conflicts as `unit: "document"`. The owner's edit always wins: the agent re-reads (`live changes`, `live score`), adapts and resubmits.

**Proposals.** `--propose` stores the patch as a proposal (`p1`, `p2`, …) instead of applying it; the result holds `proposal` with its `diff` and `summary`. The owner previews it in the window and accepts or rejects it there; the agent cannot accept. A proposal is judged against the revision it is accepted from, so do not combine `--propose` with `--base`. Its `stale` flag turns true when edits by someone else since the proposal overlap the cells it would change. Use `withdraw` to retract one.

**Without a window** (`window: false`): `play`, `stop` fail with `LIVE_NO_WINDOW`, while `open` and `select` return `{"ok": true, "handled": false}`: nothing consumed the request.

`live save` with no `--output` writes the session's open project file. With `--output` it writes a copy (`"copy": true`); the session and the owner's window keep their own file. Announce such a copy with `take` if the owner should open it.

`live serve` prints one JSON line when it is listening (`{"ok": true, "event": "listening", "pid": …, "url": …, "path": …, "kind": "headless", "discovery_file": …}`), then blocks. On Ctrl+C it prints `{"event": "stopped", "revision": …, "dirty": …}` and does not write unsaved edits; run `live save` first. To stop a server started in the background, end only that process by its `pid`.

```sh
CHIPLOOM_HOME=/tmp/chiploom python -m tracker4agents live serve exports/song/project.json &
python -m tracker4agents live status
python -m tracker4agents live patch --base 0 --label "Soften intro" --op '{"op": "set", "pattern": 0, "row": 4, "channel": 0, "cell": "E-2 04 C28"}'
python -m tracker4agents live changes --since 0
```

For the collaboration procedure, see [the live reference](../skills/chiploom/references/live.md) and [the agent guide](AGENT_GUIDE.md#composing-with-the-owner-in-the-window-live).

## MCP adapter

```sh
python -m tracker4agents mcp [--root DIR]
```

`mcp` speaks the Model Context Protocol over standard input and output (JSON-RPC 2.0, one message per line). It supports protocol versions `2025-06-18`, `2025-03-26` and `2024-11-05`, `initialize`, `ping`, `tools/list` and `tools/call`. `--root` sets the working directory used for relative paths in tool arguments (default: the directory the server starts in).

Each tool call runs the equivalent `chiploom` command in a **child process**, so the result is exactly the CLI's JSON: it arrives as `structuredContent` (and as text), with `isError: true` when the command failed, carrying the same `code`/`message` fields. Nothing a command prints can corrupt the protocol stream. A command is stopped after 600 seconds (`TIMEOUT`).

| Tools | Maps to |
| --- | --- |
| `estimate`, `validate`, `inspect`, `export`, `render`, `preview`, `migrate` | the commands of the same name (`validate` takes `report`, `inspect` takes `pattern`, `grid`, `row`, `rows`) |
| `patch` | `patch` with `source`, `output`, `ops` (a JSON array) and `label` |
| `report`, `compare`, `feedback` | the commands of the same name; `compare` offers `mp3`, `language`, `seed` and `seconds` but not `labels` |
| `samples_list`, `samples_inspect`, `samples_preview`, `samples_add` | `samples list`, `inspect`, `preview`, `add` (no `extract`, `edit` or `audit`) |
| `live_sessions`, `live_status`, `live_score`, `live_patch`, `live_changes`, `live_proposals`, `live_withdraw`, `live_take`, `live_takes`, `live_open`, `live_play`, `live_stop`, `live_select`, `live_save` | the `live` subcommands; `live_patch` takes `ops`, `base_revision`, `label`, `propose`, `author` |

There are 29 tools. `demo`, `import`, `analyze`, `gui` and `live serve` are not exposed; use the CLI for them. Read-only tools carry `readOnlyHint`.

Configuration for a client that launches stdio servers (field names vary by client; this is the common shape):

```json
{
  "mcpServers": {
    "chiploom": {
      "command": "<path to the checkout>/.venv/Scripts/python.exe",
      "args": ["-m", "tracker4agents", "mcp"],
      "cwd": "<path to the checkout>"
    }
  }
}
```

Use the virtual environment's interpreter on the host where the files live (`.venv/bin/python` on Linux and macOS). The adapter is covered by the project's automated tests (`tests/test_mcp.py`) and was exercised by hand over a raw stdio pipe. It has **not** been tested with any specific MCP client, so no client is claimed to work. Agents with a terminal, such as Codex or Hermes, can keep calling the CLI directly; nothing requires MCP.

## Error contract and codes

Failures emit one JSON object on **stderr** and exit with status 2:

```json
{"ok": false, "error": "ValidationError", "code": "NOTE_RANGE",
 "message": "ops[0] (transpose): Transposing E-1 by -12 leaves C-1..B-3."}
```

| Field | Meaning |
| --- | --- |
| `ok` | Always `false` |
| `error` | Python exception class name; informational |
| `code` | Stable identifier. **Branch on this**, never on the wording |
| `message` | English explanation |
| `message_fr` | The original French core diagnostic, present when `message` is a translation |
| `conflicts`, `revision` | Only for `LIVE_CONFLICT`: the contested units and the current revision |
| `errors`, `error_count` | Only for `validate --report` (`PROJECT_INVALID`): one entry per independent problem |

Some core diagnostics keep their French wording in `message` in this version, notably when a position prefix such as `ops[1] (set): ` or `Pattern 0, row 00: ` is added. The `code` is the reliable signal. Argument-parser errors, `--help` and `--version` are plain text.

### Codes

| Group | Codes |
| --- | --- |
| Files and formats | `JSON_SYNTAX`, `IO_ERROR`, `SCHEMA`, `UNKNOWN_FIELD`, `MOD_FORMAT`, `ARCHIVE_INVALID`, `FILE_TOO_LARGE`, `INTEGER_RANGE`, `INVALID_VALUE`, `TEXT_ASCII`, `TEXT_LENGTH`, `TEXT_TYPE` |
| Score content | `NOTE_UNKNOWN`, `NOTE_RANGE`, `EFFECT_FORMAT`, `EFFECT_PARAM`, `EFFECT_UNSUPPORTED`, `CELL_DUPLICATE`, `FLOW` (invalid `Bxx`/`Dxx` target), `TIMING` (`F00`/`F20`, or no room for `timing`), `PATTERNS`, `ORDERS` |
| Samples | `SAMPLE_SLOT`, `SAMPLE_REF` (a cell uses a slot that does not exist), `SAMPLE_LOOP`, `SAMPLE_LENGTH`, `SAMPLE_PCM`, `SAMPLE_PCM_HASH`, `RECIPE_INVALID`, `SAMPLE_LIBRARY` |
| Project validation | `PROJECT_INVALID` (the wrapper of `validate --report`; each entry has its own code) |
| Patch | `PATCH_FORMAT`, `PATCH_OP`, `PATCH_FIELD`, `PATCH_CELL`, `PATCH_BOUNDS` |
| Output and migration | `OUTPUT_PATH` (source equals output, wrong extension, existing directory, bank path), `MIGRATION_MISMATCH` |
| Rendering | `FFMPEG_MISSING`, `RENDER_LIMIT` (over 120 s, sample rate, preroll or unreachable order), `RENDER_TIMEOUT`, `RENDER_FAILED` |
| Live: connection | `LIVE_NOT_RUNNING` (no matching session, or it did not answer), `LIVE_TIMEOUT`, `LIVE_AUTH`, `LIVE_FORBIDDEN` (browser request), `LIVE_HOST`, `LIVE_BAD_REQUEST`, `LIVE_BAD_RESPONSE`, `LIVE_METHOD`, `LIVE_UNKNOWN_METHOD`, `LIVE_TOO_LARGE`, `LIVE_COMMAND` |
| Live: editing | `LIVE_CONFLICT`, `LIVE_BASE` (invalid `--base`), `LIVE_AUTHOR`, `LIVE_LABEL`, `LIVE_PARAMS`, `LIVE_PROPOSAL`, `LIVE_TAKE` |
| Live: window | `LIVE_NO_WINDOW`, `LIVE_OPEN`, `LIVE_REQUEST`, `LIVE_SAVE_PATH`, `LIVE_CONTEXT`, `LIVE_ERROR` |
| Generic fallbacks | `VALIDATION`, `RUNTIME_ERROR`, `ERROR`; `FEEDBACK_INVALID` (feedback text or rating) |
| MCP adapter only | `TIMEOUT` (a command ran over 600 seconds), `CLI_ERROR` (the command printed something that was not JSON) |

New codes may be added; existing ones keep their meaning. A code in a family you do not recognise should be treated as an error of that family.

### Validation report entries

`validate --report` on a JSON project lists every independent problem:

```json
{"ok": false, "error": "ValidationError", "code": "PROJECT_INVALID", "message": "Project validation failed.",
 "errors": [
   {"path": "patterns[0].rows['00']", "code": "NOTE_UNKNOWN", "message": "Pattern 0, row 00: …"},
   {"path": "patterns[1].rows['01']", "code": "PATCH_CELL",
    "message": "Pattern 1, row 01: Unreadable cell '--- -- A0'; expected 'NOTE SS EEE', e.g. 'C-2 01 C20'."}
 ],
 "error_count": 2}
```

Each entry has `path` (where in the file), `code`, `message` and, when translated, `message_fr`. Paths look like `patterns[4].events[12]` for the sparse layout and `patterns[4].rows['0C']` for grid rows. Success prints the usual `validate` result with `errors: []` and `error_count: 0`.
