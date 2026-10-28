"""HTTP side of the browser studio: static files, joining and the same-origin web API.

Defences, in the order they apply to every request on `/web/`:

* there is no code to type: `POST /web/join` hands a same-origin page its own cookie and CSRF value;
  what keeps another website out is the checks below, not a secret;
* the listener decides what is served (`role`): the LAN listener never serves the agent API;
* the client must be loopback, or private/link-local on the LAN listener;
* `Host` must be one of this listener's own names (DNS rebinding);
* a POST must be JSON, come from this exact origin (`Origin` equals `http://<Host>`; `Sec-Fetch-Site`
  must say same-origin when sent), and the API also needs the HttpOnly SameSite=Strict cookie plus
  the per-device CSRF header;
* no CORS headers are ever sent, and every answer carries a strict Content-Security-Policy.
"""

from __future__ import annotations

import http.cookies
import ipaddress
import json
import re
from pathlib import Path
from typing import Any

from . import brand
from .api import WEB_API, Binary, Call

DIRECTORY = Path(__file__).resolve().parent
STATIC = {"/web": "index.html", "/web/": "index.html", "/web/index.html": "index.html",
          "/web/app.js": "app.js", "/web/cells.js": "cells.js", "/web/style.css": "style.css"}
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8"}
MAX_JOIN_BODY = 2048
MAX_API_BODY = 256 * 1024
CSRF_HEADER = "X-ChipLoom-CSRF"
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer", "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin", "Cache-Control": "no-store",
}


def cookie_name(port: int) -> str:
    """Cookies are shared by every port of a host, so the name carries the listener's port."""
    return f"chiploom_web_{port}"


LAN_NETWORKS = tuple(ipaddress.ip_network(text) for text in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "fc00::/7", "fe80::/10"))


def client_allowed(address: str, role: str) -> bool:
    """Loopback peers always; on the LAN listener also RFC 1918 / link-local / unique-local peers.

    (`ipaddress.is_private` is not used: it also covers documentation and reserved ranges.)"""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return True
    return role == "lan" and any(ip.version == network.version and ip in network for network in LAN_NETWORKS)


def _fail(handler, status: int, code: str, message: str, headers: dict | None = None, **extra) -> None:
    handler.send_json(status, {"ok": False, "error": "ValidationError", "code": code, "message": message, **extra},
                      {**SECURITY_HEADERS, **(headers or {})})


def _origin(headers: dict, host: str) -> bool:
    origin = (headers.get("Origin") or "").lower()
    if origin not in (f"http://{host}", f"http://{host[:-3]}" if host.endswith(":80") else None):
        return False
    site = headers.get("Sec-Fetch-Site")
    return site is None or site == "same-origin"


def _normal_host(value: str | None) -> str:
    host = (value or "").strip().lower()
    return host if re.search(r":\d+$", host) else f"{host}:80"


def handle(handler, owner, method: str) -> None:
    """Answer one request below `/web/`. `handler` is the live server's request handler."""
    httpd = handler.server
    path = handler.path.split("?", 1)[0]
    handler.body_consumed = False
    try:
        if not owner.web_enabled:
            return _fail(handler, 404, "LIVE_WEB_OFF", "The browser studio is turned off on this session.")
        if not client_allowed(handler.peer(), httpd.role):
            return _fail(handler, 403, "LIVE_FORBIDDEN", "This address may not use the browser studio.")
        host = _normal_host(handler.headers.get("Host"))
        if host not in httpd.allowed_hosts:
            return _fail(handler, 403, "LIVE_FORBIDDEN", "Unexpected Host header; open the address ChipLoom printed.")
        if method == "GET":
            return _static(handler, path)
        if path == "/web/join":
            return _join(handler, owner, httpd, host)
        match = re.fullmatch(r"/web/api/([a-z_]+)", path)
        if not match:
            return _fail(handler, 404, "LIVE_UNKNOWN_METHOD", "Unknown web path.")
        if match.group(1) not in WEB_API:
            return _fail(handler, 404, "LIVE_UNKNOWN_METHOD", f"Unknown method; use one of {sorted(WEB_API)}.")
        return _api(handler, owner, httpd, host, match.group(1))
    finally:
        if method == "POST" and not handler.body_consumed:
            try:
                handler.drain(int(handler.headers.get("Content-Length") or 0))
            except ValueError:
                pass


# Generated or packaged assets: path -> (producer, content type, cache policy).
GENERATED = {
    "/web/theme.css": (brand.theme_css, "text/css; charset=utf-8", "no-store"),
    "/web/logo.png": (brand.logo_png, "image/png", "public, max-age=3600"),
    "/web/emblem.png": (brand.emblem_png, "image/png", "public, max-age=3600"),
}


