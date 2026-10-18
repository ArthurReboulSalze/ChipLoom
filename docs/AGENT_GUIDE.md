# Composing with Codex or Hermes Agent

ChipLoom provides musical operations and file formats. Your agent provides the creative decisions and the reasoning loop. No model API key or embedded model is required by ChipLoom itself; configure the agent separately.

## Workspace and execution

Clone the repository and use a local Python 3.12+ environment. Install `-e .` for the CLI aliases, or run `python -m tracker4agents` directly from the checkout. The optional `desktop` dependency is only for the human window. FFmpeg/libopenmpt is needed for rendering; editing and MOD export work without it.

In Codex, open the cloned project and begin a task there. The repository's `AGENTS.md` gives project guidance. Codex's own configuration controls tool access and approval behavior. [Official project-instruction documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

In Hermes Agent, use a session whose terminal/file tools can access this checkout, and ask it to read `AGENTS.md` and this guide. With a remote or container terminal, clone the project there as well; a Windows path is not automatically accessible to that environment. The CLI workflow does not require changing Hermes core or installing an MCP integration. The repository now provides a reusable [ChipLoom skill](../skills/chiploom/SKILL.md), including a [source-selection and bank-building workflow](../skills/chiploom/references/sample-bank.md). Ask the agent to read it, or copy the complete skill folder into your agent's skill directory. Cloning the repository does not install it automatically.

The command workflow is exercised by this project's tests and by Codex during development. A user-reported Hermes run with glm-5.3-flash completed two original MOD compositions on Debian 13, Python 3.13.5 and FFmpeg 7.1.5. This confirms that reported headless workflow, not every model/provider or the Linux GUI. See [the feedback and follow-up](HERMES_FEEDBACK.md).

## A complete composition loop

1. Establish duration, approximate tempo, mood and target MOD profile. The current owner-approved workflow uses the local sample library exclusively; new sample synthesis and waveform drawing are deferred until the owner resumes them.
2. Inspect an included project and, when useful, read the reference study. Use a reference's construction ideas without assuming its samples or melody should be copied.
3. Create a **new** project JSON with embedded library PCM, patterns and order list. Record the library IDs and select a coherent palette before writing the arrangement. Avoid replacing the included examples.
4. Validate. Fix any rejected note range, sample loop or unsupported effect before exporting.
5. Export the actual MOD, then render that exported file. Generate an HTML listening bundle if useful.
6. Check duration, signal levels, transitions and loop behavior. Explain which checks were performed; listening quality is still a musical judgment.
7. Revise short sections from the user's feedback. Keep variations concise when requested.
8. Deliver paths to the MOD, editable project and requested listening artifacts.

```sh
python -m tracker4agents inspect examples/pixel_rush.project.json --pattern 0
python -m tracker4agents validate exports/my-song/project.json
python -m tracker4agents export exports/my-song/project.json --output exports/my-song/my-song.mod
python -m tracker4agents render exports/my-song/my-song.mod --output exports/my-song/my-song.wav --mp3-output exports/my-song/my-song.mp3
python -m tracker4agents preview exports/my-song/project.json --output exports/my-song-review --language en
```

Use the interpreter installed on the same host as the files. Successful CLI responses are JSON on stdout. Data/render errors return JSON on stderr and exit code 2. `--help`, `--version` and argparse usage errors use normal CLI text.

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

The read-only report collects independent JSON errors with paths such as `patterns[4].events[12]`, including collisions and both writers. It reports one primary problem per field/sample/event plus collisions; repair these and run it again for any dependent problems. Invalid containers cannot be inspected further. Malformed JSON and binary MOD parsing still stop at the first decoding error. Reports never produce a repaired score.

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

For arrangement changes, edit a copied JSON score or build `Module`/`Pattern` objects, then validate the result. The CLI does not yet expose every edit as its own subcommand. Undo history is in memory, not stored in the project JSON.

## Project data and samples

The schema is `tracker4agents.project.v1`; `examples/*.project.json` are complete executable examples. A pattern contains sparse events:

```json
{"row": 8, "channel": 3, "note": "E-3", "sample": 8, "effect": "C27"}
```

`C27` sets volume to hexadecimal 27 (decimal 39). Sample 0 keeps the current sample. A sample/effect without a new note is meaningful and must not be discarded. Sharps have no extra hyphen: `C-3`, `G#3`, `A#2` are valid; `G#-3` is not. Tracker note names `C-1` through `B-3` are the profile's period-table labels, not scientific octave numbers.

Samples can use signed 8-bit PCM or a deterministic recipe. The current composition workflow uses library PCM only. Recipe support remains available for existing projects and future work: drawing defines amplitude points, and synthesis recipes include `draw`, `kick`, `snare`, `hat`, `kick_hat`, `snare_hat` and `pluck`. Their parameters are validated data, never executable source code. Seeds preserve reproducible noise.

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
size alone is not a musical suitability test. Keep new synthesis deferred. Do not copy reference patterns merely to
demonstrate sample reuse. The native window now has a bottom **Song samples / Sample
library** area with search, type/role filters, note-based audition and undoable insertion.
The agent still uses CLI/Python; the human can choose a bank folder, reload it and add
the same entries without narrowing the tracker. Occupied slots require an explicit
replacement choice. The selected bank folder is stored in local desktop preferences.

## Studying references

```sh
python -m tracker4agents analyze path/to/reference.mod --output exports/reference-study.json
python -m tracker4agents analyze path/to/selection.zip --output exports/selection-study.json --probe
```

The analyzer accepts a bounded subset of 31-sample MOD layouts, including the two-channel files in the supplied selection. It does not support arbitrary tracker formats or compressed MOD encodings. ZIP contents are read as bytes; archive paths are not extracted. Original files are unchanged.

Reports contain hashes and aggregate structure, not PCM or complete melodies. Effect and note counts describe stored patterns, which may be unused or repeated in playback. Similarity compares exact cells in the union of occupied cells; it is not a perceptual similarity score. Duration estimates from libopenmpt do not prove lossless import into the editor.

For the latest selection, read `references/SELECTION_FR.md`. Useful composition ideas include short phrases, repeated accompaniment with a changed lead, small looped waveforms, and sample changes without a new note. None of this changes an agent model's weights.

## Human handoff

The human can open the same project with `gui`, inspect and edit it, and save back to JSON. F5 reloads agent changes with protection for unsaved GUI edits. Avoid concurrent overwrites of a file the human is editing.

The HTML page is a portable inspection/listening artifact, not a second editor. Its soundtrack comes from the actual exported MOD. The optional server is loopback-only and must be started explicitly.

## MCP status

There is no `mcp` command, MCP server process, discovery endpoint or installed Codex/Hermes connector in this version. JSON output alone is not MCP. See `docs/ARCHITECTURE.md` for the proposed adapter boundary and current functionality.
