# Articulation norms

October 29, 2026. Measured with `chiploom norms` on the owner's local selection of tracker modules: **49 modules** (12 MOD, 37 XM; 2 to 32 channels, 24 of them with four channels), read along their first playback cycle. Five more files were not measured: 2 Impulse Tracker files and 3 MODs the importer refuses (an out-of-range note, an undefined effect). The modules are not published. The numbers below are durations and proportions only: no names, notes, sequences or patterns, so they describe how the references *play*, never what they play, and cannot be used to reproduce one. The full output is in [norms.json](norms.json) (all modules, then MOD and XM separately).

Percentiles pool every arpeggio run, note or channel of the selection; "per module" lines take one median per module, so a long song does not outweigh a short one.

## Arpeggios

An arpeggio run is the rows during which one note keeps an `0xy` effect before a new note, a key off or a cut.

| Measure | p25 | p50 | p75 | p90 |
| --- | --- | --- | --- | --- |
| Run length (rows) | 1 | 1 | 2 | 4 |
| Run length (ticks: rows × speed) | 3 | 5 | 8 | 16 |
| Run length (seconds) | 0.08 | 0.10 | 0.16 | 0.31 |
| Run length, per module median (rows) | 1 | 2 | 16 | 16 |
| Share of note starts carrying an arpeggio, on arpeggio channels | 0.25 | 0.57 | 0.99 | 1.00 |

36 of the 49 modules use arpeggios. In most of them a chord note is struck again after one or two rows; a minority holds an arpeggio for a whole beat or more (the per-module p75 of 16 rows), usually on a sparse channel.

## Notes

| Measure | p25 | p50 | p75 | p90 |
| --- | --- | --- | --- | --- |
| Note length (seconds, until the next note, key off or cut on the channel) | 0.10 | 0.12 | 0.18 | 0.32 |
| Note length, per module median (seconds) | 0.10 | 0.12 | 0.16 | 0.24 |

How notes end, per module median: the next note **94%**, a cut (`C00`, XM volume `10`, `ECx`) **0.5%**, a key off **0%**, the song's end 0.3%. Rests come from retriggers and from samples and envelopes that decay, not from written cuts.

## Channels

| Measure (per playing channel) | p25 | p50 | p75 | p90 |
| --- | --- | --- | --- | --- |
| Share of the song the channel sounds | 0.45 | 0.75 | 0.94 | 1.00 |
| Longest stretch without a rest (seconds) | 4.8 | 25.6 | 61.4 | 87.3 |
| Rests per minute | 0.4 | 3.1 | 36 | 145 |
| Note starts per second | 0.6 | 2.2 | 4.8 | 7.0 |

Longest stretch with many channels (at least max(4, 60%)) sounding together: p50 1.9 s, p75 22.7 s, p90 42.4 s.

A channel sounds until its note is silenced. In an XM, a key off lets the instrument's volume envelope and fadeout play out (a median release of about 2.5 s on this selection), and that fading tail counts as sounding down to silence. The first version of these tables, published the same day, cut every XM note at its key off and showed channels sounding 58% of the time with 12.5 rests per minute.

## Tempo

Speed of the first row: p25 4, p50 4, p75 6. BPM: 125 in at least three quarters of the modules (p90 131).

## MOD and XM

The four-channel MODs play their channels almost all the time (median share 1.0, median longest stretch 20.5 s, almost no rests) with dense lines (4.2 notes per second per channel); the XMs spread more channels thinner (median share 0.69, 2.1 notes per second, 4.5 rests per minute, their key offs fading out through envelopes rather than stopping dead). Arpeggio runs and note lengths are about the same in both: one or two rows. See `mod` and `xm` in [norms.json](norms.json).

## What this means for composing (judgments)

- Strike arpeggio chords again every row or two; a run of three rows or more is already long for this selection, and a held arpeggio of a beat or more is the exception, on a sparse channel.
- Short notes are the rule (about one row). Lines breathe through retriggers, sample decay and envelopes rather than through `C00` or key offs.
- A four-channel MOD keeps every channel busy; with more channels (XM), give each channel less to do and let some rest.
- These are the owner's references, not rules of music: depart from them on purpose, and say so.

Reproduce with `python -m tracker4agents norms path/to/selection --output exports/norms.json`.
