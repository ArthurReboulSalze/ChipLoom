# ChipLoom roadmap

Updated 29 October 2026, after the 0.9.0 release. Earlier planning notes (translated from the original French) are kept in
[docs/history](history/).

## 0.7.0: compose together

Version 0.7 groups what was first planned as four releases (0.7 to 1.0).

| Theme | What landed |
| --- | --- |
| Agent ergonomics | Compact project schema v2 (base64 PCM with hashes), batch `patch` operations, `inspect --grid`, stable error codes with English messages |
| Composing together | Live sessions between the window and the agent: instant edits, an author-aware change journal, conflict refusal, proposals to accept or reject, announced versions, auto-reload with three-way merge |
| Tracking in the window | Keyboard note entry (QWERTY/AZERTY), block selection, copy/paste, moving notes, transposition, order editor |
| Hearing edits at once | Real-time playback in the window through libxmp when available; rendered playback as the fallback |
| Musical quality loop | `report` measurements, blind A/B `compare` pages, `feedback` stored in the project |
| Distribution | MCP stdio adapter, PyPI-ready packaging, Windows standalone build script, desktop tests in CI on Windows and Linux |

See the [changelog](../CHANGELOG.md) for details and the [CLI reference](CLI.md) for contracts.

## 0.8.0: shape sounds and share the session

Version 0.8 groups what was proposed after 0.7 as four releases (0.8 to 1.0).

| Theme | What landed |
| --- | --- |
| Consolidation | MCP adapter tested with real clients and documented configurations; window: drag-and-drop of blocks, comparing a take with the current song, a reliable "agent connected" indicator, agent `open` requests that never time out on the owner's prompt; Linux desktop tested on a real Debian machine with sound; CI actions on current versions |
| Sound workshop in the window | Sample editor (loop points, volume, fine tune, trim) on undoable copies; recipe editor with immediate listening and waveform drawing; sample levels against the bank with one-click matching; reusable instruments (a sample plus a short effect phrase) |
| Browser studio | A local web page joining the same live session as the window, opened by its address, with no code; listening, an editable grid and the Agent tab, usable from a tablet; works with a headless `live serve` too |
| Wider formats | `E6x` pattern loops and `EEx` pattern delays, more four-channel MOD variants, MOD with 2 to 32 channels, and a first XM profile with its own validation, all editable in the window |
| Playing by ear | Keyboard audition of the current instrument, sample, recipe or instrument, up to 6 notes mixed with the song in the real-time stream |

Patch releases followed: 0.8.1 fixed a playback freeze and added the Linux build, 0.8.2 fixed the MCP tools in the standalone builds, and 0.8.3 made XM and wide MOD songs workable for agents from start to export (blank projects, sample insertion in the CLI, MCP and window, XM pattern length and header, engines at the same level), with the fixes from a ten-song test run by agents. 0.8.4 added Copper Skies, a ten-channel XM demo reworked live with the owner, and turned what that session taught into the agent skill and a `report` warning for held arpeggios. 0.8.5 shipped the first 0.9 piece, `chiploom lint`, with window gestures the owner asked for (folding the library panel, `Ctrl`+wheel column zoom, `Ctrl`+click to clear every mute and solo).

## 0.9.0: hear what the agent cannot, and a bank the owner manages

The Copper Skies session (0.8.4) set the direction. Every fault the owner heard was a fault of
*behaviour over time*: arpeggios held for bars, a pad retriggered until it pumped, a bass that never
breathed. The score was valid, `report` counted the notes, and nothing flagged it. Two review passes
also found a dozen effects that did not do what the agent believed (a `9xx` without a note, `Rxy`
under a volume column, an instrument number without a note in an XM), and a bass that sounded two
octaves below where it was written. Version 0.9 gives the agent measurements for those things, so
the owner's ear is no longer the first check.

