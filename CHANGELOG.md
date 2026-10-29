# Changelog

## Unreleased

- Add `chiploom norms`: articulation norms measured on the owner's reference MOD and XM modules (files, folders, ZIPs), as percentiles over the selection and over per-module medians: how long an arpeggio runs before it is struck again (rows, ticks, seconds), how long notes last and how they end (next note, key off, cut), how much each channel sounds and rests, note density, crowded sustain and tempo. Durations and proportions only: no file names in the aggregate, no notes or patterns, so the numbers can guide the agent without cloning a reference. `--details` lists per-module measures locally.
- Comments with a place: the owner (or an agent) attaches a remark to a block of the song (`place`: pattern, rows, channels; or the whole song) with the block's cells as they were. Live API `comments`, `comment`, `reply`, `resolve` (and reopen), commands `live comments|comment|reply|resolve`, MCP tools `live_comments`, `live_comment`, `live_reply`, and the same methods in the browser studio API as `human-web`. Every change is a `kind: "comment"` journal entry; `live status` gives `open_comments`. Comments are saved in `metadata.comments`, outside the undo history (`COMMENT_INVALID`, `COMMENT_UNKNOWN`). `feedback --pattern ...` ties a listening note to a block.
- Browser studio: comments with a place. Select a cell or a block and press **Comment**; covered cells get a corner mark, and the Agent tab lists comments (Go to, Reply, Resolve, Reopen, whole-song comments) with an open count that updates live. Leaving the Score tab closes the cell editor's bottom sheet, so the Agent tab is no longer squeezed on tablets. The feature lives in its own `web/comments.js`.
- Window: comments with a place. Select cells and press Ctrl+M (or right-click the grid, or the Agent menu) to tell the agent exactly where; covered cells get a small corner mark with the comment as tooltip, and a Comments column in the Agent tab lists them with Go to, Reply, Resolve/Reopen and Show resolved. The list and the marks update live when the agent replies or resolves, comments work with live collaboration off, and an agent's comment no longer triggers a re-render. The feature lives in `desktop_comments.py`.
- `desktop.py` is split into mixin modules by responsibility (layout, menus, preferences, files, song view, transport, editing, collaboration), each under 450 lines with a docstring naming what it relies on. The audio cache takes one lock per key, so two renders of the same module no longer collide on Windows.
- `report` now follows when each channel is heard. `channels[].sounding` gives the sounding fraction, the longest run without a rest (with its note starts and notes per second) and the rest count, measured along the timeline from note starts, key offs, `ECx`, `C00` / XM volume `10`, one-shot lengths and XM envelopes that fall to 0. `global.sustain` gives the longest stretch with many channels sounding at once. `channels[].pitch` gives each channel's lowest and highest heard fundamental in Hz, from recipe frequencies or the `samples inspect` pitch estimate (`samples.slots[].pitch` says which). New factual warnings: `channel_never_rests` for held material (a run over 16 s with fewer than 1 note start per second; busy legato lines and percussion one-shots are left alone), `crowded_sustain` (over 16 s), `pitch_too_low` (under 40 Hz) and `pitch_too_high` (over 3000 Hz). On the first published Copper Skies, `channel_never_rests` flags the two held arpeggio channels; the current version and the other demos raise none of these warnings.
- Add `chiploom live sync PROJECT.json` and the MCP tool `live_sync`: a regenerated project goes into the open window as small undoable patches (samples, structure, then one per changed pattern), each checked against the revision read first, so the owner's newer edits stop the sync instead of being overwritten. `--dry-run` shows the plan, `verified` says whether the session now matches the project, and what patches cannot carry (non-recipe PCM, XM envelopes, metadata) is listed under `not_synced`. The live API gains a read-only `module` method that returns the whole song.
- `lint` follows effect memory: `effect_memory_empty` flags an effect with parameter `00` (repeat the last value) before any value was given on the channel (XM: every effect with a memory, `5xy` and `6xy` sharing the `Axy` value; MOD: `3xx`, `4xy`, `7xy`, `9xx`), `zero_parameter` flags MOD `100`, `200`, `A00`, `E10`, `E20`, `EA0`, `EB0`, which ProTracker does not remember, and `offset_past_end` now counts a `900` with its remembered offset.
- `compare --equalize` (MCP `equalize`) turns the louder render down to the integrated loudness of the quieter one before the MP3 copies are made; the page says so, and the result and `comparison.json` record the target and each side's gain.
- The skill puts the version in every delivered file name and versions published media links, since a cached file under the same name plays an older version.

## 0.8.5 — 2026-10-29

