"""Portable local state and audio cache; this module has no Qt dependency."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import wave

from . import __version__, audio, formats, project
from .document import listening_copy
from .i18n import LANGUAGES
from .model import Module, ValidationError, playback_plan
from .themes import THEMES


class AppState:
    def __init__(self, directory: Path):
        self.directory = directory
        self.path = directory / "session.json"
        self.values = {"recent_files": [], "volume": 65, "loop": True, "follow": True,
                       "language": "en", "theme": "midnight"}
        try:
            if self.path.stat().st_size < 100_000:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.values.update(loaded)
        except (OSError, ValueError):
            pass
        volume = self.values.get("volume")
        self.values["volume"] = max(0, min(100, volume)) if type(volume) is int else 65
        for key in ("loop", "follow"):
            if type(self.values.get(key)) is not bool:
                self.values[key] = True
        if self.values.get("language") not in LANGUAGES:
            self.values["language"] = "en"
        if not isinstance(self.values.get("theme"), str) or self.values["theme"] not in THEMES:
            self.values["theme"] = "midnight"
        if not isinstance(self.values.get("sample_library"), str):
            self.values["sample_library"] = None

    def recent(self) -> list[Path]:
        paths = self.values.get("recent_files", [])
        return [Path(path) for path in paths[:12] if isinstance(path, str)] if isinstance(paths, list) else []

    def remember(self, path: Path):
        current = str(path.resolve())
        self.values["recent_files"] = [current] + [str(other) for other in self.recent() if str(other) != current][:11]
        self.values["last_file"] = current

    def save(self):
        project.write_json(self.path, self.values)


class AudioCache:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def prepare(self, module: Module, audible: tuple[bool, ...] | None = None) -> Path:
        """Render the module (MOD or XM, any channel count) to a WAV, with the muted channels silenced."""
        duration = playback_plan(module)["duration_seconds"]
        if duration > 120:
            raise ValidationError("L'écoute de cette version est limitée aux cycles de 120 secondes ; le module reste consultable et éditable.")
        # One state per channel of this module; a take with another channel count than the window's keeps what fits.
        audible = (tuple(audible) if audible is not None else ())[:module.channels]
        audible += (True,) * (module.channels - len(audible))
        rendered_module = listening_copy(module, audible)
        payload = formats.encode(rendered_module)
        key = hashlib.sha256(payload + f"desktop-{__version__}-48000-openmpt".encode()).hexdigest()
        source, destination = self.directory / f"{key}{formats.extension(rendered_module)}", self.directory / f"{key}.wav"
        if destination.is_file():
            try:
                with wave.open(str(destination), "rb") as stream:
                    if stream.getnframes() > 0 and stream.getframerate() == 48000 and stream.getnchannels() == 2:
                        return destination
            except (OSError, EOFError, wave.Error):
                pass
        project.atomic_bytes(source, payload)
        audio.render(source, destination, seconds=duration)
        return destination

    def sample(self, module: Module, index: int) -> Path:
        sample = module.samples[index]
        if not sample.pcm:
            raise ValidationError("Cet emplacement de sample est vide.")
        # 16-bit XM samples need both bytes in the key; the XM facts change the pitch of the preview.
        payload = (bytes(value & 255 for value in sample.pcm) if sample.bits == 8
                   else b"".join(value.to_bytes(2, "little", signed=True) for value in sample.pcm))
        facts = (sample.loop_start, sample.loop_length, sample.finetune, sample.volume, sample.bits,
                 sample.relative_note, module.format)
        key = hashlib.sha256(payload + str(facts).encode()).hexdigest()
        destination = self.directory / f"sample-{key}.wav"
        if not destination.is_file():
            audio.sample_preview(sample, destination, module.format)
        return destination

    def library_sample(self, library, sample_id: str, note: str = "C-2") -> Path:
        entry = library.get(sample_id)
        identity = [entry[key] for key in ("pcm_sha256", "loop_start", "loop_length", "finetune", "volume")]
        key = hashlib.sha256(json.dumps([*identity, note, "library-audition-v1"]).encode()).hexdigest()
        destination = self.directory / f"library-{key}.wav"
        if not destination.is_file():
            library.audition(sample_id, destination, note=note)
        return destination