| Theme | Proposal |
| --- | --- |
| Behaviour over time | **Done in 0.9.0:** `report` measures, per channel, how much of the song it sounds without a rest (XM releases after a key off included), the longest run of identical cells whatever the effect, and when too many channels sustain at once; `held_arpeggio` becomes one warning among several of this kind |
| Sounding pitch | **Done in 0.9.0:** `report` computes the frequency each channel is heard at (recipe frequency or sample pitch estimate, plus `relative_note` and `finetune`) and flags a bass below 40 Hz or a lead above 3 kHz |
| Tracker lint | **Done (0.8.5, effect memory rules in 0.9.0):** `chiploom lint` and its summary in `validate --report` list inert or misleading cells with the reason (`9xx`, `E5x` and an XM instrument number without a note, a `9xx` past the sample's end, `Rxy` cancelled by the volume column, `K00`, slides with both nibbles, `E9x`/`ECx`/`EDx` past the row's ticks, portamento with no note, held `0xy`). The effect memory rules (`effect_memory_empty`, MOD `zero_parameter`, `900` repeating an offset past the sample) followed |
| Measured norms | **Done in 0.9.0:** `chiploom norms` measures, and `references/NORMS.md` publishes; originally: `analyze` extracts articulation statistics from the owner's references (how long an arpeggio runs before a retrigger, the sounding fraction of each channel, how often chords are cut) and publishes them as neutral numbers the skill can cite instead of the agent's taste |
| Generator to window | **Done in 0.9.0:** `chiploom live sync PROJECT.json`: diff a project file against the open session and apply the differences as one undoable patch per pattern, so a script-written song can be reworked live without hand-made patches |
| Feedback with a place | **Done in 0.9.0:** the owner attaches a comment to a selection in the window (or the browser studio); the agent reads it with `live changes`, and `feedback` stores it with its pattern, rows and channels. These placed comments feed the taste profile below |
| Delivery hygiene | **Done in 0.9.0:** the skill names every delivered file with its version (`song-v3.mp3`) and versions published media links, and `compare --equalize` matches both renders' loudness so the louder take no longer wins by default |
| Owner-managed bank (added during 0.9) | **Done in 0.9.0:** a shared active bank, one-sample import from songs, modules and WAVs with the owner's name and role, measured tuning and its correction kept in the bank, palette retuning, a 62-sound starter bank built on first use, the window's Bank menu, Tuning and Palettes pages, drops, the sample-mode switch, a clearer Agent tab and an in-app help |

## After 0.9

These are proposals. Each still needs the owner's agreement.

1. **Musical intelligence.** A `variations` command that writes several versions of a section from one
   brief for A/B listening; a taste profile built from feedback, placed comments, A/B choices and
   accepted or rejected proposals, read by the agent before composing ("arpeggios struck, never held"
   is a durable preference, not a one-off fix); arrangement templates (intro, verse, build, chorus,
   bridge) with durations and densities measured on the owner's references.
2. **XM in the window.** An `instrument_envelope` patch operation and an envelope editor, panning and
   relative note on the sample card, and the row count of a new pattern.
3. **MIDI import** (agreed with the owner for the release after 0.9). Read a Standard MIDI File with the
   standard library: ticks quantized to a chosen row grid, tempo to speed/BPM, each instrument spread
   over as many channels as its polyphony (or chords turned into `0xy` arpeggios), velocity to the volume
   column or `Cxx`, note ends to key offs or cuts, channel 10 drums mapped by note to kick, snare and hats,
   notes outside a MOD's three octaves transposed with a warning. At import the owner picks a bank sample
   or a recipe per instrument, proposed by role from the General MIDI program, and the measured tuning of
   each sample is corrected so written C sounds C. The result is an ordinary project the agent reads and
   reworks in the live session. `import-midi FILE --map ...` and an MCP tool for agents. Importing someone
   else's song reproduces it: fine for private work, never a source for published compositions.
4. **Effect styles** (proposed by the owner for after 0.9). A library of effect gestures applied to a
   selection: level (fade in/out, rhythmic gate, accents, tremolo), echo (the note repeated quieter a few
   rows later, same or free channel), pitch (slide into a note, fall-off, vibrato that widens, kick pitch
   drop), rhythm (retrigger rolls that speed up before a downbeat, stutter, hard cuts), timbre (sample
   offset sweeps, XM panning ping-pong) and struck arpeggio patterns, each with an intensity and a speed.
   A gesture adapts to the song's speed/BPM, format (MOD or XM volume column) and effect memory, passes
   `lint`, and is one undoable edit. In the window: select, right-click, "Apply FX style"; for agents
   `fx apply STYLE --pattern --rows --channels`, a patch operation and an MCP tool, and the owner can ask
   for one in a placed comment. The styles are a core feature, not a window one: the agent uses them while
   composing (the skill says which gesture suits which role and section, e.g. a roll before a downbeat, an
   echo on a sparse lead), `report` names the styles a song uses, and the window only calls the same core.
   Presets measured on the owner's references (which effect sequences recur and with what settings:
   effect gestures, never notes).
5. **Starter banks** (proposed by the owner for after 0.9), so a new user has a usable bank without their
   own modules. (a) A base bank generated by ChipLoom recipes (drums, pulse and triangle basses and leads,
   drawn cycles, several variants each): no rights question, tuned together, roles and names filled in.
   (b) A small bundled bank of CC0 or public-domain samples only, each with its licence, source and author
   in a credits file, kept to a few MB. (c) Download presets ("Build a base bank"): known free packs
   fetched only when the user asks, checked against a digest, imported with measured roles and tuning;
   candidates to verify licence by licence (single-cycle waveform sets such as AKWF, CC0 packs on
   Freesound and OpenGameArt). Never a pack whose licence forbids redistribution or is unclear.
6. **Publishing.** Upload the package to PyPI (an owner action) and keep attaching the Windows and Linux
   builds to GitHub releases.
7. **macOS.** Not tested yet: window, real-time audio and a standalone build.
8. **Richer XM.** Multi-sample instruments, the rest of the XM effect set, then IT.
9. **Local phrase model** (see the October study in the history folder), only if the agent with
   references, variations and the taste profile proves insufficient.