def _static(handler, path: str) -> None:
    if path in GENERATED:
        produce, content_type, cache = GENERATED[path]
        body = produce()
        if body is None:
            return _fail(handler, 404, "LIVE_UNKNOWN_METHOD", "Not available.")
        return handler.send_bytes(200, body, content_type, {**SECURITY_HEADERS, "Cache-Control": cache})
    name = STATIC.get(path)
    if name is None:
        return _fail(handler, 404, "LIVE_UNKNOWN_METHOD", "Not found.")
    try:
        body = (DIRECTORY / name).read_bytes()
    except OSError:
        return _fail(handler, 500, "LIVE_ERROR", "The page files are missing from this installation.")
    handler.send_bytes(200, body, CONTENT_TYPES[Path(name).suffix], SECURITY_HEADERS)


def _envelope(handler, host: str) -> bool:
    """Content type and origin of a POST; answers the error itself and returns False when it is wrong."""
    content_type = (handler.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type != "application/json":
        _fail(handler, 415, "LIVE_BAD_REQUEST", "Send JSON with Content-Type: application/json.")
        return False
    if not _origin(handler.headers, host):
        _fail(handler, 403, "LIVE_FORBIDDEN", "Cross-origin requests are not accepted.")
        return False
    return True


def _body(handler, limit: int) -> dict | None:
    """The JSON object of a POST, or None after answering an error."""
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        length = -1
    if length < 0:
        _fail(handler, 400, "LIVE_BAD_REQUEST", "Invalid Content-Length.")
        return None
    if length > limit:
        _fail(handler, 413, "LIVE_TOO_LARGE", f"The request body is limited to {limit} bytes.")
        return None
    raw = handler.rfile.read(length) if length else b"{}"
    handler.body_consumed = True
    try:
        params = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        params = None
    if not isinstance(params, dict):
        _fail(handler, 400, "LIVE_BAD_REQUEST", "The body must be a JSON object.")
        return None
    return params


def _join(handler, owner, httpd, host: str) -> None:
    """Give this page its cookie and CSRF value. Same-origin only: a page on another origin is refused
    before its body is read, so it cannot become a device or read the answer. A browser that already
    holds a valid cookie keeps its device (reloads do not add one)."""
    if not _envelope(handler, host):
        return
    params = _body(handler, MAX_JOIN_BODY)
    if params is None:
        return
    unknown = set(params) - {"name"}
    if unknown:
        return _fail(handler, 422, "LIVE_PARAMS", f"Unknown parameters {sorted(unknown)}.")
    web = owner.session.web
    record = _device(handler, owner, httpd)
    if record is not None:
        return handler.send_json(200, {"ok": True, "csrf": record["csrf"], "device": web.view(record), "author": "human-web"},
                                 SECURITY_HEADERS)
    token, device = web.join(listener=httpd.role, agent=handler.headers.get("User-Agent") or "", name=params.get("name"))
    cookie = (f"{cookie_name(httpd.server_address[1])}={token}; Path=/web; HttpOnly; SameSite=Strict; "
              f"Max-Age={int(web.token_ttl)}")
    record = web.authenticate(token, httpd.role)
    handler.send_json(200, {"ok": True, "csrf": record["csrf"], "device": device, "author": "human-web"},
                      {**SECURITY_HEADERS, "Set-Cookie": cookie})


def _device(handler, owner, httpd) -> dict | None:
    jar = http.cookies.SimpleCookie()
    try:
        jar.load(handler.headers.get("Cookie") or "")
    except http.cookies.CookieError:
        return None
    morsel = jar.get(cookie_name(httpd.server_address[1]))
    return owner.session.web.authenticate(morsel.value if morsel else None, httpd.role)


def _api(handler, owner, httpd, host: str, method: str) -> None:
    if not _envelope(handler, host):
        return
    device = _device(handler, owner, httpd)
    if device is None:
        return _fail(handler, 401, "LIVE_WEB_AUTH", "This browser has not joined the session (or its cookie expired); reload the page.")
    # `hello` hands a reloaded page its CSRF value back. It changes nothing and, being same-origin only
    # (no CORS), no other site can read the answer.
    if method != "hello" and not owner.session.web.csrf_ok(device, handler.headers.get(CSRF_HEADER)):
        return _fail(handler, 403, "LIVE_CSRF", "Missing or wrong CSRF header; reload the page.")
    params = _body(handler, MAX_API_BODY)
    if params is None:
        return
    try:
        result: Any = WEB_API[method](Call(owner.session, owner, device, httpd.role), params)
    except Exception as exc:  # structured failure instead of a dropped connection
        return handler.send_error_payload(exc, None, SECURITY_HEADERS)
    if isinstance(result, Binary):
        return handler.send_bytes(200, result.data, result.content_type, {**SECURITY_HEADERS, **result.headers})
    handler.send_json(200, {"ok": True, **result}, SECURITY_HEADERS)
