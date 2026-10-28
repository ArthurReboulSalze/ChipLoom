"""Portable HTML listening bundles built from an existing project or strict MOD."""
from __future__ import annotations

from pathlib import Path
import tempfile

from . import __version__, audio, formats, project
from .model import playback_plan
from .review import write_preview


def create_bundle(source: Path, output: Path, mp3: bool = False, ffmpeg: str | None = None,
                  language: str = "en") -> dict:
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise ValueError("Preview output must be a new directory; choose another name to preserve existing files.")
    if language not in ("en", "fr"):
        raise ValueError("Preview language must be en or fr.")
    module = project.load(source) if source.suffix.lower() == ".json" else formats.read(source)
    payload = formats.encode(module)
    plan = playback_plan(module)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Build the entire bundle before publishing its directory. A failed renderer
    # leaves neither a broken HTML page nor a modified source project.
    with tempfile.TemporaryDirectory(prefix=".chiploom-preview-", dir=output.parent) as temporary:
        folder = Path(temporary) / "bundle"
        folder.mkdir()
        module_path = folder / f"module{formats.extension(module)}"
        project.atomic_bytes(module_path, payload)
        project.write_json(folder / "module.project.json", project.to_dict(module))
        render = audio.render(module_path, folder / "module.wav", ffmpeg=ffmpeg)
        render["output"] = "module.wav"
        encoded = audio.export_mp3(folder / "module.wav", folder / "module.mp3", ffmpeg) if mp3 else None
        if encoded:
            encoded["output"] = "module.mp3"
        for slot, sample in enumerate(module.samples, 1):
            if sample.pcm:
                audio.sample_preview(sample, folder / "samples" / f"{slot:02d}.wav", module.format)
        report = {"schema": "chiploom.preview.v1", "version": __version__, "title": module.title,
            "mod_sha256": audio.sha256(module_path), "mod_roundtrip_byte_exact": formats.encode(formats.read(module_path)) == payload,
            "duration_seconds": plan["duration_seconds"], "render": render, "optional_mp3": encoded,
            "scope": "One renderer and structural round-trip; musical quality and physical audio output are not assessed."}
        project.write_json(folder / "validation.json", report)
        write_preview(module, folder / "preview.html", "module.wav", "validation.json",
                      "module.mp3" if mp3 else None, language=language)
        folder.rename(output)
    return {"ok": True, "title": module.title, "preview": str(output / "preview.html"),
        "mod": str(output / f"module{formats.extension(module)}"), "project": str(output / "module.project.json"),
        "wav": str(output / "module.wav"), "mp3": str(output / "module.mp3") if mp3 else None,
        "validation": str(output / "validation.json"), "language": language,
        "duration_seconds": plan["duration_seconds"]}
