"""One entry point for the module file formats (MOD, XM): detect, read, encode, replay copy.

The codecs live in `mod.py` and `xm.py`; everything that only needs "the bytes of this module"
(rendering, export, previews, the CLI) goes through here so a format is never special-cased
at the call site.
"""

from __future__ import annotations

from pathlib import Path

from . import mod, xm
from .model import Module, ValidationError

EXTENSIONS = {".mod": "mod", ".xm": "xm"}
XM_MAGIC = b"Extended Module: "


def detect(payload: bytes) -> str:
    """"xm" for an Extended Module header, otherwise "mod" (the MOD decoder then checks the rest)."""
    return "xm" if payload[:17] == XM_MAGIC else "mod"


def format_of_path(path: Path | str) -> str | None:
    return EXTENSIONS.get(Path(path).suffix.lower())


def refuse_other_trackers(head: bytes) -> None:
    """A clear refusal for the tracker formats ChipLoom recognises but does not read (whatever the extension)."""
    if head[:4] == b"IMPM":
        raise ValidationError("Impulse Tracker (.it) modules are not supported yet.", "IT_UNSUPPORTED")
    if head[44:48] == b"SCRM":
        raise ValidationError("Scream Tracker 3 (.s3m) modules are not supported yet.", "S3M_UNSUPPORTED")


def decode(payload: bytes) -> Module:
    refuse_other_trackers(payload[:48])
    return xm.decode(payload) if detect(payload) == "xm" else mod.decode(payload)


def read(path: Path) -> Module:
    path = Path(path)
    with path.open("rb") as stream:
        head = stream.read(48)
    refuse_other_trackers(head)
    if path.suffix.lower() == ".xm" or head[:17] == XM_MAGIC:
        return xm.read(path)
    return mod.read(path)


def encode(module: Module) -> bytes:
    if module.format == "xm":
        return xm.encode(module)
    if module.format == "mod":
        return mod.encode(module)
    raise ValidationError(f"Unknown module format {module.format!r}.", "FORMAT")


def encode_for_replay(module: Module) -> bytes:
    """Canonical bytes of the same music for an in-process replay engine (see the codecs)."""
    return xm.encode_for_replay(module) if module.format == "xm" else mod.encode_for_replay(module)


def import_notes(module: Module) -> list[dict]:
    return xm.import_notes(module) if module.format == "xm" else mod.import_notes(module)


def extension(module: Module) -> str:
    return ".xm" if module.format == "xm" else ".mod"
