# ChipLoom roadmap

Updated 29 October 2026, after the 0.8.4 release. Earlier planning notes (translated from the original French) are kept in
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

Patch releases followed: 0.8.1 fixed a playback freeze and added the Linux build, 0.8.2 fixed the MCP tools in the standalone builds, and 0.8.3 made XM and wide MOD songs workable for agents from start to export (blank projects, sample insertion in the CLI, MCP and window, XM pattern length and header, engines at the same level), with the fixes from a ten-song test run by agents. 0.8.4 added Copper Skies, a ten-channel XM demo reworked live with the owner, and turned what that session taught into the agent skill and a `report` warning for held arpeggios.

## 0.9: hear what the agent cannot

The Copper Skies session (0.8.4) set the direction. Every fault the owner heard was a fault of
*behaviour over time*: arpeggios held for bars, a pad retriggered until it pumped, a bass that never
breathed. The score was valid, `report` counted the notes, and nothing flagged it. Two review passes
also found a dozen effects that did not do what the agent believed (a `9xx` without a note, `Rxy`
under a volume column, an instrument number without a note in an XM), and a bass that sounded two
octaves below where it was written. Version 0.9 gives the agent measurements for those things, so
the owner's ear is no longer the first check.

| Theme | Proposal |
| --- | --- |
| Behaviour over time | `report` measures, per channel, how much of the song it sounds without a rest, the longest run of identical cells whatever the effect, and when too many channels sustain at once; `held_arpeggio` becomes one warning among several of this kind |
| Sounding pitch | `report` computes the frequency each channel is heard at (recipe frequency or sample pitch estimate, plus `relative_note` and `finetune`) and flags a bass below 40 Hz or a lead above 3 kHz |
| Tracker lint | **Started (unreleased):** `chiploom lint` and its summary in `validate --report` list inert or misleading cells with the reason (`9xx`, `E5x` and an XM instrument number without a note, a `9xx` past the sample's end, `Rxy` cancelled by the volume column, `K00`, slides with both nibbles, `E9x`/`ECx`/`EDx` past the row's ticks, portamento with no note, held `0xy`). Still to do: rules that need the effect memory across rows (`Hxy` and `Txy` tick counts, `9xx` and slide memory) |
| Measured norms | `analyze` extracts articulation statistics from the owner's references (how long an arpeggio runs before a retrigger, the sounding fraction of each channel, how often chords are cut) and publishes them as neutral numbers the skill can cite instead of the agent's taste |
| Generator to window | `chiploom live sync PROJECT.json`: diff a project file against the open session and apply the differences as one undoable patch per pattern, so a script-written song can be reworked live without hand-made patches |
| Feedback with a place | The owner attaches a comment to a selection in the window (or the browser studio); the agent reads it with `live changes`, and `feedback` stores it with its pattern, rows and channels. These placed comments feed the taste profile below |
| Delivery hygiene | The skill names every delivered file with its version (`song-v3.mp3`), and `compare` gains `--equalize` so the louder take no longer wins by default |

## After 0.9

These are proposals. Each still needs the owner's agreement.

1. **Musical intelligence.** A `variations` command that writes several versions of a section from one
   brief for A/B listening; a taste profile built from feedback, placed comments, A/B choices and
   accepted or rejected proposals, read by the agent before composing ("arpeggios struck, never held"
   is a durable preference, not a one-off fix); arrangement templates (intro, verse, build, chorus,
   bridge) with durations and densities measured on the owner's references.
2. **XM in the window.** An `instrument_envelope` patch operation and an envelope editor, panning and
   relative note on the sample card, and the row count of a new pattern.
3. **Publishing.** Upload the package to PyPI (an owner action) and keep attaching the Windows and Linux
   builds to GitHub releases.
4. **macOS.** Not tested yet: window, real-time audio and a standalone build.
5. **Richer XM.** Multi-sample instruments, the rest of the XM effect set, then IT.
6. **Local phrase model** (see the October study in the history folder), only if the agent with
   references, variations and the taste profile proves insufficient.
