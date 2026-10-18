# Changelog

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
