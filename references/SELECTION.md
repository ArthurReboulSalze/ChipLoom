# Module selection study

October 15, 2026 — 15 files analyzed read-only from a locally supplied archive, whose integrity was verified before and after the study. The import column and the "Consequences for the tool" section have been updated for the 0.8 importer. The references are designated S01 to S15; their names and fingerprints are not published here.

The measurements and the relationships between patterns are in [selection-analysis.json](selection-analysis.json). The observations below concern the construction recorded in the data; they are not a critical listening, a certain identification of musical roles or model training. The originals, samples and complete melodies are not copied into the repository.

## Overview

The durations in this table are the estimates from **FFprobe/libopenmpt**, not the number of orders multiplied by 64 rows. Jumps and loops can change the path. Pattern numbers are decimal in this report.

| Reference | Channels | Stored patterns / orders | Duration | Total PCM | Editable import (0.8) |
| --- | --- | --- | --- | --- | --- |
| S01 | 4 | 6 / 7 | 33.28 s | 1,368 B | No |
| S02 | 4 | 4 / 4 | 25.60 s | 2,570 B | Yes |
| S03 | 2 | 9 / 12 | 46.08 s | 1,688 B | Yes |
| S04 | 4 | 5 / 7 | 35.84 s | 2,212 B | Yes |
| S05 | 4 | 5 / 7 | 40.00 s | 1,326 B | Yes |
| S06 | 4 | 2 / 4 | 30.72 s | 442 B | Yes |
| S07 | 4 | 2 / 2 | 10.24 s | 2,116 B | Yes |
| S08 | 4 | 4 / 4 | 46.08 s | 1,660 B | No |
| S09 | 4 | 1 / 1 | 7.68 s | 4,264 B | Yes |
| S10 | 4 | 4 / 4 | 22.40 s | 3,872 B | Yes |
| S11 | 4 | 3 / 4 | 20.48 s | 4,394 B | Yes |
| S12 | 4 | 4 / 10 | 115.20 s | 728 B | No |
| S13 | 4 | 2 / 4 | 20.48 s | 3,366 B | Yes |
| S14 | 4 | 1 / 1 | 15.36 s | 2,026 B | Yes |
| S15 | 2 | 3 / 5 | 32.00 s | 1,298 B | Yes |

A sample command without a note can reassign the same sample: this count alone does not guarantee a change of timbre.

The files use **101 non-empty sample slots**, totaling 33,330 bytes of PCM. These are not necessarily 101 different sounds: some may be identical. 70 slots are at most 128 bytes in size, the median size is 50 bytes and 71 slots have a loop longer than two bytes.

## Construction of the fifteen pieces

**S01.** The order list `5,0,2,0,1,3,4` starts with a distinct pattern before the repeats. Patterns 0, 1 and 2 share a majority of their occupied cells; patterns 3 and 4 form another close pair. Seven samples are enough, including three 14-byte waves. Arpeggios and volume commands are very present. Lead: a short introduction, a family of variants, then an answer, with contrasts obtained through the patterns.

**S02.** Four patterns, speed 5 at 125 BPM in the strict plan. Between 0 and 1, then between 2 and 3, channels **1, 2 and 4 are identical**; only channel 3 changes. Channel 4 contains only 12 events with a non-zero period but **244 events with a sample and no new period** across the stored patterns. Lead: keep a stable accompaniment and make one line evolve, while sculpting the timbres inside the notes.

**S03.** Two channels, four samples and twelve orders `0,7,1,4,2,3,5,6,2,3,5,8`. The F03 commands give a fast grid; patterns 5 and 6 keep the second channel exactly. Lead: with few voices, alternate the roles over time and vary one line while keeping the other. This file is not a four-channel MOD despite its extension.

**S04.** The arrangement `2,3,4,3,4,1,1` does not play pattern 0. In patterns 2, 3 and 4, channels **2, 3 and 4 are identical**; the variants concern channel 1. Channel 2 has 185 sample commands without a note across the stored set. Lead: distinguish the stored data from the played arrangement and build targeted variants, without rewriting all the voices.

**S05.** The orders `2,0,2,1,3,1,4` reuse motifs; patterns 3 and 4 have about 86% identical occupied cells. The file contains E6x pattern loops and Dxx jumps. Lead: a small variation at the end of a phrase can be enough to restart a motif. Its playback requires a player that understands these effects.

**S06.** Two patterns repeated in pairs `0,0,1,1`, only **442 bytes of PCM** spread over eight samples. Speed 8 does not produce a particularly fast grid; the movement comes notably from the many 6xx commands and from the articulation. Lead: perceived speed cannot be reduced to BPM or to the number of notes. A sustained sound can stay active thanks to its effects.

