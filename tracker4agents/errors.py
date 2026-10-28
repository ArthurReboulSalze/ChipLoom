"""Stable error codes and English messages for the agent boundary.

Core diagnostics are written in French (the desktop localizes them). Agents get
a machine-readable `code` that never changes with the wording, plus an English
`message`; the original text is kept as `message_fr` when it differs.

Raise sites should pass an explicit `code=`; the table below only classifies
older or foreign messages (French core text, English library/archive text).
"""

from __future__ import annotations

import re

import json

from .i18n import error_text
from .model import ValidationError

# Ordered: the first matching substring wins, so specific entries come first.
_BY_MESSAGE: tuple[tuple[str, str], ...] = (
    ("Note inconnue", "NOTE_UNKNOWN"),
    ("hors des 36 notes", "NOTE_RANGE"),
    ("trois chiffres hexadécimaux", "EFFECT_FORMAT"),
    ("définie deux fois", "CELL_DUPLICATE"),
    ("volume Cxx", "EFFECT_PARAM"),
    ("Bxx pointe", "FLOW"),
    ("Dxx attend", "FLOW"),
    ("F00 et F20", "TIMING"),
    ("seul E00/E01", "EFFECT_UNSUPPORTED"),
    ("non pris en charge par le profil", "EFFECT_UNSUPPORTED"),
    ("hors du profil ProTracker", "EFFECT_UNSUPPORTED"),
    ("points de boucle", "SAMPLE_LOOP"),
    ("boucle trop courte", "SAMPLE_LOOP"),
    ("sans boucle doit", "SAMPLE_LOOP"),
    ("invalid loop", "SAMPLE_LOOP"),
    ("longueur paire", "SAMPLE_LENGTH"),
    ("valeurs PCM signées", "SAMPLE_PCM"),
    ("liste PCM manquante", "SAMPLE_PCM"),
    ("recette", "RECIPE_INVALID"),
    ("synthèse inconnus", "RECIPE_INVALID"),
    ("onde dessinée", "RECIPE_INVALID"),
    ("Type de sample inconnu", "RECIPE_INVALID"),
    ("nombre fini attendu", "RECIPE_INVALID"),
    ("ASCII imprimable", "TEXT_ASCII"),
    ("caractères maximum", "TEXT_LENGTH"),
    ("texte attendu", "TEXT_TYPE"),
    ("nom textuel", "TEXT_TYPE"),
    ("champs inconnus", "UNKNOWN_FIELD"),
    ("Schéma attendu", "SCHEMA"),
    ("Expected schema", "SCHEMA"),
    ("Unsupported sample library schema", "SCHEMA"),
    ("objet JSON attendu", "SCHEMA"),
    ("tableau attendu", "SCHEMA"),
    ("emplacements de samples", "SAMPLE_SLOT"),
    ("emplacement de sample", "SAMPLE_SLOT"),
    ("Sample slot", "SAMPLE_SLOT"),
    ("existing slot", "SAMPLE_SLOT"),
    ("patterns", "PATTERNS"),
    ("liste d'événements", "PATTERNS"),
    ("liste d'ordres", "ORDERS"),
    ("orders[", "ORDERS"),
    ("Not a supported MOD", "MOD_FORMAT"),
    ("restart/tempo", "MOD_FORMAT"),
    ("MOD tronqué", "MOD_FORMAT"),
    ("Taille MOD", "MOD_FORMAT"),
    ("Texte MOD", "MOD_FORMAT"),
    ("Ordres inactifs", "MOD_FORMAT"),
    ("En-tête du sample", "MOD_FORMAT"),
    ("trop grand", "FILE_TOO_LARGE"),
    ("exceeds", "FILE_TOO_LARGE"),
    ("FFmpeg", "FFMPEG_MISSING"),
    ("ffprobe", "FFMPEG_MISSING"),
    ("limite de temps", "RENDER_TIMEOUT"),
    ("Déroulement trop long", "RENDER_LIMIT"),
    ("120 secondes", "RENDER_LIMIT"),
    ("Un rendu doit durer", "RENDER_LIMIT"),
    ("fréquence de rendu", "RENDER_LIMIT"),
    ("prélecture", "RENDER_LIMIT"),
    ("pas atteint", "RENDER_LIMIT"),
    ("doit avoir une extension", "OUTPUT_PATH"),
    ("chemin distinct", "OUTPUT_PATH"),
    ("doit être distincte", "OUTPUT_PATH"),
    ("must differ", "OUTPUT_PATH"),
    ("outside the sample bank", "OUTPUT_PATH"),
    ("must be a new directory", "OUTPUT_PATH"),
    ("Output must", "OUTPUT_PATH"),
    ("ZIP", "ARCHIVE_INVALID"),
    ("Archive", "ARCHIVE_INVALID"),
    ("archive", "ARCHIVE_INVALID"),
    ("No .mod references", "ARCHIVE_INVALID"),
    ("entier attendu", "INTEGER_RANGE"),
    ("sample library", "SAMPLE_LIBRARY"),
    ("Sample library", "SAMPLE_LIBRARY"),
    ("library sample", "SAMPLE_LIBRARY"),
    ("sample bank", "SAMPLE_LIBRARY"),
    ("Invalid PCM", "SAMPLE_LIBRARY"),
    ("PCM size mismatch", "SAMPLE_LIBRARY"),
    ("PCM hash mismatch", "SAMPLE_LIBRARY"),
)

