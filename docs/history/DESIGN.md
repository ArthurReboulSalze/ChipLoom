# ChipLoom design

*This is an English translation of the original October 2026 design notes, which were written in French. It is kept as a historical record.*

October 15, 2026 — Version 0.4.0: ChipLoom name, agent documentation, standalone HTML export and reference study. The Linux window remains to be validated.

The prototype gives an agent a short path from a structured score to a standalone MOD file. The agent works on notes, effects and sample recipes; the exporter builds the binary; existing players then render that file. The score and the PCM do not depend on a model provider.

## Decisions made

**Python core with no package dependencies.** Python makes it possible to inspect and modify the data, while relying on native players for audio. The agent uses the model, JSON and the command line without a window or Qt. Music processing does not depend on the graphical toolkit.

**Window for the human, optional.** Qt Widgets / PySide6 provides the library, patterns, samples, transport and touch-ups. This interface contains no parallel music engine: its operations go through the same independent `Document` as those of a Python agent. The agent can also keep writing a JSON project directly and then run validation and export. F5 reloads the shared file, protecting unsaved local edits. No mouse control is needed for the agent.

**JSON score independent of the binary.** `tracker4agents.project.v1` keeps the title, the target profile, the samples, the patterns, the order list and the metadata. Each pattern contains a list of non-empty cells identified by their row and channel. The representation keeps effect commands, including commands placed without a new note.

**Strict MOD export.** The first target is `M.K.`, four channels and 31 sample slots. Length limits, note periods and loops are checked before writing. Texts that are too long, unexpected periods and functions outside the profile lead to an explicit refusal. The internal reader is used to check the structure and to re-import files of the same profile; it does not claim to cover the historical variants.

**Sounds computed and then embedded in the MOD.** Drawn waves are generated from amplitude points. The percussion and the lead use oscillators, noise and computed envelopes. The tool centers and quantizes the values to 8-bit PCM. Sounds without a loop start with two null bytes and end with a short fade-out. Sustained waves have a loop aligned on two bytes.

**External, bounded playback.** The main engine is libopenmpt, exposed through FFmpeg. The second is libxmp 4.7.3, built locally from a verified archive. Libxmp uses its ProTracker personality and its A500 mixer; the active state is read back from the engine to check that these settings are in effect. The native worker is isolated in a subprocess. Both renders use the exported MOD as input.

**Optional MP3.** The MOD file remains the main result. The MP3 is a listening copy made from the WAV rendered from that MOD, encoded with libmp3lame. It replaces none of the composition data.

## Code layout

| File | Responsibility |
| --- | --- |
| `tracker4agents/model.py` | Musical objects, periods, constraints and timeline. |
| `tracker4agents/synth.py` | Deterministic sample recipes and quantization. |
| `tracker4agents/project.py` | JSON reading/writing, schema checks and atomic writes. |
| `tracker4agents/mod.py` | Encoding and decoding of the M.K. binary profile. |
| `tracker4agents/demo.py` | Original score and sound palette of First Light. |
| `tracker4agents/audio.py` | Renders, MP3 copy and PCM measurements. |
| `tracker4agents/_xmp_worker.py` | Native libxmp calls and playback trace. |
| `tracker4agents/review.py` | Generation of the local listening and inspection page. |
| `tracker4agents/preview.py` | Complete HTML bundle from an existing project or MOD, with relative links and publication after a successful render. |
| `tracker4agents/references.py` | Read-only structural analysis of MOD and ZIP files, separate from the strict import. |
| `tracker4agents/cli.py` | Commands usable by an agent and JSON responses. |
| `tracker4agents/document.py` | Validated musical transactions, undo/redo, saving and export. No Qt dependency. |
| `tracker4agents/desktop_services.py` | Local session, recent files and render cache. No Qt dependency. |
| `tracker4agents/desktop.py` | Qt window for the human and WAV playback through Qt Multimedia. |
| `tracker4agents/level_meter.py` | RMS/peak measurement of the decoded PCM and Qt stereo level meter. |
| `tracker4agents/themes.py` | Four palettes and styles shared by controls, patterns and waveforms. |
| `tracker4agents/i18n.py` | English/French texts and translation of common core diagnostics for the window. |
| `tools/setup_reference.py` | Reproducible setup of the second player. |