**S07.** Two patterns and a 10.24 s loop. Channel 3 has four events with a non-zero period and 124 sample commands without a new period. Vibrato is frequent. Lead: make a compact musical statement and work on the evolution of the sound over a few rows.

**S08.** Four patterns played in the order `1,0,3,2`. Channels 1 and 2 remain identical between all pairs of patterns; some pairs also keep the third. The file uses E9x and EFx. Lead: the change can concentrate on the last voice, but effects that modify the sample require a specific compatibility analysis.

**S09.** A single pattern and a single non-empty sample of 4,264 bytes, with a 978-byte loop. The third channel contains no new pitch event. The other channels reuse the same material at different notes with volume and pitch settings. Lead: a restricted palette can serve a complete phrase; multiplying samples is not a goal in itself.

**S10.** Four patterns, strong presence of vibrato and arpeggios. Channel 3 has 190 sample commands without a new note. The presence of Bxx jumps explains why the duration should not be deduced from four fully unrolled patterns. Lead: build the movement of the timbre and control the phrase endings in the score.

**S11.** Three patterns for `0,1,1,2`, that is, a form with a central repeat and a distinct ending. Two samples are only 20 bytes; others are much longer. The E0x commands drive the filter according to the capabilities of the player. Lead: mix very short waves and sounds with a more developed attack to give contrast.

**S12.** Four patterns feed ten orders, over 115.20 s. Channels 1 and 3 are identical across several patterns, and 1/2 also keep channel 4. The fourth channel has 176 sample commands without a new note across the stored patterns. Lead: a long construction can be based on a small reserve of motifs; for our next trials, keep this technique but condense the form based on your feedback about variations that are too long.

**S13.** Two patterns repeated `0,0,1,1`, speed 4, 20.48 s. Ten samples mix long sounds and short loops; the Cxx commands are numerous. Lead: two contrasting sections, each repeated once, can make an immediately readable form.

**S14.** A single 15.36 s pattern at speed 12. Ten samples, several of which share a 28-byte loop with different lead-in lengths. Lead: work on the attack and the envelope to differentiate the sounds, even when their loop is short.

**S15.** Two channels, three patterns and the order list `1,0,0,0,2`. Patterns 0 and 2 share 87.5% of their occupied cells. Lead: entrance, repetition of a main motif and a small closing variant; repetition is an arrangement decision, not necessarily an absence of work.

## What I take from this for composing

These leads are design choices deduced from the structure, not universal rules or melodies to reuse:

1. Write a short phrase, then an answer or a modified ending before making the piece longer.
2. Keep two or three channels stable between two variants and change precisely the line that matters.
3. Plan a family of very short looped samples; draw new shapes and then write the timbre changes in the cells.
4. Work on volumes and slides inside the notes, instead of lengthening all the variations.
5. Separate the rhythm of the notes from the speed at which the timbre evolves. Evaluate variations over one or two bars.
6. Test the transitions and the real restart of the loop, not just the first pattern.

The codes 0xy, 3xx, 4xy, 6xy, E6x, E9x and EFx have distinct behaviors; the count is not enough to reconstruct their audible result. The definitions are detailed in the [official OpenMPT effect reference](https://wiki.openmpt.org/Manual:_Effect_Reference).

## Consequences for the tool

**Twelve files out of fifteen are editable** (six in 0.7, ten in 0.8 after the conscious import of the variants, twelve with the N-channel modules). Each import is verified byte for byte: the re-exported MOD is identical to the original, and the playback plan (rows, E6x loops, tempo) matches the trace of the libxmp player for these twelve files. The importer keeps the restart byte, the inactive orders, the unusual sample headers (loop of length 0, high nibble of the finetune, non-zero start of a sound without a loop) and the texts outside printable ASCII, then writes them back identically; it lists these preservations in `import_notes`. S03 and S15 are two-channel modules (signature `2CHN`): the model now handles from 2 to 32 channels.

Three files remain refused, each for its own reason:

- **S01**: a single cell carries a period (1024) outside the 36 notes of the profile. No silent conversion, no note removal.
- **S08 and S12**: EFx commands (invert loop). They rewrite the sample data during playback, and libxmp and libopenmpt render them differently; the profile therefore cannot promise them.

The original MOD is never normalized or rewritten: the analysis stays read-only, and a conversion that would not preserve the original byte for byte (loop exceeding the end of the sample, volume above 64, M.K. signature with more than 64 patterns) is flagged in `import_notes` with the type `converted`.

## Reproducing the study

With your local archive and FFprobe/libopenmpt in the PATH:

```sh
python -m tracker4agents analyze path/to/selection.zip --output exports/selection-study.json --probe
```

Without `--probe`, the statistics remain available with Python alone; the strict-plan durations are computed only for compatible files. The local report contains identifying metadata: remove it before publishing. The measurements are not a verification of the authors or of the historical provenance.