# Fragments the shared i18n table does not cover (labels and composite messages).
_EXTRA_FRAGMENTS_EN: tuple[tuple[str, str], ...] = (
    ("Événement du pattern", "Event of pattern"),
    ("Projet:", "Project:"),
    ("Projet JSON", "JSON project"),
    (" définie deux fois — ", " defined twice — "),
    ("existant:", "existing:"),
    ("nouveau:", "new:"),
    ("Valeur attendue : ", "Expected value: "),
    ("Nom textuel attendu.", "Expected a text name."),
    ("Liste d'événements invalide (256 maximum).", "Invalid event list (256 maximum)."),
    (" tableau de 1 à 31 emplacements attendu", " expected an array of 1 to 31 slots"),
    (" tableau de 1 à 64 patterns attendu", " expected an array of 1 to 64 patterns"),
    (" entrées attendu", " entries expected"),
    ("Un effet doit contenir", "An effect must contain"),
)

_BY_TYPE: tuple[tuple[type, str], ...] = (
    (json.JSONDecodeError, "JSON_SYNTAX"),
    (OSError, "IO_ERROR"),
)


def error_code(exc: BaseException) -> str:
    """Stable identifier for an exception; explicit `code` first, then the table."""
    explicit = getattr(exc, "code", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    for kind, code in _BY_TYPE:
        if isinstance(exc, kind):
            return code
    message = str(exc)
    for fragment, code in _BY_MESSAGE:
        if fragment in message:
            return code
    if isinstance(exc, ValidationError):
        return "VALIDATION"
    if type(exc).__name__ == "RenderError":
        return "RENDER_FAILED"
    if isinstance(exc, RuntimeError):
        return "RUNTIME_ERROR"
    if isinstance(exc, ValueError):
        return "INVALID_VALUE"
    return "ERROR"


_CONTEXT_PREFIX = re.compile(r"^((?:ops\[\d+\] \([^)]*\): |Pattern \d+, row [0-9A-Fa-f]{2}: )+)")


def english_text(message: str) -> str:
    """English wording of a diagnostic string (core French text is mapped, others pass through).

    Context prefixes such as `ops[2] (set): ` or `Pattern 0, row 10: ` are kept and the
    core message after them is translated on its own.
    """
    match = _CONTEXT_PREFIX.match(message)
    if match:
        return match.group(1) + english_text(message[match.end():])
    text = error_text("en", message)
    for source, target in _EXTRA_FRAGMENTS_EN:
        text = text.replace(source, target)
    return text


def english_message(exc: BaseException) -> str:
    return english_text(str(exc))


def error_payload(exc: BaseException) -> dict:
    """The structured failure emitted on stderr by the CLI."""
    original = str(exc)
    message = english_message(exc)
    payload = {"ok": False, "error": type(exc).__name__, "code": error_code(exc), "message": message}
    if message != original:
        payload["message_fr"] = original
    # Live conflicts tell the agent exactly which of the owner's edits it would overwrite.
    for key in ("conflicts", "revision", "violations", "reasons"):  # "reasons": why an XM to MOD conversion was refused
        if getattr(exc, key, None) is not None:
            payload[key] = getattr(exc, key)
    return payload


def diagnostic_payload(entry: dict) -> dict:
    """Localize one `project.diagnose` entry: keep path/code, English message, French original."""
    original = entry["message"]
    message = english_text(original)
    result = {"path": entry["path"], "code": entry["code"], "message": message}
    if message != original:
        result["message_fr"] = original
    return result