- Add `chiploom lint` and the MCP tool `lint` (`chiploom.lint.v1`): cells whose effect does nothing or not what the score suggests, along the playback timeline, each with its pattern, row, channel, grid text and the reason. Rules: `offset_without_note`, `offset_past_end`, `finetune_without_note`, XM `instrument_without_note`, XM `retrig_volume_ignored`, XM `key_off_k00`, `slide_both_nibbles`, `tick_effect_after_row`, `portamento_without_note` and `held_arpeggio`. `--strict` exits 1 on any finding; `validate --report` adds a `lint` summary. The published songs lint clean; the first version of Copper Skies would have shown its 100 held arpeggios. The skill and the agent guide run it before delivery.
- Window: the library panel folds away again when its divider is dragged to the left edge (and reopens when dragged back); `Ctrl` + wheel over the pattern widens or narrows the track columns from about 0.5× to 2.4×, in whole wheel notches, with the Mute/Solo strip aligned; `Ctrl`+click on any Mute or Solo button makes every track audible again, in the real-time engine and the rendered playback alike. The window remembers the folded panel and the zoom; the "?" shortcut list, the button tooltips and the About text name both gestures, in English and French.

## 0.8.4 — 2026-10-29

- `render --mp3-output` takes `--mp3-normalize` (MCP `mp3_normalize`): the MP3 listening copy is scaled to a -1 dBFS peak and the result says by how much; the WAV keeps the engine's level. A ten-channel XM renders about 9 dB below full scale in libopenmpt, so its listening copy was much quieter than a four-channel MOD's.
- New demo, Copper Skies: a cracktro-style XM in ten channels made only with created samples, on the listening page and in the README. `tools/compose_copper_skies.py` rebuilds its project with the Python API (envelopes, auto-vibrato, fadeout, ping-pong loops, relative notes, the volume column, patterns of 32 to 128 rows and every XM effect ChipLoom accepts but `E6x`); tests check that the shipped project encodes to the shipped XM. `.gitignore` now excludes `.xm` files outside the approved demos.
- Copper Skies reworked live with the owner, through the open window and `live patch`: the arpeggios are struck on a 3-3-2 groove instead of held for bars, the second arpeggio channel answers on the same eighth grid, and a new steady `Continuo bass` instrument strikes the low root on the accents (22 instruments). It now opens the listening page, and an animated listening card (`docs/assets/copper-skies-card.svg`) at the top of the README links to it, since GitHub does not play audio in a README.
- The listening room links the Copper Skies files with `?v=<version>`, so a browser that cached an earlier MP3 (GitHub Pages allows ten minutes) fetches the new one.
- `report` measures `held_arpeggios` per channel and warns `held_arpeggio` when one note keeps an `0xy` arpeggio for more than 1.2 s without a new note or a cut. The skill and the agent guide say how to play tracker arpeggios and accompaniment on the rhythm (struck hits, quiet tails, a silent last row, two channels on one grid, no slow-attack pad retriggered) and that an XM keeps the playing sample when an instrument number comes without a note.

## 0.8.3 — 2026-10-29

Feedback from an agent that composed an eight-channel library-mode song through the MCP adapter.

