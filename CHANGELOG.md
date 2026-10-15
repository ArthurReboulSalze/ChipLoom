# Changelog

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
