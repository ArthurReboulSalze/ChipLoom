# Composing with Codex or Hermes Agent

ChipLoom provides musical operations and file formats. Your agent provides the creative decisions and the reasoning loop. No model API key or embedded model is required by ChipLoom itself; configure the agent separately.

## Workspace and execution

Clone the repository and use a local Python 3.12+ environment. Install `-e .` for the CLI aliases, or run `python -m tracker4agents` directly from the checkout. The optional `desktop` dependency is only for the human window. FFmpeg/libopenmpt is needed for rendering; editing and MOD export work without it.

In Codex, open the cloned project and begin a task there. The repository's `AGENTS.md` gives project guidance. Codex's own configuration controls tool access and approval behavior. [Official project-instruction documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

In Hermes Agent, use a session whose terminal/file tools can access this checkout, and ask it to read `AGENTS.md` and this guide. With a remote or container terminal, clone the project there as well; a Windows path is not automatically accessible to that environment. The CLI workflow does not require changing Hermes core or installing an MCP integration; an optional [MCP adapter](#mcp-adapter) exists for clients that prefer it. The repository now provides a reusable [ChipLoom skill](../skills/chiploom/SKILL.md), including a [source-selection and bank-building workflow](../skills/chiploom/references/sample-bank.md). Ask the agent to read it, or copy the complete skill folder into your agent's skill directory. Cloning the repository does not install it automatically.

The command workflow is exercised by this project's tests and by Codex during development. A user-reported Hermes run with glm-5.3-flash completed two original MOD compositions on Debian 13, Python 3.13.5 and FFmpeg 7.1.5. This confirms that reported headless workflow, not every model/provider or the Linux GUI. See [the feedback and follow-up](HERMES_FEEDBACK.md).

## A complete composition loop

1. Establish duration, approximate tempo, mood and target MOD profile. The current owner-approved workflow uses the local sample library exclusively; new sample synthesis and waveform drawing are deferred until the owner resumes them.
2. Inspect an included project and, when useful, read the reference study. Use a reference's construction ideas without assuming its samples or melody should be copied.
3. Create a **new** schema v2 project JSON with embedded library PCM, patterns and order list. Record the library IDs and select a coherent palette before writing the arrangement. Avoid replacing the included examples. Write patterns as grid `rows` (see [Project data and samples](#project-data-and-samples)), or build the first version with `patch` operations on a copy.
4. Read what you wrote back with `inspect --pattern N --grid` and validate. Fix any rejected note range, sample loop or unsupported effect before exporting. `validate --report` lists every independent problem with a stable `code` and a `path`.
5. Revise with `patch`: batches of operations that apply as one validated transaction ([below](#editing-with-patch-operations)). Write each revision to a new file so earlier versions stay available.
6. Export the actual MOD, then render that exported file. Generate an HTML listening bundle if useful.
7. Measure with `report` and, when two versions exist, build a blind A/B page with `compare` ([Measuring and comparing versions](#measuring-and-comparing-versions)). Check duration, signal levels, transitions and loop behavior. Explain which checks were performed; listening quality is still a musical judgment.
8. Revise short sections from the user's feedback and record it with `feedback`. Keep variations concise when requested.
9. Deliver paths to the MOD, editable project and requested listening artifacts.

```sh
python -m tracker4agents inspect examples/pixel_rush.project.json --pattern 0 --grid --rows 8
python -m tracker4agents validate exports/my-song/project.json
python -m tracker4agents export exports/my-song/project.json --output exports/my-song/my-song.mod
python -m tracker4agents render exports/my-song/my-song.mod --output exports/my-song/my-song.wav --mp3-output exports/my-song/my-song.mp3
python -m tracker4agents preview exports/my-song/project.json --output exports/my-song-review --language en
```

Use the interpreter installed on the same host as the files. Successful CLI responses are JSON on stdout. Data/render errors return JSON on stderr and exit code 2, with a stable `code`, an English `message` and, for translated core diagnostics, the original French text as `message_fr`. Branch on `code` (for example `NOTE_RANGE`, `PATCH_OP`, `LIVE_CONFLICT`), not on wording; the full list is in [the CLI reference](CLI.md#error-contract-and-codes). `--help`, `--version` and argparse usage errors use normal CLI text.

The preview command exports its own complete bundle from the same project. To avoid stale or accidentally overwritten media, choose a fresh bundle directory for each revision. Share the entire bundle. HTML generation is optional; the agent never needs to open a browser or desktop window to compose.

## Plan the duration before composing

At constant timing, **seconds per row = speed × 2.5 / BPM**. An order is an entry in the playback list: it selects a pattern, which can be repeated in other orders. A full pattern has 64 rows. At speed 6 and **125 BPM**, this gives 7.68 seconds per full order; it is not a fixed duration at every tempo.

| BPM | Speed | Seconds / 64-row order | Eight full orders |
| --- | --- | --- | --- |
| 125 | 6 | 7.68 | 61.44 s |
| 128 | 6 | 7.50 | 60.00 s |
| 160 | 6 | 6.00 | 48.00 s |
| 164 | 6 | 5.8537 | 46.8293 s |

```sh
python -m tracker4agents estimate --orders 8 --speed 6 --bpm 128
```

For shorter phrases, `--rows 32` estimates 32 played rows per order; the actual score still needs an early `D00` break. Timing changes, Bxx jumps and Dxx breaks invalidate the constant-timing estimate. Validate the finished score for its playback plan.

`validate` and `inspect` include a `warnings` array when the first cycle exceeds the 120-second render limit. The MOD remains valid. Render a bounded excerpt with `--seconds`, or shorten the arrangement; full-cycle HTML previews remain limited to 120 seconds.

## Diagnose and audition a section

```sh
python -m tracker4agents validate exports/my-song/project.json --report
python -m tracker4agents render exports/my-song/my-song.mod --from-order 6 --seconds 10 --output exports/my-song/drop.wav
```

The read-only report collects independent JSON errors, each with a `path` such as `patterns[4].rows['0C']` or `patterns[4].events[12]`, a `code` and a `message`, including collisions and both writers. It reports one primary problem per field/sample/row/event plus collisions; repair these and run it again for any dependent problems. Invalid containers cannot be inspected further. Malformed JSON and binary MOD parsing still stop at the first decoding error. Reports never produce a repaired score.

`--from-order` is a **zero-based order index**, not a pattern number. It selects the first visit to that order in the first playback cycle, including a nonzero entry row after Dxx. The renderer decodes from the beginning and discards the prefix, preserving sample/effect state. The cut uses the playback plan's nominal timestamp; native engine timing can differ by milliseconds. Preroll is bounded to 600 seconds and the output to 120 seconds. Without `--seconds`, the excerpt runs to the end of the first cycle. Unreachable orders are rejected.

## Editing through Python

`Document` offers validated transactions and undo/redo without Qt. Indices for patterns, rows and channels are zero-based; sample slots are 1–31.

```python
from pathlib import Path
from tracker4agents.document import Document
from tracker4agents.model import cell

doc = Document.open(Path("examples/pixel_rush.project.json"))
doc.replace_cell(0, 0, 3, cell("G-2", 10, "C28"))
doc.transpose(0, 1, 1)
doc.save_project(Path("exports/my-variation/project.json"))
doc.export_mod(Path("exports/my-variation/my-variation.mod"))
```

This example makes a variation of an included song. It is not a new composition algorithm. Each accepted document edit is validated before it replaces the current document and can be undone in that process.

`Document.patch(ops, label)` runs the same batch operations as the CLI (next section) as one undoable step. For other arrangement changes, build `Module`/`Pattern` objects, then validate the result. Undo history is in memory, not stored in the project JSON.

## Editing with patch operations

`patch` is the normal way for an agent to revise a score. It applies a list of operations to a copy of a project, validates the whole result, and writes a new project, or writes nothing: an error names the failing operation (`ops[1] (set): …`) and no output file is created.

```sh
python -m tracker4agents patch exports/my-song/v1.project.json --output exports/my-song/v2.project.json \
  --label "Octave up on the lead" --ops exports/my-song/lead-up.ops.json
```

with `lead-up.ops.json`:

```json
[
  {"op": "transpose", "pattern": 1, "row": 0, "rows": 32, "channel": 0, "semitones": 12},
  {"op": "write", "pattern": 1, "row": 32, "lines": [
    "C-2 04 C38 | E-1 06 C2B | --- -- ... | E-2 0B C27",
    "--- -- ... | --- -- ... | --- -- ... | --- -- ..."
  ]},
  {"op": "add_pattern", "copy_of": 1, "name": "A - Hook B"}
]
```

The result lists `changes` (one line per changed cell, such as `P01 r00 ch1: C-2 04 C38 → C-3 04 C38`), the new `duration_seconds` and any `warnings`. Read `changes` to confirm that the edit touched what you meant. The operations are `set`, `write`, `clear`, `copy`, `move`, `transpose`, `add_pattern`, `remove_pattern`, `rename_pattern`, `set_orders`, `insert_order`, `remove_order`, `move_order`, `title`, `timing`, `sample` and `library_sample`; every field is in the [operations table](CLI.md#operations).

Habits that work well:

- Look before you write: `inspect --pattern N --grid --row R --rows K` shows the cells you are about to change in the same text you will write.
- Use `write` with `lines` for a whole bar and `cells` with `step` for a line of notes on one channel; use `copy` and `move` for repeating or shifting phrases; use `transpose` for key changes.
- Keep one patch to one musical intent and label it. Several small patches give a clearer history than one large rewrite.
- An empty string in `cells` clears that cell; `"--- -- ..."` is an explicit empty cell.
- `library_sample` inserts library audio by ID with the same exact-PCM rules as `samples add`. New sample synthesis stays deferred.

## Project data and samples

New projects use the schema `tracker4agents.project.v2`. Version 1 files still load, and `chiploom migrate SRC --output NEW.json` rewrites them without changing the encoded MOD (`pixel_rush` goes from 192 KB to 34 KB). `examples/*.project.json` are complete executable examples and may still be v1. In v2 a pattern is a grid of `rows`: each key is a two-digit hexadecimal row `00` to `3F` and each value holds four cells separated by `|`, written `NOTE SS EEE`, where `---`, `--` and `...` mean empty note, sample and effect. Rows that are completely empty are left out.

```json
{"name": "Hook", "rows": {
  "00": "C-2 04 C38 | E-1 06 C2B | E-2 08 037 | E-3 0B C27",
  "01": "--- -- ... | --- -- A03 | --- -- 037 | --- 0C A03"
}}
```

Samples store `pcm_base64` with a verified `pcm_sha256` (plus loop fields), or a `recipe`. v2 also reads the older sparse layout, a list of events such as `{"row": 8, "channel": 3, "note": "E-3", "sample": 8, "effect": "C27"}`, which is what v1 files contain. A pattern uses either `rows` or `events`.

`C27` sets volume to hexadecimal 27 (decimal 39). Sample 0 keeps the current sample. A sample/effect without a new note is meaningful and must not be discarded. Sharps have no extra hyphen: `C-3`, `G#3`, `A#2` are valid; `G#-3` is not. Tracker note names `C-1` through `B-3` are the profile's period-table labels, not scientific octave numbers.

Samples can use signed 8-bit PCM or a deterministic recipe. **The default composition workflow uses library PCM only.** Recipes are for existing projects and for the owner-requested mode [Songs made only with created samples](#songs-made-only-with-created-samples): `wave` (pulse, triangle, saw, sine, noise), `draw`, `kick`, `snare`, `hat`, `kick_hat`, `snare_hat` and `pluck`; `chiploom synth types` lists their parameters. Their parameters are validated data, never executable source code. Seeds preserve reproducible noise.

A JSON project preserves recipe provenance. Importing a MOD preserves its PCM but cannot reconstruct the recipe that produced it. Do not label imported sounds as agent-created.

## Using a local sample bank

Reuse of the owner's local bank is authorized for the current composition workflow.
Use `samples` to extract a reference selection into
a local bank, search its neutral labels, audition candidates, and insert a chosen entry
into a new project. See [CLI sample commands](CLI.md#local-sample-library). The bank's
original reference labels stay in private provenance; use IDs and neutral names in
compositions and public documentation. Signal-based role suggestions need listening.

A fresh clone ships no reference bank. To reproduce the workflow with a user's own
collection, use the [bank-building skill reference](../skills/chiploom/references/sample-bank.md):
select authorized MODs or a ZIP, save the local source list, import each into the same
bank, audit, audition and refine neutral labels, then write a short original test MOD.
Imports are atomic per input, not across a list. Report partial failures and discover
IDs in the new bank rather than relying on the developer's fixed demo palette.

```sh
python -m tracker4agents samples list --tag bass-candidate --compatible --limit 8
python -m tracker4agents samples inspect SMP-0001
python -m tracker4agents samples preview SMP-0001 --note A-1 --output exports/song/audition.wav
python -m tracker4agents samples add SMP-0001 --project exports/song/project.json --output exports/song/with-bass.project.json
```

Inspect the sample's loop and fine tune before assigning musical notes. A sample slot
or tracker note is not a standardized instrument pitch. Start with compatible entries;
use `--adapt` only when the documented one-shot adaptation is desired. The inserted
project embeds the audio and keeps neutral provenance in `metadata.sample_sources`.

Python access uses the same standard-library implementation:

```python
from pathlib import Path
from tracker4agents import project
from tracker4agents.sample_library import SampleLibrary

bank = SampleLibrary(Path("exports/sample_library"))
candidates = bank.search(tags=["bass-candidate"], compatible_only=True, limit=8)
sample, adaptations = bank.sample(candidates["samples"][0]["id"])
module, insertion = bank.insert(project.load(Path("exports/song/project.json")),
                                candidates["samples"][0]["id"])
project.write_json(Path("exports/song/with-bass.project.json"), project.to_dict(module))
```

Insertion returns a validated copy and its slot number. Respect occupied slots and
the 31-slot limit. Use a library-only palette, then validate, export and render the
actual MOD. Prefer compatible tuning and a consistent percussion character; raw waveform
size alone is not a musical suitability test. Do not create new samples in library mode; the created-samples mode below is only for when the owner asks for it. Do not copy reference patterns merely to
demonstrate sample reuse. The native window now has a bottom **Song samples / Sample
library** area with search, type/role filters, note-based audition and undoable insertion.
The agent still uses CLI/Python; the human can choose a bank folder, reload it and add
the same entries without narrowing the tracker. Occupied slots require an explicit
replacement choice. The selected bank folder is stored in local desktop preferences.

## Songs made only with created samples

Use this mode **only when the owner asks for a song made with created samples**. Library mode stays the default: without that request, take samples from the owner's bank. Do not mix the two in one song unless the owner asks for it. Early synthesized samples sounded uneven, so the mode is built around a tested palette, auditions with measurements, and loudness matched to the owner's library.

The loop is palette, audition, tune, compose:

```sh
# 1. A starter palette: 13 samples, sample_source "synthesized", one empty pattern, volumes matched to the bank
python -m tracker4agents synth palette --output exports/my-song/v1.project.json --title "My Song"
# 2. Audition anything you add or change (no FFmpeg needed); read tuning_cents and loudness in the result
python -m tracker4agents synth preview --recipe '{"type": "wave", "shape": "pulse", "duty": 0.125, "frequency": 261.63}' \
  --note C-2 --output exports/my-song/audition.wav
# 3. Add timbres in free slots (14-31); the volume is matched to the role's level
python -m tracker4agents synth add exports/my-song/v1.project.json --name "Saw bass" --role bass \
  --recipe '{"type": "wave", "shape": "saw", "frequency": 130.81}' --output exports/my-song/v2.project.json
# 4. Compose with patch ops (slot numbers are in the palette output), then check and export
python -m tracker4agents patch exports/my-song/v2.project.json --ops ops.json --output exports/my-song/v3.project.json
python -m tracker4agents validate exports/my-song/v3.project.json --sample-source synthesized
python -m tracker4agents report exports/my-song/v3.project.json
```

Palette slots: 1 Kick, 2 Snare, 3 Hat, 4 Kick+hat, 5 Snare+hat, 6 Triangle bass, 7 Pulse bass, 8 / 9 / 10 pulse leads at 12.5 / 25 / 50 %, 11 Triangle chord, 12 Noise texture, 13 Pluck lead. See [the CLI reference](CLI.md#starter-palette) for roles and uses.

Keeping timbres coherent:

- Build the arrangement from a few families (the palette's pulses and triangles share one oscillator character) and add a new recipe only for a reason you can state, such as a missing register or a pulse width.
- Pitch is part of the recipe: `frequency` is what you hear at note C-2, and the preview reports the error in cents. Palette waves are within a couple of cents; if you give `cycles` yourself, read `tuning_cents`. Use bass samples at 130.81 Hz and lead and chord samples at 261.63 Hz so the usual note ranges (bass in octaves 1 and 2, leads in 2 and 3) keep the same spacing as the palette.
- Move between the three pulse leads mid-note (`sample` only, no note) for pulse-width movement; use `C00` to cut bass and chords, arpeggio effects `037` and `047` for chords, and `drive` 0.3 on drum recipes, which the palette already uses.
- Treat loudness as measured, not heard. `synth add` and `synth palette` land each sample on its role's level in the owner's bank (or on fixed reference levels without a bank): the median of its group, except that kicks aim at the upper quartile of the percussion and hats at the lower quartile, so hats sit below snares and snares below kicks. `report` flags a played sample more than 6 dB from its reference. That compares samples one by one at their default volume; it does not say how the mix sounds. Texture and drums sit near full scale because the bank's do. Listen, and lower volume with `Cxx` where a part masks the others.
- Save `sample_source` in the project (the palette does it). `validate` checks a declared source on its own; add `--sample-source synthesized` as the explicit final check. Library samples are then refused in that project; set `"sample_source": "mixed"` in the JSON only when the owner asks for both.
- Describe what you measured as measurements (tuning, loudness, peak) and what you think of the sound as a judgment.

## Studying references

```sh
python -m tracker4agents analyze path/to/reference.mod --output exports/reference-study.json
python -m tracker4agents analyze path/to/selection.zip --output exports/selection-study.json --probe
```

The analyzer accepts a bounded subset of 31-sample MOD layouts, including the two-channel files in the supplied selection. It does not support arbitrary tracker formats or compressed MOD encodings. ZIP contents are read as bytes; archive paths are not extracted. Original files are unchanged.

Reports contain hashes and aggregate structure, not PCM or complete melodies. Effect and note counts describe stored patterns, which may be unused or repeated in playback. Similarity compares exact cells in the union of occupied cells; it is not a perceptual similarity score. Duration estimates from libopenmpt do not prove lossless import into the editor.

For the latest selection, read `references/SELECTION_FR.md`. Useful composition ideas include short phrases, repeated accompaniment with a changed lead, small looped waveforms, and sample changes without a new note. None of this changes an agent model's weights.

## Human handoff

The human can open the same project with `gui`, inspect and edit it, and save back to JSON. F5 reloads agent changes with protection for unsaved GUI edits. Avoid concurrent overwrites of a file the human is editing: when the owner has the window open, use a live session ([next section](#composing-with-the-owner-in-the-window-live)) instead of rewriting their file.

The HTML page is a portable inspection/listening artifact, not a second editor. Its soundtrack comes from the actual exported MOD. The optional server is loopback-only and must be started explicitly.

## Composing with the owner in the window (live)

When the owner has ChipLoom open, you can edit the song they are looking at. Your edits show up in the window at once, can be undone there with the owner's own undo, and are recorded in a journal that says who changed what. The window shows live edits, and the owner can accept or reject your proposals. A headless session, `chiploom live serve SONG.json`, offers the same interface without a window (`play` and `stop` then fail with `LIVE_NO_WINDOW`, while `open` and `select` report `handled: false`).

The loop:

1. **Find the session**: `live sessions`, then `live status`. Note `revision`, the open `path`, the owner's cursor and selection, and `pending_proposals`. Use `--session` when several are running.
2. **Read**: `live score` for the overview, `live score --pattern N` for the cells. Read `live changes --since 0` to see what the owner has been doing.
3. **Edit with a base**: send a small patch with `--base REV`, where `REV` is the `revision` you last read, and a `--label` that describes the intent. The result returns the new `revision`; keep it.
4. **On `LIVE_CONFLICT`**: someone else edited a cell, name, sample, the order list or the title you were about to change. Nothing was applied. Read the `conflicts` in the error (each shows the `current` cell and `yours`) and `live changes --since REV`. **The owner's edits win**: adapt your patch to what is there now, or drop that part, then resubmit with the new `revision`.
5. **Propose big rewrites**: for anything larger than a few bars ("redo the bass", "new drums for the chorus"), use `live patch --propose`. The owner previews it in the window and accepts or rejects it. You cannot accept it yourself and you cannot act as `human`; the song does not change until they decide. Check `live proposals` afterwards, and `withdraw` one you want to replace.
6. **Announce versions**: when you write a finished alternative as its own file, tell the window with `live take FILE --label "..."`, and the owner can open it from there. Use `live select` to point at a passage and `live play` to start playback when a window is attached. `live save --output FILE` writes a copy and leaves the owner's file open in the window.
7. **Listen to their reply**: record what the owner says with `feedback` and read `live changes` again before the next round.

```sh
python -m tracker4agents live status
python -m tracker4agents live changes --since 0
python -m tracker4agents live patch --base 3 --label "Fill before the chorus" \
  --op '{"op": "write", "pattern": 2, "row": 56, "lines": ["--- -- ... | --- -- ... | --- -- ... | A-2 0B C30"]}'
python -m tracker4agents live patch --propose --label "Redo the bass in pattern 1" --ops exports/song/new-bass.ops.json
```

Etiquette that follows from the mechanics: without `--base` no conflict check runs, so always pass it when the owner might be editing. Two agents sharing the default author `agent` do not conflict with each other; give each its own `--author`. Keep patches small enough that a conflict is cheap. The owner's cursor and selection (in `live status`) show where they are working; avoid that region unless asked. If no window is running, `live sessions` is empty and you fall back to the file workflow above. The command details are in [the CLI reference](CLI.md#live-sessions) and the procedure is condensed in [the skill's live reference](../skills/chiploom/references/live.md).

## Measuring and comparing versions

**Measurements.** `report` describes a score in numbers: per-channel note starts, density, range and gaps; the tempo and the duration along the real playback path; how much is repeated; which samples are used; and an *estimated* key. It reads the score, not the sound, so it can say how many notes a channel plays and over what range, not whether the part is good. Use it to check a plan ("the lead should rest in the intro", "no drums for sixteen rows") and to describe a revision. State the numbers as measurements and your reading of them as judgment.

**Blind comparison.** Once you have two versions, `compare` builds a page where the owner hears them as X and Y in random order, picks a preference, optionally rates melody, groove, sound palette and arrangement, and then sees which was which, with measured peak and RMS. Use `--seconds` for a bounded excerpt (required when a cycle is over 120 seconds), `--labels` for readable version names and `--mp3` for easy playback. Keep in mind:

- It is a casual blind test. The answer key is in `comparison.json` and, encoded, in the page. Do not read it before the owner has listened.
- Loudness is not equalized, and a louder version tends to win. If the versions differ in level, say so when you present the result.
- One listener, one session: the result is one person's preference on one day.

**Feedback.** Record what the owner says with `feedback --text "..." --rating 4 --version v2 --output NEW.json`. It writes a new project with the entry in `metadata.feedback`, keyed to the version label you named; the score is untouched. Start the next revision from that file or its source, and say in your reply what you changed in response.

```sh
python -m tracker4agents report exports/my-song/v2.project.json
python -m tracker4agents compare exports/my-song/v1.project.json exports/my-song/v2.project.json \
  --output exports/my-song-compare --seconds 30 --labels "v1" "v2 brighter lead" --mp3
python -m tracker4agents feedback exports/my-song/v2.project.json --text "Lead is better; drums too loud" \
  --rating 4 --version "v2 brighter lead" --output exports/my-song/v2-feedback.project.json
```

## MCP adapter

`python -m tracker4agents mcp [--root DIR]` runs a Model Context Protocol server on standard input and output. It exposes 34 tools (estimate, validate, inspect, patch, export, render, preview, report, compare, feedback, migrate, four `samples_*` tools, five `synth_*` tools and the `live_*` set) and wraps the CLI: each call runs the matching command in a child process, so a tool result is the CLI's JSON, with `isError` set when the command failed. Arguments and results follow the CLI reference; patch operations are passed as a JSON array in `ops`.

A client that launches stdio servers can use this shape (field names vary by client):

```json
{"mcpServers": {"chiploom": {"command": "<checkout>/.venv/Scripts/python.exe", "args": ["-m", "tracker4agents", "mcp"], "cwd": "<checkout>"}}}
```

The adapter is covered by the project's automated tests and was driven by hand over a stdio pipe. It has not been tested with a specific MCP client, so this guide claims no client compatibility. It is optional: Codex and Hermes Agent can keep using the CLI directly, which gives the same results. See [the architecture note](ARCHITECTURE.md#is-it-mcp) for scope and evidence.
