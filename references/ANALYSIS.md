# First construction references

October 15, 2026. The two supplied modules were read without modification. The detailed observations and parameters are kept in `analysis.json` under the identifiers A01 and A02. The names and fingerprints of the originals are omitted from this published study. No sample or note sequence from these references was copied into Pixel Rush.

| Reference | Stored patterns | Orders | CIA timing | Cycle duration |
| --- | --- | --- | --- | --- |
| A01 | 8 | 12 | speed 5, tempo 141 | 65.248 s |
| A02 | 7 | 8 | speed 6, tempo 125 | 61.440 s |

Speed and tempo are read together: at equal tempo, a lower speed makes the rows advance faster. For A01, the 736 rows played include a pattern jump; the duration therefore cannot be computed simply as twelve whole patterns.

**Reuse and variation.** A01 chains the patterns `0,1,2,0,1,2,3,4,5,6,6,7`. A02 uses `1,0,2,3,4,5,5,6`. The repeats and variants give the piece its shape while limiting the data to store.

**Tiny samples.** The 16 non-empty samples of A01 total 4,436 bytes. Several have a 28-byte loop, preceded by a lead-in of variable length. The 12 samples of A02 total 7,708 bytes. The size of the sound material is therefore not enough to predict how rich its use will be.

**Articulation written in the patterns.** Volume, vibrato and portamento commands take up a significant share. In the stored patterns of A02, the second channel contains 82 sample changes without a new note: the instrument changes while the pitch stays driven by the current note or a slide. This technique deserves to be distinguished from a simple sample retrigger.

**Application to Pixel Rush.** The new piece uses its own triangle waves and 32- or 64-byte pulses, as well as synthesized percussion. Pulse widths change during some notes, volumes follow small contours and one passage uses real portamentos. Eight orders reuse seven patterns over 32 bars, with an entrance, theme, answer, airy passage, build-up and return.

These observations concern the data in the files. They are not an independent verification of the authors or of the historical provenance.

To recompute the observations from an original kept locally:

```powershell
python -m tracker4agents analyze path/to/reference.mod --output exports/reference-study.json
```
