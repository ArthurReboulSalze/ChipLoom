# Licensing and reference material

The original project source and documentation are released under MIT by Arthur Reboul Salze; see the root LICENSE.

The included example scores and sample-generation recipes were created for this project. At the owner's request, two curated original demos, **Pixel Rush** and **Voltage Odyssey V2**, are published with MOD, MP3 and editable projects in `docs/listen/media/`. Their samples were synthesized for ChipLoom; no historical reference PCM or recordings are included. The manifest records file hashes. Other generated exports remain outside Git.

The header logo was generated for ChipLoom with the built-in image generation tool and approved by the owner. Its prompt and transparent PNG are in `docs/assets/`.

User-supplied historical modules are reference inputs only. Their source archives, MOD files, PCM samples and audio renders are not distributed in this repository. Published studies use neutral reference IDs, structural counts and pattern relationships; original filenames, internal titles and reference hashes are omitted. These observations do not establish authorship or historical provenance. The MIT license does not grant rights to those third-party compositions.

External software is installed or built separately and retains its own license:
- [Qt for Python / PySide6 licensing](https://doc.qt.io/qtforpython-6/licenses.html)
- [FFmpeg legal information](https://ffmpeg.org/legal.html) — actual obligations depend on its build.
- [libopenmpt](https://lib.openmpt.org/libopenmpt/) — the playback library accessed through FFmpeg.
- [libxmp](https://github.com/libxmp/libxmp) — the optional pinned reference decoder built under .tools.

No external replay-engine binary or source archive is bundled in the Python package. Standalone application distribution will need a separate dependency and notice review for its actual package contents.
