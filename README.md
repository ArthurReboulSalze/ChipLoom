# ChipLoom

**An agent-driven MOD tracker, with a desktop editor and portable HTML listening pages.**

ChipLoom gives agents such as **OpenAI Codex** and **Nous Research Hermes Agent** a concrete way to compose tracker music: write notes and effects, draw or synthesize samples, validate the score, export a real `.mod`, render it, and revise it from feedback. The human can inspect, listen and make edits in the native window, or open a generated HTML listening page.

The musical project is structured JSON. The exported MOD contains its samples and plays independently in a compatible tracker. WAV and MP3 are listening copies.

[Guide en français](docs/USAGE_FR.md) · [Agent workflow](docs/AGENT_GUIDE.md) · [CLI reference](docs/CLI.md) · [Reference studies](references/README.md) · [Architecture and MCP](docs/ARCHITECTURE.md)

## What this project is

- A Python music toolkit and CLI that an existing agent can use through file and terminal tools.
- An optional Qt desktop application for a human, with four-channel patterns, sample previews, cell editing, undo/redo, mute/solo, stereo level meter, four themes, and English/French UI. English is the default.
- An optional static HTML listening bundle, generated from an existing MOD or project. It needs neither Qt nor an agent to view.
- An early, strict four-channel ProTracker-style MOD editor. XM and IT are future work.

ChipLoom does **not** include an AI model, run an autonomous agent, train model weights, or currently provide an MCP server. Codex or Hermes supplies the planning and composition; ChipLoom supplies the musical data model and verifiable outputs. It is an independent project, without affiliation with OpenAI or Nous Research.

## Install

Python **3.12+** is required. The core uses only the Python standard library. Working from a cloned checkout is the supported setup.

```sh
git clone https://github.com/ArthurReboulSalze/ChipLoom.git
cd ChipLoom
python -m venv .venv
```

The repository is currently private; cloning requires access to it. On Linux, use `python3` to create the environment.

On Windows:

```powershell
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\chiploom.exe --help
```

On Linux:

```sh
.venv/bin/python -m pip install -e .
.venv/bin/chiploom --help
```

The Python package keeps its original name, `tracker4agents`, for compatibility. Every command can also be run as `python -m tracker4agents ...` with the chosen interpreter. Existing projects and desktop session folders keep working.

Audio playback, rendering and HTML bundles require **FFmpeg built with libopenmpt** on PATH. MP3 additionally requires **libmp3lame**. The optional reference duration probe uses `ffprobe` with libopenmpt. These executables are not bundled. Check availability with:

```sh
ffmpeg -demuxers
ffmpeg -encoders
```

