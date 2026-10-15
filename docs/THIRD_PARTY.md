# Licensing and reference material

The original project source and documentation are released under MIT by Arthur Reboul Salze; see the root LICENSE.

The included example scores and sample-generation recipes were created for this project. Generated demo outputs can be rebuilt locally and are not committed as media bundles.

User-supplied historical modules are reference inputs only. Their source archives, MOD files, PCM samples and audio renders are not distributed in this repository. Aggregate reports include filenames, internal titles, hashes, structural counts and pattern relationships. Filenames and internal text are not independent verification of authorship or provenance. The MIT license does not grant rights to those third-party compositions.

External software is installed or built separately and retains its own license:
- [Qt for Python / PySide6 licensing](https://doc.qt.io/qtforpython-6/licenses.html)
- [FFmpeg legal information](https://ffmpeg.org/legal.html) — actual obligations depend on its build.
- [libopenmpt](https://lib.openmpt.org/libopenmpt/) — the playback library accessed through FFmpeg.
- [libxmp](https://github.com/libxmp/libxmp) — the optional pinned reference decoder built under .tools.

No external replay-engine binary or source archive is bundled in the Python package. Standalone application distribution will need a separate dependency and notice review for its actual package contents.
