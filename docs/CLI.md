# ChipLoom command reference

Use `chiploom` after editable installation, or `python -m tracker4agents` from the checkout. The examples below use the module form to make the chosen interpreter explicit.

| Command | Input | Result |
| --- | --- | --- |
| `demo` | Built-in song and seed | Reproduces an original example, MOD and project; optional renders |
| `inspect` | Strict MOD or JSON | Structured summary; optional 64-row pattern |
| `validate` | Strict MOD or JSON | Validates profile and computes playback plan |
| `import` | Strict MOD | JSON with PCM; no inferred synthesis recipes |
| `export` | JSON project | Real self-contained MOD |
| `render` | Strict MOD | WAV from the actual MOD; optional MP3 |
| `preview` | Strict MOD or JSON | New portable HTML/media directory |
| `analyze` | Reference MOD or ZIP | Read-only aggregate report; broader than editable profile |
| `gui` | Optional MOD or JSON | Native human window, optional dependency required |

## Common commands

```sh
python -m tracker4agents --version
python -m tracker4agents demo --song first-light --output exports/first-light --no-audio
python -m tracker4agents demo --song pixel-rush --mp3
python -m tracker4agents inspect examples/pixel_rush.project.json --pattern 0
python -m tracker4agents validate examples/pixel_rush.project.json
python -m tracker4agents export examples/pixel_rush.project.json --output exports/custom.mod
python -m tracker4agents import exports/custom.mod --output exports/imported.project.json
python -m tracker4agents render exports/custom.mod --output exports/custom.wav --mp3-output exports/custom.mp3
python -m tracker4agents preview exports/custom.mod --output exports/custom-review --mp3 --language fr
python -m tracker4agents analyze path/to/modules.zip --output exports/study.json --probe
python -m tracker4agents gui examples/pixel_rush.project.json
```

`preview --output` is a **new directory**, not an HTML filename. It renders one complete supported cycle and creates `preview.html`, `module.mod`, `module.project.json`, `module.wav`, `validation.json`, sample WAVs, and optionally `module.mp3`. It publishes the directory only after successful completion. The HTML player loops from the module's computed restart time after the first pass.

`analyze --output` is a JSON filename. `--probe` adds ffprobe/libopenmpt duration estimates. Without that flag, analysis uses only the standard library. Per-file failures appear under `analysis_error`; successful entries remain in the report. A report with any failed file returns exit code 2. `editable_in_current_profile: false` is a compatibility fact, not an analysis failure. Archives are limited to 512 entries and 64 MiB expanded; each MOD is limited to 4 MiB.

`render` supports `--engine openmpt|xmp`, `--seconds` (greater than 0, at most 120), `--sample-rate` (8000–96000), `--ffmpeg` and `--xmp-library`. `preview` also accepts `--ffmpeg`. XMP requires the optional separately built reference library.

`gui --state-dir PATH` chooses a session/cache folder. `gui --no-restore` skips the previous file and uses a built-in example when no input is supplied. Language and theme are selected in the window and stored there.

## Response contract

Successful non-GUI operations emit JSON to stdout. Runtime, input and rendering failures emit `{"ok": false, "error": "...", "message": "..."}` to stderr with code 2. Normal argument-parser errors, help and version are text. Some core diagnostics retain their original French wording; scripts should use exit status and structured fields, not parse a translated sentence.

The analysis command returns a compact report location and count to stdout, with detailed per-file facts in its output JSON. Rendering validates the MOD before launching a decoder. Export validates before replacing its destination. Source and output must differ for import, export and analysis.

## Output ownership

Export, import, render and analysis may replace the explicitly requested output file after validation. Preview refuses an existing output directory. Demo output is reproducible generated content and may be refreshed in its designated directory. Always choose output paths separate from user-supplied references.

Generated files can contain the project's user-authored metadata and music. Review a bundle before publishing it. ChipLoom does not upload it automatically.
