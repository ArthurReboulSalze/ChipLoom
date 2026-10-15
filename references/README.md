# Reference studies

These reports document musical construction for agents to consult while composing original pieces. They do not train model weights or include source MOD files, PCM or complete note sequences.

- [Initial two references](ANALYSE.md): repetition, small samples and in-note sample changes used as inspiration for Pixel Rush.
- [Fifteen-module selection](SELECTION_FR.md): a per-module study in French, with arrangement, channel variation, effects and implications for the importer.
- [Machine-readable selection report](selection-analysis.json): neutral reference IDs, aggregate measurements and strict editing compatibility.

The selection has 13 four-channel and 2 two-channel modules, 101 occupied sample slots and 33,330 PCM bytes in total. Seventy occupied slots are at most 128 bytes. Six modules pass the current strict editor profile; all fifteen were structurally analyzed without modifying the supplied archive.

The main patterns are compact arrangements, repeated accompaniment with one changing channel, and timbre changes within sustained notes. Counts describe stored patterns, not necessarily the audible playback sequence. Read the full study before treating a count as a musical conclusion. Published reports use IDs A01–A02 and S01–S15; original filenames, internal titles and reference hashes remain outside the current published reports.

Reproduce with `python -m tracker4agents analyze path/to/selection.zip --output exports/study.json --probe`. The optional probe requires ffprobe/libopenmpt. Local analyzer output includes source metadata; remove identifying fields before publishing it. The original archive is intentionally absent from Git.
