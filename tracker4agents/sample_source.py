"""Where a project's samples come from: `metadata.sample_source` and its checks.

A project may declare `"sample_source"`: `"library"` (only PCM taken from a sample bank),
`"synthesized"` (only ChipLoom recipes) or `"mixed"` (anything). Without a declaration nothing is
enforced. Standard library only.
"""

from __future__ import annotations

from .model import Module, ValidationError

SOURCES = ("library", "synthesized", "mixed")


class SampleSourceError(ValidationError):
    """A violation of the declared or required sample source; `violations` lists the offending slots."""

    def __init__(self, message: str, violations: list[dict]):
        super().__init__(message, "SAMPLE_SOURCE")
        self.violations = violations


def declared(module: Module) -> str | None:
    value = module.metadata.get("sample_source") if isinstance(module.metadata, dict) else None
    if value is None:
        return None
    if value not in SOURCES:
        raise SampleSourceError(f"metadata.sample_source must be one of {list(SOURCES)}, got {value!r}.",
                                [{"slot": None, "reason": "invalid sample_source value"}])
    return value


def counts(module: Module) -> dict:
    """Non-empty slots by origin: `recipe` (rebuilt from a recipe) or `embedded_pcm` (stored bytes)."""
    recipe = [slot for slot, item in enumerate(module.samples, 1) if item.pcm and item.recipe is not None]
    embedded = [slot for slot, item in enumerate(module.samples, 1) if item.pcm and item.recipe is None]
    return {"recipe": len(recipe), "embedded_pcm": len(embedded),
            "recipe_slots": recipe, "embedded_pcm_slots": embedded}


def violations(module: Module, required: str | None = None) -> tuple[str | None, list[dict]]:
    """(mode checked, violations). `required` (from --sample-source) overrides the declaration."""
    found = declared(module)
    mode = required or found
    problems: list[dict] = []
    if required and found in ("library", "synthesized") and found != required:
        problems.append({"slot": None, "reason": f"the project declares sample_source {found!r}, "
                                                 f"not {required!r}"})
    if mode == "synthesized":
        for slot, item in enumerate(module.samples, 1):
            if item.pcm and item.recipe is None:
                problems.append({"slot": slot, "name": item.name,
                                 "reason": "embedded PCM without a recipe (not synthesized by ChipLoom)"})
    elif mode == "library":
        for slot, item in enumerate(module.samples, 1):
            if item.pcm and item.recipe is not None:
                problems.append({"slot": slot, "name": item.name,
                                 "reason": "synthesized from a recipe (not a library sample)"})
    return mode, problems


def enforce(module: Module, required: str | None = None) -> dict:
    """Raise SAMPLE_SOURCE (with the offending slots) or return a summary of what was checked."""
    mode, problems = violations(module, required)
    if problems:
        slots = [str(item["slot"]) for item in problems if item["slot"] is not None]
        detail = f"slot(s) {', '.join(slots)}" if slots else problems[0]["reason"]
        raise SampleSourceError(f"Sample source {mode!r} is not respected: {detail}.", problems)
    found = counts(module)
    return {"declared": declared(module), "required": required, "checked": mode if mode != "mixed" else None,
            "recipe": found["recipe"], "embedded_pcm": found["embedded_pcm"]}


def guard_insert(module: Module, kind: str) -> None:
    """Refuse a library insertion into a synthesized project and a recipe into a library project."""
    found = declared(module)
    if kind == "library" and found == "synthesized":
        raise SampleSourceError(
            "This project declares sample_source 'synthesized'; library samples are refused. Set "
            "metadata.sample_source to 'mixed' only if the owner asks for both.",
            [{"slot": None, "reason": "library sample into a synthesized project"}])
    if kind == "recipe" and found == "library":
        raise SampleSourceError(
            "This project declares sample_source 'library'; created samples are refused. Set "
            "metadata.sample_source to 'mixed' only if the owner asks for both.",
            [{"slot": None, "reason": "recipe sample into a library project"}])
