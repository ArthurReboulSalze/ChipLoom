# Composing with Codex or Hermes Agent

ChipLoom provides musical operations and file formats. Your agent provides the creative decisions and the reasoning loop. No model API key or embedded model is required by ChipLoom itself; configure the agent separately.

## Workspace and execution

Clone the repository and use a local Python 3.12+ environment. Install `-e .` for the CLI aliases, or run `python -m tracker4agents` directly from the checkout. The optional `desktop` dependency is only for the human window. FFmpeg/libopenmpt is needed for rendering; editing and MOD export work without it.

In Codex, open the cloned project and begin a task there. The repository's `AGENTS.md` gives project guidance. Codex's own configuration controls tool access and approval behavior. [Official project-instruction documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

In Hermes Agent, use a session whose terminal/file tools can access this checkout, and ask it to read `AGENTS.md` and this guide. With a remote or container terminal, clone the project there as well; a Windows path is not automatically accessible to that environment. The CLI workflow does not require changing Hermes core or installing an MCP integration. A reusable Hermes skill may be added later; no skill is automatically installed by this repository. [Official Hermes skills documentation](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills).

The command workflow is exercised by this project's tests and by Codex during development. A live Hermes session has not yet been used for end-to-end validation.

## A complete composition loop

1. Establish duration, approximate tempo, mood, target MOD profile and whether the user wants new samples or explicitly authorizes reuse.
2. Inspect an included project and, when useful, read the reference study. Use a reference's construction ideas without assuming its samples or melody should be copied.
3. Create a **new** project JSON with sample recipes, patterns and order list. Avoid replacing the included examples.
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

`C27` sets volume to hexadecimal 27 (decimal 39). Sample 0 keeps the current sample. A sample/effect without a new note is meaningful and must not be discarded. Tracker note names `C-1` through `B-3` are the profile's period-table labels, not scientific octave numbers.

Samples can use signed 8-bit PCM or a deterministic recipe. Drawing means defining amplitude points; synthesis recipes include `draw`, `kick`, `snare`, `hat`, `kick_hat`, `snare_hat` and `pluck`. Read the included recipes before constructing one. Their parameters are validated data, never executable source code. Seeds preserve reproducible noise.

A JSON project preserves recipe provenance. Importing a MOD preserves its PCM but cannot reconstruct the recipe that produced it. Do not label imported sounds as agent-created.

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
