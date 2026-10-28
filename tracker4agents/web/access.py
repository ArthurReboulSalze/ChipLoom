"""Joined browsers: how a page earns its own cookie and CSRF value for a live session.

There is no code to type. A browser that opens the studio address joins automatically and receives
its own token in an HttpOnly, SameSite=Strict cookie plus a CSRF value; what keeps another website
out is the same-origin checks of `gateway`, not a secret the owner has to carry around. The agent's
bearer token never reaches a page. Everything lives in memory: a stopped session forgets every device.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Callable

TOKEN_TTL = 12 * 3600         # a joined browser quietly joins again after this long
MAX_DEVICES = 20


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(char for char in value if char.isprintable())[:limit].strip()


class WebAccess:
    """The browsers that joined a session.

    A web token is stored only as its SHA-256; the page never sees anything but its own cookie and
    a CSRF secret. Tokens are bound to the listener that issued them ("loopback" or "lan").
    """

    def __init__(self, clock: Callable[[], float] = time.time, token_ttl: float = TOKEN_TTL):
        self._clock = clock
        self._token_ttl = token_ttl
        self._lock = threading.Lock()
        self._devices: dict[str, dict] = {}       # sha256(token) -> device record
        self._counter = 0

    @property
    def token_ttl(self) -> float:
        return self._token_ttl

    # --- joining --------------------------------------------------------------------------

    def join(self, *, listener: str, agent: str = "", name: str = "") -> tuple[str, dict]:
        """Register a browser. Returns `(token, device)`; the token is never stored, only its hash."""
        now = self._clock()
        with self._lock:
            self._purge(now)
            if len(self._devices) >= MAX_DEVICES:
                oldest = min(self._devices, key=lambda key: self._devices[key]["_seen"])
                del self._devices[oldest]
            token = secrets.token_urlsafe(32)
            self._counter += 1
            device = {"id": f"d{self._counter}", "name": _clean(name, 40) or f"Browser {self._counter}",
                      "agent": _clean(agent, 80), "listener": listener,
                      "joined_at": _iso(now), "_seen": now, "_expires": now + self._token_ttl,
                      "csrf": secrets.token_urlsafe(24)}
            self._devices[_digest(token)] = device
            return token, self._view(device)

    # --- devices --------------------------------------------------------------------------

    def authenticate(self, token: object, listener: str) -> dict | None:
        """The internal record (with its CSRF secret) of the device owning `token`, or None."""
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            return None
        now = self._clock()
        with self._lock:
            self._purge(now)
            device = self._devices.get(_digest(token))
            if device is None or device["listener"] != listener:
                return None
            device["_seen"] = now
            return device

    @staticmethod
    def csrf_ok(device: dict, supplied: object) -> bool:
        return isinstance(supplied, str) and hmac.compare_digest(device["csrf"].encode(), supplied.encode())

    def devices(self) -> list[dict]:
        with self._lock:
            self._purge(self._clock())
            return [self._view(device) for device in self._devices.values()]

    def view(self, device: dict) -> dict:
        with self._lock:
            return self._view(device)

    def forget(self, listener: str | None = None) -> int:
        """Drop every device, or those of one `listener` (when a listener closes or the session stops)."""
        with self._lock:
            doomed = [key for key, device in self._devices.items() if listener is None or device["listener"] == listener]
            for key in doomed:
                del self._devices[key]
            return len(doomed)

    # --- internals ------------------------------------------------------------------------

    def _purge(self, now: float) -> None:
        for key in [key for key, device in self._devices.items() if device["_expires"] <= now]:
            del self._devices[key]

    @staticmethod
    def _view(device: dict) -> dict:
        public = {key: value for key, value in device.items() if not key.startswith("_") and key != "csrf"}
        return {**public, "last_seen": _iso(device["_seen"]), "expires_at": _iso(device["_expires"])}
