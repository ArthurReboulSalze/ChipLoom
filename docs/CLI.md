# ChipLoom command reference

Use `chiploom` after editable installation, or `python -m tracker4agents` from the checkout. The examples below use the module form to make the chosen interpreter explicit.

| Command | Input | Result |
| --- | --- | --- |
| `demo` | Built-in song and seed | Reproduces an original example, MOD and project; optional renders |
| `inspect` | Strict MOD or JSON | Structured summary; optional pattern as rows or `--grid` tracker text |
| `validate` | Strict MOD or JSON | Playback plan, duration warnings; `--report` collects independent JSON errors with codes; `--sample-source` and a declared `metadata.sample_source` check where samples come from |
| `estimate` | Order count, speed, BPM, rows | Constant-timing duration estimate without a source file |
| `import` | Strict MOD | Schema v2 JSON with PCM; no inferred synthesis recipes |
| `migrate` | Project v1/v2 or MOD | Compact schema v2 project; the MOD it encodes is unchanged |
| `patch` | Project (or MOD) and a list of operations | New editable project; all operations apply or none does |
| `export` | JSON project | Real self-contained MOD or XM; `--output` must end in `.mod` or `.xm` (`OUTPUT_PATH`), unless `--format` is given to choose another extension deliberately |
| `render` | MOD, XM or JSON project | WAV from the actual module file (a project is encoded to a temporary module first), with level and loudness measurements; optional MP3 |
| `preview` | Strict MOD or JSON | New portable HTML/media directory |
| `analyze` | Reference MOD or ZIP | Read-only aggregate report; broader than editable profile |
| `norms` | Reference MOD/XM files, folders or ZIPs | Articulation norms: arpeggio runs, note lengths and endings, rests, density; percentiles only |
| `lint` | Project, MOD or XM | Cells whose effect does nothing, or not what the score suggests, with the reason |
| `report` | Project or MOD | Measurements of the played score: density, ranges, gaps, repetition, estimated key |
| `compare` | Two projects or MODs | New directory with a blind A/B listening page |
| `feedback` | Project | New project with the owner's listening feedback in its metadata |
| `live` | Running window or headless session | Compose together: read, patch, propose, announce takes, drive playback |
| `mcp` | MCP client on stdin/stdout | Model Context Protocol adapter over these commands |
| `samples` | Local sample bank, reference MOD/ZIP or project | Extract, search, inspect, audition, edit labels, insert and audit |
| `synth` | Recipe JSON, project, optional sample bank | Songs made only with created samples: list recipe types, audition, add, starter palette, reference levels |
| `gui` | Optional MOD or JSON | Native human window, optional dependency required |

## Common commands

```sh
python -m tracker4agents --version
python -m tracker4agents demo --song first-light --output exports/first-light --no-audio
python -m tracker4agents demo --song pixel-rush --mp3
python -m tracker4agents inspect examples/pixel_rush.project.json --pattern 0 --grid --rows 8
python -m tracker4agents validate examples/pixel_rush.project.json
python -m tracker4agents new --output exports/new-song/project.json --channels 8 --patterns 4 --bpm 120
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

`new --output NEW.json` writes a blank project to start a song: `--patterns N` empty patterns played in order (default 1), one empty sample slot, `Fxx` speed and BPM on the first row (`--speed`, default 6; `--bpm`, default 125), `--channels N` (2 to 32, default 4; other counts than 4 use the `protracker-nch-pal-v1` profile), `--title` and `--sample-source library|synthesized|mixed|none` (recorded as `metadata.sample_source`, default `library`). Fill the empty slot with `samples add` or a `library_sample` operation. The output must not exist yet (`OUTPUT_PATH`). The result is `inspect`'s summary plus `output`, `speed`, `bpm` and `sample_source`. `--format xm` writes a blank XM instead (profile `fasttracker2-xm-v1`): `--channels` 2 to 32, `--patterns` up to 256, `--rows` rows per pattern (1–256, default 64; a MOD refuses `--rows` other than 64 with `PATTERNS`), the speed and BPM in the header (`metadata.xm.default_speed`, `default_bpm`; BPM 32–255) with no `Fxx`, the linear frequency table, restart position 0 and one empty instrument; the result adds `rows_per_pattern`.

`analyze --output` is a JSON filename. `--probe` adds ffprobe/libopenmpt duration estimates. Without that flag, analysis uses only the standard library. Per-file failures appear under `analysis_error`; successful entries remain in the report. A report with any failed file returns exit code 2. `editable_in_current_profile: false` is a compatibility fact, not an analysis failure. Archives are limited to 512 entries and 64 MiB expanded; each MOD is limited to 4 MiB.

`render` supports `--engine openmpt|xmp`, `--seconds` (greater than 0, at most 120), `--sample-rate` (8000–96000), `--ffmpeg` and `--xmp-library`. `--mp3-output` writes a listening copy of the WAV; with `--mp3-normalize` the copy is scaled so its sample peak sits at -1 dBFS and `optional_mp3.normalized` gives the gain applied (the WAV keeps the engine's level, which is well below full scale for a multi-channel XM; see **Level** below). `preview` also accepts `--ffmpeg`. XMP requires the optional separately built reference library (`XMP_MISSING` when it is not set up).

`render` takes a MOD, an XM or a `.json` project. A project is validated, encoded to a temporary module file of its own format (MOD or XM), rendered, and the temporary file is removed; the result then also has `source_kind: "project"`, `module_format` and `module_sha256` (the encoded module), while `source_sha256` is the project file's hash. The output must end in `.wav` (`OUTPUT_PATH`). Every result has:

| Field | Meaning |
| --- | --- |
| `engine`, `version`, `trace` | The replay engine; `trace` is the libxmp order/row trace (null for libopenmpt) |
| `requested_seconds`, `from_order`, `start_seconds` | What was rendered |
| `audio` | Measurements of the WAV: `duration_seconds`, `frames`, `peak`, `peak_dbfs`, `rms_dbfs`, `dc_mean`, `clipped_samples`, `longest_quiet_window_seconds`, `boundary_jump`, `sha256` |
| `loudness` | `integrated_lufs`, `true_peak_dbtp`, `lra_lu` and `method`, measured by FFmpeg's `ebur128=peak=true` filter (EBU R 128). Values are null for silence. Without FFmpeg (possible with `--engine xmp`) the values and `method` are null and `reason` says why |
| `ended_before_requested` | `true` when `--seconds` asked for more than one playback cycle from the start point and the WAV stopped at the end of the song (libopenmpt does not loop; libxmp keeps playing and fills the length). Then `module_seconds` gives the length of that cycle and `warnings` explains it |
| `source_sha256`, `output` | Hash of the source, path of the WAV |

**Level.** libopenmpt (the default) is the level reference. It plays an XM about 6 dB below a four-channel MOD and lowers the level as channels are added: by 6 dB for a MOD with 8 or more channels, and by up to 6 dB more for an XM with 32 channels. libxmp's master volume is set from a measured table so that both engines render the same module at the same level, within about 0.2 dB for a centred note and 1 dB on the test songs; the libxmp result gives the value as `master_volume`. Differences in pan law remain. `python tools/calibrate_xmp_level.py` measures the remaining gap for every channel count.

`gui --state-dir PATH` chooses a session/cache folder. `gui --no-restore` skips the previous file and uses a built-in example when no input is supplied. Language and theme are selected in the window and stored there.

## Response contract

Successful non-GUI operations emit JSON to stdout. Runtime, input and rendering failures emit `{"ok": false, "error": "...", "code": "...", "message": "..."}` to stderr with exit status 2; see [Error contract and codes](#error-contract-and-codes). Normal argument-parser errors, help and version are text. The `message` is English; when the core diagnostic was written in French, the original is kept as `message_fr`. Scripts should use exit status and the `code` field, not parse a sentence.

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
python -m tracker4agents samples extract path/to/modules/ --library exports/sample_library   # folder: MOD, XM, ZIP, recursive
python -m tracker4agents samples audit
python -m tracker4agents samples list --category cycle --tag bass-candidate --compatible --limit 10
python -m tracker4agents samples list --role kick --limit 10
python -m tracker4agents samples list --query smooth --format xm --offset 0 --limit 10
python -m tracker4agents samples inspect SMP-0001
python -m tracker4agents samples preview SMP-0001 --note C-2 --seconds 1 --output exports/auditions/pulse.wav
python -m tracker4agents samples edit SMP-0001 --name "Warm Pulse" --category cycle --tag bass-candidate --tag warm
python -m tracker4agents samples add SMP-0001 --project exports/song/project.json --output exports/song/with-pulse.project.json
python -m tracker4agents samples palettes --role bass --format xm
python -m tracker4agents samples palette PAL-0003
python -m tracker4agents samples use-palette PAL-0003 exports/song/blank.json --output exports/song/v1.project.json
```

`extract SOURCE` reads a `.mod`, an `.xm`, a ZIP holding either, or a folder (recursive;
its ZIPs are opened too). A MOD is read with the same bounded 31-sample layouts as structural
analysis, including the supplied two-channel references: unsupported patterns/restart bytes
do not prevent reading their samples. An XM yields every sample of every instrument
(`xm.read_samples`), multi-sample instruments included. Every module is read before the bank
is written. A single refused file is an error; in a ZIP or folder, refused members are counted
by code in `refused` (`IT_UNSUPPORTED`, `S3M_UNSUPPORTED`, `MOD_LAYOUT`, `XM_FORMAT` ...) and
the other modules are imported. Archive paths are never extracted. Limits are 512 members and
64 MiB expanded per ZIP, 4 MiB per MOD, 24 MiB per XM, 256 MiB per folder.

The manifest `library.json` (`chiploom.sample-library.v2`; a v1 bank is read and rewritten
as v2 on its next update) contains stable `SMP-0001` IDs, neutral names, PCM digests,
playback settings, measured features, editable labels and the fields below. `pcm/` holds
exact PCM, one file per distinct payload: `<sha256>.pcm` for signed 8-bit bytes,
`<sha256>.pcm16` for signed little-endian 16-bit frames (`bits` says which; `loop_start`,
`loop_length` and `bytes` count frames and bytes respectively). Different loop, volume,
fine-tune, bit depth, loop mode, panning or relative-note settings remain separate entries.
Original filenames, titles, sample labels and source fingerprints exist only in
`private/provenance.json`; ordinary search/inspect results do not include them. A generated
`.gitignore` excludes bank contents from Git.

Per entry: `format_origin` (`mod` or `xm`), `bits` (8 or 16), `loop_mode` (`forward` or
`pingpong`), `panning` (0-255, 128 centred), `relative_note` (-96..95), `finetune` (-8..7 for
a MOD sample, -128..127 in 1/128 semitone for an XM one), `envelope` (XM only, else null:
`volume_envelope`, `sustained`, `vibrato` booleans and the `fadeout` value; the envelope itself
is not copied), and the role fields: `role` (kick, snare, hat, clap, tom, cymbal, perc, bass,
chord, lead, pluck, pad, texture, fx, unknown), `role_confidence` (high/medium/low),
`role_evidence` (short reasons), `role_occurrences` (source occurrences that agree) and
`role_source`: `song` when `usage.study` scored it from how a reference plays the slot,
`sound` when only the PCM and the XM instrument were available (a sample dropped from a
multi-sample instrument, a module the importer refuses), `pcm` when the module is no longer on
disk (entries of an older bank; the evidence says so). When the same PCM occurs in several
modules, the role with the most evidence wins. Roles are evidence-based suggestions to confirm
by listening, never a listening verdict. `compatibility.adapt` lists what `--adapt` would
change to fit a MOD (null when nothing can). `samples list` filters with `--role` and
`--format`; `samples audit` counts entries by role, confidence, bits, loop mode and origin.

**Pitch estimate.** `samples inspect` adds `sample.pitch`, a measurement (`"measurement": "estimate"`) of the
fundamental heard when the sample plays at tracker note `C-2`:

```json
{"measurement": "estimate", "method": "loop-cycles", "reference_note": "C-2", "finetune": 0,
 "playback_rate_hz": 8287.137, "loop_length": 112, "loop_cycles": 4, "cycle_length": 28.0,
 "periodicity": 1.0, "region": [0, 112], "estimated_hz_at_c2": 295.969, "nearest_note": "D4",
 "pitch_class": "D", "cents": 13.5, "transpose_semitones": 2, "reason": null, "note": "..."}
```

- `playback_rate_hz` is the PAL rate at `C-2` for the sample's finetune (ProTracker period table: 8287 Hz at finetune 0). For an XM-origin entry the reference is FastTracker's `C-4` (`reference_note`): 8363 Hz shifted by the relative note and the 1/128-semitone finetune; the field keeps its `_at_c2` name.
- `method: "loop-cycles"` (loops up to 1024 bytes): the loop repeats, so the pitch is `playback_rate_hz x loop_cycles / loop_length`. `loop_cycles` is the largest number of whole cycles for which every shift by a multiple of `loop_length / loop_cycles` still correlates at 0.85 or more (circular autocorrelation). A 112-byte loop can hold 4 cycles of 28. `periodicity` is the weakest of those correlations.
- `method: "autocorrelation"`: a YIN estimate over a longer loop, or over a one-shot after its loudest attack. `cycle_length` is the period in bytes; `periodicity` is 1 minus the aperiodicity (1 is perfectly periodic).
- `method: null`, with every frequency field null and a `reason`, for silent samples, flat loops, loops that repeat below 20 Hz, and noise or drums with no stable period.
- `nearest_note` uses scientific pitch names (A4 = 440 Hz). `transpose_semitones` (-5..+6) is the pitch-class offset from the written note to the heard note: +2 means a written C sounds D, so write a note 2 semitones lower to hear the written pitch class. Each semitone up multiplies the frequency by 2^(1/12).

