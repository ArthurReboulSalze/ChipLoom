# ChipLoom roadmap

Updated 29 October 2026, after the 0.8.3 release. Earlier planning notes (translated from the original French) are kept in
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

## After 0.8

These are proposals. Each still needs the owner's agreement.

1. **Musical intelligence.** A `variations` command that writes several versions of a section from one
   brief for A/B listening; a taste profile built from feedback, A/B choices and accepted or rejected
   proposals, read by the agent before composing; arrangement templates (intro, verse, build, chorus,
   bridge) with durations and densities measured on the owner's references.
2. **Publishing.** Upload the package to PyPI (an owner action) and keep attaching the Windows and Linux
   builds to GitHub releases.
3. **macOS.** Not tested yet: window, real-time audio and a standalone build.
4. **Richer XM.** Multi-sample instruments, full envelopes and the rest of the XM effect set, then IT.
5. **Local phrase model** (see the October study in the history folder), only if the agent with
   references, variations and the taste profile proves insufficient.
