# Changelog

## 0.7.0 — 2026-10-27

This release groups what was first planned as four releases (0.7 to 1.0). See the [roadmap](docs/ROADMAP.md).

**For agents**

- Add project schema `tracker4agents.project.v2`: PCM stored as base64 with a verified SHA-256, and patterns written as readable grid `rows` (`"00": "C-2 04 F06 | A-1 06 F7D | --- -- ... | A-2 08 E01"`). Files are written compactly, one line per sample and row. Version 1 files and the sparse `events` layout still load. Voltage Odyssey V2 goes from 690 KB to 117 KB and Pixel Rush from 192 KB to 34 KB. `chiploom migrate` rewrites a project or MOD as v2 and refuses to write if the exported MOD would change.
- Add `patch`: batch edit operations (`set`, `write`, `clear`, `copy`, `move`, `transpose`, pattern and order operations, `timing`, `sample`, `library_sample`) applied as one validated, all-or-nothing transaction, with a readable `changes` summary. Add `inspect --pattern N --grid [--row R --rows K]`.
- Add a structured error contract: failures on stderr carry a stable `code`, an English `message` and, for translated core diagnostics, the original French `message_fr`. `validate --report` entries gain `code` and grid-aware paths. The codes are listed in the CLI reference.
- Add live sessions (`chiploom live ...`, `live serve` for a headless session): a localhost-only server with a token, an author-aware change journal, `--base` conflict refusal (`LIVE_CONFLICT` with the contested cells; the owner's edits win), proposals the owner accepts or rejects, announced versions (takes), and requests to play, stop, select and open. The agent cannot act as `human`.
- Add the musical quality loop: `report` (measurements of the played score, with an estimated key labelled as an estimate), `compare` (a blind A/B page; a casual test with the answer key in `comparison.json` and without loudness matching) and `feedback` (listening notes stored in the project).
- Add `chiploom mcp`, a Model Context Protocol adapter over standard input and output with 29 tools that run the matching CLI commands. It is covered by automated tests; it has not been tested with specific MCP clients, and agents with a terminal can keep using the CLI.
- Update the agent guide, CLI reference, architecture note and ChipLoom skill (with new patch and live references) for all of the above.

**In the window**

- Add keyboard note entry: Edit mode (Ctrl+E), Step, Octave (F1–F3 or numpad +/−) and an Auto/QWERTY/AZERTY keyboard setting (Auto picks AZERTY for French input). Hexadecimal entry fills the sample and effect columns; Delete clears a cell and Backspace clears it and moves up.
- Add block selection and editing: Ctrl+C/X/V with the clipboard in the same grid text the agent prints, Alt+arrows to move a block, Ctrl+↑/↓ to transpose by a semitone and Ctrl+Shift+↑/↓ by an octave.
- Add an order editor: Insert, New, Duplicate, Remove, ↑/↓ and Rename….
- Reload automatically when the file changes on disk: a clean window applies one undoable "Agent changes" step; unsaved local edits are merged three ways, with conflicts listed in the status bar and the file's version kept. Changed cells flash. F5 still reloads by hand.
- Add live collaboration (Agent menu, on by default, with a status-bar indicator). Agent edits appear at once, highlighted and undoable with Ctrl+Z. A bottom Agent tab shows proposals (preview overlay, Accept with Ctrl+Enter, Reject, Listen to proposal, Clear preview, and a conflict dialog that asks whether to accept anyway) and takes (Open take).
- Play in real time through libxmp when it is available, so edits, mutes and solos are heard without re-rendering. Exports and listening copies still render with FFmpeg/libopenmpt, so small differences are possible. Without libxmp the window falls back to rendered playback.

**Distribution and project**

- Add `python tools/build_windows.py [--zip]` for a standalone Windows folder with `ChipLoom.exe` (window) and `chiploom-cli.exe` (command line). FFmpeg is not bundled. Prepare the package for PyPI; it is not yet published.
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