`samples list` items carry a compact `pitch` (`estimated_hz_at_c2`, `nearest_note`, `cents`, `transpose_semitones`,
`loop_cycles`) for loops up to 1024 bytes and `null` otherwise; inspect a one-shot for its estimate.

`samples preview` writes the WAV and returns the same measurements as `synth preview`: `volume`, `finetune`,
`sample` (`bytes`, `looped`, `loop_start`, `loop_length`, `pcm_peak`), `loudness` (`role`: null for a library sample,
`group` from the entry's category and tags, `loudness_db`, `peak_db`, `default_reference_db`, `note`) and `audio`
(`peak`, `peak_dbfs`, `rms_dbfs`, `clipped_samples`), plus the `pitch` block with `at_preview_note`
(`note`, `estimated_hz`, `nearest_note`, `pitch_class`, `cents`, `transpose_semitones`, or null without an estimate).

Reimport preserves IDs, user-edited names/tags and playback variants. Only one writer
may update a bank at a time. A stale `.write.lock` left by a terminated process must be
removed only after checking that no writer is running. The manifest is replaced last;
an interrupted update can leave unreferenced PCM files, never a partially written PCM
or manifest. Automatic multi-process editing is not supported.

Categories are `cycle`, `percussion`, `texture`, `effect`, `unclassified` and `silent`.
Tags such as `bass-candidate` and the scored `role` are heuristic suggestions, not a
listening verdict. `list` supports all requested `--tag` filters, `--role`, `--format`,
case-insensitive query words (the role counts as text), pagination and `--compatible`.
`inspect` returns the complete entry and checks the stored PCM. `audit` verifies every
referenced payload and recomputes compatibility with the current MOD profile. It does not
rewrite imported sounds.

`preview` produces a mono 44.1 kHz PCM16 WAV for a tracker note C-1 through B-3, with
0.05–5 seconds duration. It honors volume, loop and fine tune, using nearest-neighbor
sampling and a fine-tune frequency approximation. An XM-origin entry is played so that
tracker note `C-2` sounds like the XM's `C-4` at the sample's own rate (relative note and
finetune included); 16-bit PCM is played at its own scale and a ping-pong loop forward. It
is an audition without pattern effects, not a reference replay or an estimate of the
original recording rate. Preview output must be outside the bank. Invalid loops or volumes
are rejected.

`add` outputs a complete editable JSON project, embedding PCM and settings. Output must
differ from input and be outside the bank. Without `--slot`, it uses an unreferenced empty
slot or appends a slot. Occupied slots require explicit `--slot N --replace`; MOD has at
most 31 slots. No existing notes or sample numbers are shifted. A bank is not needed to
reopen that JSON or play its exported MOD. The project's `metadata.sample_sources[slot]`
records the library ID, the adaptations and the entry's `role`.

Into an XM project, an XM-origin entry is inserted **native** (16-bit, ping-pong loop,
panning, relative note, finetune kept; the result's `xm.native` is true) and a MOD-origin
entry is converted like `convert` converts a MOD sample. Into a MOD project, an entry outside
the MOD profile is refused (`SAMPLE_INCOMPATIBLE`, the message lists what `--adapt` would do)
unless `--adapt` is passed, which applies these changes on the inserted copy, in order, and
reports them in `adaptations`: `convert-16-bit-to-8-bit` (high byte), `unfold-pingpong-loop`
(the loop followed by its reverse, twice as long, forward), `drop-panning`, `map-xm-tuning`
(the nearest MOD finetune; a relative note is not applied, the message says how many semitones
to transpose the notes), `align-to-even-bytes` (length and loop points), and the two one-shot
changes of earlier versions, `clear-inactive-loop-start` and `prepend-two-zero-bytes`. The
bank PCM is never changed. Samples longer than 65534 bytes after conversion, invalid active
loops and other unsupported settings still fail.

**Palettes.** `palettes.json` (`chiploom.sample-palettes.v1`) holds one palette per readable
source module with a neutral ID `PAL-0001`: `format`, `channels`, `speed`, `bpm`,
`duration_seconds`, `entries` (bank IDs with `role`, `confidence`, `note_starts`, `share` of
the song's note starts and the `channels` that play them; `note_starts` 0 for a sample the
song never plays, such as a dropped multi-sample), `channel_layout` (per channel: `role`,
`roles`, the `entries` it plays, `note_ons`, `notes_per_second`, `sounding_fraction`),
`structure` (`orders`, `orders_played`, `distinct_patterns`, `sections` as `start_order` /
`orders` / `seconds` / `active_channels` count, `channel_entry_order` by channel,
`loop_start_seconds`) and a one-line `summary` such as `kick snare hat · bass · chord · lead×2`.
No notes, no names, no pattern data; the private provenance alone maps a `PAL` ID to its
source, and a re-extraction of the same module keeps its ID. A module the importer refuses or
cannot decode yields its samples but no palette (`modules_without_palette`).

- `samples palettes [--role ROLE] [--format mod|xm] [--channels N]` lists palettes with their summary.
- `samples palette PAL-0003` shows one palette.
- `samples use-palette PAL-0003 PROJECT --output NEW.json [--slots N ...] [--adapt] [--all]`
  inserts the palette's played entries into a library-mode project in role order (drums,
  bass, chords, leads, pads, textures, effects; the most played first inside a role) and
  returns `slot_map` (slot, ID, role, confidence, adaptations) and the palette's channel
  layout. `--slots` gives the target slot of each entry in that order (no gaps, no occupied
  slot), `--all` also inserts the entries the song never plays, `--adapt` is needed for
  entries outside the MOD profile when the project is a MOD. Write your own notes afterwards.

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
IDs and write a new test score. Songs made only with created samples are a separate mode ([Created samples](#created-samples-synth)), used when the owner asks for it.
`--with-xmp` needs the optional libxmp setup; omit it
for libopenmpt alone. `--no-audio` builds the MOD/project without external decoders.

The optional native window exposes the same bank in its bottom **Sample library**
tab. Search and auditions run without changing the score. Insertion goes through
`Document.insert_library_sample`, so the change is undoable and embeds PCM in the
project. The GUI remembers its selected bank folder; the CLI's default path remains
relative to the working directory. The human can choose a different folder without
changing any CLI configuration. See [the user guide](USER_GUIDE.md#sample-library-in-the-window).

## Planning and diagnostics (v0.5.0)

```sh
python -m tracker4agents estimate --orders 18 --speed 6 --bpm 125
python -m tracker4agents validate examples/pixel_rush.project.json --report
python -m tracker4agents render docs/listen/media/voltage_odyssey_v2.mod --from-order 6 --seconds 10 --output exports/drop.wav
```

`estimate` accepts `--orders` 1–256 (a MOD holds 128), `--rows` 1–256 (default 64; a MOD pattern is 64 rows, an XM pattern 1–256), `--speed` 1–31 (default 6) and `--bpm` 33–255 (default 125), all decimal integers. It returns seconds per order, total duration, assumptions and warnings. It assumes constant timing and no jumps or early breaks.

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
  "columns": "row | ch0 | ch1 | ch2 | ch3 (note sample effect)",
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

`patch` applies a list of operations to a copy of a project and writes the result. The operations form **one transaction**: if any fails, or the final score does not validate, nothing is written. A failure names the operation, for example `ops[1] (set): …`. Patterns, orders, rows and channels are zero-based; sample slots are 1–31. The same numbering is used in every result an agent reads (`changes`, `inspect`, `report`, `live score`); only the window and the browser studio show tracks from 1. Cells use the grid text above.

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
| `--output PATH` | Edited `.json` project, a new file. Writing over the source needs `--in-place`; replacing another existing file needs `--overwrite` (`OUTPUT_PATH` otherwise, so an earlier revision is never lost by a typo) |
| `--ops FILE` | JSON file with a list of operations; `-` reads standard input |
| `--op JSON` | One operation (or a list) as JSON; repeat for several. Give either `--ops` or `--op` |
| `--label TEXT` | Name for the change history (default `Patch`) |
| `--in-place` | Allow `--output` to be the source |
| `--overwrite` | Allow `--output` to replace an existing file other than the source |

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

`changes` lists up to 40 lines (`P00 r04 ch1` is pattern 0, row `04`, channel 1, counted from 0 like the operations, so the second channel) and ends with a count when more cells changed; order, pattern-count, sample and title changes get their own lines. `results` has one entry per operation; `add_pattern` and `insert_order` report the new `pattern` and `order` index.

### Operations

Every operation is an object with an `"op"` and the fields below. Unknown fields are rejected (`UNKNOWN_FIELD`). A **block** is `row` (default 0), `rows`, `channel` (default 0) and `channels`; it must stay inside the pattern's rows (0–63 in a MOD) and the module's channels (0–3 in a four-channel song, 0 to N-1 with N channels).

| `op` | Fields | Effect |
| --- | --- | --- |
| `set` | `pattern`, `row`, `channel`, then `cell` (`"E-2 04 C28"`) **or** any of `note`, `sample` (0–31), `effect` | Replace one cell. With `note`/`sample`/`effect`, fields you omit keep their current value; `note: "---"` or `effect: "..."` clears that part |
| `write` | `pattern`, `row` (default 0), `step` (default 1, 1–64), and either `cells` + `channel`, or `lines` | `cells`: consecutive cells down one channel, `step` rows apart. `lines`: whole grid rows with one cell per channel (`"C-2 04 C38 \| --- -- ... \| …"`, an optional `00 \|` row prefix is accepted); do not give `channel`. An empty string or `---` clears that cell |
| `clear` | `pattern` + block (`rows` and `channels` default 1) | Empty a block |
| `copy` | `pattern` + block (defaults 1 row, 1 channel), `to_pattern`, `to_row`, `to_channel` (default: same place) | Copy a block, possibly to another pattern |
| `move` | same fields as `copy` | Copy, then empty the source block |
| `transpose` | `pattern`, `semitones` (−35 to 35) + block | Shift notes only. Block defaults differ: from `row` to the end of the pattern, 1 channel. Leaving `C-1`–`B-3` fails (`NOTE_RANGE`) |
| `add_pattern` | optional `copy_of`, `name`, `insert_order`, `length` (XM only, 1–256, default 64) | Append a pattern (empty, or a copy, which keeps its length), at most 100 in a MOD and 256 in an XM. It is also appended to the order list by default; `insert_order` is a position, `"end"` or `null` for none |
| `remove_pattern` | `pattern` | Delete a pattern that no order uses; later patterns are renumbered in the order list |
| `rename_pattern` | `pattern`, `name` (at most 64 characters) | Rename |
| `set_orders` | `orders` (list of pattern indices) | Replace the whole order list. The last stored pattern must appear in it |
| `insert_order` | `pattern`, optional `at` (default: end) | Insert one order |
| `remove_order` | `at` | Delete one order |
| `move_order` | `at`, `to` | Move one order |
| `title` | `title` | Set the module title (ASCII, validated) |
| `timing` | `bpm` (33–255) and/or `speed` (1–31) | Write `Fxx` speed and BPM on the first played row; the one you leave out keeps its current value. Needs two free effect columns there or existing `Fxx` effects, otherwise `TIMING`; other effects are never overwritten. The result gives the `bpm` and `speed` written |
| `sample` | `slot` (1–31, 1–128 in an XM), optional `volume` (0–64), `finetune` (−8 to 7; −128 to 127 in an XM, in 1/128 semitone), `name`, and in an XM `panning` (0–255, 128 centred), `relative_note` (−96 to 95 semitones), `loop_mode` (`forward` or `pingpong`) | Change a sample's playback settings or name. PCM is never touched. The XM fields on a MOD are refused (`MOD_XM_FIELD`) |
| `library_sample` | `id`, optional `library` (default `exports/sample_library`), `slot`, `replace`, `adapt` | Insert a library entry exactly like `samples add`: exact PCM, occupied slots need `slot` + `replace`, `adapt` only for the documented one-shot adaptation. In an XM (slots 1–128) the sample is converted exactly like `convert` converts a MOD sample (finetune `16 × MOD finetune − 20`, 8-bit, forward loop, centred) and the result adds `xm` (`finetune`, `relative_note`). Refused (`SAMPLE_SOURCE`) in a project declared `synthesized` |
| `recipe_sample` | `name`, `recipe`, optional `slot` (1–31; default: the first free slot), `volume` (0–64), `finetune` (−8 to 7), `replace`, `role`, `match`, `library` | Insert a created sample (see [Created samples](#created-samples-synth)). An occupied slot is refused (`SAMPLE_SLOT`) unless `replace` is true. Without `volume`, the volume is set from the reference level of the sample's `role` (`kick`, `snare`, `hat`, `bass`, `lead`, `chord`, `texture`; inferred from the recipe when omitted): `match` is `"defaults"` (default), `"library"` (with `library`: a bank folder) or `"none"` (volume 40). The result lists the slot, the measured facts and the `loudness` record. In an XM (slots 1–128) the sample is converted like a MOD sample by `convert` and keeps its recipe; `finetune` stays the MOD value (−8 to 7). Refused (`SAMPLE_SOURCE`) in a project declared `library` |
| `pattern_length` | `pattern`, `rows` (1–256), optional `truncate` (default false) | XM only: resize a pattern. Shrinking past rows that hold notes or effects is refused (`PATTERN_TRUNCATE`) unless `truncate` is true, which drops them. The result gives `rows_before`, `rows` and `cells_dropped`. Refused on a MOD (`MOD_OP_UNSUPPORTED`): a MOD pattern always has 64 rows |
| `xm_header` | any of `restart_position` (an order index), `default_speed` (1–31), `default_bpm` (32–255), `frequency_table` (`linear` or `amiga`) | XM only: edit the header values in `metadata.xm`; the fields you leave out keep their value. The result gives `before` and `after`. Changing the frequency table keeps note pitches but changes how far portamento, vibrato and arpeggio slide. Refused on a MOD (`MOD_OP_UNSUPPORTED`): a MOD starts at speed 6 / 125 BPM (use `timing`) |

`timing`, `xm_header`, `pattern_length`, `Fxx` effects and any order operation change the playback plan, so read `duration_seconds` and `warnings` in the result. Besides the duration warnings, `warnings` (in `patch`, `validate` and `inspect`) flags flow that plays but is probably not meant: an XM `Dxx` breaking to a row past the end of the next pattern (players start that pattern at row 0; a MOD refuses it with `FLOW`), and a song that loops back to an order (end of the order list, the XM restart position, or a backward `Bxx`) at another speed or BPM than on its first pass, which a `Fxx` on that row fixes.

Errors in a patch use these codes: `PATCH_FORMAT` (not JSON, empty list, more than 2000 operations), `PATCH_OP` (unknown operation), `PATCH_FIELD` (missing, conflicting or wrongly typed field), `PATCH_CELL` (unreadable cell text), `INTEGER_RANGE` (a pattern, row, channel or slot index out of range, with the valid range in the message), `PATCH_BOUNDS` (a block or written rows running past the pattern's last row or the module's last channel), plus the score codes (`NOTE_UNKNOWN`, `NOTE_RANGE`, `ORDERS`, `PATTERNS`, `SAMPLE_SLOT`, …) when the edited score is invalid.

```json
{"ok": false, "error": "ValidationError", "code": "PATCH_OP",
 "message": "ops[0] (fly): unknown operation; use one of ['add_pattern', 'clear', 'copy', …]."}
```

## Created samples (synth)

Songs made **only with created samples** are a mode for when the owner asks for them; library samples stay the default (see [the agent guide](AGENT_GUIDE.md#songs-made-only-with-created-samples)). A created sample is a **recipe**: JSON data that rebuilds the same 8-bit PCM every time, stored in the project as `recipe` instead of bytes. Recipes never contain code.

| Command | Result |
| --- | --- |
| `synth types` | `{"ok", "count", "types": [...]}`: every recipe type with `purpose`, `looped` and `parameters` (`kind`, `min`, `max`, `default`, `description`, `applies_to`, `choices`, `required`) |
| `synth levels [--library PATH]` | Reference loudness per group (`percussion`, `bass`, `lead`, `texture`): `source` (`library` or `defaults`), `groups` with `count`, `p25_db`, `p50_db`, `p75_db`, `median_db` (= p50), `spread_db` (interquartile range), `min_db`, `max_db`, and `role_targets_db` / `role_points` (the level each role aims at and which quartile). Aggregate only: no names, IDs or file names |
| `synth preview --recipe JSON --output OUT.wav [--name N] [--note C-2] [--seconds 1.0] [--volume 64] [--finetune 0] [--role R]` | Writes a 44.1 kHz mono WAV (no FFmpeg needed; loop and fine tune honoured; 0.05–5 s). `--note` is a MOD note label, `C-1` to `B-3`, here and in `samples preview`; an XM label is refused with `NOTE_UNKNOWN` and its MOD equivalent (XM `C-4` is MOD `C-2`). Returns `sample` (bytes, loop, cycles, `heard_hz_at_c2`, `tuning_cents`), `loudness` and `audio` (`peak`, `peak_dbfs`, `rms_dbfs`) for an agent that cannot listen |
| `synth add PROJECT --recipe JSON --name N --output OUT.json [--slot S] [--replace] [--volume V] [--finetune F] [--role R] [--match-library [PATH] \| --no-match]` | Runs the `recipe_sample` operation and writes a **new** project (the output must differ from the input); an XM project works too (the sample is converted like `convert` does and keeps its recipe). Returns `slot`, `name`, `role`, `sample`, `loudness`, `reference`, `duration_seconds` |
| `synth palette --output NEW.json [--title T] [--style default] [--channels N] [--format mod\|xm] [--match-library [PATH] \| --no-match]` | Writes a **new** project (an existing output is refused with `OUTPUT_PATH`) with `"sample_source": "synthesized"`, one empty pattern, `--channels` 2 to 32 (default 4) and the starter palette below. `--format xm` writes the same palette as a blank XM (as `new --format xm`: 64-row pattern, speed 6 / 125 BPM in the header) whose instruments are converted like `convert` does and keep their recipes; its result adds `notation` (play the uses' `C-2` as XM `C-4`). Returns `format`, `channels`, `slots` (slot, name, role, use, recipe, volume, `hand_set_volume`, `hand_set_db`, `target_db`, `measured_db`, `deviation_db`, `limited_by_peak`, `tuning_cents`) and `free_slots` |

`--recipe` takes JSON text or `@file.json` (handy where shell quoting is awkward). Every recipe error has the code `RECIPE_INVALID`.

### Recipe reference

`frequency` is the pitch in Hz **heard when the sample plays at tracker note C-2** (period 428, finetune 0). A looped wave holds a whole number of cycles in an even number of bytes; without `cycles`, ChipLoom picks the fewest cycles that land within 2 cents of the pitch, and `synth preview` reports the result as `tuning_cents`.

| Type | Parameters (range, default) | Purpose |
| --- | --- | --- |
| `wave` | `shape` (`pulse`, `triangle`, `saw`, `sine`, `noise`; required); `frequency` (30–2000, 261.625565); `cycles` (1–64, automatic); `duty` (0.05–0.95, 0.5; pulse only); `length` (64–65534, even, 2048), `smooth` (0–0.95, 0), `binary` (false) and `seed` (0–2³²−1, 0), noise only; `peak` (0.01–1, 0.88) | Clean looped chip wave, the whole sample looping; or a looped noise buffer. Parameters that do not apply to the shape are rejected |
| `kick`, `snare`, `hat`, `kick_hat`, `snare_hat` | `duration` (0.01–1.5 s; 0.24, 0.19, 0.048, 0.24, 0.19), `peak`, `seed`, `drive` (0–1, 0) | One-shot drums; the `_hat` forms add a hat tick on top. `drive` is a soft saturation that raises the RMS level of a short hit (0.3 suits matching a sample bank); omitted, the sound is unchanged |
| `pluck` | `duration` (0.36), `frequency`, `duty` (0.1–0.9, 0.32), `peak`, `seed`, `drive` | One-shot plucked tone with a baked decay |
| `draw` | `points` (4–256 values in −1…1, required), `cycles` (16), `frequency`, `peak` | Your own looped wave |

Recipes are deterministic: the same recipe always builds the same bytes, and the recipe types that existed before `wave` build byte-identical samples.

### Starter palette

`synth palette` writes 13 samples. The drum recipes and the hand-set volumes come from the Pixel Rush palette; the waves are the same timbres, now tuned. Slots 14–31 are free (14–128 in an XM).

| Slot | Name | Role | Use |
| --- | --- | --- | --- |
| 1 | Kick | kick | Drums, trigger at C-2 |
| 2 | Snare | snare | Drums |
| 3 | Hat | hat | Drums, off-beat ticks |
| 4 | Kick+hat | kick | Kick with a hat on top: two hits from one drum channel |
| 5 | Snare+hat | snare | Snare with a hat on top |
| 6 | Triangle bass | bass | Soft low line, octaves 1–2 (130.81 Hz at C-2) |
| 7 | Pulse bass | bass | 25 % pulse for accents |
| 8 | Pulse 12 lead | lead | 12.5 % pulse, thin and reedy |
| 9 | Pulse 25 lead | lead | The all-round 25 % pulse |
| 10 | Pulse 50 lead | lead | Hollow square, the fullest |
| 11 | Triangle chord | chord | Chords and arpeggios (`037`, `047`) |
| 12 | Noise texture | texture | Looped 1-bit noise bed; stop it with `C00` |
| 13 | Pluck lead | lead | One-shot pluck, re-trigger each note |

### Loudness matching

The **loudness** of a sample is the RMS of its audible PCM times its MOD volume / 64, in dB relative to full scale (a half-scale square is 6 dB below a full-scale one). The audible PCM is the loop for a looped sample, or a one-shot up to its last 64-byte window within 20 dB of its loudest. It is a measurement at the sample's default volume: `Cxx`, arpeggios, other channels and the ear's frequency weighting are not included.

References come from the **distribution of loudness per group** of a sample bank: `percussion` (kick, snare, hat), `bass`, `lead` (also chords) and `texture` (also effects). Groups come from the bank's heuristic categories and tags. Inside `percussion` each role aims at its own point of the bank's distribution: **kick and kick+hat at the upper quartile (p75), snare and snare+hat at the median, hat at the lower quartile (p25)**, so a hat sits below a snare and a snare below a kick, as the bank's own percussion does. Every other role (bass, lead, chord, texture) aims at the median of its group. `synth palette` and `synth add` set each created sample's volume so its loudness lands on its role's target, raising the recipe `peak` when volume 64 is not enough:

- `--match-library [PATH]` uses the bank at `PATH` (default `exports/sample_library`). This is the default when that bank exists.
- **One automatic rule.** `synth add`, `synth palette`, `sample draw --as-recipe`, `sample_match_level` and `report` choose the reference the same way when none is forced: an explicit bank wins; else `exports/sample_library` under the working directory when it exists, for library and synthesized projects alike; else the fixed levels below. Each result says which one it used (`reference`, and for `report` and `sample_match_level` also the path and a `reason`). The `recipe_sample` patch operation is the exception: its `match` defaults to `"defaults"`, so a patch file gives the same volumes in any working directory; pass `"match": "library"` to use a bank.
- Without a bank, fixed reference levels are used, measured once from an aggregate of a local bank (p25 / median / p75, dB): `percussion` −11.9 / −6.2 / −3.8, `bass` −8.5 / −7.3 / −5.0, `lead` −12.5 / −9.9 / −5.9, `texture` −6.2 / −2.8 / −1.7.
- `--no-match` keeps the stated or default volumes; an explicit `--volume` also disables matching.
- A target that volume 64 and `peak` 1 cannot reach is reported with `limited_by_peak: true` and the remaining `deviation_db`. `report` flags the same case: a slot's `reachable_db` is its level at volume 64 with its peak at full scale, and a `sample_level_off_reference` warning says "limited by peak" when the reference is above it.
- The `loudness` record holds `role`, `group`, `reference`, `target_db`, `unmatched_db`, `volume`, `measured_db`, `deviation_db` and, if raised, `peak_raised_from`.

### Where samples come from: `metadata.sample_source`

A project may declare `"sample_source"` in `metadata`: `"library"` (only PCM from a sample bank; no recipe samples), `"synthesized"` (every non-empty sample has a recipe) or `"mixed"` (anything). Undeclared projects are not constrained.

- `validate SRC --sample-source synthesized|library` fails with `SAMPLE_SOURCE` and lists the offending slots in `violations` (`slot`, `name`, `reason`). The flag overrides the declaration; a conflicting `library`/`synthesized` declaration is itself a violation.
- Without the flag, `validate` **also checks a declared source** and reports violations as errors, so a declared project cannot pass `validate` while breaking its own rule. `validate --report` returns the same violations as `PROJECT_INVALID` entries with the code `SAMPLE_SOURCE` and the path `samples[N]` (collected once the structural checks pass). A successful `validate` prints `sample_source` (`declared`, `required`, `checked`, `recipe`, `embedded_pcm`).
- `samples add`, patch `library_sample` and the window's library insertion are refused with `SAMPLE_SOURCE` in a `synthesized` project; `recipe_sample` and `synth add` are refused in a `library` project. Set `"sample_source": "mixed"` in the JSON, only when the owner asks for both.
- `export` does not check the declaration; validate first.

## Measuring and comparing versions

### lint

```sh
python -m tracker4agents lint exports/song/project.json [--strict]
```

`lint` takes a project, MOD or XM and prints `chiploom.lint.v1` JSON: cells whose effect does nothing (`inert`), does something other than the cell suggests (`misleading`), or works but tires the ear (`texture`). It follows the playback timeline like `report`, so it knows each row's speed and the instrument playing on each channel; a cell played several times is listed once with `times_played`, and patterns that are never played are not linted. Rules follow FastTracker II for an XM and ProTracker for a MOD. A finding is advice about the score, not a validation error: the song still validates, exports and plays. `--strict` exits with status 1 when there is any finding (for scripts); `validate --report` adds a `lint` summary (`count`, `counts`).

| Code | Kind | Cell |
| --- | --- | --- |
| `offset_without_note` | inert | `9xx` without a note in the same cell |
| `offset_past_end` | misleading | `9xx` at or past the end of the sample (`frames` gives its length): FastTracker II plays nothing |
| `finetune_without_note` | inert | `E5x` without a note in the same cell |
| `instrument_without_note` | misleading | XM: an instrument number other than the playing one, without a note; FastTracker II keeps the playing sample and only resets the volume and the envelope (a MOD sample swap is not flagged) |
| `retrig_volume_ignored` | misleading | XM: `Rxy` with a volume change `x` and a volume set in the volume column, which FastTracker II applies after each retrigger |
| `key_off_k00` | misleading | XM: `K00`; write `===` in the note column instead |
| `slide_both_nibbles` | misleading | `Axy`, `5xy`, `6xy`, `Hxy` or `Pxy` with both nibbles set: only the first runs |
| `tick_effect_after_row` | inert | `E9x`, `ECx` or `EDx` whose tick is not reached at the row's speed (an `EDx` note is then never played in FastTracker II) |
| `portamento_without_note` | inert | `3xx`, `5xy` or a volume-column `Fx` on a channel that has not played a note yet |
| `held_arpeggio` | texture | one note under an `0xy` arpeggio for more than 1.2 s without a new note or a cut (`rows`, `seconds`; the same measure as `report`) |
| `effect_memory_empty` | inert | an effect with parameter `00`, which repeats the last value given to it on the channel, before any value was given: in an XM every effect with a memory (`1xx` `2xx` `3xx` `4xy` `7xy` `9xx` `Axy` `Hxy` `Pxy` `Rxy` `E1x` `E2x` `EAx` `EBx` `X1x` `X2x`; `5xy` and `6xy` share the `Axy` value), in a MOD `3xx` `4xy` `7xy` `9xx`. A `900` also counts for `offset_past_end` with the remembered offset |
| `zero_parameter` | inert | MOD: `100`, `200`, `A00`, `E10`, `E20`, `EA0` or `EB0`, which ProTracker does not remember, so they do nothing (`500` and `600` still run their portamento or vibrato) |

Each finding has `code`, `kind`, `order`, `pattern`, `row`, `channel`, `cell` (grid text), `message` and `times_played`; `counts` totals them by code, `clean` is true when there is none, and `rules` describes every rule. At most 500 findings are listed (`truncated`).

### report

```sh
python -m tracker4agents report exports/song/project.json
```

`report` takes a project or MOD and prints `chiploom.report.v1` JSON. Loudness is compared with a reference chosen by the same rule as `sample_match_level` and `synth add` (see [Loudness matching](#loudness-matching)): `--library PATH` (explicit, must exist); else the default bank `exports/sample_library` under the working directory when it exists, for library and synthesized projects alike; otherwise the fixed reference levels. `samples.loudness_reference` says which one was used and why: `{"source": "library" | "defaults", "path": "<bank folder>" | null, "selection": "explicit" | "automatic" | "default", "reason": "..."}`. Channels are numbered from 0 everywhere in the report (`channels[].channel`, repetition blocks, the `channels` list of each sample slot, warning messages such as "Channel 0 starts no note"), like patch operations. Everything in it is a **measurement of the symbolic score along its playback timeline** (first replay cycle, with repeated orders, jumps and tempo changes counted as played). It does not render audio and is not a quality verdict. The `scope` field says so in the output itself.

| Section | Contents |
| --- | --- |
| `timing` | Duration, loop start and length, rows and orders played, speed and BPM range, tempo changes |
| `channels` | Per channel: note starts, notes per second, density, lowest and highest note, range, samples used (by note starts or sample switches), effects used, portamento targets, longest gap without a note, `held_arpeggios` (`count` of runs longer than 1.2 s where one note keeps an `0xy` arpeggio without a new note or a cut, and the `longest`: `start_played_row`, `rows`, `seconds`), `sounding` and `pitch` (see [Sounding and heard pitch](#sounding-and-heard-pitch)) |
| `global` | Note starts, rows with and without a note start, `pitch_classes` (every note start, percussion included), a `key_estimate` that leaves percussion out (see below), `sustain` (the longest stretch with many channels sounding at once), `sounding_note` and `pitch_note` (the rules and simplifications of the two channel blocks, in the output itself) |
| `repetition` | Identical patterns, distinct pattern contents, patterns never played, repeated-block fractions for 4-, 8- and 16-row blocks |
| `samples` | Per slot: size, loop, volume, `note_ons` (note starts that play it), `sample_changes` (cells that select it without starting a note: a mid-note sample switch, a key-off or a tone-portamento target), channels, `source` (`recipe` or `embedded_pcm`), `library_id` (or null), `role` and `role_source` (see below), `loudness_db`, `peak_db`, `group`, `reference_db`, `deviation_db`, `reachable_db`, `limited_by_peak`, `pitch` (where the slot's heard frequency comes from, see below); empty and never-played slots (a slot is never played only when no cell of the played timeline selects it); `sources` counts (`recipe`, `embedded_pcm`, `declared`); `loudness_reference` |
| `warnings` | Duration and other warnings, including `sample_never_played`, `sample_level_off_reference` for a used sample more than 6 dB from its group's reference (with `limited_by_peak: true` and "limited by peak" in the message when the reference is out of reach) and `held_arpeggio` for a channel with `held_arpeggios` (`channel`, `count`, `longest_seconds`): an arpeggio held that long buzzes without pause, while one struck on the rhythm (a new note every few rows, or a `C00` / XM volume `10` cut between hits) does not trigger it; `channel_never_rests`, `crowded_sustain`, `pitch_too_low` and `pitch_too_high` (see below) |

**Slot roles.** Each slot's role decides its loudness group and whether the key estimate counts it. `role_source` says where it came from, in this order: `recorded` (`metadata.sample_sources[slot].role`, written by `recipe_sample`, `synth add` and `sample_match_level`), `recipe` (the recipe type), `library` (the bank category of the slot's `library_id`, when a bank is the loudness reference), `heuristic` (a one-shot PCM sample is percussion, a loop over 256 bytes texture, a shorter loop lead).

Two values are estimates and say so: the key, and the PCM pitch estimate behind `pitch` for slots without a recipe. The key is a correlation with standard major and minor profiles, labelled `is_estimate: true` with a margin and a confidence level whose thresholds are heuristics chosen for this tool. Note starts that play a percussion slot (kick, snare, hat or the percussion group) are left out, because drums written at a fixed note such as `C-2` would otherwise pull every song towards C. `key_estimate.percussion_excluded` lists the excluded slots (`slot`, `name`, `role`, `role_source`, `note_starts`) and the total, and `key_estimate.pitch_classes_counted` is the histogram actually used; check the list, since roles can be inferred. When the runner-up is the relative major or minor (`runner_up_is_relative`), `high` confidence needs a margin of at least 0.20: a loop such as Am-F-C-G counts almost the same pitch classes in both keys, so read the top candidates. Tracker note names are period labels and sample tuning is unknown, so the sounding pitch can differ from the written note (`channels[].pitch` gives it in Hz). A "row without a note start" is not audible silence, because sustained or looped samples keep sounding.

#### Sounding and heard pitch

`channels[].sounding` follows when each channel is heard, along the same timeline. A channel sounds from a note start until it is silenced: a key off (XM `===`, or `Kxx` at its tick), a note cut `ECx` at its tick, `C00` or XM volume column `10`, or a one-shot (unlooped) sample running out. A one-shot lasts its length in frames (minus a `9xx` offset) at its playback rate at the written note: MOD `3546895 / period × 2^(finetune / 96)`, XM `8363 × 2^((note − 49 + relative_note) / 12 + finetune / 1536)` (the linear table; an Amiga-table XM is read the same way). A looped sample sounds until it is silenced or replaced. A later `Cxx`, volume-column volume or sample number brings back a voice that is still playing after a `C00`. In an XM, a volume envelope without a loop that falls to 0 before any sustain point ends the note there (ticks at the BPM of the note start). Simplifications, stated in `global.sounding_note`: a key off ends the note even when the instrument has a volume envelope (release and fadeout are ignored), volume slides and other envelope shapes are not applied, note delays and pitch effects are ignored, and a one-shot counts until its last frame, quiet tail included.

| Field | Meaning |
| --- | --- |
| `fraction`, `seconds` | Sounding time, as a fraction of the cycle and in seconds |
| `longest_run_seconds`, `longest_run` | The longest stretch without a rest: `start_played_row`, `start_seconds`, `rows`, `seconds`, `percussion_only` (every note in it plays a percussion one-shot), `note_starts` (the channel's note starts inside the run) and `notes_per_second` |
| `longest_non_percussion_run` | The longest run with at least one note that is not a percussion one-shot (null if none); `channel_never_rests` reads this one |
| `rests` | Silences of at least 0.05 s after the channel's first note (a final silence before the cycle ends counts). Shorter gaps, such as a retrigger or a one-shot ending just before the next note, join the runs on both sides |

`global.sustain` is the longest stretch during which at least `threshold_channels` = max(4, ceil(0.6 × channels)) channels sound at once (runs, short gaps joined): `threshold_channels`, `channels`, `longest_seconds`, `start_played_row`, `start_seconds`, `rows`, `rule`. A four-channel MOD needs all four.

`channels[].pitch` gives the lowest and highest heard fundamental of the channel's pitched note starts (percussion slots left out): `lowest` and `highest` (`hz`, `note`, `slot`, or null), `note_starts_measured` and `note_starts_without_estimate`. A note's heard frequency is the slot's frequency at its reference note (MOD `C-2`, XM `C-4`, with the slot's finetune and relative note) moved by the written note. `samples.slots[].pitch` says where that frequency comes from: `estimated` (true or false), `method` (`recipe` for a wave, draw or pluck recipe, whose `frequency` is the pitch heard at MOD `C-2` finetune 0, i.e. at 8287 Hz, so an XM `C-4` at 8363 Hz sounds about 16 cents higher unless the finetune compensates; `estimate` for the PCM pitch estimate of `samples inspect`), `reference_note`, `hz_at_reference` and `reason` when there is none (percussion, unpitched noise recipe, no stable periodicity, or no note start plays the slot). Slots without an estimate are skipped. Portamento, arpeggio and vibrato are not applied, and an estimate can land on an octave of the fundamental.

Warnings, factual with the threshold in the message:

- `channel_never_rests` (`channel`, `seconds`, `start_played_row`, `note_starts`, `notes_per_second`): a channel holds slow material, a run without a rest that is both longer than 16 s and has fewer than 1.0 note starts per second (one note per bar under an arpeggio, a held continuo or pad). A busy legato line (a bass in eighth notes) is measured but not flagged, and runs made only of percussion one-shots do not count. A rest needs a key off, a cut, `C00` / XM volume `10`, or a one-shot that runs out.
- `crowded_sustain` (`seconds`, `threshold_channels`, `start_played_row`): `global.sustain` lasts more than 16 s.
- `pitch_too_low` / `pitch_too_high` (`channel`, `note`, `slot`, `hz`): a channel's lowest heard fundamental is below 40 Hz, or its highest above 3000 Hz. A bass recipe at 130.8 Hz with `relative_note` −24 played at XM `C-3` is heard at about 16.5 Hz.

### norms

```sh
python -m tracker4agents norms path/to/selection.zip path/to/xm-folder --output exports/norms.json [--details]
```

`norms` measures how the owner's reference modules *play*, never what they play: every MOD and XM in the given files, folders (recursive) and ZIP archives that the importer accepts is followed along its first playback cycle (as `report`), and the result (`chiploom.norms.v1`) holds percentiles (p10, p25, p50, p75, p90) of:

- `arpeggio`: `run_rows`, `run_ticks` (rows × speed, comparable across speeds) and `run_seconds` of every arpeggio run (the rows one note keeps an `0xy` before a new note, a key off or a cut), `run_rows_module_median` (one median per module), `modules_with_arpeggios`, and `channel_note_share` (the share of note starts carrying an arpeggio, on channels where it is at least 10%);
- `notes`: `seconds` (until the next note, a key off or a cut on the channel), `seconds_module_median`, and `endings_module_median` (the share of notes ended by the next note, a key off, a cut or the song's end);
- `channels`: `sounding_fraction`, `longest_run_seconds`, `rests_per_minute`, `notes_per_second`, one value per playing channel;
- `crowded_sustain_seconds` and `tempo` (`speed`, `bpm` of the first row).

`modules` counts what was measured (by format and channel count) and what was skipped (by error code: unsupported variants, unreadable files, files over 8 MiB). Nothing in the aggregate names a file or keeps a note, a sequence or a pattern, so it can be published without exposing or cloning a reference; `--details` adds per-module measures with file names for local inspection only. The skill cites the published norms as measured references (see `references/`). Errors: `NORMS_INPUT` (a missing source, an unreadable archive, nothing measurable).

### compare

```sh
python -m tracker4agents compare exports/song/v1.project.json exports/song/v2.project.json \
  --output exports/song-compare --seconds 20 --labels "Original" "Lift lead" --seed 7 --mp3 --language en
```

`compare` renders both versions and builds a **blind A/B page** in a new (or empty) directory: `index.html`, neutral-named `x.wav`/`y.wav` (plus each version's module, `x.mod` or `x.xm` and `y.mod` or `y.xm` after its own format, and optional MP3 copies), `answer_key.json` and `comparison.json`. Which version is X is random; `--seed` makes it repeatable. After the listener chooses a preference, optionally rates melody, groove, sound palette and arrangement, and submits, the page reveals the versions and shows per-version measurements.

| Option | Meaning |
| --- | --- |
| `FIRST`, `SECOND` | Two projects or MODs, different files |
| `--output DIR` | New or empty directory; it must not contain a source file |
| `--seconds S` | Render the same excerpt length (greater than 0, at most 120) from the start of both. Without it each version's full first cycle is rendered, and a cycle over 120 s is refused |
| `--labels A B` | Names shown after the reveal (default derived from the file names); they must differ |
| `--seed N` | Seed for the X/Y assignment |
| `--mp3`, `--ffmpeg`, `--language en\|fr` | MP3 copies, FFmpeg path, page language |
| `--show-answer` | Also print the X/Y mapping (`answer_key`) in the result |

The result gives the paths (`x.mod` and `y.mod` hold the real module paths, `.xm` for an XM version) and `answer_key_file`, the path of `answer_key.json`; it does **not** print the X/Y mapping unless `--show-answer` is given, so an agent that runs `compare` for the owner does not learn the answer. This is a **casual blind test, not secrecy**: the answer is in `answer_key.json`, in `comparison.json` and, base64-encoded, in the page source. **Loudness is not equalized unless `--equalize` is given** (MCP `equalize`): a louder version tends to be preferred. With `--equalize` the louder render is turned down to the integrated loudness of the quieter one (FFmpeg `ebur128`; never turned up, so nothing clips) before the MP3 copies are made, the page says so, and the result and `comparison.json` record `equalized` (`target_lufs` and each side's `gain_db`). Without it the page shows the measured peak and RMS of both renders after submission. An agent that reads `answer_key.json` or `comparison.json` before the owner listens has spoiled the test.

### feedback

```sh
python -m tracker4agents feedback exports/song/v1.project.json --text "Bass is too busy in the second half" \
  --rating 3 --version v1 --output exports/song/v1-feedback.project.json
```

`feedback` copies a project to a **new** `.json` file with an entry appended to `metadata.feedback`: `{"text", "rating", "source", "version", "recorded_at"}`. `--rating` is an integer 1–5 and optional, `--source` defaults to `owner`, `--version` should match the label you gave the version you asked about. Text is limited to 2000 characters without control characters. `--pattern N` (with `--row`, `--rows`, `--channel`, `--channels`) ties the note to a block of the score and adds `place` to the entry. Feedback is recorded, not interpreted; it does not change the score or any model.

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
| `live status` | `path`, `title`, `revision`, `dirty`, `orders`, `pattern_count`, `pending_proposals`, `takes`, `window` (is a window attached), `web_devices` (connected browsers), `last_change`. A window also reports its cursor, selection and playback state, and `pending_request` while an `open` request waits for the owner (see below) |
| `live score [--pattern N --row R --rows K]` | Without `--pattern`, an overview (orders, duration, patterns with the orders that use them, samples with `library_id` when recorded). With it, grid `lines` |
| `live patch (--ops FILE\|- \| --op JSON …) [--base REV] [--label TEXT] [--propose] [--author NAME]` | Apply the operations from [Patch](#operations) to the open song as one undoable transaction; with `--propose`, only offer them |
| `live sync PROJECT.json [--dry-run] [--label TEXT] [--author NAME] [--library DIR]` | Bring a project file (typically regenerated by a script) into the open song: the differences go as a few undoable patches, one per changed pattern, each checked against the revision read first. See [Syncing a project](#syncing-a-project-into-the-session) |
| `live changes [--since REV] [--author NAME]` | Journal entries after `REV`, each with `revision`, `author`, `label`, `at`, `kind`, `diff` and `summary`, plus a grouped `summary` for `human` (the window and connected browsers) and `agent`. `kind` is `patch`, `edit`, `reload`, `open`, `accept` or `request` (see below) |
| `live proposals` | Pending proposals with `id`, `label`, `status`, `ops`, `diff`, `summary`, `stale` |
| `live withdraw ID` | Withdraw your own pending proposal |
| `live take PATH --label TEXT` | Announce a saved `.json` project or `.mod` as a take (id `t1`, `t2`, …) the owner can open from the window |
| `live takes` | List takes with title, duration, size and SHA-256 |
| `live comments [--status open\|resolved\|all]` | Comments attached to places in the song (open ones by default); see [Comments](#comments) |
| `live comment TEXT [--pattern N --row R --rows K --channel C --channels K] [--author NAME]` | Attach a comment to a block (or, without `--pattern`, to the whole song) |
| `live reply ID TEXT [--author NAME]` | Reply to a comment |
| `live resolve ID [--text TEXT] [--reopen] [--author NAME]` | Mark a comment resolved, with an optional closing reply, or reopen it |
| `live open (PATH \| --take ID)` | Ask the window to open a file or a take |
| `live play [--order N]` / `live stop` | Start or stop playback in the window (`LIVE_NO_WINDOW` without a window) |
| `live select --pattern N --row R --channel C [--rows K --channels K]` | Move the window's selection to show a passage |
| `live save [--output PATH]` | Save the project JSON |
| `live serve SOURCE [--port N] [--web] [--lan [--lan-host ADDRESS] [--lan-port N]] [--no-web]` | Host a headless session on a project or MOD until Ctrl+C. `--web` also prints the address of the browser studio (no code), `--lan` offers the studio (only the studio) to the private network and implies `--web`, `--no-web` turns the studio off |
| `live web [--status]` | Print the address of the browser studio of the running session (the local-network address first when that option is on). `--status` lists the connected browsers (`id`, `name`, `agent`, `listener`, `joined_at`, `last_seen`) instead. `LIVE_WEB_OFF` when the studio is off |

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

**Open requests that wait for the owner.** `live open` asks the window to open a file or a take. If the window has no unsaved changes it opens at once and the reply is `{"ok": true, "handled": true, "opened": "<path>"}`. If it has unsaved changes, the owner must first answer a save-or-discard question, which can take minutes, so the reply comes immediately with `handled: "pending"` and nothing else has happened yet:

```json
{"ok": true, "handled": "pending", "prompt": true, "request_id": "o1"}
```

While the question is open:

- `live status` carries `pending_request`: `{"request_id": "o1", "kind": "open", "path": "...", "take": "t1" or null, "waiting_for": "the owner's save or discard answer"}`. It disappears when the owner answers.
- A second `live open` is not queued: it returns `{"ok": true, "handled": false, "reason": "another open request is waiting for the owner's answer"}`.
- When the owner has answered, the outcome is written to the journal as an entry with `author: "human"`, an empty `diff`, `kind: "request"` and these fields: `request: "open"`, `request_id`, `outcome` (`"opened"`, `"declined"` when the owner cancelled, or `"failed"` when the file could not be opened), `path` and `take`. Its `label` reads *Open request: the file was opened*, *Open request: the owner declined* or *Open request: the file could not be opened*. Read it with `live changes --since REV`. When the file was opened, the usual `kind: "open"` entry (the document was replaced, which conflicts with every older `--base`) comes just before it.

So after a `pending` reply, do not assume the file is open: poll `live status` for `pending_request` or read `live changes --since REV` for the `kind: "request"` entry with your `request_id`. Other results are `handled: true` (done) and `handled: false` (nothing consumed the request; a `reason` says why when the window knows).

`live save` with no `--output` writes the session's open project file. With `--output` it writes a copy (`"copy": true`); the session and the owner's window keep their own file. Announce such a copy with `take` if the owner should open it.

`live serve` prints one JSON line when it is listening (`{"ok": true, "event": "listening", "pid": …, "url": …, "path": …, "kind": "headless", "discovery_file": …}`), then blocks. On Ctrl+C it prints `{"event": "stopped", "revision": …, "dirty": …}` and does not write unsaved edits; run `live save` first. To stop a server started in the background, end only that process by its `pid`.

The **browser studio** is a web page served by the same session at `/web/` (loopback only unless the owner enables `--lan` or the window's local-network option, which expose only the studio over plain HTTP, never the agent API). There is no pairing code: a browser that opens the address joins by itself and edits as `human-web`. `live web` prints the address; the agent's bearer token never reaches the page. See the [user guide](USER_GUIDE.md#browser-studio).

```sh
CHIPLOOM_HOME=/tmp/chiploom python -m tracker4agents live serve exports/song/project.json &
python -m tracker4agents live status
python -m tracker4agents live patch --base 0 --label "Soften intro" --op '{"op": "set", "pattern": 0, "row": 4, "channel": 0, "cell": "E-2 04 C28"}'
python -m tracker4agents live changes --since 0
```

For the collaboration procedure, see [the live reference](../skills/chiploom/references/live.md) and [the agent guide](AGENT_GUIDE.md#composing-with-the-owner-in-the-window-live).

### Comments

The owner can attach a comment to a block of the song, in the window or the browser studio ("track 5 drags here"), so the agent knows exactly where. A comment is:

```json
{"id": "c3", "author": "human", "text": "Track 5 drags here", "at": "2026-10-29T10:00:00Z",
 "place": {"pattern": 1, "row": 0, "rows": 32, "channel": 4, "channels": 1},
 "cells": ["00 | --- -- -- ...", "..."],
 "status": "open", "replies": [{"author": "agent", "text": "Moved it to the eighth grid", "at": "..."}],
 "resolved_by": null, "resolved_at": null}
```

`place` is null for a remark about the whole song. `cells` keeps the block as grid text (at most 32 rows) as it was when the comment was written, so it still says what the owner pointed at after later edits. Authors follow the live rules: `human` from the window, `human-web` from a browser, and an agent name (never one starting with `human`) from the agent API, which may also write comments of its own (for example "listen from here").

- Every new comment, reply, resolution and reopening is a journal entry with `kind: "comment"`, an empty `diff`, `comment` (its id), `action` (`created`, `replied`, `resolved`, `reopened`) and `place`, so `live changes` shows them in order with the edits. `live status` gives `open_comments`.
- Comments are saved with the project under `metadata.comments` and come back when it is reopened. They live beside the score, outside the undo history: undoing a note never removes a comment, and adding one makes the project unsaved.
- Errors: `COMMENT_INVALID` (empty or longer than 1000 characters, a place outside the song, an already resolved comment), `COMMENT_UNKNOWN`. At most 300 comments are kept (the oldest resolved ones go first) and 50 replies per comment.
- MCP tools: `live_comments`, `live_comment`, `live_reply` (with `resolve` or `reopen`).

The usual loop: read `live comments` (or the `kind: "comment"` entries of `live changes`), select the place with `live select` if useful, fix it with `live patch`, then `live resolve ID --text "what I changed"` so the owner sees the answer next to their comment.

`feedback` takes the same place (`--pattern N --row R --rows K --channel C --channels K`) to store a listening note tied to a block in `metadata.feedback`.

### Syncing a project into the session

`live sync PROJECT.json` is for the agent that rewrites or regenerates a whole project (with a script, say) while the owner has the song open. Instead of reopening the file, which would replace the owner's undo history, it sends only the differences, as ordinary agent patches the owner sees highlighted and can undo one by one.

1. It reads the session's whole module and its `revision` in one call (the live API's `module` method: a schema v2 project with every sample's PCM, plus the recipes of recipe samples).
2. It compares the module with the project, slot by slot and pattern by pattern (patterns are matched by index), and turns the differences into [operations](#operations).
3. It simulates every patch on a copy with the checks the session runs, then sends them in this order, each with `base_revision` set to the revision read in step 1:
   - `<label>: samples`: `recipe_sample` with `replace` for a recipe sample whose PCM or loop changed, `library_sample` with `replace` (from `--library`, default `exports/sample_library`) when the project's `metadata.sample_sources` records the slot's `library_id`, then `sample` for name, volume, finetune and, in an XM, panning, relative_note and loop_mode. A slot is only sent when the simulated insertion gives exactly the project's PCM and loop;
   - `<label>: structure`: title, new patterns (`add_pattern`, with `copy_of` when the session already holds an identical pattern), pattern names, XM pattern lengths (`pattern_length`, with `truncate` when rows are cut), the order list (`set_orders`), patterns removed at the end (`remove_pattern`) and the XM header (`xm_header`). New patterns travel with the order list because a MOD must list its last pattern;
   - `<label>: <pattern name>`: one patch per pattern whose cells differ, with one `write` per changed channel (from its first to its last changed row) or a `clear` when those rows become empty.

   When an intermediate step would be invalid (for example a `Bxx` in an old pattern that points past the new order list), the structure and all the cells go as one patch, `<label>: whole song`.
4. It reads the session again and checks that everything it sent now matches the project.

`--label` sets the prefix (default `Sync`); `--author` is the patch author (default `agent`); `--dry-run` plans and prints the patches with their `ops` and sends nothing.

```json
{"ok": true, "project": ".../exports/song/project.json", "revision_before": 12, "revision_after": 15,
 "unchanged": false, "verified": true, "not_synced": [],
 "patches": [{"label": "Regen: structure", "pattern": null, "op_count": 1, "revision": 13, "changed": true},
             {"label": "Regen: Verse", "pattern": 2, "op_count": 2, "revision": 14, "changed": true},
             {"label": "Regen: Chorus", "pattern": 3, "op_count": 1, "revision": 15, "changed": true}]}
```

- `unchanged: true` with an empty `patches` list: the session already matches the project for everything a patch can carry.
- `verified: false` comes with `mismatches` (the first ten, each with `unit`, its coordinates, `project` and `session`) and `mismatch_count`, typically because the owner edited something else while the sync ran.
- **Not synced.** Patch operations cannot carry everything. These differences are listed in `not_synced`, each with `what` and a `reason`, and are never sent: PCM edits of samples that have neither a recipe nor a recorded `library_id`, sample slots that exist only in the session, XM instrument data (`XM instrument N` with the differing `fields`: envelopes, auto-vibrato, fadeout), other `metadata.xm` values, `metadata.sample_sources` records (an inserted sample writes its own) and the rest of the project `metadata`. Reload the project in the window (`live open PATH`) to take them, at the cost of the window's undo history.
- The project and the session must have the same format and channel count (`LIVE_SYNC_FORMAT` otherwise). A plan the session would refuse fails with `LIVE_SYNC_PLAN` before anything is sent.
- **Conflicts.** If the owner edited, after the read, a unit a patch would change, that patch fails with `LIVE_CONFLICT` and the sync stops. The error (on stderr, exit code 2) carries the usual `conflicts` and `revision`, plus `sync`: `revision_before`, `applied` (the patches already in the window, with their revisions), `failed`, `not_applied` and `not_synced`. Read `live changes`, adapt the project and sync again: only what still differs is sent.

## MCP adapter

```sh
python -m tracker4agents mcp [--root DIR]
```

`mcp` speaks the Model Context Protocol over standard input and output (JSON-RPC 2.0, one message per line). It supports protocol versions `2025-11-25`, `2025-06-18`, `2025-03-26` and `2024-11-05`, `initialize`, `ping`, `tools/list` and `tools/call`. `--root` sets the working directory used for relative paths in tool arguments (default: the directory the server starts in).

Each tool call runs the equivalent `chiploom` command in a **child process**, so the result is exactly the CLI's JSON: it arrives as `structuredContent` (and as text), with `isError: true` when the command failed, carrying the same `code`/`message` fields. Nothing a command prints can corrupt the protocol stream. A command is stopped after 600 seconds (`TIMEOUT`).

| Tools | Maps to |
| --- | --- |
| `estimate`, `validate`, `inspect`, `export`, `render`, `preview`, `migrate` | the commands of the same name (`validate` takes `report`, `inspect` takes `pattern`, `grid`, `row`, `rows`) |
| `patch` | `patch` with `source`, `output`, `ops` (a JSON array) or `ops_file` (a path to a JSON file holding it; give exactly one) and `label` |
| `new_project` | `new` with `output`, `title`, `channels`, `patterns`, `speed`, `bpm`, `sample_source` |
| `report`, `compare`, `feedback` | the commands of the same name; `compare` offers `mp3`, `language`, `seed` and `seconds` but not `labels` |
| `samples_list`, `samples_inspect`, `samples_preview`, `samples_add` | `samples list`, `inspect`, `preview`, `add` (no `extract`, `edit` or `audit`) |
| `sample_schema`, `sample_edit`, `sample_draw`, `sample_waveform`, `instruments_list`, `instruments_show`, `instruments_save`, `instruments_delete`, `instruments_apply` | the `sample` and `instruments` commands of the [sound workshop](#sound-workshop-sample-editing-and-instruments); `trim`, `loop` and `fade` are two-integer arrays, `phrase` a list of strings |
| `convert`, `export_format` | `convert` and `export --format` ([multi-channel MOD and XM](#multi-channel-mod-and-xm)) |
| `synth_types`, `synth_levels`, `synth_preview`, `synth_add`, `synth_palette` | `synth types`, `levels`, `preview`, `add`, `palette`; `recipe` is a JSON object, `match_library` a bank folder, `no_match` a boolean |
| `live_sessions`, `live_status`, `live_score`, `live_patch`, `live_changes`, `live_proposals`, `live_withdraw`, `live_take`, `live_takes`, `live_open`, `live_play`, `live_stop`, `live_select`, `live_save` | the `live` subcommands; `live_patch` takes `ops` or `ops_file`, `base_revision`, `label`, `propose`, `author` |

There are 51 tools; the full list, with every argument, is in [MCP.md](MCP.md#tools). `validate` also takes `sample_source`; `report` takes `library`. `demo`, `import`, `analyze`, `gui` and `live serve` are not exposed; use the CLI for them. Read-only tools carry `readOnlyHint`.

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

Use the virtual environment's interpreter on the host where the files live (`.venv/bin/python` on Linux and macOS). The adapter is covered by the project's automated tests (`tests/test_mcp.py`), and `tools/mcp_smoke.py` drives it with the official Python MCP SDK as a client (see [what was tested](MCP.md#what-was-tested)). It has **not** been tried in a model-driven session with an application such as Codex, Claude Desktop or Claude Code, so no application is claimed to work. Agents with a terminal, such as Codex or Hermes, can keep calling the CLI directly; nothing requires MCP.

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
| `violations` | Only for `SAMPLE_SOURCE`: the offending slots with `slot`, `name` and `reason` |
| `errors`, `error_count` | Only for `validate --report` (`PROJECT_INVALID`): one entry per independent problem |
| `reasons` | Only for `CONVERT_REFUSED`: every cause, each with its own `code` and `message` |

A position prefix such as `ops[1] (set): ` or `Pattern 0, row 00: ` is kept and the text after it is translated. A failing patch operation keeps the code of the underlying error (`RECIPE_INVALID`, `SAMPLE_SLOT`, `SAMPLE_LIBRARY`, ...); `PATCH_OP` means an unknown operation. The `code` is the reliable signal. Argument-parser errors, `--help` and `--version` are plain text.

### Codes

| Group | Codes |
| --- | --- |
| Files and formats | `JSON_SYNTAX`, `IO_ERROR`, `SCHEMA`, `UNKNOWN_FIELD`, `MOD_FORMAT` (not a supported MOD: unknown signature, bad size or truncated data), `MOD_FLT8` (an FLT8 module, which stores each pattern as two four-channel halves), `MOD_VARIANT` (an Octalyser or TakeTracker signature such as CD81, OCTA or TDZx), `MOD_METADATA` (an invalid `metadata.mod` block), `FORMAT` (a format name other than `mod` or `xm`), `ARCHIVE_INVALID`, `FILE_TOO_LARGE`, `INTEGER_RANGE`, `INVALID_VALUE`, `TEXT_ASCII`, `TEXT_LENGTH`, `TEXT_TYPE` |
| Score content | `NOTE_UNKNOWN`, `NOTE_RANGE`, `EFFECT_FORMAT`, `EFFECT_PARAM`, `EFFECT_UNSUPPORTED`, `CELL_DUPLICATE`, `FLOW` (invalid `Bxx`/`Dxx` target), `TIMING` (`F00`/`F20`, or no room for `timing`), `PATTERNS`, `ORDERS` |
| XM and channels | `CHANNELS` (a channel count outside 2 to 32), `MOD_XM_FIELD` (an XM-only field such as the volume column on a MOD), `XM_SAMPLE` (bits, loop mode or volume of an XM sample), `XM_VOLUME_COLUMN` (an invalid volume-column byte), `XM_METADATA` (an invalid `metadata.xm` block), `XM_OP_UNSUPPORTED` (a sample-editing patch operation that only applies to MOD), `MOD_OP_UNSUPPORTED` (`pattern_length` or `xm_header` on a MOD), `PATTERN_TRUNCATE` (`pattern_length` would drop notes without `truncate`), `CONVERT_REFUSED` (an XM that does not fit the MOD profile; `reasons` lists every cause) |
| XM import | `XM_VERSION` (only version 0x0104), `XM_SAMPLE_TYPE` (stereo or ADPCM samples), `XM_INSTRUMENT_HEADER` (an instrument header shorter than 29 bytes or running past the file), `XM_FORMAT` (a malformed or truncated XM), `IT_UNSUPPORTED` / `S3M_UNSUPPORTED` (an Impulse Tracker or Scream Tracker 3 module, whatever its extension). Multi-sample instruments, odd header sizes, oversized fadeouts, unordered envelope points, loop type 3 and undefined effects are imported with notes (see [XM profile](#xm-profile-fasttracker2-xm-v1)) |
| Samples | `SAMPLE_SLOT`, `SAMPLE_REF` (a cell uses a slot that does not exist), `SAMPLE_LOOP`, `SAMPLE_LENGTH`, `SAMPLE_PCM`, `SAMPLE_PCM_HASH`, `RECIPE_INVALID` (a recipe parameter, role or recipe JSON), `SAMPLE_LIBRARY` (unknown library ID, missing or invalid bank), `SAMPLE_SOURCE` (the project's sample source is not respected; `violations` lists the slots), `SAMPLE_CLIP` (a gain would clip) |
| Instruments | `INSTRUMENT_INVALID` (an instrument file or field), `INSTRUMENT_NOT_FOUND` (unknown instrument ID), `INSTRUMENT_EXISTS` (the ID exists and `replace` was not set) |
| Project validation | `PROJECT_INVALID` (the wrapper of `validate --report`; each entry has its own code) |
| Patch | `PATCH_FORMAT`, `PATCH_OP`, `PATCH_FIELD`, `PATCH_CELL`, `PATCH_BOUNDS` |
| Output and migration | `OUTPUT_PATH` (source equals output, wrong extension, existing directory, bank path), `MIGRATION_MISMATCH` |
| Rendering | `FFMPEG_MISSING`, `XMP_MISSING` (the libxmp reference library is not set up for `--engine xmp`), `RENDER_LIMIT` (over 120 s, sample rate, preroll or unreachable order), `RENDER_TIMEOUT`, `RENDER_FAILED` |
| Live: connection | `LIVE_NOT_RUNNING` (no matching session, or it did not answer), `LIVE_TIMEOUT`, `LIVE_AUTH`, `LIVE_FORBIDDEN` (browser request), `LIVE_HOST`, `LIVE_BAD_REQUEST`, `LIVE_BAD_RESPONSE`, `LIVE_METHOD`, `LIVE_UNKNOWN_METHOD`, `LIVE_TOO_LARGE`, `LIVE_COMMAND` |
| Live: editing | `LIVE_CONFLICT`, `LIVE_BASE` (invalid `--base`), `LIVE_AUTHOR`, `LIVE_LABEL`, `LIVE_PARAMS`, `LIVE_PROPOSAL`, `LIVE_TAKE`, `LIVE_SYNC_FORMAT` (`live sync` across formats or channel counts), `LIVE_SYNC_PLAN` (a planned sync patch the session would refuse) |
| Live: window | `LIVE_NO_WINDOW`, `LIVE_OPEN`, `LIVE_REQUEST`, `LIVE_SAVE_PATH`, `LIVE_CONTEXT`, `LIVE_ERROR` |
| Live: browser studio | `LIVE_WEB_OFF` (the studio is turned off for the session), `LIVE_WEB_AUTH` (this browser has not joined, or its cookie expired), `LIVE_CSRF`, `LIVE_LAN` (the LAN listener could not start), `LIVE_RENDER` (invalid preview request), `LIVE_RENDER_UNAVAILABLE` (no renderer), `LIVE_BUSY` (another preview is rendering) |
| Generic fallbacks | `VALIDATION`, `RUNTIME_ERROR`, `ERROR`; `FEEDBACK_INVALID` (feedback text or rating) |
| MCP adapter only | `TIMEOUT` (a command ran over 600 seconds), `CLI_ERROR` (the command printed something that was not JSON), `INVALID_ARGUMENTS` (tool arguments that do not match the tool's schema) |

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

## Sound workshop: sample editing and instruments

These tools shape sounds **on a copy of a project** and keep the music in the notes. They exist for the owner (the window's sound workshop) and for agents the owner asks to edit a sound. The default composition policy of an agent is unchanged: take library samples as they are, shape them with notes, volume and effects, and record the library IDs. Every command below writes a **new** `.json` project; the input is never touched. Everything is also available as [patch operations](#operations) (one validated, undoable transaction) and as MCP tools.

### Sample edits (patch operations)

All of them take `slot` (1-31, an occupied slot) and work on the signed 8-bit PCM. Offsets are bytes and even. Every result has `changed` (false when nothing differed: the recipe and provenance are then left alone). Unknown fields are `UNKNOWN_FIELD`.

| `op` | Fields | Effect |
| --- | --- | --- |
| `sample_loop` | `loop_start`, `loop_length`, optional `adapt` | Set the loop (even points, at least 4 bytes, ending inside the sample; `SAMPLE_LOOP` otherwise). `loop_length` 0 removes the loop and needs `loop_start` 0. **A sample without a loop must begin with two zero bytes** (the replayer's silent no-loop word): if the first two bytes are not zero, removing the loop is refused with `SAMPLE_LOOP` unless `adapt` is true, which prepends two zero bytes and leaves the original PCM intact. Reports `seam_jump` (difference between the last loop byte and the first, 0-255: a measure of the click at the seam) and `adaptations` |
| `sample_trim` | `start`, `end` (at least one), `adjust_loop`, `adapt` | Keep exactly `pcm[start:end]` (both even, at least 4 bytes; `SAMPLE_LENGTH`). A loop that stays whole moves with the bytes. A range that cuts the loop is refused (`SAMPLE_LOOP`) unless `adjust_loop`, which keeps the part of the loop inside the range (`loop-shortened`; under 4 bytes the loop is removed, `loop-removed`). A result without a loop that would not begin with two zero bytes needs `adapt` (same prepend as above) |
| `sample_gain` | `db` (-60 to 60), `allow_clip` | Multiply the PCM by 10^(db/20), rounding halves away from zero. A gain that would leave -128..127 is refused (`SAMPLE_CLIP`; the message gives the clean headroom) unless `allow_clip`, which clamps and reports `clipped`. Reports `peak_before`, `peak_after`, `changed_bytes` and `headroom_db` (the clean headroom **before** the gain) |
| `sample_fade` | `fade_in`, `fade_out` (bytes, at least one), `allow_loop` | Linear fade from/to silence over the first/last bytes. On a looped sample a fade must stay outside the loop (`SAMPLE_LOOP`) unless `allow_loop` (every repeat would then dip) |
| `sample_set_pcm` | `pcm_base64`, `pcm_sha256`, optional `loop_start`, `loop_length` (default: no loop), `name`, `volume`, `finetune`, `replace`, `adapt` | Put drawn or computed PCM in a slot (an existing one, or the next free slot). Same hash-checked encoding as a schema v2 project (`SAMPLE_PCM`, `SAMPLE_PCM_HASH`); an occupied slot needs `replace` and keeps its name, volume and fine tune unless given; a one-shot needs its two zero bytes or `adapt`. Refused (`SAMPLE_SOURCE`) in projects declared `library` or `synthesized` |
| `sample_match_level` | optional `role`, `library`, `match` | Set the volume to the reference level of the sample's role (`kick`, `snare`, `hat`, `bass`, `lead`, `chord`, `texture`, or a group; default: the recorded role, else the recipe, else the bank category of the slot's `library_id` when a bank is the reference, else the loop heuristic). Reference: `library` (a bank folder) wins; otherwise `exports/sample_library` when it exists, else the fixed levels, as in [Loudness matching](#loudness-matching). `match` forces it: `"defaults"` (fixed levels; not with `library`), `"library"` (a bank is required) or `"auto"` (default). If volume 64 cannot reach the target, clean gain is added to the PCM (never clipped; `limited_by_peak` is true when the peak still falls short). A recipe sample **stays a recipe**: its volume is matched and its `peak` raised if needed (`method: "recipe"`, `gain_db` 0, `peak_raised_from`/`peak` when raised). The role used is saved in `metadata.sample_sources[slot].role` (other provenance fields are kept), so `report` compares the sample with the same group. Result: `method`, `role`, `role_source` (`op`, `recorded`, `recipe`, `library`, `heuristic`), `target_db`, `volume_before`, `volume`, `gain_db`, `measured_db`, `deviation_db`, `limited_by_peak`, `reference` (`library` or `defaults`), `reference_path`, `reference_selection`, `reference_reason` |
| `apply_instrument` | see [Instruments](#instruments) | Write a note and the instrument's effect phrase |

```json
{"op": "sample_trim", "slot": 4, "start": 0, "end": 800, "adapt": true}
{"op": "sample_loop", "slot": 7, "loop_start": 128, "loop_length": 512}
{"op": "sample_gain", "slot": 7, "db": -3.5}
{"op": "sample_fade", "slot": 4, "fade_out": 200}
{"op": "sample_match_level", "slot": 7, "role": "bass"}
```

**Provenance.** Every edit that changes PCM or the loop is recorded in the project's `metadata.sample_sources[slot]`. Schema v2 stays compatible: `metadata` is free-form, and library and recipe insertion already write that map.

| Edited slot | Entry after the first edit |
| --- | --- |
| Recipe sample | `{"origin": "derived", "derived_from": "recipe", "recipe": {the recipe that built the PCM}, "recipe_type", "role"?, "edited": true, "edits": [...], "edit_count": 1}`. The slot's `recipe` is dropped: the project now stores the edited bytes (`pcm_base64`) |
| Library sample | its entry keeps `library_id` and `origin`, plus `"edited": true`, `edits`, `edit_count` |
| Other embedded PCM | `{"origin": "embedded-pcm", "edited": true, "edits": [...], "edit_count": n}` |
| `sample_set_pcm` | `{"origin": "drawn", "pcm_sha256", "replaced_library_id"?}` |

`edits` keeps the last 16 operations as `{"op": "sample_gain", "db": -3.5}`; `edit_count` is the total. Inserting another sample in the slot (`library_sample`, `recipe_sample`) replaces the entry. `report` and the window read `role` and `library_id` from it.

**Sample source rules.** Editing a library sample in a `library` project is shaping and is allowed (its `library_id` stays). Drawn or embedded PCM is refused in `library` and `synthesized` projects (`SAMPLE_SOURCE`), and so is any PCM edit of a recipe sample in a `synthesized` project (it would drop the recipe and fail `validate`). In that case use `sample_match_level`, change the recipe, or draw with the `draw` recipe (`sample draw --as-recipe`). `SAMPLE_SOURCE` errors carry `violations`.

### `sample` commands

| Command | Result |
| --- | --- |
| `sample edit PROJECT --slot N --output OUT.json [--trim START END] [--loop START LENGTH \| --no-loop] [--fade IN OUT] [--gain DB] [--match-level [--role R] [--library PATH]] [--adjust-loop] [--adapt] [--allow-clip] [--allow-loop] [--label L]` | Applies the given edits in this fixed order (trim, loop, fade, gain, match-level) as one transaction and writes a **new** project (the output must differ from the input). Returns `changed`, `results` (one entry per operation, in that order), `changes`, `duration_seconds` and `sample` (`bytes`, `volume`, `finetune`, loop, `recipe`, `pcm_sha256`, `peak`, `loudness_db`, `provenance`) |
| `sample draw PROJECT --slot N --points JSON --output OUT.json [--cycles 16] [--frequency 261.63] [--peak 0.88] [--name N] [--volume V] [--finetune F] [--replace] [--as-recipe]` | Draws a looped wave from 4-256 points between -1 and 1 (`@file.json` accepted) into a slot. By default the PCM is embedded (`sample_set_pcm`, volume 40 unless `--volume`); with `--as-recipe` a `draw` recipe is stored (`recipe_sample`), which also works in `synthesized` projects, and without `--volume` its volume is matched like `synth add` (to `exports/sample_library` when it exists, else the fixed levels) |
| `sample waveform SOURCE --slot N [--buckets 128]` or `sample waveform --recipe JSON` | `{"bytes", "loop_start", "loop_length", "bucket_count", "buckets": [[min, max], ...]}`: the signed PCM's minimum and maximum per bucket, for drawing a waveform or for a reader that cannot listen. `SOURCE` is a project, a MOD or an XM; a 16-bit XM sample adds `"bits": 16` and its buckets span -32768..32767 |
| `sample schema` | Every recipe type with parameters, ranges, defaults and a valid `default_recipe`, plus `roles`, `notes` and `limits`: what a form needs |

Errors use the usual contract. `SAMPLE_CLIP` (a gain would clip) is new; the others are existing codes: `SAMPLE_LOOP`, `SAMPLE_LENGTH`, `SAMPLE_SLOT`, `SAMPLE_PCM`, `SAMPLE_PCM_HASH`, `SAMPLE_SOURCE`, `RECIPE_INVALID`, `PATCH_FIELD`.

### Instruments

An instrument is a sample plus how to play it: default volume and fine tune, and a **phrase** of up to 32 effect rows written on the rows that follow the note (a plucked bass is a sample and `["000", "C30", "C20", "C10"]`). One JSON file per instrument, in an instrument folder (default `exports/instruments`, ignored by git with the rest of `exports/`). IDs are `INS-0001`, `INS-0002`, ...; names are neutral ASCII labels of at most 22 characters (they become the sample name).

```json
{
  "schema": "chiploom.instrument.v1",
  "id": "INS-0001",
  "name": "Soft Pluck",
  "role": "bass",
  "tags": ["pluck"],
  "volume": 44,
  "finetune": 0,
  "phrase": ["000", "C30", "C20", "C10"],
  "sample": {"kind": "recipe", "recipe": {"type": "wave", "shape": "triangle", "frequency": 130.81}}
}
```

`sample` is one of `{"kind": "library", "library_id": "SMP-0007"}` (the ID only: no PCM is copied, the bank is read when the sample is inserted), `{"kind": "recipe", "recipe": {...}}`, or `{"kind": "pcm", "pcm_base64", "pcm_sha256", "loop_start", "loop_length", "origin"?}`, where `origin` (`library_id`, `edited`, `derived_from: "recipe"`, `recipe_type`) says where edited PCM came from. `role`, `tags` (up to 16 lowercase words), `volume` (default 40) and `finetune` (default 0) are optional. Phrase rows are three hexadecimal digits; `...`, `---` and an empty string mean `000`. `Bxx`, `Dxx` and `Fxx` (song flow and timing) and effects the profile does not play are refused. Errors: `INSTRUMENT_INVALID`, `INSTRUMENT_NOT_FOUND`, `INSTRUMENT_EXISTS`, `UNKNOWN_FIELD`, plus the sample and recipe codes.

**`apply_instrument`** fields: `pattern`, `channel`, `row`, `note`, `instrument` (an ID in the instrument folder, or an inline instrument object), and optional `slot`, `replace`, `length`, `overwrite`, `library` (sample bank for library instruments, default `exports/sample_library`) and `instruments` (instrument folder, default `exports/instruments`).

- The note goes on `row` with the instrument's sample number. Phrase row 0 is the effect of that same row, row 1 the next row, and so on, in the same channel.
- It stops at the next row of that channel that holds a note (`stopped: "next_note"`), after `length` rows (default: the phrase length; `"length"` when that cuts the phrase), at row 63 (`"end_of_pattern"`) or at the end of the phrase (`"phrase_end"`). It never crosses into another pattern. Only the cells listed in `rows_written` change; sample numbers in later cells are left alone. Because a phrase stops at the next note that already exists, apply the instruments of one channel **from the last note to the first** (or write all notes first and use `overwrite`): applied in time order, an early phrase runs over rows where later notes will go, and those notes keep its effects (they are only listed in `skipped`).
- Existing effects are kept: a phrase row that meets one is listed in `skipped` unless `overwrite` is true, and `Bxx`/`Dxx`/`Fxx` are never replaced. A `000` phrase row never clears anything.
- The sample is reused when the song already holds an identical one (same PCM, loop, volume and fine tune; the name does not matter). Otherwise it goes in `slot` (an occupied one needs `replace`) or the first free slot (`SAMPLE_SLOT` when all 31 are in use). A library instrument whose sample the song already holds, unedited, needs no bank.
- Sample source rules as for any insertion: library instruments are refused in `synthesized` projects, recipe instruments in `library` projects (`SAMPLE_SOURCE`). PCM instruments are refused in both, unless their `origin.library_id` makes them a library sample in a `library` project.
- Result: `slot`, `slot_reused`, `instrument`, `name`, `rows_written`, `phrase_rows`, `stopped`, `skipped`, `sample`.

| Command | Result |
| --- | --- |
| `instruments list [--dir D] [--query Q] [--tag T] [--role R] [--offset N] [--limit N]` | `{"ok", "folder", "total", "instruments": [...], "invalid"?}`: summaries without PCM; unreadable files are listed in `invalid` instead of failing the list |
| `instruments show ID [--dir D] [--full]` | One instrument; `--full` includes embedded PCM |
| `instruments save --name N (--project P --slot S \| --recipe JSON \| --library-id SMP-... \| --json JSON) [--phrase "000,C30,C20"] [--role R] [--tag T] [--volume V] [--finetune F] [--embed] [--id INS-... --replace] [--dir D]` | Saves and returns `instrument`. From a project slot: a recipe sample becomes a recipe instrument, an unedited library sample a library one, an edited or embedded sample a PCM one (`--embed` forces PCM), with the slot's volume and fine tune. `--phrase` is a comma- or space-separated list, or a JSON list. An existing `--id` needs `--replace` (`INSTRUMENT_EXISTS`) |
| `instruments delete ID [--dir D]` | Deletes the file; `{"deleted": "INS-0001"}` |
| `instruments apply PROJECT --output OUT.json (--instrument ID \| --inline JSON) --pattern P --channel C --row R --note N [--slot S] [--replace] [--length L] [--overwrite] [--library PATH] [--dir D] [--label L]` | Runs `apply_instrument` and writes a **new** project. Returns `applied` (the result above), `changes`, `changed`, `duration_seconds` |

### Python API for the window

Everything is Qt-free and takes plain data. The window should route edits through the document so each one stays a single undoable transaction:

```python
document.patch([{"op": "sample_gain", "slot": 3, "db": -3}], "Gain")        # tracker4agents.document.Document
document.patch([{"op": "sample_set_pcm", "slot": 5, "replace": True,
                 **sample_tools.pcm_fields(pcm, loop_start, loop_length)}], "Draw")
document.patch([{"op": "apply_instrument", "pattern": 0, "channel": 1, "row": 8, "note": "C-2",
                 "instrument": "INS-0001", "instruments": "exports/instruments"}], "Instrument")
```

| Function (module `tracker4agents.sample_tools` unless noted) | Use |
| --- | --- |
| `preview_recipe(recipe, note="C-2", seconds=1.0, volume=64, finetune=0, name="Preview", role=None) -> (wav_bytes, measurements)` | Audition a recipe in memory (mono 16-bit 44.1 kHz WAV, loop and fine tune honoured; no FFmpeg, no file) with the sample facts, loudness and WAV peak/RMS. Raises `ValidationError` (`RECIPE_INVALID` or `INVALID_VALUE`) |
| `render_wav(sample, note="C-2", seconds=1.0) -> (wav_bytes, int16_values)` | The same for any `Sample` (an edited slot); identical bytes to `audio.audition_sample` |
| `recipe_schema() -> dict` | Types, parameters (`kind`, `min`, `max`, `default`, `choices`, `applies_to`, `required`), a valid `default_recipe` per type, `roles`, `notes`, `limits` |
| `draw_to_pcm(points, cycles=16, frequency=261.625565, peak=0.88) -> tuple[int, ...]` | PCM of a looped drawn wave (the `draw` recipe's maths); the loop is the whole sample |
| `pcm_fields(pcm, loop_start=0, loop_length=None) -> dict` | The `pcm_base64`, `pcm_sha256`, `loop_start` and `loop_length` fields of a `sample_set_pcm` operation (default: the whole sample loops) |
| `waveform_summary(pcm, buckets=128) -> list[tuple[int, int]]` | (min, max) per bucket; fewer buckets than requested when the sample is shorter |
| `with_loop`, `trim`, `gain`, `fade`, `match_level`, `headroom_db` | The pure edits behind the operations: take a `Sample`, return `(new Sample, report)`; useful for a live preview before committing the operation |
| `tracker4agents.instruments`: `InstrumentLibrary(folder)` (`list`, `get`, `save`, `delete`), `normalize`, `from_slot(module, slot, name, phrase=(), role=None, tags=None, volume=None, finetune=None, embed=False)`, `parse_phrase`, `build_sample` | The instrument folder and capturing an instrument from a song |

MCP tools: `sample_schema`, `sample_edit`, `sample_draw`, `sample_waveform`, `instruments_list`, `instruments_show`, `instruments_save`, `instruments_delete`, `instruments_apply`, with the arguments of the commands (`trim`, `loop` and `fade` are two-integer arrays, `phrase` a list of strings). The patch operations are also reachable through the `patch` and `live_patch` tools.

## Multi-channel MOD and XM

ChipLoom reads and writes MOD files with 2 to 32 channels and a first FastTracker 2 XM profile. Four-channel `M.K.` projects, MODs and playback plans are unchanged.

### Channels

`Module.channels` is 4 by default. A MOD names its channel count by signature: `M.K.`/`M!K!`/`FLT4`/`4CHN` (four), `2CHN` to `9CHN`, `10CH` to `32CH`. `FLT8` (Startrekker pairs of patterns) is refused with `MOD_FLT8`; `CD61`/`CD81`/`OCTA`/`TDZx` (Octalyser and TakeTracker rules) with `MOD_VARIANT`. libopenmpt and libxmp place MOD channels left-right-right-left, repeating, for 6 and 8 channels as for 4; a plan agrees with libxmp's trace on 2, 6, 8, 10 and 16 channels.

`new --channels N` writes a blank project with N channels. In a project, `channels` is a top-level field (absent means 4) and the profile is `protracker-4ch-pal-v1` for four channels or `protracker-nch-pal-v1` otherwise. A grid row holds one cell per channel separated by `|`; `events` use `"channel": 0..N-1`. Patch operations (`set`, `write` with `lines` or `cells`, `copy`, `move`, `clear`, `transpose`, `timing`) and the live `select` request check rows and channels against the pattern and the module. `audible` in a live context has one boolean per channel.

### XM profile (`fasttracker2-xm-v1`)

A project is an XM when it has `"format": "xm"` and `"profile": "fasttracker2-xm-v1"`; a file is an XM when it starts with `Extended Module: `. Supported: 2 to 32 channels, patterns of 1 to 256 rows (`"length"` in the pattern object, default 64), up to 256 patterns and orders, up to 128 instruments with **exactly one sample each** (an imported multi-sample instrument is reduced to one sample, with a note), 8-bit and 16-bit samples (project fields `bits`, `loop_mode` `forward|pingpong`, `panning` 0-255, `relative_note` -96..95, `finetune` -128..127, loop points counted in sample frames), the volume column, linear and Amiga frequency tables. `module.samples[i]` is instrument i+1; header values and the parts the tools do not edit live in `metadata.xm`: `tracker_name`, `frequency_table` (`linear|amiga`), `restart_position`, `default_speed`, `default_bpm`, `inactive_orders`, and `instruments.<n>` with `volume_envelope`/`panning_envelope` (`points`, `sustain`, `loop_start`, `loop_end`, `type`), `vibrato`, `fadeout`. They are stored and written back; the tools do not edit envelopes. The `xm_header` patch operation edits `restart_position`, `default_speed`, `default_bpm` and `frequency_table`; `pattern_length` resizes a pattern and `add_pattern` takes a `length`.

New files are written with the tracker name `FastTracker v2.00`, which makes libxmp and libopenmpt keep FastTracker II's flow behaviour.

**Notation.** The same label means a different note in the two formats, so grid text is always read with the module's format. A MOD cell is `NOTE SS EEE` with notes `C-1`..`B-3`. An XM cell is `NOTE II VV EEE`: notes `C-0`..`B-7` (`C-4` is middle C; `===` is key off), the instrument in hexadecimal, `VV` the raw volume-column byte in hexadecimal (`--` empty), and the effect as a letter or digit plus two hexadecimal digits (`0`-`9`, then `A`-`Z`, so `G40` is global volume 40 and `X12` extra-fine porta down). Volume column: `10`-`50` set volume, `6x`/`7x` slide down/up, `8x`/`9x` fine slide, `Ax` vibrato speed, `Bx` vibrato, `Cx` panning, `Dx`/`Ex` pan slide left/right, `Fx` tone portamento; `01`-`0F` and `51`-`5F` are refused (`XM_VOLUME_COLUMN`). A ProTracker `C-2` (period 428) is an XM `C-4`.

**Effects.** Accepted: `0`-`9`, `A`-`H`, `K`, `L`, `P`, `R`, `T`, `X`, and `E1x E2x E3x E4x E5x E6x E7x E9x EAx EBx ECx EDx EEx`. Refused with `EFFECT_UNSUPPORTED`: the other letters and `E0x`, `E8x`, `EFx` (undefined in FastTracker II). `F00` is refused (`TIMING`), `Fxx` below `20` is the speed and `20` and above the tempo, `Dxx` is a decimal row (`00`-`99`), `Cxx` and `Gxx` stop at `40`. The playback plan follows speed, tempo, `Bxx`, `Dxx`, `E6x` and `EEx` exactly like libxmp (checked against its trace on generated files); the other effects are accepted and left to the replay engines, which are not compared sample for sample.

**Playback plan.** The timeline starts at the header's `default_speed` and `default_bpm`, uses each pattern's own row count, and at the end of the order list returns to `restart_position` when the song already passed through that order (libxmp's rule), else to order 0. For files claiming FastTracker II or OpenMPT an `E60` also sets the row on which the next order change starts (FastTracker II's loop bug, reproduced by libxmp); other tracker names do not. A break on a delayed row skips a row in a MOD but not in an XM. A `Dxx` row past the end of the next pattern starts that pattern at row 0 (valid, with a plan warning; see [Patch](#patch)). libopenmpt's own song length uses a different loop detection and can differ on looping songs.

**Import.** Unsupported input is refused with a code: `XM_VERSION` (only 0x0104), `XM_SAMPLE_TYPE` (stereo, ADPCM), `XM_INSTRUMENT_HEADER` (an instrument header shorter than 29 bytes or running past the file), `XM_FORMAT` (anything malformed), `SAMPLE_LENGTH`; an Impulse Tracker or Scream Tracker 3 file, whatever its extension, is `IT_UNSUPPORTED` / `S3M_UNSUPPORTED`. Everything else is kept or reported in `import_notes` (`preserved` or `converted`, like a MOD): trailing data after the last sample (`TRAILING_DATA_DROPPED`), a loop running past the sample end (`SAMPLE_LOOP_CLAMPED`), loop values on an unlooped sample (`SAMPLE_IGNORED_LOOP_KEPT`), non-ASCII names (`TEXT_KEPT_RAW`), a file with no instrument (`INSTRUMENT_ADDED`) and packing that differs from ChipLoom's (`REPACKED`). Real-world FastTracker II files add these notes:

- `XM_HEADER_SIZE_KEPT` (preserved): an instrument header of an unusual size (FastTracker II writes 33 bytes for an empty instrument) or an empty instrument whose sample header size field is not 40. The header size field says where the sample headers start, so any size is honoured; the size is kept in `instruments.<n>.header_size` (and `sample_header_size`) and written back as read. A sample header size field other than 40 on an instrument *with* samples is read with that stride (below 40, the 40 known bytes are read anyway, as OpenMPT does) and written back as 40-byte headers: `XM_SAMPLE_HEADER_RESIZED` (converted).
- `XM_FADEOUT_CLAMPED` (preserved): a fadeout above 4095 (MilkyTracker and OpenMPT write up to 32767). `fadeout` holds the clamped value and `fadeout_raw` the file's, which is written back until `fadeout` is edited; an agent can only write 0 to 4095.
- `XM_ENVELOPE_POINTS_KEPT` (preserved): envelope ticks that do not increase strictly. The points are kept as read with `"ticks_as_read": true` on that envelope and written back; players reorder or clamp them. Without that flag (which only the importer sets) `validate` keeps refusing such points.
- `XM_MULTISAMPLE_REDUCED` (converted): an instrument holding several samples. The profile keeps one sample per instrument: the one its key map assigns to the most notes (ties: the first), `instruments.<n>.samples_dropped` counts the others and the note's `details` give `samples`, `kept` and `keymap_notes`. Such a file cannot re-export byte for byte; `xm.read_samples(payload)` returns every sample of every instrument (PCM, loop, volume, finetune, panning, relative note, `keymap_notes`, envelopes, vibrato, fadeout) for bank extraction. A key map naming samples the instrument does not hold is dropped with `XM_KEYMAP_DROPPED` (converted).
- `XM_LOOP_TYPE_KEPT` (preserved): a sample with both loop bits set (type 3, undefined). It plays as a ping-pong loop, as in libxmp and OpenMPT, and `instruments.<n>.sample_loop_type` 3 writes the type back as read while the loop stays ping-pong.
- `EFFECT_IGNORED` (converted): an effect the profile refuses in a cell (`E0x`, `E8x`, `EFx`, `F00`, undefined letters). FastTracker II ignores them; the cell's effect is cleared and the note lists the effect and every cell (`pattern`, `row`, `channel`). Writing such an effect through `patch` stays refused (`EFFECT_UNSUPPORTED`).

Files written by ChipLoom re-export byte for byte; an imported file re-exports byte for byte unless it carries a `converted` note.

### Commands

```text
chiploom new --format xm --channels 8 --rows 128 --speed 4 --bpm 140 --output song.json
chiploom synth palette --format xm --channels 6 --output palette.json
chiploom export project.json --output song.xm          # by extension, or --format mod|xm
chiploom import song.xm --output song.json              # .mod and .xm; prints import_notes
chiploom convert song.mod --output song.xm              # MOD to XM
chiploom convert song.xm --output song.mod              # XM to MOD, only when it fits
chiploom validate|inspect|render|report|preview|compare song.xm
```

`export` converts a project of the other format first (the result has a `conversion` report). `convert` takes a MOD, XM or project and writes `.mod`, `.xm` or a `.json` project (`--to` overrides the extension). A `.json` output without `--to` gets the other format than the source's, since `convert` changes the format (a same-format project comes from `import`, or `--to` naming the source's own format, which copies). A project output keeps every sample recipe.

**Samples in an XM.** `samples add`, `library_sample`, `recipe_sample` and `synth add` work on an XM (instruments 1–128): the sample is converted exactly like MOD to XM converts a MOD sample (below), with its recipe and its `metadata.sample_sources` entry (`library_id`) kept, so a synthesized XM still passes `validate --sample-source synthesized`. The PCM-editing operations (`sample_loop`, `sample_trim`, `sample_gain`, `sample_fade`, `sample_set_pcm`, `sample_match_level`) and `apply_instrument` stay MOD-only (`XM_OP_UNSUPPORTED`).

**MOD to XM** keeps the order list, patterns, instruments, effects and PCM: MOD notes `C-1`..`B-3` become XM `C-3`..`B-5`; the Amiga frequency table keeps slides and vibrato meaningful; every sample gets finetune `-20/128` semitone (plus `16` per MOD finetune step) so XM `C-4` sounds like the PAL period 428 (measured within 0.1 Hz in libopenmpt and libxmp); channels are centred because a MOD file stores no panning; sample recipes and `metadata.sample_sources` are kept (`RECIPES_KEPT`); the header's `default_speed`/`default_bpm` take the `Fxx` of the first played row, which stay in the pattern (`HEADER_TIMING`). The report lists what changed: `FILTER_EFFECT_DROPPED` (E0x), `E5X_REMAPPED`, `TIMING_DIFFERS` (a MOD-only flow quirk), and `lossless` is false then. **XM to MOD** is refused with `CONVERT_REFUSED` and a `reasons` list (`code`, `message`, where) unless the XM has at most 31 instruments, 8-bit forward-looped samples with even lengths and loops, centred panning, a finetune that is an exact MOD step (`-20 + 16n`), 64-row patterns, notes `C-3`..`B-5`, no volume column, key off or envelopes, only MOD effects, the Amiga table, speed 6 / 125 BPM (or header values that the first played row restates with `Fxx`) and restart 0. Recipes are kept both ways, and MOD to XM to MOD gives the same MOD bytes.

MCP: `convert` and `export_format` (appended to the tool list).