- Add `chiploom new` and the MCP tool `new_project`: a blank project with one empty sample slot, empty patterns in order, initial speed and BPM, a channel count from 2 to 32 (`protracker-nch-pal-v1` beyond four) and `metadata.sample_source` (`library` by default). A library-mode song no longer starts from a hand-written JSON file, and `samples: []` is refused with an English message that points to it.
- The `library_sample` operation defaults `library` to `exports/sample_library`, like `samples add`.
- The MCP `patch` and `live_patch` tools take `ops_file` (a path to a JSON list of operations) as an alternative to inline `ops`.
- `samples inspect` gives a `pitch` block: the estimated fundamental at C-2 with its method, nearest note, cents and `transpose_semitones`. For a short loop it counts the whole cycles the loop holds (a looped cycle's pitch follows its loop length); otherwise it uses a YIN autocorrelation estimate, or `null` with a reason. `samples list` items carry a compact version.
- `samples preview` returns the same `audio`, `loudness` and `sample` measurements as `synth preview` (one shared helper), plus the pitch at the preview note.
- `report` on a library-mode project uses `exports/sample_library` as its loudness reference when it exists, instead of the fixed defaults; `samples.loudness_reference` says which reference was used and why. `--library` still overrides it.
- The blind comparison page labelled channel 0 wrongly (a falsy check); fixed with the zero-based numbering.
- Channel numbers are zero-based in every result an agent reads, as in the operations: `changes` lines (`ch0` is the first channel), `inspect --grid` and `live score` headers, and `report`. The window and the browser studio still show tracks from 1.
- The MCP server instructions, the skill and the patch reference describe MOD with 4 to 32 channels instead of four only.

A test run of ten songs composed by agents (library and created samples, MOD with 4, 6 and 8 channels, XM with 6 to 16 channels, one song driven only through the MCP adapter) found the following, now fixed.

**XM songs**

- MOD→XM conversion keeps sample recipes (XM→MOD too), so a synthesized project stays synthesized after `convert`. Before, every recipe was dropped while the conversion still claimed `lossless`. `convert` writes recipes into `.json` outputs, and a `.json` output without `--to` gets the other format.
- `samples add`, `library_sample`, `synth add` and `recipe_sample` work on XM projects (instruments 1–128) and convert the sample exactly as `convert` does (finetune `16×f−20`, 8-bit, forward loop, centred), keeping its library ID or recipe. Before, `samples add` copied the raw MOD finetune into an XM and mistuned the sample.
- `new --format xm` (`--rows`, header speed and BPM) and the MCP `new_project` `format`/`rows` parameters start a blank XM; `synth palette --channels N --format mod|xm` (MCP `channels`, `format`) starts a synthesized song of any width.
- New patch operations `pattern_length` (XM; `truncate` to drop notes, `PATTERN_TRUNCATE`) and `xm_header` (`restart_position`, `default_speed`, `default_bpm`, `frequency_table`), refused on a MOD with `MOD_OP_UNSUPPORTED`. On an XM, `timing` also sets the header defaults.
- MOD→XM sets the XM header's default speed and BPM from the `Fxx` on the first played row (the `Fxx` stay); MOD→XM→MOD stays byte-identical.
- Playback plans, `validate`, `inspect` and `patch` warn about an XM `Dxx` past the end of the next pattern and about a loop that comes back at a different speed or BPM.
- `estimate` accepts up to 256 rows and 256 orders; previews explain XM note labels (XM `C-4` is MOD `C-2`). `compare` writes and reports `x.xm`/`y.xm` for XM versions.

- The window adds library samples and created sounds to an XM song: the library insert and **Create → Add to song** convert the sample as `convert` does, in up to 128 instruments. A drawing goes in as a recipe there, because plain drawn sample data is a MOD sample edit.

**Patch**

- `patch` refuses to replace an existing output file other than the source unless `--overwrite` is given (MCP `overwrite`), so a typo no longer clobbers an earlier revision.
- `timing` takes `bpm`, `speed` or both; the one left out keeps its value. Its result gives the values written.
- `changes` says which sample fields changed (`sample 04 changed: volume, finetune`) and reports renamed patterns, pattern lengths and XM header changes. A warning names cells where an existing `Bxx`/`Dxx`/`Fxx` was removed (typically a `write` over row 0 that erased the initial tempo).
- A failing operation keeps its real code (`RECIPE_INVALID`, `SAMPLE_SLOT`, `SAMPLE_LIBRARY`, ...); `PATCH_OP` only means an unknown or missing operation. A JSON object that is not an operation gives `PATCH_FORMAT`; a missing `--ops` file gives `IO_ERROR` with its absolute path. Malformed notes in cells get a spelling hint (`C#2` in a MOD, `C#4` in an XM).
- The MCP `patch` description lists the cell formats and every operation, and links to the right section of the CLI reference.

**Report and loudness**

- The key estimate leaves out note starts that play percussion slots (role from `sample_sources`, the recipe, the bank category or the loop heuristic) and lists them in `key_estimate.percussion_excluded`. Every test song had been reported as "C major, high" because drums written at `C-2` dominated the count. Confidence is no longer "high" when the runner-up is the relative key by less than 0.20.
- Slots used only by mid-note sample switching (pulse-width movement) count as played (`sample_changes`) and are no longer flagged `sample_never_played`.
- `report` and `sample_match_level` choose the loudness reference by the same rule as `synth add` and `synth palette`: an explicit bank, else `exports/sample_library` when it exists, else the fixed levels; both say which and why. `sample_match_level` saves the role it used, so `report` compares the sample with the same target, and takes `match` (`auto`, `library`, `defaults`). `sample draw --as-recipe` matches loudness like `synth add`.
- `report` samples list `library_id`, `role`, `role_source`, `reachable_db` and `limited_by_peak`; the level warning says when a target is out of reach.
- `compare` writes the answer key to `answer_key.json` and prints it only with `--show-answer`, so running it no longer spoils the blind test.

**Render, export and errors**

- `render` accepts a `.json` project (rendered from a temporary MOD or XM) and reports integrated loudness, true peak and loudness range (FFmpeg `ebur128`) in a `loudness` field. A `--seconds` longer than the song says so (`ended_before_requested`, `module_seconds`, a warning).
- libxmp renders at libopenmpt's level. libopenmpt plays an XM about 6 dB below a four-channel MOD and lowers the level as channels are added (6 dB for a MOD with 8 channels or more, up to 12 dB for a 32-channel XM), while libxmp kept one level and clipped on busy XM songs. libxmp's master volume now comes from a table measured per format and channel count (`tools/calibrate_xmp_level.py`), in renders (`master_volume` in the result) and in the window's real-time playback. The engines agree within 0.2 dB on a centred note and within 0.7 dB on the test songs, against 6 to 10 dB before.
- `export` refuses an output that is not `.mod` or `.xm` unless `--format` is given (`OUTPUT_PATH`).
- Render, MP3, synth-recipe and libxmp errors reach agents in English with specific codes (`RENDER_LIMIT`, `OUTPUT_PATH`, `RECIPE_INVALID`, new `XMP_MISSING`); the French original stays in `message_fr`. Unknown-note messages keep the note, validation messages say "channel" instead of "track", and an unknown MOD signature names the signature found instead of the old four-channel message. `sample waveform` reads XM files.
- The CLI reference documents the missing codes (`CHANNELS`, `CONVERT_REFUSED`, the `XM_*` import codes, `MOD_FLT8`, `MOD_VARIANT`, ...), the N-channel bounds (`INTEGER_RANGE` for an index, `PATCH_BOUNDS` for a block), and how to apply instruments from the last note to the first. The agent guide no longer says that sample synthesis is deferred, and the sample-bank reference starts its test song with `new`.

## 0.8.2 — 2026-10-28

- Fix `chiploom-cli mcp` in the standalone builds: its tools started the CLI with `-m tracker4agents`, which a frozen program does not accept, so every tool call failed. Installs from a checkout or a wheel were not affected. The release workflow now makes one MCP tool call through each archive.
- README: new screenshots of 0.8.1 (an eight-channel MOD with the sound workshop, the Agent tab, the browser studio) and wording for up to 32 channels.

## 0.8.1 — 2026-10-28

- Fix a freeze of the window in rendered playback (sample auditions, and the song without libxmp), seen about one run in two in the Windows CI. `QMediaPlayer.stop()` and `setSource()` make Qt's FFmpeg backend wait for its audio thread while that thread destroys a renderer connected to the window's `QAudioOutput`; as that object is a Python wrapper, the thread needs the GIL, which the direct call holds, so both wait for ever. The window now runs these two calls through the event loop with `media_call` (PySide releases the GIL there), still synchronously. The meter also reads the rendered WAV at the playback position instead of receiving decoded buffers from the audio thread.
- CI runs each desktop test module in a child process and prints every thread, native frames included, if it hangs.
- The Windows build now includes the browser studio page (the first 0.8.0 zip lacked it and was replaced).
- Add a standalone Linux build, `ChipLoom-<version>-linux-x86_64.tar.gz`, attached to releases next to the Windows zip. `tools/build_windows.py` becomes `tools/build_standalone.py`, which builds for the platform it runs on (`--archive`, with `--zip` kept as an alias); the release workflow builds both on Windows and on Ubuntu 22.04 (glibc 2.35 and newer). On Linux the bundle restores the user's `LD_LIBRARY_PATH` for the programs it starts, so the system FFmpeg does not load the bundled `libstdc++`; the workflow renders a demo with it to check.
- Tolerate one late audio buffer in the stalled-GUI real-time test, which a slow CI machine missed once.

## 0.8.0 — 2026-10-28

This release groups what was proposed after 0.7 as four releases (0.8 to 1.0). See the [roadmap](docs/ROADMAP.md).

**For agents**

- Widen the formats. `Module.channels` takes 2 to 32 values and MOD files with `2CHN` to `9CHN` and `10CH` to `32CH` signatures are read and written, alongside `M.K.`, `M!K!`, `FLT4` and `4CHN`. Header details the model cannot express (signature, restart byte, inactive order entries, odd sample headers, non-ASCII text) are kept in `metadata.mod`, so a clean import re-exports byte for byte. What must change (a loop running past the sample end, volumes above 64, an `M.K.` module with more than 64 patterns, which is written as `M!K!`) is converted and listed in `import_notes`. `FLT8`, the Octalyser and TakeTracker signatures (`CD61`, `CD81`, `OCTA`, `TDZx`) and `EFx` stay refused, each with its own code. The `E6x` pattern loop and the `EEx` pattern delay are now accepted and followed by the playback plan, the validator and the measurements.
- Add a first FastTracker 2 XM profile, `fasttracker2-xm-v1`: 2 to 32 channels, patterns of 1 to 256 rows, up to 128 instruments with exactly one sample each, 8-bit and 16-bit samples, forward and ping-pong loops, panning, relative note, the volume column and linear or Amiga frequency tables. XM cells read `NOTE II VV EEE`. Unsupported input is refused with an `XM_*` code instead of being approximated. The CLI reads, writes, validates, inspects, renders, previews, compares and reports `.xm` files.
- Add `convert` (a MOD to XM keeps notes, effects and PCM and reports what an XM plays differently; an XM to MOD only when the XM fits the MOD profile, otherwise refused with `CONVERT_REFUSED` and a list of `reasons`) and `export --format mod|xm`. `import` now prints its `import_notes`.
- Extend project schema v2 for these formats without a new version: a top-level `channels` (absent means 4), `format` and the profile `protracker-nch-pal-v1` for other channel counts, the XM sample fields `bits`, `loop_mode`, `panning` and `relative_note`, the XM pattern `length`, and `metadata.xm` for the header values the tools do not edit. Grid rows hold one cell per channel. Four-channel `M.K.` projects, MODs and playback plans are unchanged.
- Make the patch operations, `inspect --grid`, `report`, `compare` and `preview` follow the module's own channel count, row count and note names. The live `select` request and the `audible` context follow the open module too. The sample-editing operations are MOD-only and are refused on an XM (`XM_OP_UNSUPPORTED`).
- Add the sample workshop to the core, usable from the CLI, patch and MCP. Seven new patch operations edit a sample on an undoable copy: `sample_loop`, `sample_trim`, `sample_gain`, `sample_fade`, `sample_set_pcm`, `sample_match_level` and `apply_instrument`. Refusals are explicit (`SAMPLE_LOOP`, the new `SAMPLE_CLIP`, `SAMPLE_SOURCE`) and each has a documented option (`adapt`, `adjust_loop`, `allow_clip`, `allow_loop`) to accept the consequence. Edits are recorded in `metadata.sample_sources`. The sample-source rules still apply: drawn or embedded PCM is refused in `library` and `synthesized` projects.
- Add `sample edit|draw|waveform|schema` and `instruments list|show|save|delete|apply`. An instrument is a sample, its volume and fine tune, and a phrase of up to 32 effect rows, kept as a JSON file in an instrument folder (`exports/instruments` by default). Applying one writes the note, the sample number and the phrase effects as one transaction. `sample_tools` also exposes the pure edits, `preview_recipe` and `recipe_schema`, which a form can use.
- Extend the live API. `live status` reports `pending_request` and `web_devices`. A `live open` that has to wait for the owner's save-or-discard answer now replies at once with `handled: "pending"` and a `request_id`; the outcome (`opened`, `declined` or `failed`) is journaled afterwards as a `kind: "request"` entry by `human`, so the agent finds it in `live changes`. A second `open` while one is waiting returns `handled: false` with a reason. The `kind` of journal entries (`patch`, `edit`, `reload`, `open`, `accept`, `request`) is now documented. Errors that carry a list of `reasons` (a refused conversion) keep it in the error payload.
- Add `live web` (prints the studio address; `--status` lists the connected browsers) and `live serve --web [--lan --lan-host --lan-port]` or `--no-web` for the browser studio (see below).
- Change the MCP adapter. It now has 45 tools: the nine sound-workshop tools (`sample_schema`, `sample_edit`, `sample_draw`, `sample_waveform`, `instruments_list`, `instruments_show`, `instruments_save`, `instruments_delete`, `instruments_apply`), plus `convert` and `export_format` (34 before). Tool schemas use typed enums and leave out an empty `required`, and protocol version `2025-11-25` is negotiated first. [docs/MCP.md](docs/MCP.md) documents the adapter and client configurations, with a tool table generated by `tools/mcp_docs.py` that a test keeps exact. `tools/mcp_smoke.py` drives the adapter with the official Python MCP SDK as a real client (checked with `mcp` 1.30.0 and 2.3.0); `tests/test_mcp_clients.py` runs it when `CHIPLOOM_MCP_CLIENT_PYTHON` points at an interpreter that has the SDK, and CI does so on Linux and Windows. It has not been tried in a model-driven session with Codex, Claude Desktop, Claude Code or another application.
- Replay stability: libxmp replays a normalised copy of the module when a header variant (restart byte, `FLT4`, `4CHN`) would crash it, and modules it does not treat as ProTracker files (6 or 8 channels, odd headers) play with the plain mixer.

**In the window**

- Add the sound workshop. In **Song samples**, a sample editor with a waveform, draggable loop handles and a trim selection, fades, gain in dB, volume and fine tune. Each edit has **Preview** (hear the edited copy and read what would change, the song untouched) and **Apply** (one undoable change), and a refusal is explained with the explicit choice offered. **Levels** compares each sample's loudness with its role's target and has **Match** and **Match all**. The **Create** tab builds a sound from a recipe, with a form generated from the recipe schema, listening after each change with measurements and a drawing canvas, and adds it to the song; **Start a synthesized song…** opens the starter palette. The **Instruments** tab saves a sample with a phrase as an instrument and applies it at the cursor (`Ctrl+I`).
- Add keyboard audition: the piano keys play the current instrument with Edit mode off, and the selected song sample, library entry, recipe or instrument in the sound tabs. In Edit mode the sample being written is heard. Up to 6 notes sound at once, mixed with the song in the real-time stream; without libxmp one rendered note plays at a time.
- Add **Agent → Open in a browser…**: the studio address with **Copy** and **Open**, **Allow devices on my local network** (plain HTTP, with a warning, remembered between sessions) and a **Connected browsers** table. The status bar shows **Browsers: N**, and edits made in a browser are announced and flash like the agent's.
- Open, play, edit and export MOD songs with 2 to 32 channels and XM songs in the window: one column group per channel with horizontal scrolling and a Mute/Solo strip that follows it, the browser studio's channel colours, the XM volume column, key off and instrument range, `.xm` open and **Export XM…**, XM sample details, and keyboard audition at the XM pitch. Sample-editing controls the core refuses on an XM are disabled with a tooltip.
- Add drag and drop of selected blocks (`Ctrl` copies), comparing a take with the current song (**Compare with current**, `Ctrl+B`), a status-bar indicator of whether an agent worked on the window in the last two minutes, and an `open` request from the agent that no longer waits on the owner's prompt.

**Browser studio**

- Add a local web page (`tracker4agents/web`: plain JavaScript with no build step and no external resources, standard library on the Python side) that joins the same live session. A **Score** tab has the order list, a pattern selector, the grid, a **Select block** mode and a cell editor; an **Agent** tab has proposals, changes and takes; a player bar listens to an excerpt rendered by the session or, with a window attached, plays on the computer. It works with a headless `live serve` too.
- Join automatically: opening the studio address gives the editor directly, with no code to type, even on the local network. The agent's token never reaches the browser, which receives its own token in an HttpOnly, SameSite=Strict cookie from a same-origin join request the page makes by itself. Browser edits are journaled as `human-web`, carry the revision they read and conflict like any other edit.
- Serve the studio on loopback only by default. `--lan` (or the window's checkbox) opens only the studio, never the agent API, to private network addresses over plain HTTP. Requests must come from the studio's own origin, the pages carry a strict content security policy, and the connected browsers live in memory only.

**Distribution, documentation and project**

- Update the GitHub Actions to current major versions, add the SDK client run to the core job and ship the web page in the package data.
- Make the documentation English-only: the French user guide becomes [the user guide](docs/USER_GUIDE.md), the reference studies become [ANALYSIS](references/ANALYSIS.md) and [SELECTION](references/SELECTION.md), and the earlier planning notes in `docs/history/` are translated. The window keeps its English and French interface.
- Add regression tests for channels, MOD variants, XM, sample editing, instruments, the web studio, the workshop, keyboard audition and the 0.8 live behaviour.

## 0.7.0 — 2026-10-27

This release groups what was first planned as four releases (0.7 to 1.0). See the [roadmap](docs/ROADMAP.md).

**For agents**

- Add project schema `tracker4agents.project.v2`: PCM stored as base64 with a verified SHA-256, and patterns written as readable grid `rows` (`"00": "C-2 04 F06 | A-1 06 F7D | --- -- ... | A-2 08 E01"`). Files are written compactly, one line per sample and row. Version 1 files and the sparse `events` layout still load. Voltage Odyssey V2 goes from 690 KB to 117 KB and Pixel Rush from 192 KB to 34 KB. `chiploom migrate` rewrites a project or MOD as v2 and refuses to write if the exported MOD would change.
- Add `patch`: batch edit operations (`set`, `write`, `clear`, `copy`, `move`, `transpose`, pattern and order operations, `timing`, `sample`, `library_sample`) applied as one validated, all-or-nothing transaction, with a readable `changes` summary. Add `inspect --pattern N --grid [--row R --rows K]`.
- Add a structured error contract: failures on stderr carry a stable `code`, an English `message` and, for translated core diagnostics, the original French `message_fr`. `validate --report` entries gain `code` and grid-aware paths. The codes are listed in the CLI reference.
- Add live sessions (`chiploom live ...`, `live serve` for a headless session): a localhost-only server with a token, an author-aware change journal, `--base` conflict refusal (`LIVE_CONFLICT` with the contested cells; the owner's edits win), proposals the owner accepts or rejects, announced versions (takes), and requests to play, stop, select and open. The agent cannot act as `human`.
- Add the musical quality loop: `report` (measurements of the played score, with an estimated key labelled as an estimate), `compare` (a blind A/B page; a casual test with the answer key in `comparison.json` and without loudness matching) and `feedback` (listening notes stored in the project).
- Add `chiploom mcp`, a Model Context Protocol adapter over standard input and output with 34 tools that run the matching CLI commands. It is covered by automated tests; it has not been tested with specific MCP clients, and agents with a terminal can keep using the CLI.
- Add songs made only with created samples, on the owner's request (library samples stay the default). `wave` recipes (pulse, triangle, saw, sine, noise) are clean looped waves tuned so note C-2 plays the stated frequency; existing recipes build byte-identical samples, and `drive` gives drum and pluck recipes a denser level. `chiploom synth types|levels|preview|add|palette` list recipes, report reference levels, audition a recipe to a WAV with measurements, insert a sample and write a coherent 13-sample starter palette. The `recipe_sample` patch operation inserts a created sample like `library_sample` does.
- Add `metadata.sample_source` (`library`, `synthesized`, `mixed`): `validate --sample-source` and a declared source fail with `SAMPLE_SOURCE` and the offending slots, and library insertion into a synthesized project (or a recipe into a library project) is refused. `report` counts recipe and embedded samples.
- Match created samples to the owner's library by loudness: `synth palette` and `synth add` set volumes from the sample bank's loudness distribution per role (median per group; kick at the upper quartile and hat at the lower quartile of the percussion; fixed measured defaults without a bank), and `report` lists each sample's loudness and flags samples more than 6 dB from their group's reference.
- Add five `synth_*` MCP tools (34 in total).
- Update the agent guide, CLI reference, architecture note and ChipLoom skill (with new patch and live references) for all of the above.

**In the window**

- Add keyboard note entry: Edit mode (Ctrl+E), Step, Octave (F1–F3 or numpad +/−) and an Auto/QWERTY/AZERTY keyboard setting (Auto picks AZERTY for French input). Hexadecimal entry fills the sample and effect columns; Delete clears a cell and Backspace clears it and moves up.
- Add block selection and editing: Ctrl+C/X/V with the clipboard in the same grid text the agent prints, Alt+arrows to move a block, Ctrl+↑/↓ to transpose by a semitone and Ctrl+Shift+↑/↓ by an octave.
- Add an order editor: Insert, New, Duplicate, Remove, ↑/↓ and Rename….
- Reload automatically when the file changes on disk: a clean window applies one undoable "Agent changes" step; unsaved local edits are merged three ways, with conflicts listed in the status bar and the file's version kept. Changed cells flash. F5 still reloads by hand.
- Add live collaboration (Agent menu, on by default, with a status-bar indicator). Agent edits appear at once, highlighted and undoable with Ctrl+Z. A bottom Agent tab shows proposals (preview overlay, Accept with Ctrl+Enter, Reject, Listen to proposal, Clear preview, and a conflict dialog that asks whether to accept anyway) and takes (Open take).
- Play in real time through libxmp when it is available, so edits, mutes and solos are heard without re-rendering. Exports and listening copies still render with FFmpeg/libopenmpt, so small differences are possible. Without libxmp the window falls back to rendered playback.
- Run real-time audio in a dedicated thread, so moving the window or opening dialogs no longer starves the sound card (0 underruns measured with the GUI blocked for 600 ms). Add Playback → Audio buffer (80, 150, 300 or 600 ms; default 150), applied without stopping playback and remembered.
- Give the tracker column a 10 px gap from the library panel and roomier Agent tab columns.

**Distribution and project**

- Add `python tools/build_windows.py [--zip]` for a standalone Windows folder with `ChipLoom.exe` (window) and `chiploom-cli.exe` (command line). FFmpeg is not bundled; libxmp is, when it has been built. The Windows build workflow builds libxmp and attaches the zip to tagged GitHub releases. Prepare the package for PyPI; it is not yet published.
- Run Ruff and a package build check in CI, and run the desktop tests on Windows and Linux (the Linux job does not block while it proves stable).
- Remove the French launcher scripts `Lancer tracker4agents.cmd`, `Installer interface Windows.cmd` and `lancer-tracker4agents.sh`; `Install ChipLoom.cmd`, `Launch ChipLoom.cmd` and `launch-chiploom.sh` remain.
- Add a roadmap and move the earlier French planning notes to `docs/history/`.
- Preview bundles and compare pages stay listen-only; browser editing is on the roadmap.
- Add regression tests for patch, the error contract, schema v2, report, compare, live sessions, the MCP adapter, keyboard entry and live integration in the window.

## 0.6.0 — 2026-10-18

- Add local sample banks: exact PCM extraction from supported MOD/ZIP inputs, deduplication with playback variants, neutral names, editable categories/tags, search, audition, compatibility checks and validated insertion through CLI/Python.
- Integrate a bottom sample browser in the human window with search, type/role filters, a waveform, note-based listening, slot selection and undo/redo. Keep all four tracker channels wide and remember the bank folder locally.
- Provide a reusable ChipLoom agent skill with a reproducible workflow for selecting modules, building a user's own bank, refining labels and composing a test MOD without private developer sample IDs.
- Document the library-first composition workflow, refresh the README and native Windows screenshot, and extend the publication audit and CI to keep bank PCM, manifests and private provenance out of Git.
- Add core and optional desktop regression tests using generated fixtures. No reference bank, borrowed-sample test music or private source list is distributed.

## 0.5.2 — 2026-10-15

- Remove the right sidebar and move song settings and audio exports above the tracker, alongside the transport and stereo meter. Use the title field as the song heading to keep the header compact.
- Give the pattern and sample views the full width beside the library, including at the minimum window size in English and French.
- Present ChipLoom as a tracker and chiptune composition toolkit for agents, with four-channel MOD support as its first format rather than a platform-specific focus.

## 0.5.1 — 2026-10-15

- Integrate the approved ChipLoom logo in the library and its emblem in the native window/taskbar icon, including installed packages.
- Simplify the right sidebar to song settings and audio exports; remove the dedicated note-cut controls while keeping effect editing in the tracker.
- Display the project filename below the title, with the full path available on hover. Preserve session settings and English/French support.
- Replace identifying metadata in published reference studies with neutral IDs and extend the publication audit to reject its reintroduction.

## 0.5.0 — 2026-10-15

- Apply feedback from a reported Hermes / glm-5.3-flash composition session on Debian 13; document its environment and verification scope.
- Explain note spelling and duplicate cells with both values and event indices. Add `validate --report` for independent JSON diagnostics.
- Add constant-timing duration planning with `estimate` and warnings when an otherwise valid score exceeds the 120-second render limit.
- Add `render --from-order` to both engines, decoding prior state before trimming a bounded excerpt. Test its PCM against a full render with inherited instruments and timing.
- Refresh the public README with the approved transparent logo, a Windows interface screenshot, clearer setup and original musical examples.
- Publish Pixel Rush and Voltage Odyssey V2 with MP3 players, MODs and editable scores on a dedicated English/French GitHub Pages listening page. Keep the publication audit restricted to these approved media hashes.

## 0.4.0 — 2026-10-15

- Name the application ChipLoom; retain the tracker4agents package, project schema and session directory. Add ChipLoom CLI and desktop launch aliases.
- Generate portable HTML bundles from existing projects or compatible MODs with `preview`, in English or French.
- Analyze reference MODs and ZIP archives without modifying or extracting original paths. Include the aggregate fifteen-module study and explicit editing compatibility results.
- Document installation and composition workflows for Codex and Hermes, the CLI, the human window, HTML delivery and the distinction from a future MCP adapter.
- Avoid reentrant loop restarts in Qt and queue decoded audio delivery to the GUI thread, preventing a reproduced stop/close deadlock after looping.
- Make GUI regression tests independent of pre-generated export folders. Add core CI for Windows and Linux and an index audit for local state, credentials and reference media.

## 0.3.0 — 2026-10-15

- Add clickable track mute headers, solo, decoded stereo metering, four color themes and persistent English/French UI preferences.

## 0.2.0 — 2026-10-15

- Add the optional PySide6 native window for humans, a shared validated Document model, undo/redo, cell/sample/timing edits, loading and audio exports.

## 0.1.0 — 2026-10-15

- Build the standard-library MOD core, deterministic sample recipes, JSON projects and CLI.
- Create First Light and Pixel Rush with original samples, HTML listening pages and validation through libopenmpt and libxmp.
