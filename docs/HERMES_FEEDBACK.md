# Hermes on Debian: field feedback

On 15 October 2026, the project owner supplied a report from a **Hermes Agent / glm-5.3-flash** session. The reported environment was **Debian 13, Python 3.13.5 and Debian FFmpeg 7.1.5 with libopenmpt and libmp3lame**.

The agent reported completing two original compositions, *Night Courier* (53.76 seconds) and *Turbo Galette* (92.16 seconds), including valid MOD exports and MP3 listening copies. It used the CLI without a graphical desktop, an MCP adapter or changes to Hermes core. The owner confirmed that the workflow worked.

This is a **user-reported end-to-end result**, not a reproduced server test by this repository's CI. The supplied report did not include a full machine log or an independent libxmp run. It does not validate the Linux desktop or every model/provider. Private delivery details and the raw session report are not republished.

## Changes made in v0.5.0

| Reported friction | Implemented response |
| --- | --- |
| Duplicate cells identified only by coordinates | Errors now show both cell values and both event indices, including an explicitly empty first event. |
| A valid 138.24-second score failed only when rendering | `validate`, `inspect` and `estimate` now warn above the 120-second render bound without rejecting the MOD. |
| Confusion between `G#-3` and `G#3` | Note diagnostics and the guide include natural and sharp examples. |
| No way to plan duration before writing the score | `estimate --orders N --speed 6 --bpm 125`, plus the timing formula and a table. |
| One CLI round trip per independent error | `validate --report` collects independent JSON diagnostics with paths. See its bounded [contract](CLI.md#planning-and-diagnostics-v050). |
| Auditioning a drop required a complete render | Both renderers accept `--from-order N --seconds S`, preserving prior replay state by decoding the prefix. |

The duration formula is **rows × speed × 2.5 / BPM**. The report's 7.68-second example applies to 64 rows at speed 6 and **125 BPM**; PAL alone does not fix the duration of every order. Pattern breaks and tempo changes need the actual playback plan.

## What stays the same

JSON scores and responses, reproducible sample recipes, executable examples, the separation between an agent's tools and the human window, and the read-only reference studies remain central. Reference study informs composition; it does not update model weights.

Regression tests cover the reported diagnostic cases and compare excerpt PCM with the matching slice of a full render, including inherited instruments, tempo, speed and nonzero pattern entry rows. The existing cross-platform core CI remains separate from this external Debian session.