Look for `libopenmpt` and `libmp3lame`, respectively. See [FFmpeg's official downloads](https://ffmpeg.org/download.html) and [libopenmpt demuxer documentation](https://ffmpeg.org/ffmpeg-formats.html#libopenmpt).

## First MOD in one command

The following examples use `python` from the configured environment. On Windows, substitute `.venv\Scripts\python.exe`; on Linux, `.venv/bin/python`.

```sh
python -m tracker4agents demo --song pixel-rush --no-audio
```

This builds the original Pixel Rush example and its samples without FFmpeg. The result includes `exports/pixel_rush/pixel_rush.mod` and its editable JSON project. The demo command reproduces a supplied composition; it does not ask an AI to compose a new one.

For audio and the optional MP3:

```sh
python -m tracker4agents demo --song pixel-rush --mp3
```

| Included original composition | Timing | Length | Samples | MOD size |
| --- | --- | --- | --- | --- |
| First Light | 125 BPM, speed 6 | 30.72 s | 8 | 17,206 bytes |
| Pixel Rush | 160 BPM, speed 6 | 48.00 s | 13 | 12,924 bytes |

Generated media is kept out of Git. Rebuild it from the recipes and source code.

## Two human listening options

### Native desktop

Windows: run **Install ChipLoom.cmd**, then **Launch ChipLoom.cmd**.

Or install the optional GUI explicitly:

```sh
python -m pip install -e ".[desktop]"
python -m tracker4agents gui examples/pixel_rush.project.json
```

Click **Track 1–4** to mute/unmute; use Solo to isolate channels. Double-click a pattern cell to edit it. F5 reloads changes made by the agent, with a guard for unsaved edits. Theme and language selectors are at the top right.

Playback uses a background MOD-to-WAV render. Edits and mute changes may need a short preparation; this is not yet a real-time tracker mixer. The meter measures decoded stereo RMS and peaks.

The window is verified on Windows. Linux launch support is prepared (`sh launch-chiploom.sh`), but Linux desktop/audio-device behavior still requires validation. The agent does not need PySide6, a display or an open window.

### Portable HTML page

```sh
python -m tracker4agents preview examples/pixel_rush.project.json --output exports/pixel-review --mp3
```

Open `exports/pixel-review/preview.html`. The bundle includes the MOD, JSON project, WAV, optional MP3, sample WAVs and a technical report. **Copy the whole directory when sharing**, not just the HTML file. This command expects a new output directory to preserve existing work.

Use `--language fr` for French page controls; English is the default. User-authored titles, names and descriptions keep their original language. The HTML view shows patterns and samples and lets you seek by clicking a row; editing remains in the JSON project or native window.

If a browser restricts local audio, serve only the output directory:

```sh
python tools/serve_previews.py --directory exports/pixel-review --port 8765
```

Open [localhost preview](http://127.0.0.1:8765/preview.html). The optional server binds to loopback and supports byte ranges for seeking. There is no remote hosting or background upload.

## Ask an agent to compose

Open this checkout in Codex, or give Hermes terminal and file access to the same checkout. Ask it to read `AGENTS.md` and `docs/AGENT_GUIDE.md`, then give a musical brief:

> Create an original 30–45 second four-channel chiptune at 150–165 BPM. Use newly synthesized samples, a short memorable motif, and variations every one or two bars. Save a new JSON project, validate it, export a MOD, and build an HTML listening bundle with an optional MP3. Preserve the reference modules and existing examples.

The [agent guide](docs/AGENT_GUIDE.md) includes the full inspect → edit → validate → export → render workflow, a Python editing example and instructions for both agents.

## Study reference modules

```sh
python -m tracker4agents analyze path/to/selection.zip --output references/local-study.json --probe
```

The analyzer reads a MOD or MOD files inside a ZIP without extracting archive paths. It reports arrangement, sample sizes/loops, effect families, channel activity and related patterns. It can study certain variants that the editor refuses; the report explicitly records that distinction.

The first selection study covers **15 files: 13 four-channel and 2 two-channel modules**. Six pass the current strict editing profile. Structural reports and observations are included; original third-party modules, their samples and audio renders are not. [Read the findings](references/SELECTION_FR.md).

## Compatibility and current limits

Editing/export targets `M.K.`, four channels, 64 rows per pattern, 1–64 patterns, 1–128 orders, 31 sample slots, and signed 8-bit mono PCM. The strict profile deliberately rejects some valid historical variants, including other signatures, restart-byte variants and several effects. This is not a general MOD converter.

Rendering is limited to 120 seconds per request. Pattern loop `E6x`, pattern delay `EEx` and destructive `EFx` are outside the current editing profile. Interactive sample drawing, arrangement/block editing, real-time mixing, MCP, XM and IT remain planned. See the [detailed format profile](docs/USAGE_FR.md#profil-mod-pris-en-charge) and [roadmap](PLAN_PROJET.md).

## Verification and development

```sh
python -m unittest discover -s tests -v
```

The suite covers MOD binary round trips, malformed inputs, synthesis, editing/undo, audio backends, portable HTML assets, reference archives and optional Qt integration. Qt/audio tests are skipped when their dependencies are absent. The CI matrix exercises the core on Windows and Linux; it does not validate a physical audio device or the Linux desktop.

For an independent second decoder, `python tools/setup_reference.py` downloads and verifies pinned libxmp 4.7.3 sources, then builds locally with CMake and a C compiler. `demo --with-xmp --mp3` checks a rendered cycle against its timing trace. No external replay-engine binaries are committed.

## License

Original project code and documentation are MIT licensed: see [LICENSE](LICENSE). Third-party reference modules remain the property of their respective rights holders and are not included or relicensed. External tools and libraries retain their own licenses; see [third-party notes](docs/THIRD_PARTY.md).
