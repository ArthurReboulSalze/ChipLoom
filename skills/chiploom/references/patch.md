# Edit a score with patch operations

Use `patch` to revise a ChipLoom project. A patch is a JSON list of operations applied to
a copy of the project and validated as one transaction: every operation applies or none
does, and nothing is written on failure. Errors name the operation (`ops[1] (set): ...`)
and carry a stable `code`. Run from the ChipLoom checkout; paths below are examples.

## Read, patch, read

```sh
python -m tracker4agents inspect exports/song/v1.project.json --pattern 1 --grid --row 0 --rows 8
python -m tracker4agents patch exports/song/v1.project.json --output exports/song/v2.project.json \
  --label "Lift lead" --op '{"op": "set", "pattern": 1, "row": 4, "channel": 0, "cell": "E-2 04 C28"}'
```

`inspect --grid` prints rows as `04 | C-2 05 C31 | --- -- ... | E-2 08 037 | --- -- ...`:
row in hex, then one cell per channel (four by default), each `NOTE SS EEE` (note or `---`, sample in hex or `--`,
effect in hex or `...`). The same text is what `set`, `write` and the project file use.
The result of `patch` lists `changes` such as `P01 r04 ch1: C-2 05 C31 → E-2 04 C28`
(pattern 1, row `04`, channel 1, counted from 0 like the operations: `ch0` is the first channel), `cells_changed`, `duration_seconds` and `warnings`.
Read them: they tell you what actually moved.

Options: `--ops FILE` (or `-` for stdin) or repeated `--op JSON` (the MCP `patch` and
`live_patch` tools take `ops` inline or `ops_file`, a path to the same JSON list); `--output` must be a
`.json` path; writing over the source needs `--in-place` (avoid it: keep versions).

## Operations

Indices for patterns, orders, rows and channels are zero-based; sample slots are 1-31.
A block is `row` (default 0), `rows`, `channel` (default 0), `channels`.

| `op` | Fields | Notes |
| --- | --- | --- |
| `set` | `pattern`, `row`, `channel`, `cell` or `note`/`sample`/`effect` | With separate fields, omitted ones keep their value |
| `write` | `pattern`, `row`, `step`, and `cells` + `channel`, or `lines` | `lines` are whole grid rows (one cell per channel); `""` or `---` clears a cell |
| `clear` | `pattern`, block | Defaults to one cell |
| `copy`, `move` | `pattern`, block, `to_pattern`, `to_row`, `to_channel` | Destination defaults to the same place; `move` empties the source |
| `transpose` | `pattern`, `semitones`, block | Notes only; block runs to the end of the pattern on one channel by default; leaving `C-1`-`B-3` fails |
| `add_pattern` | `copy_of`, `name`, `insert_order` | Appended to the pattern list and, by default, to the order list; max 64 patterns |
| `remove_pattern` | `pattern` | Only if no order uses it; later indices shift down |
| `rename_pattern` | `pattern`, `name` | At most 64 characters |
| `set_orders` | `orders` | Whole list; the last stored pattern must appear in it |
| `insert_order`, `remove_order`, `move_order` | `pattern`+`at`; `at`; `at`+`to` | Change the playing order |
| `title` | `title` | ASCII, length-limited |
| `timing` | `bpm`, `speed` | Writes `Fxx` on the first played row; needs two free effect columns or existing `Fxx`, else `TIMING` |
| `sample` | `slot`, `volume`, `finetune`, `name` | Settings and name only; PCM is never changed |
| `library_sample` | `id`, `library`, `slot`, `replace`, `adapt` | Same rules as `samples add` (exact library PCM); `library` defaults to `exports/sample_library`; fills the first empty slot unless `slot` is given; refused in a project declared `synthesized` |
| `recipe_sample` | `name`, `recipe`, `slot`, `volume`, `finetune`, `replace`, `role`, `match`, `library` | Created sample for the owner-requested created-samples mode; occupied slots need `replace`; volume matched to the role's level unless `volume` is given; refused in a project declared `library` |

Examples:

```json
{"op": "write", "pattern": 2, "row": 0, "channel": 1, "step": 2, "cells": ["C-2 06 ...", "", "E-2 06 C20"]}
{"op": "write", "pattern": 2, "row": 56, "lines": ["--- -- ... | --- -- ... | --- -- ... | A-2 0B C30"]}
{"op": "copy", "pattern": 1, "row": 0, "rows": 8, "channel": 0, "channels": 2, "to_pattern": 2, "to_row": 8}
{"op": "transpose", "pattern": 1, "row": 0, "rows": 32, "channel": 1, "semitones": 5}
{"op": "add_pattern", "copy_of": 1, "name": "A - Hook B", "insert_order": 3}
```

A song with more than four channels starts from `chiploom new --channels N` (MCP
`new_project`); the operations then accept channels 0 to N-1 and `lines` hold N cells.

## Habits

- One patch, one musical intent, one `--label`. Write each revision to a new file.
- Check `duration_seconds` after any order, `timing` or `Fxx` change.
- Do not use patches to change the stored PCM of a library sample; insert another library
  entry instead. Create samples (`recipe_sample`) only when the owner asks for a song made with created samples.
- Common failures: `NOTE_UNKNOWN` (use `C-1`..`B-3`, `G#3` not `G#-3`), `PATCH_CELL`
  (bad cell text), `PATCH_BOUNDS` (past row 63 or the last channel, 3 in a four-channel song), `ORDERS` (a pattern is
  still used, or the last pattern is not in the order list), `TIMING`.
- Full field list and error codes: `docs/CLI.md` (sections Patch and Error contract).

## Sample edits and instruments (when the owner asks)

The default policy stays: use library samples as they are and shape them with notes, volume and effects.
When the owner asks to edit a sound, the sound workshop operations work on the project copy and never touch
the bank: `sample_loop` (`loop_length` 0 removes the loop; a one-shot must start with two zero bytes, so use
`adapt` to prepend them), `sample_trim` (keeps the PCM bytes exactly; cutting into a loop needs `adjust_loop`),
`sample_gain` (refuses to clip unless `allow_clip`), `sample_fade`, `sample_set_pcm` (drawn PCM, not allowed in
library or synthesized projects) and `sample_match_level` (volume, then clean gain, to the role's reference
level). Editing a recipe sample drops its recipe and records `derived_from: "recipe"` in
`metadata.sample_sources`; an edited library sample keeps its `library_id` with `edited: true`. An instrument
(`chiploom instruments ...`, operation `apply_instrument`) is a sample plus a phrase of effect rows written
after the note, up to the next note in the channel. Fields, results and codes: `docs/CLI.md`, section Sound
workshop.