## First musical trial

First Light uses four channels: percussion, bass, arpeggios and melody. The eight samples include single percussion hits, kick/hi-hat and snare/hi-hat combinations so they fit on one channel, two looped drawn waves and a lead with a built-in envelope.

The Am–F–C–G progression repeats over four sections with melodic and rhythmic variations. The arpeggios use the tracker commands `037` and `047`. Volumes and vibrato are also written in the patterns. The last row returns to the first order with `B00`.

At speed 6 and 125 BPM in CIA timing, a row lasts 0.12 seconds. The four 64-row patterns therefore form a loop of 30.72 seconds. The saved score and the binary make it possible to reproduce this trial.

The example sources stay separate from the outputs. An agent can edit `examples/first_light.project.json`, then export a new variant to another file with the `export` and `render` commands.

## Verification and scope of the results

The exporter is checked against a small separately assembled binary fixture, against the format limits and against incorrect inputs. The demo passes an exact binary round trip as well as a reconstruction from the saved JSON project.

Both players render a full loop, with no saturated PCM sample and no prolonged silence detected. The libxmp trace confirms the order, row, speed, tempo and time of each row. The tests also check two consecutive loops and a separate fixture with a speed change, a tempo change and a `D10` jump.

The fingerprints, parameters and results are recorded in `exports/first_light/validation.json`. Renders from different players can vary because of mixing, filtering and resampling; their numerical equality is not a success criterion.

Compatibility with third-party modules and comparative listening to references remain to be evaluated. Artistic quality is judged by ear. No model training is included in this prototype.

## Window and playback

Opening accepts MOD files of the strict profile and existing JSON projects. An invalid open keeps the current document. Notes, samples and effects are editable; an operation is applied to a copy, fully validated, then added to a history of 50 operations. An error changes no note. The JSON keeps the sample recipes; a MOD import keeps the PCM without inventing its origin.

Listening renders the MOD in a worker and then loads the WAV into `QMediaPlayer`. Computations and subprocesses do not block the window's event loop. A fingerprint of the binary, the mix and the version serves as the cache key. Each preparation has an identifier; a result that became obsolete after another open or an edit does not replace the current listening. The audio helpers do not open consoles on Windows.

The mute/solo mode uses a copy of the document, keeps the speed and jump effects, then renders the corresponding mix. It does not modify the saved data. WAV/MP3 exports follow this mix; MOD export keeps the whole song. The audio loop returns to the resume time computed in the module so it does not systematically replay the introduction. Sample previews take volume and fine tuning into account, without claiming to reproduce the Paula filtering.

Each channel has a large clickable button above its columns and a Solo button. A muted channel carries the MUTED label and its notes are dimmed. Successive clicks during audio preparation keep the playback intent and the resume time; only the last requested mix is loaded. Mute keeps the short preparation tied to the WAV render.

The level meter receives the 16-bit stereo PCM decoded by Qt with `QAudioBufferOutput`, for the song as well as for sample previews. It measures RMS and peaks, applies the main volume and shows two bars with a gradual decay and a value in dBFS. Stopping and seeking clear the old measurements. It is a loudness indicator, with no frequency analysis. This buffer output requires Qt's FFmpeg multimedia backend, used in the Windows trials. [Official QAudioBufferOutput API](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QAudioBufferOutput.html).

The Midnight, Amber, Violet and Light palettes also apply to the patterns, the channel controls and the waveform. The text catalog uses English by default and offers French; Qt dialogs use their French translation. Changing the language preserves the document, the history and any values still being typed. The musical data is not translated, and the technical details of an external tool may keep their original language. Theme and language are saved in the local session as soon as they are selected. These features remain specific to the window and impose no graphical dependency on the agent.

