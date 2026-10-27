# ChipLoom roadmap

Updated 27 October 2026, with version 0.7.0. Earlier planning notes, in French, are kept in
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

## Next

These are proposals, in priority order. Each still needs the owner's agreement.

1. **Real-time playback, next steps.** The window now plays through libxmp in real time when the
   library is available, so edits, mutes and solos are heard at once; without it, playback falls back
   to a rendered WAV. Exports and listening copies still use FFmpeg/libopenmpt, so the two engines can
   differ slightly. What remains: shipping libxmp in more builds, and checking the engines against each
   other and on real audio hardware beyond Windows.
2. **Browser editing session.** A local web page that joins the same live session as the
   window, so the owner can edit and compose with their agent from a browser, without the Qt
   application. It needs a safe way for the page to obtain the session token: today the live
   server deliberately refuses browser requests so that other websites cannot change a song.
3. **Publishing.** Upload the package to PyPI and attach the Windows build to a GitHub release. Both
   are owner actions: the repository only prepares them.
4. **Wider MOD import.** Accept `E6x` pattern loops and `EEx` pattern delays in the playback plan, then
   other four-channel signatures, with explicit and reversible conversions. Six of the fifteen
   reference modules currently pass the editing profile.
5. **Linux desktop listening.** CI now runs the window offscreen on Linux; a session on a real Linux
   desktop with audio output remains to be done.
6. **XM**, with its own validation profile, after the MOD workflow is stable.
7. **Sample creation**: songs made only with created samples exist as an owner-requested mode
   (`synth` commands, tuned waves, a starter palette and loudness matching to the owner's library). Interactive
   waveform drawing in the window remains deferred, and library samples stay the default.
8. **Local phrase model** (see the October study in the history folder), only if the agent with
   references proves insufficient.
