# ChipLoom user guide

ChipLoom is a tracker toolkit that an agent can use, plus a working window for the human. The project keeps the JSON score, the sample recipes and the standalone MOD export. Four-channel MOD is the first supported format; the 0.8 work adds more MOD channel counts and a first XM profile (see [Supported formats and limits](#supported-formats-and-limits)).

The program is called **ChipLoom**. The Python package keeps the name `tracker4agents` so that commands, projects and sessions keep working. The launchers are `Install ChipLoom.cmd` and `Launch ChipLoom.cmd` on Windows and `launch-chiploom.sh` on Linux. The old French-named launchers (`Lancer tracker4agents.cmd`, `Installer interface Windows.cmd`, `lancer-tracker4agents.sh`) were removed in 0.7.0.

ChipLoom is designed to be used by an agent such as **Codex** or **Hermes Agent**: the agent composes and revises, the software validates and produces a real MOD. The window is for the human; the agent works through JSON, Python and the command line. No model is embedded and no training is done. An optional MCP adapter (`chiploom mcp`) wraps the command line; it is covered by automated tests and a smoke run with the official Python MCP SDK, but has not been tried in a model-driven session with an application, and an agent with a terminal can do without it. The [agent guide](AGENT_GUIDE.md) explains the workflow; [MCP.md](MCP.md) describes the adapter.

## Listen to the examples and compose with Hermes

**[Listen to Pixel Rush and Voltage Odyssey V2](https://arthurreboulsalze.github.io/ChipLoom/)**: two MP3 players with the MODs and editable projects to download. The songs and their samples were created for ChipLoom.

A user test with **Hermes / glm-5.3-flash on Debian 13** produced two original compositions. The [documented feedback](HERMES_FEEDBACK.md) keeps that result apart from CI and from the Linux window, which remains to be validated.

Since version 0.5.0 you can plan the duration, group errors and listen to an excerpt:

```sh
python -m tracker4agents estimate --orders 8 --speed 6 --bpm 128
python -m tracker4agents validate examples/pixel_rush.project.json --report
python -m tracker4agents render docs/listen/media/voltage_odyssey_v2.mod --from-order 6 --seconds 10 --output exports/drop.wav
```

At constant speed, duration = rows × speed × 2.5 / BPM: eight orders of 64 rows at speed 6 and 128 BPM make one minute. `validate` accounts for real changes and jumps. Beyond 120 seconds it emits a warning without invalidating the MOD. The report gathers the independent errors, with a first error per field, sample or event, and the collisions; dependent errors may need a new validation after the fix.

`--from-order` counts orders from zero. The pre-roll keeps the instruments and effects that were active before the excerpt; the cut follows the theoretical time, with small differences possible depending on the engine. Limits: 600 seconds of pre-roll and 120 seconds of excerpt.

## Install and launch

### Windows

Install Python 3.12 or newer, then run **`Install ChipLoom.cmd`** and **`Launch ChipLoom.cmd`**.

A ready-made standalone folder is attached to each [GitHub release](https://github.com/ArthurReboulSalze/ChipLoom/releases) as `ChipLoom-<version>-windows.zip`. It can also be built with `python tools/build_standalone.py` (add `--archive` for the zip) after installing `.[desktop]` and PyInstaller. The result, `build/windows/ChipLoom/`, contains `ChipLoom.exe` (the window) and `chiploom-cli.exe` (the command line, named differently because Windows ignores case in file names). FFmpeg is not included; libxmp is, if the library was built beforehand. The package is prepared for PyPI but not yet published.

To start the window from a configured environment:

```powershell
.venv\Scripts\python.exe -m tracker4agents gui
.venv\Scripts\python.exe -m tracker4agents gui exports/pixel_rush/pixel_rush.mod
```

### Linux

The code is prepared for Linux with `pathlib`, Qt data folders and the same widgets and services. Prepare an install with `python3 -m venv .venv`, then `.venv/bin/python -m pip install -e '.[desktop]'`, and start it with `sh launch-chiploom.sh`. FFmpeg with libopenmpt and the Qt system dependencies must be present. **The core and the FFmpeg renders are verified by the Ubuntu CI; the Linux window and its physical audio output remain to be validated.** The system requirements are described in the [official Qt for Python documentation](https://doc.qt.io/qtforpython-6/gettingstarted.html).

Each [GitHub release](https://github.com/ArthurReboulSalze/ChipLoom/releases) also has a standalone build, `ChipLoom-<version>-linux-x86_64.tar.gz`, that needs no Python: extract it and run `./ChipLoom` (the window) or `./chiploom-cli` (the command line). It is built on Ubuntu 22.04, so it needs glibc 2.35 or newer (Debian 12, Ubuntu 22.04 and later). FFmpeg with libopenmpt is not bundled (`sudo apt install ffmpeg`); if the window does not start, install `libxcb-cursor0`. libxmp is bundled for real-time playback. `python tools/build_standalone.py --archive` builds the same archive on a Linux machine.

### Requirements for audio

Python 3.12 or newer is required. The core uses only the Python standard library. The main render and the MP3 need an FFmpeg with libopenmpt and libmp3lame respectively, on the PATH. The window adds only the optional `desktop` dependency (PySide6).

**The window is optional for the agent.** The core, the document model, the recipes, import/export and the structured commands work without PySide6, without a screen and without an open application. The agent edits the same project as the human through the JSON, `patch`, the Python API or a live session; the window reloads or shows the change at once. The agent never needs to drive the interface with a mouse. The MCP adapter (`chiploom mcp`) is optional.

## The window

The window is a **Qt Widgets / PySide6** application, with no HTML page. It lets you:

- find **First Light**, **Pixel Rush** and recent files; open a MOD or a JSON project, including by drag and drop;
- listen, pause, move the playback position in the song or to a pattern row, and follow the four channels; the loop respects the module's restart position;
- mute or unmute a channel by clicking its large **Track 1-4** button above the pattern, or hear it alone with **Solo**; inaudible channels are dimmed, without changing the score. `Ctrl`+click on any **Track** or **Solo** button clears every mute and solo at once, so all channels are heard again;
- follow the sound level on an **animated stereo meter**, which measures the average level and the peaks of the audio being played, also while a sample is being auditioned;
- choose among four themes (**Midnight**, **Amber**, **Violet**, **Light**) and switch between **English** and **Français** with the menus at the top right; English is the default;
- show the samples and their loops, listen to them separately, and edit, create and level them in the [sound workshop](#sound-workshop);
- hear sounds from the piano keys ([keyboard audition](#keyboard-audition)) and let a tablet or second screen edit with you ([open in a browser](#open-in-a-browser));
- edit notes, sample numbers and effects by double-click, from the keyboard (see below) or by blocks, and transpose a pattern channel;
- edit the order list and follow the changes made by the agent, live or through the file;
- set the title, the starting tempo and speed, undo/redo and save the project;
- export the **MOD**, a WAV or an optional MP3. Audio export uses the currently audible channels; the MOD keeps all channels.

The Smp and Effect columns and the row and order numbers are in hexadecimal. Transposition applies to the whole channel of the displayed pattern, including its other occurrences in the order list. Effects are edited directly in the table. The song settings, the WAV/MP3 exports and the meter are at the top of the window: the tracker takes the full width to the right of the library. Drag the divider between the library and the tracker all the way to the left to hide the library; drag it back from the left edge to show it again. Over the pattern, `Ctrl` + mouse wheel widens or narrows the track columns, to see fewer or more channels at once (the grid point under the pointer stays in place and the **Mute**/**Solo** strip follows); the plain wheel still scrolls the rows. The tempo setting refuses to erase other effects if two columns are not free on the first row.

`Ctrl+S` saves an already open JSON project; for a MOD it offers a new JSON project. `Ctrl+Shift+S` saves under another name. `Ctrl+Z` undoes, `Ctrl+Shift+Z` redoes (`Ctrl+Y` also works) and Space starts and stops playback when the pattern table has focus. **F5** reloads the file, for example after a change by the agent. A confirmation protects unsaved edits when you change file or close the window.

### Playback

When libxmp is available, the window plays the song **in real time**: edits, channel mutes and solos are heard at once, with no new render. Exports and listening copies are still rendered by FFmpeg/libopenmpt; small differences between the two engines are possible. libxmp is set to libopenmpt's level for the module's format and channel count, so switching engines does not change the volume. **Playback → Real-time playback** turns the engine on or off.

Without libxmp, the window falls back to rendered playback: the real MOD is rendered to WAV in the background and played by Qt, with a cache, and an edit needs a short preparation before the next listen. On Windows, `python tools/setup_reference.py` builds the pinned libxmp; on Linux, the `libxmp4` package works. Rendered audio cycles remain limited to 120 seconds.

Real-time audio runs in its own thread, so moving the window or opening a dialog no longer cuts the sound. **Playback → Audio buffer** sets the latency (Low · 80 ms, Normal · 150 ms, High · 300 ms, Very high · 600 ms; 150 ms by default). A shorter buffer lets you hear an edit sooner; a longer one gives more margin on a busy machine. The setting is applied without stopping playback and is remembered.

### Session, themes and languages

The session and the cache stay in the local data folder chosen by Qt (`AppData/Local/tracker4agents/tracker4agents` on Windows). The window remembers the last file, recent files, volume, follow and loop options, theme, language, the sample library folder, whether the library panel is hidden and the zoom of the track columns. Theme and language apply immediately, without interrupting playback or clearing an entry in progress. Titles and sample names keep their original text. `--state-dir` selects another folder.

### Keyboard entry, blocks and orders

- **Note entry:** turn on **Edit mode** (`Ctrl+E`), then play the piano keys. The lower row starts at the base octave, the upper row one octave higher. **Octave** is set with `F1` to `F3` or the numeric keypad `+`/`-`; **Step** sets how many rows the cursor advances after each entry. The **Keyboard** setting offers Auto, QWERTY and AZERTY; Auto chooses AZERTY when the input language is French.
- QWERTY keys: lower row `Z S X D C V G B H N J M , L . ; /`, upper row `Q 2 W 3 E R 5 T 6 Y 7 U I 9 O 0 P`. AZERTY keys: lower row `W S X D C V G B H N J , ; L : M !`, upper row `A é Z " E R ( T - Y è U I ç O à P`.
- In the Smp and Effect columns, hexadecimal digits are typed directly (on AZERTY the digit row without Shift is accepted). `Delete` clears the cell; `Backspace` clears it and moves up one row.
- **Blocks:** `Ctrl+C`, `Ctrl+X` and `Ctrl+V` copy, cut and paste. The clipboard holds the same grid text that the agent sees (`inspect --grid`), so you can paste what the agent wrote. `Alt` + arrows moves the block; `Ctrl+Up`/`Ctrl+Down` transposes it by a semitone and `Ctrl+Shift+Up`/`Ctrl+Shift+Down` by an octave.
- **Drag and drop:** press on a selected block and drag it. A drop indicator shows where it will land and the block moves when you release the button; hold `Ctrl` to copy it instead (the indicator then reads "+ Copy"). Near the top or bottom edge the pattern scrolls. A short press without dragging stays an ordinary click. Like every edit, a drop is one undoable step.
- **Order editor:** **Insert**, **New**, **Duplicate**, **Remove**, up/down arrows to move, and **Rename…** for the current pattern. A song always keeps at least one order; removing the last order that uses a pattern also removes that pattern.

### Automatic reload and merge

When the open file changes on disk (for example after a `patch` command by the agent), the window reloads it by itself. With no unsaved local edits, the reload forms a single undoable step, "Agent changes". If there are local edits, the window performs a three-way merge: conflicting cells are listed in the status bar and the file's version is kept. Changed cells flash. **F5** always reloads on demand.

### Sample library in the window

The bottom area offers **Song samples**, **Sample library**, and the **Create**, **Instruments** and **Agent** tabs (see below). The tracker keeps its full width; the horizontal splitter adjusts the height of the two areas.

1. In **Sample library**, click **Folder…** to choose a bank that contains `library.json`. From this repository, `exports/sample_library` is detected by default. **Refresh** reloads additions and tags changed by the agent.
2. Search for a name, an ID or a tag, and filter by type or role. **MOD compatible** shows the entries that can be used immediately. Roles remain suggestions, to be confirmed by listening.
3. Select a sample to see its waveform and settings. **Listen** or a double-click starts an audition at the chosen note; **Stop** ends it. The meter at the top follows this audition too. Song playback pauses while you listen.
4. Keep **New / free slot**, then click **Add to song**. The PCM and its settings are embedded in the project; the notes of the score are not changed. For an occupied slot, choose it and explicitly check **Replace**. If all 31 slots are filled, that choice becomes necessary.
5. **Ctrl+Z** undoes the addition or replacement; redo is available. Save the project or export the MOD to keep the change.

For the few entries that need an adaptation, uncheck the compatibility filter and select the sample. **Adapt copy** allows the limited preparation described in the [CLI contract](CLI.md#local-sample-library); the bank original is kept. Other incompatibilities block the addition. A missing library leaves the song open and editable; the **Folder…** button lets you find it again.

The project JSON and the MOD are standalone after insertion. The library and the audio caches stay local. By default, composition uses only samples from the bank. On request, a song can be made only from created samples (see [Songs made only with created samples](#songs-made-only-with-created-samples)).

### Live collaboration with the agent

The **Agent** menu contains **Live collaboration**, on by default; a status-bar indicator shows *Live: off*, *Live: listening* or *Live: agent connected*. The agent finds the window with `chiploom live`.

- The agent's edits appear at once, highlighted, and are undone with `Ctrl+Z` like yours.
- The agent sees your edits. If it would overwrite one, its edit is refused (`LIVE_CONFLICT`): it re-reads and adapts. Your edits win.
- For a broader rewrite ("redo the bass"), the agent can send a **proposal**. The bottom **Agent** tab shows it as a violet overlay. **Listen to proposal**, then **Accept** (`Ctrl+Enter`) or **Reject**; **Clear preview** removes the overlay. If the song changed in the meantime, a conflict dialog lists the cells and asks whether to accept anyway and overwrite them.
- Versions announced by the agent (`take`) appear in the same tab; **Open take** loads one.
- The agent can ask the window to play, stop, seek, select a passage or open a file. Opening first asks you what to do with unsaved changes.

**Comparing a take with the current song.** In the Agent tab, select a take and press **Compare with current** (or choose Agent → *Compare a take with the current song*, `Ctrl+B`). The window plays the take first (B). Each further press switches between the take (B) and the current song (A) at the same position in the song. The label under the take list shows what you are hearing, and **End comparison** returns to the current song. Only what is played is swapped: your document, its undo history and the change journal are never touched. If you edit the current song while hearing the take, the window switches back to A so that you hear your edit.

**Comments.** To tell your agent exactly where something is wrong, select a cell or a block in the grid and press `Ctrl+M` (or right-click → *Comment on the selection…*, or Agent → *Comment on the selection…*), then type your remark. Agent → *Comment on the whole song…* (also in the grid's right-click menu) writes a remark without a place. Cells covered by an open comment carry a small corner triangle in the theme's accent colour, and hovering one shows the comment. The Agent tab's **Comments** column lists open comments first, with their author, time, place (for example `Pattern 01 · rows 00-1F · channels 4-5`, rows in hexadecimal as in the grid) and replies; the header shows how many are open. **Go to** (or a double-click) shows the pattern and selects the block, **Reply** answers, **Resolve** closes a comment, and **Show resolved** also lists the resolved ones with **Reopen**. The list and the markers update by themselves when your agent comments, replies or resolves, and the status line names it. Comments are saved with the project and make it unsaved like an edit (they are not part of the undo history), and they also work with live collaboration switched off. See [Comments in the CLI reference](CLI.md#comments) for how the agent reads them.

Without a window, `chiploom live serve SONG.json` hosts the same session headless. The server listens only on the local machine (loopback) and requires a token that only the command line reads. See the [CLI reference](CLI.md#live-sessions) and the [agent guide](AGENT_GUIDE.md#composing-with-the-owner-in-the-window-live).

### Sound workshop

The sound workshop shapes the samples of the open song without leaving the window. It has three parts: the **sample editor** and the **Levels** view in the **Song samples** tab, the **Create** tab and the **Instruments** tab. Every change goes through the same validated operations as the command line ([patch operations](CLI.md#sample-edits-patch-operations)), so each one is a **single undoable step** (`Ctrl+Z`), and nothing touches the song until you press **Apply** or **Add to song**.

The agent's default policy is unchanged: unless you ask for sound editing or for a song made only of created samples, the agent composes from library samples as they are. These tools are for you.

#### The sample editor

Select a sample in the **Song samples** list; the editor sits to its right (the **Edit** and **Levels** buttons under the list switch between the two pages). It shows:

- **The waveform** of the sample, with the loop as a shaded band between two amber handles. Drag a handle to move the loop start or end. Drag in an empty part of the waveform to select a range (the trim selection); double-click to clear it. Positions are bytes of the sample and always even.
- **Numeric fields** for the same things, each with its own **Preview** and **Apply** buttons: **Loop** (start and length in bytes; length 0 means no loop), **Trim** (from and to), **Gain** (in dB, with the clean headroom shown beside it) and **Fade** (bytes faded in at the start and out at the end). Under the waveform, **Loop = selection** turns the selected range into the loop, **No loop** removes it and **Whole sample** clears the selection.
- **Volume** and **fine tune**, with **Play sample** and **Apply**, as before.

**Preview or Apply.** **Preview** builds the edited copy in memory, draws it over the waveform in the warning colour, plays it from C-2 and prints what would change (for example the bytes kept, the peak before and after a gain, or the jump at the loop seam). The song is not touched, and song playback pauses while the copy plays. Changing any field cancels the preview. **Apply** makes the change for real, as one undoable patch.

**Refusals and choices.** The editor does not silently change a sound. When the core refuses an edit, you get a sentence saying why, nothing is changed, and where the [CLI](CLI.md#sample-edits-patch-operations) has an explicit option for it, a question offers that option:

| Refusal | What it means | The choice offered |
| --- | --- | --- |
| `SAMPLE_CLIP` | The gain would push loud bytes past the 8-bit limit (the message gives the largest clean gain) | Apply anyway and flatten the loudest bytes (`allow_clip`) |
| `SAMPLE_LOOP`, trim | The kept range cuts into the loop | Keep only the part of the loop inside the range (`adjust_loop`) |
| `SAMPLE_LOOP`, fade | A fade reaches into the loop, so every repeat would dip | Fade inside the loop anyway (`allow_loop`) |
| `SAMPLE_LOOP`, no loop | A sample without a loop must start with two silent bytes (the replayer's no-loop marker) | Add two zero bytes in front; the sound itself stays the same (`adapt`) |
| `SAMPLE_SOURCE` | The song only allows samples from its declared source (library or synthesized), so this edit is not allowed | None: change the recipe, use **Match**, or edit in a song that allows it |

Editing a library sample in a library song is shaping and is allowed; its library ID stays on record. Edited samples keep a record of their edits in the project (`metadata.sample_sources`).

#### Levels

**Levels** (under the sample list) compares how loud each sample is with the target for its role (kick, snare, hat, bass, lead, chord or texture). The role is the one recorded in the project, otherwise inferred from the sound; roles remain suggestions. Targets come from the sample bank selected in the **Sample library** tab when there is one, otherwise from built-in reference levels, and the line above the table says which. The table shows slot, sample, role, level, target and difference; a difference of more than 6 dB is flagged with `!`.

**Match** sets one sample's volume to its target, and **Match all** does every sample, each as one undoable step. If volume 64 cannot reach the target, clean gain is added to the PCM without clipping. A sample made from a recipe stays a recipe. Levels are the samples' own loudness at their volume, not a measurement of the mix.

#### Create

The **Create** tab builds a sound from a recipe, the same numeric recipes the agent uses (`wave`, `draw`, `kick`, `snare`, `hat`, `kick_hat`, `snare_hat`, `pluck`). It has three columns.

1. **Recipe.** Choose the recipe type; the form below is generated from the recipe schema, so each parameter has the range the core enforces and parameters that do not apply to the chosen shape are hidden.
2. **Sound.** With **Listen after each change** on (the default), the recipe plays shortly after you stop editing; **Listen** plays it on demand. Underneath, the measurements: size, looped or one-shot, playback rate at the chosen note, tuning error in cents, loudness against the bank reference, and peak and RMS in dBFS. A recipe the core cannot build says why instead of playing. For the `draw` recipe a **drawing canvas** replaces the wave controls: paint one cycle with the mouse, start from **Sine**, **Triangle**, **Saw**, **Square** or **Clear**, and change the number of points (4 to 256).
3. **Add to song.** Name (up to 22 characters), **Role**, **Slot** (the first free slot, or any slot; an occupied one asks before replacing it), **Note** and fine tune, and **Volume**. **Match the volume to the role's level** is on by default and uses the sample bank when one is found, otherwise the built-in levels; uncheck it to choose a volume. **Add to song** runs the `recipe_sample` operation as one undoable step. For a drawing, **Keep the drawing as plain sample data instead of a recipe** stores the computed bytes (`sample_set_pcm`) instead of the recipe; this is refused in songs that only allow library or synthesized samples.

**Start a synthesized song…** (bottom left) opens a new project holding the 13-sample starter palette of created samples (kick, snare, hat, basses, leads, noise), volumes matched to the bank or to the built-in levels. It asks what to do with unsaved changes first. The project records `"sample_source": "synthesized"`; see [Songs made only with created samples](#songs-made-only-with-created-samples).

#### Instruments

An instrument is a sample, its volume and fine tune, and a short **phrase** of effects that follow the note (a plucked bass can be a sample with the phrase `000`, `C30`, `C20`, `C10`). The **Instruments** tab keeps them as small JSON files in a folder, `exports/instruments` by default; **Folder…** chooses another one and the window remembers it. The tab has three columns.

- **Instruments:** a search box, the list (id, name, role, phrase rows), **Folder…** and **Delete** (after a confirmation).
- **Save the selected sample:** takes the sample selected in **Song samples**, a name, a role and a phrase of effect rows (three hexadecimal digits each, `000` for nothing; **+ Row** and **− Row** change the length, up to 32 rows) and **Save instrument** writes it as a new file with the next ID (`INS-0001`, ...). A recipe sample is saved as a recipe, an unedited library sample as its library ID and anything else as its PCM. Selecting an instrument in the list loads its name, role and phrase into the form.
- **Apply at the cursor:** choose the **Note**, then **Apply at cursor** (`Ctrl+I`, or a double-click in the list). The window writes the note and the sample number at the pattern cursor and the phrase effects on the rows that follow, in the same channel, as one undoable step. The sample is added to the song if it is not already there (an identical sample is reused). Effects already in the way are kept and counted in the status line, unless **Replace effects already in the way** is checked. The phrase stops at the next note in the channel, at the end of the pattern or at the end of the phrase.

The same files work from the command line: `chiploom instruments` and the `apply_instrument` operation are described in the [CLI reference](CLI.md#instruments).

### Keyboard audition

The piano keys can be used to hear sounds, not only to enter notes. The keys are the two rows described in [Keyboard entry, blocks and orders](#keyboard-entry-blocks-and-orders); the rows depend on the **Keyboard** setting (Auto, QWERTY or AZERTY). The hint next to the editing controls shows the current octave and layout.

| Note | Lower row, QWERTY | Lower row, AZERTY | Upper row, QWERTY | Upper row, AZERTY |
| --- | --- | --- | --- | --- |
| C | `Z` | `W` | `Q` | `A` |
| C# | `S` | `S` | `2` | `é` |
| D | `X` | `X` | `W` | `Z` |
| D# | `D` | `D` | `3` | `"` |
| E | `C` | `C` | `E` | `E` |
| F | `V` | `V` | `R` | `R` |
| F# | `G` | `G` | `5` | `(` |
| G | `B` | `B` | `T` | `T` |
| G# | `H` | `H` | `6` | `-` |
| A | `N` | `N` | `Y` | `Y` |
| A# | `J` | `J` | `7` | `è` |
| B | `M` | `,` | `U` | `U` |
| C, one octave up | `,` | `;` | `I` | `I` |
| C# | `L` | `L` | `9` | `ç` |
| D | `.` | `:` | `O` | `O` |
| D# | `;` | `M` | `0` | `à` |
| E | `/` | `!` | `P` | `P` |

The lower row starts at the base octave (**Octave**, 1 to 3, 2 by default: `Z` plays C-2) and the upper row starts one octave higher. The notes of the module run from C-1 to B-3, so a key that would go beyond B-3 at the current octave plays nothing. **F1**, **F2** and **F3** set the octave, and the numeric keypad `+` and `-` move it by one; this works on every page below.

**What the keys play**

- **In the pattern with Edit mode on:** the key enters the note as always and you hear it with the sample it writes.
- **In the pattern with Edit mode off:** the key plays the current instrument at that pitch and writes nothing. The current instrument is the sample selected in **Song samples**, or, when none is selected, the sample of the cell under the cursor.
- **In Song samples, Sample library, Create and Instruments:** the key plays the selected song sample, the selected library entry, the recipe in the form, or the selected instrument. This works while the focus is on a list, a button or the tab bar. Text fields, number boxes, editable lists and the instrument phrase grid keep their keys for typing, and shortcuts with `Ctrl` or `Alt` are never taken. Space still plays and pauses.

**Playing.** Up to **6 notes** can sound at once; beyond that the oldest is cut off. A looped sample sounds for as long as the key is down and fades out in about 10 ms when you let go; a one-shot plays to its end. Holding a key does not retrigger it (auto-repeat is ignored), and a note stops if the focus moves while its key is down.

**Delay and the song.** With real-time playback (libxmp), the notes are mixed into the audio stream, so you can play over the song. When the song is stopped, a key is heard within about 40 ms. While the song plays, the note joins the next audio block and the delay follows **Playback → Audio buffer** (80 to 600 ms, 150 ms by default), the same as for edits. Without libxmp, the window plays one rendered note at a time through the sample player: a new note replaces the previous one and playing a note pauses the song.

### Open in a browser

**Agent → Open in a browser…** opens a dialog for the [browser studio](#browser-studio), the web page that joins the same live session so that a tablet or a second screen can listen and edit with you. No code is needed: opening the address is enough. Live collaboration must be on (Agent menu); if it is off, the dialog says so and its controls are disabled. The dialog is not modal: you can keep it open while you work.

1. **Address.** The address to open in the browser, with **Copy** and **Open** (which opens it in this computer's default browser). Without the network option this is the local address of this computer (`http://127.0.0.1:<port>/web/`); with it, the first local-network address.
2. **Allow devices on my local network.** Off by default: only this computer can reach the studio. Check it to open the studio, and only the studio, to the private network addresses of this computer so that a tablet can connect. This uses plain HTTP, and the dialog shows a warning: anyone on that network who knows the address can listen and edit, so turn it on only on a network you trust. If no private address is available or the port is taken, the option unchecks itself and says why. The window remembers your choice and applies it again the next time live collaboration starts.
3. **Connected browsers.** A table with each browser's name, its user agent, whether it connects from this computer or the local network, and when it was last seen.

While at least one browser is connected, the status bar shows **Browsers: N**. An edit made in the browser appears in the window as it happens, with the changed cells flashing, and the status line names its origin: *Edit from a browser (human-web): …*. Stopping live collaboration or closing the window forgets every connected browser. The command-line way to get the address, and the security notes, are in [Browser studio](#browser-studio).

### More channels and XM in the window

The window opens, plays, edits and exports MOD files with 2 to 32 channels and XM files of the `fasttracker2-xm-v1` profile, as the command line does. The header line shows the format and the channel count, for example *MOD · 8 CHANNELS · PAL* or *XM · 6 CHANNELS*.

- **Grid.** One group of columns per channel (Note, Smp, Effect; Note, Ins, Vol, Effect for an XM), with a separator between channels and a thicker one every four. When the channels do not fit, the grid scrolls horizontally and the **Mute** and **Solo** strip above it follows the scroll; `Ctrl` + wheel narrows the columns to show more channels at once; following playback only scrolls vertically. Each pattern keeps its own row count.
- **Channel colours** are the same as in the browser studio: the theme's four colours, then lighter and darker variants of them for channels 5 and up.
- **XM entry.** The octave goes from 0 to 7 (4 by default), instrument numbers go from 01 to 80, the Vol column takes the volume-column byte in hex (40 is full volume) and effects take 0-9 then A-Z. In Edit mode, the key before 2 on the top row (1 on QWERTY, & on AZERTY) enters a key off (`===`). The help line under the grid repeats this.
- **Blocks.** Copy, cut, paste, move and transpose work on any channel count; pasting between a MOD and an XM is refused with a message, because their cells differ.
- **Samples.** An XM sample's card shows its bits, panning, relative note and loop mode. Volume, fine tune (-128 to 127 on an XM) and **Play sample** work. The library insert and **Create → Add to song** put a sample into an XM, converted as `chiploom convert` converts a MOD sample (8-bit, play it at C-4 for the MOD's C-2), in up to 128 instruments; a drawing is added as a recipe, because keeping it as plain sample data is a MOD sample edit. The editing controls of the sound workshop and the Instruments **Apply** are disabled on an XM, with a tooltip, because those sample operations are MOD-only. **Levels** says it does not apply to XM.
- **Files.** **Open…** accepts `.xm` files, and **Export MOD…** becomes **Export XM…** for an XM song. To change format, use `chiploom convert` (see the [command reference](CLI.md)).
- **Keyboard audition** plays XM samples at their real pitch (relative note, fine tune, 16-bit, ping-pong loops) and follows the channel under the cursor.

Not yet in the window: editing XM panning and relative note, choosing the row count of a new pattern (**New** creates 64 rows), and a gate-note command.
## HTML previews and compare pages

Both options remain available. To create a listening bundle from an existing project:

```powershell
python -m tracker4agents preview examples/pixel_rush.project.json --output exports/pixel-review --mp3 --language fr
```

Open `exports/pixel-review/preview.html`. The folder also contains the MOD, the project, the WAV, the optional MP3, the samples and a report. Choose a new folder for each revision; to share, copy the whole folder. Without `--language fr`, the HTML controls are in English. The preview works without Qt and complements the native window.

`compare A B --output folder` creates a blind A/B listening page (X and Y in random order). It is an informal test: the answer is in `answer_key.json`, in `comparison.json` and, encoded, in the page, and the command prints it only with `--show-answer`. The volumes of the two versions are not equalized unless you add `--equalize`, which turns the louder render down to the loudness of the quieter one. The page is listen-only.

If your browser restricts audio from local pages, serve the folder with a local server:

```powershell
python tools/serve_previews.py --port 8764 --directory exports/first_light
```

Then open the [local preview](http://127.0.0.1:8764/preview.html). The server stops with `Ctrl+C`. The page is self-contained and uses no remote service. To browse several compositions with one local server:

```powershell
python tools/serve_previews.py --port 8765
```

Then open [Pixel Rush](http://127.0.0.1:8765/pixel_rush/preview.html) or [First Light](http://127.0.0.1:8765/first_light/preview.html). This server supports HTTP byte ranges, which are needed to move the playback position in a WAV immediately without waiting for the full download. It binds to loopback only.

## Browser studio

The browser studio is a local web page that joins the same live session as the window, so a tablet or a second screen can listen to the song and edit it with you. Unlike the preview pages, it edits the open song. It is new in 0.8. There is nothing to pair and no code to type: you open the address and the studio appears.

**What it offers.** The page has a **Score** tab with the order list, a pattern selector, the pattern grid, a **Select block** mode and a cell editor, and an **Agent** tab with the agent's proposals (accept or reject), recent changes and takes. A player bar at the bottom listens from a row or an order for a chosen length and can mute channels. When a window is attached to the session, a **Sound** switch chooses between **This device** (the page plays an excerpt rendered by the session) and **Computer** (the ChipLoom window plays). The page has its own theme and EN/FR language controls. If the connection drops (for example because the session was stopped), it says so and offers **Try again**.

**Comments.** To tell your agent exactly where something is wrong, select a cell (or a block in **Select block** mode) and press **Comment** in the editor's header, type your remark and send it (Ctrl+Enter also sends). Cells covered by an open comment carry a small corner mark in the grid; hovering one shows the comment, and selecting it shows the comment above the editor, which is how you read it on a tablet. The **Agent** tab has a **Comments** list: open comments first, with their author, time, place (for example `Pattern 01 · rows 00-1F · channels 4-5`, rows in hexadecimal as in the grid) and replies, each with **Go to** (shows the pattern and selects the block), **Reply** and **Resolve**. **Comment on the whole song** writes a remark without a place, and **Show resolved** also lists the resolved ones with **Reopen**. The count of open comments appears on the Agent tab, and the list updates by itself when your agent replies or resolves. Comments from the browser are written as `human-web`; see [Comments in the CLI reference](CLI.md#comments) for how the agent reads them.

**Getting the address.** The agent's token never reaches the browser. When the page opens, it joins the session by itself and the server gives that browser its own token in a cookie; there is nothing for you to type. There are three ways to find the address:

- in the window, **Agent → Open in a browser…** (see above);
- from a terminal, `chiploom live web` prints the studio address (the local-network one first when that option is on); `chiploom live web --status` lists the connected browsers;
- with a headless session, `chiploom live serve SONG.json --web` also prints the address when it starts.

Browser edits are journaled under the author `human-web`. Like the agent's edits they carry the revision the page last read, so they conflict with newer agent or window edits in the same way (your window edits still win over the agent's).

**Reaching it from another device.** By default the studio is served only on this computer (`http://127.0.0.1:<port>/web/`). To use a tablet on the same network:

```sh
chiploom live serve exports/song/project.json --web --lan
```

`--lan` implies `--web`; `--lan-host ADDRESS` restricts it to one private IPv4 address of this computer and `--lan-port` picks the port. In the window, use **Allow devices on my local network** in the **Open in a browser** dialog. `--no-web` turns the studio off for a session.

**Security notes.**

- Everything is local. The agent API stays on loopback; the LAN listener serves **only** the studio, never the agent API, and only to clients on private network ranges (10.x, 172.16-31.x, 192.168.x, link-local and unique-local addresses).
- There is no code or password. On the local network, anyone who knows the address can open the studio, listen and edit, and the traffic is **plain HTTP**. Turn the network option on only on a network you trust.
- A joined browser holds its own token in an HttpOnly, SameSite=Strict cookie, plus a per-device request-forgery secret, both handed out automatically to a page of the studio itself. The token expires after 12 hours (the page then joins again by itself) and is stored only as a hash. At most twenty browsers are kept; the oldest makes room. Everything is kept in memory: stopping the session forgets every browser.
- Requests must come from the studio's own origin and host name; no cross-origin access is allowed, so another website open in the same browser cannot join or edit. The pages carry a strict content security policy.
- The studio's API is deliberately small: grid edits, proposals, takes, comments, selection, play/stop and short renders. It cannot save, read or open files, or touch sample banks.

## Planning, editing and measuring with an agent

The starting file is `examples/first_light.project.json`. A new song starts from `chiploom new --output exports/song/project.json` (`--channels 2` to `32`, `--format xm` with `--rows` for an XM), or from `chiploom synth palette` for a song made only with created samples. An agent can read and edit that JSON, then use these commands:

```powershell
python -m tracker4agents validate examples/first_light.project.json
python -m tracker4agents inspect examples/first_light.project.json --pattern 0
python -m tracker4agents export examples/first_light.project.json --output exports/custom.mod
python -m tracker4agents render exports/custom.mod --output exports/custom.wav --mp3-output exports/custom.mp3
```

For a render with libxmp:

```powershell
python -m tracker4agents render exports/custom.mod --engine xmp --output exports/custom.libxmp.wav
```

Both engines render at the same level: libxmp's volume is set to libopenmpt's for the module's format and channel count. libopenmpt plays an XM about 6 dB below a four-channel MOD and lowers the level as channels are added, so compare loudness between songs of the same format and width.

Successful commands return JSON. Data and render errors write an object `{"ok": false, "error", "code", "message"}` to stderr (with `message_fr` for the original French text of translated core diagnostics) and exit with code 2. Scripts must rely on `code`, never on the wording; the list of codes is in the [CLI reference](CLI.md#error-contract-and-codes). An export validates the data before replacing its destination; a render uses a temporary file before replacing its output.

Rows and channels are numbered from zero. Sample slots go from 1 to 31; zero keeps the current sample. Notes use the historical ProTracker notation `C-1` to `B-3`. Their pitch also depends on the sample: these names are not scientific-pitch octaves.

Since version 0.7.0, new projects use the schema `tracker4agents.project.v2`. Each pattern is a grid of rows (`rows`): the key is a two-digit hexadecimal row number, `00` to `3F`, and the value holds the four cells separated by `|`. A cell is written `NOTE SS EEE`; `---`, `--` and `...` stand for an empty note, sample and effect. Fully empty rows are omitted.

```json
{"name": "Boot", "rows": {
  "00": "C-2 04 F06 | E-1 06 FA0 | E-2 08 037 | E-2 0A E01",
  "01": "--- -- ... | --- -- A03 | --- -- 037 | --- 0B 412"
}}
```

Samples store `pcm_base64` with a `pcm_sha256` checked at load time (and the loop fields), or a recipe. Files are written compactly, one line per sample and per pattern row. Schema v2 also reads the older event layout, which is that of v1 projects:

```json
{"row": 8, "channel": 3, "note": "E-3", "sample": 8, "effect": "C27"}
```

`effect` holds three hexadecimal digits. Here, `C27` sets the volume to 39 on a scale of 0 to 64. An event without a note can change the volume, the vibrato or another effect of the voice already playing. A missing cell is empty. A pattern uses either `rows` or `events`, never both.

`chiploom migrate old.json --output new.json` rewrites a v1 project (or a MOD) as v2 without changing the exported MOD: `voltage_odyssey_v2` goes from 690 KB to 117 KB and `pixel_rush` from 192 KB to 34 KB. `inspect --pattern N --grid` prints a pattern in that same text.

### Batch edits with `patch`

```powershell
python -m tracker4agents inspect exports/song/v1.project.json --pattern 1 --grid --rows 8
python -m tracker4agents patch exports/song/v1.project.json --output exports/song/v2.project.json --label "Higher lead" --op '{"op": "transpose", "pattern": 1, "channel": 0, "semitones": 12}'
```

`patch` applies a list of operations to a copy of the project, validates the result and writes a new project, or writes nothing: an error names the faulty operation (`ops[1] (set): …`). The operations are `set`, `write`, `clear`, `copy`, `move`, `transpose`, `add_pattern`, `remove_pattern`, `rename_pattern`, `set_orders`, `insert_order`, `remove_order`, `move_order`, `title`, `timing`, `sample` and `library_sample`, plus the sample-editing and instrument operations added in 0.8. The fields are listed in the [CLI reference](CLI.md#operations).

### Measure, compare, give feedback

- `report` measures the played score: density, range, rests, repetition, estimated key (an estimate, not a fact). These are measurements, not a musical judgment.
- `compare A B --output folder` creates a blind A/B listening page, as described above.
- `feedback --text … --rating 1-5 --version … --output new.json` stores your opinion in the metadata of a copy of the project.

### MCP adapter

`python -m tracker4agents mcp` starts an MCP server on standard input and output. Its tools run the commands above and return the same JSON results. It is covered by automated tests and by a smoke run with the official Python MCP SDK as a client; it has not been tried in a model-driven session with an application. The [CLI reference](CLI.md#mcp-adapter) gives a sample configuration and [MCP.md](MCP.md) lists every tool.

Samples can be defined by a numeric recipe (`wave`, `draw`, `kick`, `snare`, `hat`, `kick_hat`, `snare_hat`, `pluck`) or by signed 8-bit PCM values. A recipe produces its PCM and loop points; it contains no executable code. Drawn waves use amplitude points, a target frequency and a number of cycles. Short sounds build their envelope directly into the sample.

Import (written in schema v2) is also available for files that belong to the supported profiles:

```powershell
python -m tracker4agents import exports/first_light/first_light.mod --output exports/imported.project.json
```

A MOD import keeps the PCM, but it cannot recover the synthesis recipes or the pattern names, which do not exist in the format. Files outside the profile are refused with an error, with no approximate conversion.

## Songs made only with created samples

The bank remains the default mode. On request, the agent can compose a song using only samples that it creates. `synth palette` writes a starter project with 13 balanced instruments (drums, basses, pulse leads, chords, noise); `synth preview` lets you hear a recipe; `synth add` or the `recipe_sample` patch operation adds one. `wave` recipes produce clean, tuned, looped waves (pulse, triangle, saw, sine, noise).

The volume of created samples is matched to your bank, role by role: the kick to the upper quartile of the percussion, the snare to the median, the hat to the lower quartile, and basses, leads and textures to the median of their family. `synth levels` prints these references, and `report` flags a sample more than 6 dB from its own. A project marked `"sample_source": "synthesized"` refuses bank samples, and the reverse; `validate --sample-source synthesized` checks it.

```powershell
python -m tracker4agents synth palette --output exports/synth-song/project.json --title "Synth song"
python -m tracker4agents validate exports/synth-song/project.json --sample-source synthesized
```

## The demo songs

**First Light** is an original composition of sixteen bars at 125 BPM. It lasts **30.72 seconds** and uses **eight samples created for the project**. Its MOD file is **17,206 bytes** and holds every sound it needs to play.

**Pixel Rush** aims at a more chiptune colour, with a **160 BPM** beat, very short triangle and square waves, timbre changes during notes and slides. It lasts **48 seconds**, uses **13 samples created for the project** and chains eight orders over seven patterns. Its MOD is **12,924 bytes**. The editable score is also available as `examples/pixel_rush.project.json`.

The demo command writes the ready-to-use files into `exports/first_light` or `exports/pixel_rush`:

- `first_light.mod`: the main module, editable in a compatible tracker.
- `first_light.mp3`: the optional listening copy.
- `first_light.wav`: the PCM render of the MOD with libopenmpt through FFmpeg.
- `first_light.libxmp.wav`: the render of the same MOD by a second, independent engine.
- `first_light.project.json`: the score and the sample recipes.
- `preview.html`: the listening and inspection page for patterns and samples.
- `validation.json`: the check results, versions and file fingerprints.
- `samples/01.wav` to `samples/08.wav`: the individual sound previews.

Pixel Rush has the same set of files in `exports/pixel_rush` (`pixel_rush.mod`, `pixel_rush.mp3`, the two WAV renders, the project JSON, the preview and the validation report).

Open `preview.html` in your browser, or serve it as described in [HTML previews and compare pages](#html-previews-and-compare-pages).

### Regenerating the demos

```powershell
python -m tracker4agents demo --mp3
python -m tracker4agents demo --song pixel-rush --with-xmp --mp3
```

The MOD is always generated. `--mp3` adds a listening copy encoded from the WAV made from the MOD. To produce only the MOD, the project and the sample previews, with no external player:

```powershell
python -m tracker4agents demo --no-audio
```

Without `--with-xmp`, generation requires only the main FFmpeg render. `--output` chooses another output folder. `--seed` changes the seed of the noise components; the score remains that of First Light. The same recipes and the same tool version reproduce the same MOD in the tested environment. All commands are run from the project root; installing the Python package is not needed for the agent's commands.

To enable the second engine, the following script downloads the official libxmp 4.7.3 sources, verifies their SHA-256 and builds the library in `.tools/libxmp`. On Windows it needs CMake and the Visual Studio C++ tools; the tools already installed on this machine were used for validation.

```powershell
python tools/setup_reference.py
python -m tracker4agents demo --with-xmp --mp3
```

The sources, the compiled library and its license stay in `.tools`. The manifest keeps the URL, the version and the fingerprints. The script performs no system installation. FFmpeg uses the version of libopenmpt included in its own build; its banner is kept in the report.

The two modules that you supplied served to examine construction and tracker techniques; the observations are kept in the [analysis of the references](../references/ANALYSIS.md) and the [fifteen-module selection study](../references/SELECTION.md). Reference analysis informs composition; it does not train a model. To study your own modules, run `python -m tracker4agents analyze path/to/selection.zip --output exports/study.json --probe`. The originals stay unchanged and outside the repository.

## Supported formats and limits

`protracker-4ch-pal-v1` targets uncompressed `M.K.` MOD files: four channels, 64 rows per pattern, up to 64 patterns, 128 orders and 31 samples. Samples are mono, signed 8-bit, of even length and limited to 65,534 bytes each. Module text is limited to printable ASCII. The 15-sample variants, `M!K!`, PC extensions and compressed modules were outside the original profile.

The profile accepts the simple effects `0` to `7`, `9`, `A`, `B`, `C`, `D`, `F`, and the extensions `E0`, `E1`, `E2`, `E4`, `E5`, `E6`, `E9`, `EA`, `EB`, `EC`, `ED`, `EE`. Volume, jump and tempo parameters are checked. `Dxx` uses a decimal row coded in BCD. `F00`, `F20` and the destructive effect `EFx` are excluded.

Durations rely on CIA timing. Renders are limited to 120 seconds and run in processes with a maximum delay. The demo resets speed, tempo and filter at the start, then returns to the first order with `B00`.

Version 0.8 widens this: MOD files with 2 to 32 channels (`M.K.`, `M!K!`, `FLT4`, `4CHN`, `6CHN`, `8CHN` and so on), more four-channel variants, the `E6x` and `EEx` effects, and a first FastTracker 2 XM profile with one sample per instrument. Some valid historical variants stay refused on purpose: `EFx`, `FLT8`, Octalyser signatures and out-of-range periods. The exact rules, error codes and conversions between MOD and XM are in the [CLI reference](CLI.md#multi-channel-mod-and-xm).

The window offers keyboard entry, block editing and order editing, a sound workshop, keyboard audition and opening the song in a browser. Interactive sample drawing exists in the workshop but the agent's default policy still uses only the local bank. The preview and compare pages are for listening and sharing; the browser studio edits through a live session. A wider MOD import and IT remain on the [roadmap](ROADMAP.md). The earlier plans, translated from the original French notes, are in [history/PROJECT_PLAN.md](history/PROJECT_PLAN.md). No model training is included.

## Checks

```powershell
python -m unittest discover -s tests -v
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite covers the format, renders, the server, the document and session, translations and themes, HTML bundles, reference analysis and the sample library, as well as, since version 0.7.0, `patch`, the error contract, schema v2, `report`, `compare`, live sessions, the MCP adapter, keyboard entry and the window's live integration; version 0.8 adds tests for the browser studio, multi-channel MOD and XM, sample editing and instruments, and the new window panels. Continuous integration runs Ruff, the core tests and the package build, plus the window tests on Windows and Linux (the Linux job does not block yet). Among other things it checks exact PCM preservation, duplicates and variants, reimport, neutral names and slot limits. The Qt tests use the real WAV files rendered by FFmpeg, the media player, keyboard entry, undo, exports and reopening a window. They cover search, filters, audition, adding and replacing samples, a missing bank, the loop after an intro, obsolete audio results, rapid mute clicks, language and theme changes during an entry, and audio levels. Sound is muted during the tests: the player's progress and its buffers are verified, not the physical speakers. Qt tests are skipped without PySide6 or FFmpeg; libxmp tests are skipped without that library.

The four themes were also inspected in native Windows windows; the screenshots and reports are in `exports/desktop`. A new process confirmed that the theme and language are restored after a full close.

The demo report holds **13 passed checks**: identical rebuild of the MOD, signal present, full duration and no PCM clipping in both players, then a match of the 256 rows with the libxmp execution trace. A separate test verifies two consecutive loops. These checks do not replace listening to the music.

The design and the current limits are described in [history/DESIGN.md](history/DESIGN.md) and the [roadmap](ROADMAP.md).

## Agent skill and personal bank

The [ChipLoom skill](../skills/chiploom/SKILL.md) lets you reproduce the work with your own modules. Ask your agent to read it from the repository, or copy the whole `skills/chiploom` folder into its skills folder. No skill is installed automatically and no reference sample is provided.

You can give it a list of MOD files, a ZIP archive, or a folder from which to choose a selection. The [bank procedure](../skills/chiploom/references/sample-bank.md) contains a JSON list and a reproducible Python loop: import into a single bank, deduplication, neutral names, classification to refine after listening, audit, then a small original test MOD. The IDs are discovered in your bank. Sources, bank, provenance and songs that use these samples stay local.