This strategy reuses the already validated player and keeps the prototype simple. It requires a preparation after each change and can cause a small gap when the loop restarts. Direct access to the player for real-time mixing will be needed for instant musical editing.

The core paths use `pathlib`. Qt chooses the user data folder, and the render commands do not use Windows audio APIs. The Windows and Linux launchers are separate. The PySide6 dependency belongs to the `desktop` option, not to the core. The Ubuntu CI validates the core installation, its tests, FFmpeg renders and the generation of a MOD. The Linux window, its Qt system dependencies and physical audio output remain to be validated.

## Proposed next options

| Priority | Option | Benefit |
| --- | --- | --- |
| 1 | Selection of 1, 2 or 4 bars, short variants and A/B comparison | Quickly adjust the length and rhythm of the variations based on your feedback on Pixel Rush. |
| 2 | Interactive sample drawing, loop point editing and pulse variants | Touch up the same numerical recipes as the agent with visual and audio feedback. |
| 3 | Copy/paste of blocks, duplicating patterns and reordering the song | Build the arrangement from the window. |
| 4 | Block editing commands and MCP integration | Give the agent precise, validatable and undoable transactions without a graphical interface. |
| 5 | Direct playback and real-time mixing | Make changes, solo and loops immediately audible. |
| 6 | Standalone packages for Windows, then Linux | Distribute the tool without requiring a manual Python installation. |

## Core extensions

The public name becomes **ChipLoom**, while the Python package, the JSON schema and the session folder identity remain `tracker4agents`. The main guide is now the English README, complemented by `docs/USER_GUIDE.md`, `docs/AGENT_GUIDE.md` and `docs/CLI.md`. The tool suits an agent with terminal commands and file access, such as Codex or Hermes; no model or MCP server is integrated. The boundary of the future MCP adapter is detailed in `docs/ARCHITECTURE.md`.

The window and the HTML export both remain available. The `preview` command accepts a project or a compatible MOD, builds the folder in a local temporary area and then publishes it after the render succeeds. The bundle files use relative links. The preview is a listening and inspection view; it does not add a second editor.

The new analysis covers 15 references, including two with two channels. Six pass the strict import; the other nine remain accessible through the separate analysis. The aggregated reports are kept in `references`, without PCM or complete melodies. The restart variants and the E6x/EFx effects encountered must be the subject of a future conscious extension of the profile, with no silent normalization.

The document now has validated operations with undo. They remain to be exposed as structured block commands and through MCP. The analysis of your references exists in `references/ANALYSIS.md`; style profiles and examples the agent can consult could extend it.

The window reuses this musical model. The XM and IT formats will need their own capabilities and compatibility profiles, rather than an implicit conversion of the MOD model.

## Technical references

- [Module formats and effects in OpenMPT](https://wiki.openmpt.org/Manual:_Module_formats).
- [Effect reference](https://wiki.openmpt.org/Manual:_Effect_Reference).
- [OpenMPT MOD reader and exporter](https://github.com/OpenMPT/openmpt/blob/master/soundlib/Load_mod.cpp).
- [MOD structure and writing in ProTracker 2 clone](https://github.com/8bitbubsy/pt2-clone/blob/master/src/pt2_module_saver.c).
- [libopenmpt documentation and API limits](https://lib.openmpt.org/libopenmpt/faq/).
- [FFmpeg's libopenmpt demuxer](https://ffmpeg.org/ffmpeg-formats.html#libopenmpt).
- [libxmp 4.7.3 public API](https://github.com/libxmp/libxmp/blob/libxmp-4.7.3/include/xmp.h).
- [Cross-platform installation of Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html).
- [Loading and playback with QMediaPlayer](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html).

The code of this prototype does not embed any player source or binary in the Python package. The setup script downloads libxmp into `.tools`, with its original license notice and a manifest of fingerprints.
