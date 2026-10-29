"""The browser studio: joining, the same-origin web API, listening, the LAN opt-in and the page files."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import wave
from http.cookies import SimpleCookie
from pathlib import Path
from unittest import mock

from tracker4agents import live, live_cli, realtime
from tracker4agents.themes import THEMES
from tracker4agents.document import Document
from tracker4agents.live import LiveClient, LiveConflict, LiveServer, LiveSession
from tracker4agents.model import ValidationError
from tracker4agents.web import access, brand, gateway
from tracker4agents.web import render as web_render
from tracker4agents.web.access import WebAccess
from tracker4agents.web.api import WEB_OPS

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "pixel_rush.project.json"
HAS_XMP = realtime.find_library() is not None
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def put(row: int, channel: int, text: str, pattern: int = 0) -> dict:
    return {"op": "set", "pattern": pattern, "row": row, "channel": channel, "cell": text}


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Base(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.dir = Path(self._directory.name)
        environment = mock.patch.dict(os.environ, {"CHIPLOOM_HOME": str(self.dir / "home")})
        environment.start()
        self.addCleanup(environment.stop)
        self.project = self.dir / "song.project.json"
        shutil.copyfile(EXAMPLE, self.project)
        self.document = Document.open(self.project)
        self.session = LiveSession(self.document)


class Browser:
    """A scripted browser talking to one listener of a server: keeps its cookie and CSRF value."""

    def __init__(self, test: unittest.TestCase, port: int, host: str = "127.0.0.1"):
        self.test, self.port, self.host = test, port, host
        self.cookie: str | None = None
        self.csrf: str | None = None

    @property
    def origin(self) -> str:
        return f"http://{self.host}:{self.port}"

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, response, response.read()
        finally:
            connection.close()

    def post(self, path: str, payload: object = None, *, origin: object = "same", cookie: object = "own", csrf: object = "own",
             content_type: str = "application/json", extra: dict | None = None, raw: bytes | None = None):
        body = raw if raw is not None else json.dumps({} if payload is None else payload).encode("utf-8")
        headers = {"Content-Type": content_type, "Content-Length": str(len(body)), **(extra or {})}
        if origin == "same":
            headers["Origin"] = self.origin
        elif origin is not None:
            headers["Origin"] = origin
        if cookie == "own":
            cookie = self.cookie
        if cookie:
            headers["Cookie"] = cookie
        if csrf == "own":
            csrf = self.csrf
        if csrf:
            headers[gateway.CSRF_HEADER] = csrf
        return self.request("POST", path, body, headers)

    def json(self, path: str, payload: object = None, **kwargs):
        status, response, data = self.post(path, payload, **kwargs)
        return status, json.loads(data.decode("utf-8")), response

    def join(self, **kwargs):
        """What the page does on load: a same-origin POST that sets the cookie and returns the CSRF value."""
        kwargs.setdefault("cookie", None)
        kwargs.setdefault("csrf", None)
        status, body, response = self.json("/web/join", {}, **kwargs)
        if status == 200 and response.headers.get_all("Set-Cookie"):
            jar = SimpleCookie()
            for header in response.headers.get_all("Set-Cookie") or []:
                jar.load(header)
            name, morsel = next(iter(jar.items()))
            self.cookie, self.csrf = f"{name}={morsel.value}", body["csrf"]
        return status, body, response

    def api(self, method: str, payload: object = None, **kwargs):
        return self.json(f"/web/api/{method}", payload, **kwargs)


class WebCase(Base):
    def setUp(self):
        super().setUp()
        self.server = LiveServer(self.session, kind="headless").start()
        self.addCleanup(self.server.stop)
        self.port = self.server._httpd.server_address[1]
        self.browser = Browser(self, self.port)

    def joined(self) -> Browser:
        status, body, _ = self.browser.join()
        self.assertEqual(status, 200, body)
        return self.browser


# --- joined browsers -------------------------------------------------------------------------

class AccessTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.access = WebAccess(clock=self.clock)

    def join(self, listener="loopback"):
        return self.access.join(listener=listener, agent="TestAgent/1", name="Tablet")

    def test_joining_creates_a_device_without_any_code(self):
        token, device = self.join()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual((device["name"], device["listener"], device["agent"]), ("Tablet", "loopback", "TestAgent/1"))
        self.assertNotIn("csrf", device)
        self.assertNotIn("paired_via", device)
        self.assertIsNotNone(self.access.authenticate(token, "loopback"))
        self.assertEqual(self.access.join(listener="loopback")[1]["name"], "Browser 2")      # default name

    def test_tokens_are_random_and_stored_hashed(self):
        first, _ = self.join()
        second, _ = self.join()
        self.assertNotEqual(first, second)
        self.assertEqual(sorted(self.access._devices), sorted(hashlib.sha256(token.encode()).hexdigest() for token in (first, second)))
        self.assertNotIn(first, json.dumps(self.access.devices()))

    def test_csrf_values_are_compared_in_constant_time(self):
        token, _ = self.join()
        device = self.access.authenticate(token, "loopback")
        with mock.patch.object(access.hmac, "compare_digest", wraps=access.hmac.compare_digest) as compare:
            self.assertTrue(WebAccess.csrf_ok(device, device["csrf"]))
            self.assertFalse(WebAccess.csrf_ok(device, "wrong"))
            self.assertFalse(WebAccess.csrf_ok(device, None))
        self.assertTrue(compare.called)

    def test_devices_listing_forgetting_and_expiry(self):
        first = self.join()
        second = self.join("lan")
        self.clock.advance(30)
        self.access.authenticate(first[0], "loopback")
        listing = {device["id"]: device for device in self.access.devices()}
        self.assertEqual(sorted(listing), ["d1", "d2"])
        self.assertGreater(listing["d1"]["last_seen"], listing["d2"]["last_seen"])
        self.assertIsNone(self.access.authenticate(second[0], "loopback"))   # a LAN token is not valid on loopback
        self.assertEqual(self.access.forget("lan"), 1)
        self.assertIsNone(self.access.authenticate(second[0], "lan"))
        self.assertEqual(self.access.forget(), 1)
        self.assertEqual(self.access.devices(), [])
        third = self.join()
        self.clock.advance(self.access.token_ttl + 1)
        self.assertIsNone(self.access.authenticate(third[0], "loopback"))

    def test_the_oldest_device_makes_room_after_twenty(self):
        for _ in range(access.MAX_DEVICES + 3):
            self.clock.advance(1)
            self.join()
        ids = [device["id"] for device in self.access.devices()]
        self.assertEqual(len(ids), access.MAX_DEVICES)
        self.assertNotIn("d1", ids)

    def test_garbage_tokens_never_authenticate(self):
        self.join()
        for token in (None, "", "x", "a" * 400, 12, b"bytes"):
            self.assertIsNone(self.access.authenticate(token, "loopback"))


# --- static page -----------------------------------------------------------------------------------

class StaticTests(WebCase):
    def test_page_files_and_content_types(self):
        expected = {"/web/": "text/html; charset=utf-8", "/web": "text/html; charset=utf-8",
                    "/web/index.html": "text/html; charset=utf-8", "/web/app.js": "text/javascript; charset=utf-8",
                    "/web/cells.js": "text/javascript; charset=utf-8", "/web/comments.js": "text/javascript; charset=utf-8",
                    "/web/style.css": "text/css; charset=utf-8"}
        for path, content_type in expected.items():
            status, response, body = self.browser.request("GET", path)
            self.assertEqual(status, 200, path)
            self.assertEqual(response.headers["Content-Type"], content_type)
            self.assertGreater(len(body), 500)
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertIsNone(response.headers["Access-Control-Allow-Origin"])
        self.assertIn(b"ChipLoom Studio", self.browser.request("GET", "/web/")[2])

    def test_the_page_is_self_contained(self):
        text = "".join((ROOT / "tracker4agents" / "web" / name).read_text(encoding="utf-8")
                       for name in ("index.html", "app.js", "cells.js", "comments.js", "style.css"))
        self.assertNotRegex(text, r"https?://(?!www\.w3\.org)")      # no CDN, no web font, no tracker
        self.assertNotIn("<style", text)
        self.assertNotIn(" style=", text)                            # the strict CSP forbids inline style attributes
        self.assertNotIn("eval(", text)

    def test_the_page_joins_by_itself_and_has_no_code_input_or_unpair_button(self):
        web = ROOT / "tracker4agents" / "web"
        page, script, style = ((web / name).read_text(encoding="utf-8") for name in ("index.html", "app.js", "style.css"))
        self.assertIn('"/web/join"', script)
        self.assertIn('id="connect-retry"', page)
        for text in (page, script, style):
            self.assertNotRegex(text.lower(), r"pair|unpair|revoke(?!objecturl)|one-time|6-digit")
        self.assertNotIn("<input", page)

    def test_no_directory_traversal_and_nothing_but_the_allowlist(self):
        for path in ("/web/../live.py", "/web/%2e%2e/live.py", "/web/..%2flive.py", "/web/__init__.py", "/web/access.py",
                     "/web/api.py", "/web//etc/passwd", "/web/app.js/", "/web/APP.JS", "/web/.", "/web/..", "/webx/",
                     "/web/%00", "/web/app.js%00.html", "/web/static/../../live.py", "/web/index.html?x=../live.py#"):
            status, _, body = self.browser.request("GET", path)
            if path.startswith("/web/index.html?"):
                self.assertEqual(status, 200)             # a query string is ignored, not interpreted
                continue
            self.assertIn(status, (404, 405), path)
            self.assertNotIn(b"import ", body, path)

    def test_package_data_ships_the_page(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        for pattern in ("web/*.html", "web/*.js", "web/*.css"):
            self.assertIn(pattern, text)
        for name in ("index.html", "app.js", "cells.js", "comments.js", "style.css", "__init__.py"):
            self.assertTrue((ROOT / "tracker4agents" / "web" / name).is_file())

    def test_a_foreign_host_header_is_refused_even_for_the_static_page(self):
        for host in ("evil.example", f"evil.example:{self.port}", f"127.0.0.1:{self.port + 1}", "", f"localhost.evil.example:{self.port}"):
            status, _, _ = self.browser.request("GET", "/web/", None, {"Host": host})
            self.assertEqual(status, 403, host)
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"LOCALHOST:{self.port}"):
            self.assertEqual(self.browser.request("GET", "/web/", None, {"Host": host})[0], 200, host)

    def test_the_studio_can_be_turned_off(self):
        with LiveServer(self.session, web=False, home=self.dir / "other") as off:
            browser = Browser(self, off._httpd.server_address[1])
            self.assertEqual(browser.request("GET", "/web/")[0], 404)
            self.assertEqual(browser.json("/web/join", {}, cookie=None, csrf=None)[0], 404)
            self.assertFalse(off.web_enabled)
            self.assertNotIn("web_url", off.info())


# --- joining over HTTP, cookie flags, same-origin and CSRF ----------------------------------------------------

class JoinHttpTests(WebCase):
    def test_joining_sets_a_scoped_http_only_cookie_and_never_exposes_the_agent_token(self):
        status, body, response = self.browser.join()
        self.assertEqual(status, 200)
        header = response.headers["Set-Cookie"]
        attributes = {part.strip().split("=")[0].lower() for part in header.split(";")}
        self.assertTrue({"httponly", "samesite", "path", "max-age"} <= attributes, header)
        self.assertIn("SameSite=Strict", header)
        self.assertIn("Path=/web", header)
        self.assertIn(f"chiploom_web_{self.port}=", header)       # scoped to this server's port: cookies ignore ports
        self.assertEqual(int(header.split("Max-Age=")[1].split(";")[0]), int(self.session.web.token_ttl))
        self.assertNotIn("Domain", header)
        cookie_value = self.browser.cookie.split("=", 1)[1]
        self.assertNotEqual(cookie_value, self.server.token)
        self.assertNotIn(self.server.token, header + json.dumps(body))
        self.assertNotIn(cookie_value, json.dumps(body))           # the token travels only in the cookie
        self.assertTrue(body["csrf"])
        self.assertEqual((body["device"]["listener"], body["author"]), ("loopback", "human-web"))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for name in ("Access-Control-Allow-Origin", "Access-Control-Allow-Credentials"):
            self.assertIsNone(response.headers[name])

    def test_no_code_is_needed_and_every_browser_gets_its_own_cookie_and_csrf_value(self):
        first, second = Browser(self, self.port), Browser(self, self.port)
        self.assertEqual((first.join()[0], second.join()[0]), (200, 200))
        self.assertNotEqual(first.cookie, second.cookie)
        self.assertNotEqual(first.csrf, second.csrf)
        self.assertEqual(len(self.session.web_devices()), 2)
        self.assertEqual(first.api("status", {})[0], 200)
        self.assertEqual(second.api("status", {})[0], 200)

    def test_joining_again_with_a_valid_cookie_keeps_the_same_device(self):
        self.assertEqual(self.browser.join()[0], 200)
        cookie, csrf = self.browser.cookie, self.browser.csrf
        status, body, response = self.browser.join(cookie=cookie)          # a reload
        self.assertEqual((status, body["csrf"]), (200, csrf))
        self.assertIsNone(response.headers["Set-Cookie"])
        self.assertEqual(len(self.session.web_devices()), 1)
        status, body, response = self.browser.join(cookie=f"chiploom_web_{self.port}=" + "a" * 43)   # a stale cookie
        self.assertEqual(status, 200)
        self.assertTrue(response.headers["Set-Cookie"])
        self.assertEqual(len(self.session.web_devices()), 2)

    def test_the_api_works_again_after_joining_following_an_expired_cookie(self):
        clock = Clock()
        self.session.web = WebAccess(clock=clock)
        self.assertEqual(self.browser.join()[0], 200)
        self.assertEqual(self.browser.api("status", {})[0], 200)
        clock.advance(self.session.web.token_ttl + 1)
        status, body, _ = self.browser.api("status", {})
        self.assertEqual((status, body["code"]), (401, "LIVE_WEB_AUTH"))
        self.assertEqual(self.browser.join()[0], 200)                       # the page does this by itself
        self.assertEqual(self.browser.api("status", {})[0], 200)

    def test_joining_requires_a_same_origin_json_post(self):
        send = lambda **kwargs: self.browser.json("/web/join", {}, cookie=None, csrf=None, **kwargs)  # noqa: E731
        self.assertEqual(send(origin="http://evil.example")[0], 403)
        self.assertEqual(send(origin=f"http://127.0.0.1:{self.port + 1}")[0], 403)
        self.assertEqual(send(origin=f"https://127.0.0.1:{self.port}")[0], 403)
        self.assertEqual(send(origin=None)[0], 403)                                       # a browser always sends Origin
        self.assertEqual(send(origin="null")[0], 403)
        self.assertEqual(send(extra={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(send(extra={"Sec-Fetch-Site": "same-site"})[0], 403)
        self.assertEqual(send(extra={"Host": "evil.example"})[0], 403)                    # DNS rebinding
        self.assertEqual(send(content_type="text/plain")[0], 415)                          # no "simple" CORS request
        self.assertEqual(send(content_type="application/x-www-form-urlencoded")[0], 415)
        self.assertEqual(self.browser.json("/web/join", None, cookie=None, csrf=None, raw=b"[1]")[0], 400)
        self.assertEqual(self.browser.json("/web/join", None, cookie=None, csrf=None, raw=b"not json")[0], 400)
        self.assertEqual(self.browser.json("/web/join", {"extra": 1}, cookie=None, csrf=None)[0], 422)
        self.assertEqual(self.session.web_devices(), [])      # none of the refusals created a device
        self.assertEqual(send(extra={"Sec-Fetch-Site": "same-origin"})[0], 200)
        status, _, _ = self.browser.request("GET", "/web/join")
        self.assertEqual(status, 404)
        self.assertEqual(self.browser.request("OPTIONS", "/web/join")[0], 405)             # no CORS preflight answer
        self.assertEqual(self.browser.json("/web/pair", {}, cookie=None, csrf=None)[0], 404)   # the old endpoint is gone

    def test_oversized_join_body_is_refused(self):
        status, body, _ = self.browser.json("/web/join", None, cookie=None, csrf=None, raw=b'{"name": "' + b"1" * 5000 + b'"}')
        self.assertEqual((status, body["code"]), (413, "LIVE_TOO_LARGE"))


class WebApiSecurityTests(WebCase):
    def test_every_method_needs_the_cookie(self):
        browser = self.joined()
        for method in ("hello", "status", "score", "changes", "patch", "proposals", "takes", "render", "devices"):
            status, body, _ = browser.api(method, {}, cookie=None)
            self.assertEqual((status, body["code"]), (401, "LIVE_WEB_AUTH"), method)
        status, body, _ = browser.api("status", {}, cookie=f"chiploom_web_{self.port}=" + "a" * 43)
        self.assertEqual(status, 401)
        status, body, _ = browser.api("status", {}, cookie="chiploom_web=" + browser.cookie.split("=", 1)[1])
        self.assertEqual(status, 401)                           # the name carries the port: a cookie from another server fails

    def test_csrf_header_is_required_except_for_hello(self):
        browser = self.joined()
        self.assertEqual(browser.api("status", {}, csrf=None)[0], 403)
        self.assertEqual(browser.api("status", {}, csrf="wrong" * 8)[0], 403)
        status, body, _ = browser.api("status", {}, csrf=None)
        self.assertEqual(body["code"], "LIVE_CSRF")
        self.assertEqual(browser.api("status", {})[0], 200)
        status, body, _ = browser.api("hello", {}, csrf=None)        # a reloaded page asks for its CSRF value
        self.assertEqual((status, body["csrf"]), (200, browser.csrf))
        other = Browser(self, self.port)
        other.join()
        self.assertNotEqual(other.csrf, browser.csrf)
        self.assertEqual(browser.api("status", {}, csrf=other.csrf)[0], 403)   # another device's value does not work either

    def test_same_origin_is_enforced_on_the_api(self):
        browser = self.joined()
        evil = {"origin": "http://evil.example"}
        self.assertEqual(browser.api("patch", {"ops": [put(1, 0, "C-2 01 ...")], "base_revision": 0}, **evil)[0], 403)
        self.assertEqual(self.session.revision, 0)
        self.assertEqual(browser.api("status", {}, origin=None)[0], 403)
        self.assertEqual(browser.api("status", {}, origin="http://localhost.evil.example:" + str(self.port))[0], 403)
        self.assertEqual(browser.api("status", {}, extra={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(browser.api("status", {}, content_type="text/plain")[0], 415)
        self.assertEqual(browser.api("status", {}, extra={"Host": "evil.example"})[0], 403)
        self.assertEqual(browser.api("status", {}, origin=f"http://localhost:{self.port}", extra={"Host": f"localhost:{self.port}"})[0], 200)
        self.assertEqual(browser.request("GET", "/web/api/status", None, {"Cookie": browser.cookie})[0], 404)
        self.assertEqual(browser.request("OPTIONS", "/web/api/status")[0], 405)

    def test_unknown_methods_and_parameters(self):
        browser = self.joined()
        status, body, _ = browser.api("save", {})
        self.assertEqual((status, body["code"]), (404, "LIVE_UNKNOWN_METHOD"))
        for name in ("open", "take", "withdraw", "web_status", "web_pair", "web_revoke", "unpair", "ping", "seek"):
            self.assertEqual(browser.api(name, {})[0], 404, name)
        status, body, _ = browser.api("score", {"bogus": 1})
        self.assertEqual((status, body["code"]), (422, "LIVE_PARAMS"))
        self.assertEqual(browser.json("/web/api/Status", {})[0], 404)
        self.assertEqual(browser.api("status", None, raw=b"[]")[0], 400)

    def test_the_page_never_learns_paths_tokens_or_library_ids(self):
        browser = self.joined()
        dump = json.dumps([browser.api(method, {})[1] for method in ("hello", "status", "score", "proposals", "takes", "devices")])
        self.assertNotIn(str(self.dir), dump)
        self.assertNotIn(self.server.token, dump)
        self.assertNotIn("sha256", dump)
        self.assertEqual(browser.api("status", {})[1]["file"], "song.project.json")
        take = self.session.add_take(self.project, "Start")
        self.session.propose([put(1, 0, "C-2 01 ...")], label="Idea")
        _, takes, _ = browser.api("takes", {})
        self.assertEqual(takes["takes"][0]["file"], "song.project.json")
        self.assertNotIn("path", takes["takes"][0])
        self.assertEqual(takes["takes"][0]["id"], take["id"])
        _, proposals, _ = browser.api("proposals", {})
        self.assertNotIn("ops", proposals["proposals"][0])

    def test_web_credentials_do_not_open_the_agent_api_and_the_agent_token_is_not_a_cookie(self):
        browser = self.joined()
        token = browser.cookie.split("=", 1)[1]
        for headers in ({"Cookie": browser.cookie}, {"Authorization": f"Bearer {token}"},
                        {"Authorization": f"Bearer {token}", "Cookie": browser.cookie, gateway.CSRF_HEADER: browser.csrf}):
            status, _, body = browser.request("POST", "/v1/status", b"{}", {"Content-Length": "2", **headers})
            self.assertEqual(status, 401, headers)
        status, _, body = browser.request("POST", "/web/api/status", b"{}", {
            "Content-Length": "2", "Content-Type": "application/json", "Origin": browser.origin,
            "Authorization": f"Bearer {self.server.token}"})
        self.assertEqual(status, 401)                  # the bearer token is not a web credential either


# --- the agent API keeps its protections --------------------------------------------------------------------

class AgentApiTests(WebCase):
    def agent(self, path="/v1/status", token="default", headers=None, body=b"{}"):
        token = self.server.token if token == "default" else token
        values = {"Content-Length": str(len(body)), **({"Authorization": f"Bearer {token}"} if token else {}), **(headers or {})}
        status, _, data = self.browser.request("POST", path, body, values)
        return status, json.loads(data.decode("utf-8"))

    def test_browser_origins_are_still_refused_on_the_agent_api(self):
        self.assertEqual(self.agent()[0], 200)
        for origin in ("http://evil.example", self.browser.origin, "null"):
            status, body = self.agent(headers={"Origin": origin})
            self.assertEqual((status, body["code"]), (403, "LIVE_FORBIDDEN"), origin)

    def test_the_agent_api_checks_the_host_header(self):
        self.assertEqual(self.agent(headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.agent(headers={"Host": f"evil.example:{self.port}"})[0], 403)
        self.assertEqual(self.agent(headers={"Host": f"localhost:{self.port}"})[0], 200)

    def test_authors_starting_with_human_are_reserved(self):
        client = LiveClient(self.server.url, self.server.token)
        for author in ("human", "human-web", "Human-Web", "humanoid"):
            with self.assertRaises(ValidationError) as caught:
                client.call("patch", ops=[put(1, 0, "C-2 01 ...")], author=author)
            self.assertEqual(caught.exception.code, "LIVE_AUTHOR", author)
            with self.assertRaises(ValidationError):
                client.call("patch", ops=[put(1, 0, "C-2 01 ...")], author=author, propose=True)
        self.assertEqual(self.session.revision, 0)
        self.assertTrue(client.call("patch", ops=[put(1, 0, "C-2 01 ...")], author="bard")["changed"])

    def test_remote_peers_never_reach_the_agent_api_or_the_studio_on_the_loopback_listener(self):
        for peer in ("203.0.113.9", "192.168.1.20", "10.0.0.5", "::ffff:192.168.1.20", "not-an-ip"):
            with mock.patch.object(live._Handler, "peer", lambda self, peer=peer: peer):
                status, body = self.agent()
                self.assertEqual((status, body["code"]), (403, "LIVE_FORBIDDEN"), peer)
                self.assertEqual(self.browser.request("GET", "/web/")[0], 403, peer)   # LAN peers need the LAN opt-in
        self.assertEqual(self.agent()[0], 200)

    def test_agent_methods_for_the_studio(self):
        client = LiveClient(self.server.url, self.server.token)
        info = client.call("web_status")
        self.assertEqual(info["local"], f"http://127.0.0.1:{self.port}/web/")
        self.assertEqual((info["lan"], info["lan_enabled"], info["devices"]), ([], False, []))
        self.assertIn("note", info)                        # explains how to reach the studio from a tablet
        self.assertNotIn("token", json.dumps(info))
        self.assertNotIn("pending_codes", info)
        self.assertEqual(self.browser.join()[0], 200)
        self.assertEqual([item["id"] for item in client.call("web_status")["devices"]], ["d1"])
        for method in ("web_pair", "web_revoke"):         # codes and revocation no longer exist
            with self.assertRaises(ValidationError) as caught:
                client.call(method)
            self.assertEqual(caught.exception.code, "LIVE_UNKNOWN_METHOD")
        with self.assertRaises(ValidationError):
            client.call("web_status", lan=True)             # an agent cannot open the LAN
        self.assertFalse(self.server.lan_enabled)


# --- editing as human-web ------------------------------------------------------------------------------------

class WebEditingTests(WebCase):
    def test_edits_are_journaled_as_human_web_and_summarised_with_the_owner(self):
        browser = self.joined()
        _, hello, _ = browser.api("hello", {})
        self.assertEqual((hello["revision"], hello["author"], hello["bpm"], hello["title"]), (0, "human-web", 160, "Pixel Rush"))
        status, result, _ = browser.api("patch", {"ops": [put(1, 0, "C-2 01 ...")], "base_revision": 0, "label": "Kick"})
        self.assertEqual((status, result["changed"], result["revision"]), (200, True, 1))
        entry = self.session.changes()["entries"][-1]
        self.assertEqual((entry["author"], entry["label"], entry["kind"]), ("human-web", "Kick", "patch"))
        self.assertEqual(self.document.module.patterns[0].get(1, 0).text(), "C-2 01 000")
        summary = self.session.changes()["summary"]
        self.assertEqual((summary["human"]["entries"], summary["agent"]["entries"]), (1, 0))
        _, changes, _ = browser.api("changes", {"since": 0})
        self.assertEqual(changes["entries"][0]["patterns"], [0])
        self.assertTrue(changes["entries"][0]["own"])
        self.assertNotIn("diff", changes["entries"][0])      # the page learns which pattern changed, then re-reads it
        self.assertEqual(self.session.context()["web_devices"], 1)

    def test_only_the_cell_operations_are_allowed(self):
        browser = self.joined()
        allowed = [{"op": "set", "pattern": 0, "row": 1, "channel": 0, "cell": "C-2 01 ..."},
                   {"op": "write", "pattern": 0, "row": 2, "channel": 0, "cells": ["D-2 01 ...", "E-2 01 ..."]},
                   {"op": "copy", "pattern": 0, "row": 1, "rows": 1, "channel": 0, "to_row": 5},
                   {"op": "move", "pattern": 0, "row": 5, "rows": 1, "channel": 0, "to_row": 6},
                   {"op": "transpose", "pattern": 0, "row": 1, "rows": 1, "channel": 0, "semitones": 2},
                   {"op": "clear", "pattern": 0, "row": 2, "rows": 2, "channel": 0}]
        for op in allowed:
            status, body, _ = browser.api("patch", {"ops": [op], "base_revision": self.session.revision})
            self.assertEqual(status, 200, (op, body))
        for op in ({"op": "title", "title": "Hacked"}, {"op": "set_orders", "orders": [0]}, {"op": "add_pattern"},
                   {"op": "library_sample", "library": str(self.dir), "id": "x"}, {"op": "recipe_sample", "name": "x", "recipe": {}},
                   {"op": "sample", "slot": 1, "volume": 0}, {"op": "timing", "bpm": 120, "speed": 6}, {"op": "remove_pattern", "pattern": 6}, "set", 3):
            status, body, _ = browser.api("patch", {"ops": [op], "base_revision": self.session.revision})
            self.assertEqual((status, body["code"]), (422, "LIVE_PARAMS"), op)
        self.assertEqual(self.document.module.title, "Pixel Rush")

    def test_patch_parameters_are_strict(self):
        browser = self.joined()
        op = put(1, 0, "C-2 01 ...")
        cases = [({"ops": [op]}, "LIVE_PARAMS"),                                           # base_revision is mandatory
                 ({"ops": [op], "base_revision": 0, "author": "agent"}, "LIVE_PARAMS"),   # the author is not the page's to choose
                 ({"ops": [op], "base_revision": 0, "propose": True}, "LIVE_PARAMS"),
                 ({"ops": [], "base_revision": 0}, "LIVE_PARAMS"),
                 ({"ops": [op] * (200 + 1), "base_revision": 0}, "LIVE_PARAMS"),
                 ({"ops": [op], "base_revision": "0"}, "LIVE_BASE"),
                 ({"ops": [op], "base_revision": 9}, "LIVE_BASE"),
                 ({"ops": [op], "base_revision": 0, "label": "x" * 81}, "LIVE_PARAMS"),
                 ({"ops": [put(1, 0, "ZZZ")], "base_revision": 0}, None),
                 ({"ops": [put(99, 0, "C-2 01 ...")], "base_revision": 0}, None)]
        for payload, code in cases:
            status, body, _ = browser.api("patch", payload)
            self.assertEqual(status, 422, payload.keys())
            if code:
                self.assertEqual(body["code"], code, payload)
        self.assertEqual(self.session.revision, 0)

    def test_a_stale_web_patch_conflicts_with_an_agent_edit(self):
        browser = self.joined()
        agent = LiveClient(self.server.url, self.server.token)
        agent.call("patch", ops=[put(1, 0, "E-2 01 ...")], label="Agent kick")
        status, body, _ = browser.api("patch", {"ops": [put(1, 0, "G-2 01 ..."), put(2, 0, "G-2 01 ...")], "base_revision": 0})
        self.assertEqual((status, body["code"], body["revision"]), (409, "LIVE_CONFLICT", 1))
        conflict = body["conflicts"][0]
        self.assertEqual((conflict["unit"], conflict["author"], conflict["current"], conflict["yours"]), ("cell", "agent", "E-2 01 ...", "G-2 01 ..."))
        self.assertEqual(self.document.module.patterns[0].get(2, 0).text(), "--- 00 000")   # atomic
        status, body, _ = browser.api("patch", {"ops": [put(2, 0, "G-2 01 ...")], "base_revision": 0})
        self.assertEqual(status, 200)                                                        # other cells go through
        status, body, _ = browser.api("patch", {"ops": [put(1, 0, "G-2 01 ...")], "base_revision": 0})
        self.assertEqual(status, 409)                                                        # still older than the agent's edit
        status, body, _ = browser.api("patch", {"ops": [put(1, 0, "G-2 01 ...")], "base_revision": self.session.revision})
        self.assertEqual(status, 200)                                                        # "overwrite" after reading the new revision

    def test_a_stale_agent_patch_conflicts_with_a_web_edit(self):
        browser = self.joined()
        browser.api("patch", {"ops": [put(1, 0, "E-2 01 ...")], "base_revision": 0, "label": "Mine"})
        with self.assertRaises(LiveConflict) as caught:
            LiveClient(self.server.url, self.server.token).call("patch", ops=[put(1, 0, "A-2 01 ...")], base_revision=0)
        self.assertEqual(caught.exception.conflicts[0]["author"], "human-web")
        self.assertEqual(caught.exception.conflicts[0]["current"], "E-2 01 ...")

    def test_window_edits_also_conflict_with_the_browser(self):
        browser = self.joined()
        self.document.patch([put(1, 0, "E-2 01 ...")], "Window edit")
        self.session.sync("human", "Window edit")
        status, body, _ = browser.api("patch", {"ops": [put(1, 0, "G-2 01 ...")], "base_revision": 0})
        self.assertEqual((status, body["conflicts"][0]["author"]), (409, "human"))

    def test_proposals_accept_and_reject(self):
        browser = self.joined()
        first = self.session.propose([put(1, 0, "C-2 01 ..."), put(2, 0, "D-2 01 ...")], author="bard", label="Bass walk")
        second = self.session.propose([put(5, 1, "E-2 01 ...")], author="bard", label="Maybe")
        _, listing, _ = browser.api("proposals", {})
        self.assertEqual([item["id"] for item in listing["proposals"]], [first["id"], second["id"]])
        shown = listing["proposals"][0]
        self.assertEqual((shown["cells_total"], shown["author"], shown["stale"]), (2, "bard", False))
        self.assertEqual(shown["cells"][0]["after"], "C-2 01 ...")
        status, body, _ = browser.api("accept", {"id": first["id"]})
        self.assertEqual((status, body["changed"]), (200, True))
        entry = self.session.changes()["entries"][-1]
        self.assertEqual((entry["author"], entry["kind"], entry["accepted_by"]), ("bard", "accept", "human-web"))
        status, body, _ = browser.api("reject", {"id": second["id"], "reason": "not now"})
        self.assertEqual((status, body["proposal"]["status"]), (200, "rejected"))
        self.assertEqual(self.session.proposals("rejected")[0]["closed_by"], "human-web")
        self.assertEqual(browser.api("accept", {"id": first["id"]})[1]["code"], "LIVE_PROPOSAL")
        self.assertEqual(browser.api("accept", {"id": "p99"})[0], 422)
        self.assertEqual(browser.api("accept", {"id": "p1", "force": "yes"})[1]["code"], "LIVE_PARAMS")

    def test_a_stale_proposal_needs_force(self):
        browser = self.joined()
        proposal = self.session.propose([put(1, 0, "G-2 01 ...")], author="bard")
        self.session.apply_patch([put(1, 0, "E-2 01 ...")], author="other")
        self.assertTrue(browser.api("proposals", {})[1]["proposals"][0]["stale"])
        status, body, _ = browser.api("accept", {"id": proposal["id"]})
        self.assertEqual((status, body["code"]), (409, "LIVE_CONFLICT"))
        self.assertEqual(browser.api("accept", {"id": proposal["id"], "force": True})[0], 200)
        self.assertEqual(self.document.module.patterns[0].get(1, 0).text(), "G-2 01 000")

    def test_play_stop_and_select_drive_the_window_when_there_is_one(self):
        browser = self.joined()
        status, body, _ = browser.api("play", {"order": 1})
        self.assertEqual((status, body["code"]), (503, "LIVE_NO_WINDOW"))
        self.assertFalse(browser.api("status", {})[1]["window"])
        seen = []
        self.session.set_handler("play", lambda payload: seen.append(("play", payload)) or {"started": True})
        self.session.set_handler("stop", lambda payload: seen.append(("stop", payload)))
        self.assertEqual(browser.api("play", {"order": 2})[1]["started"], True)
        self.assertEqual(browser.api("stop", {})[1]["handled"], True)
        self.assertEqual(seen, [("play", {"order": 2}), ("stop", {})])
        self.assertTrue(browser.api("status", {})[1]["window"])
        self.assertEqual(browser.api("play", {"order": 99})[0], 422)
        self.assertEqual(browser.api("select", {"pattern": 1, "row": 3, "channel": 2})[1]["handled"], False)
        self.assertEqual(self.session.context()["selection"]["row"], 3)

    def test_devices_are_listed_for_every_browser(self):
        first, second = self.joined(), Browser(self, self.port)
        second.join()
        _, listing, _ = first.api("devices", {})
        self.assertEqual([(item["id"], item["current"]) for item in listing["devices"]], [("d1", True), ("d2", False)])
        self.assertEqual(len(self.session.web_devices()), 2)
        self.assertEqual(first.api("unpair", {})[0], 404)       # nothing to revoke: a browser simply joins again

    def test_stopping_the_server_forgets_every_device(self):
        browser = self.joined()
        self.server.stop()
        self.assertEqual(self.session.web_devices(), [])
        with self.assertRaises(OSError):
            browser.request("GET", "/web/")


# --- listening in the browser -----------------------------------------------------------------------------------------

def read_wav(data: bytes):
    with wave.open(io.BytesIO(data)) as reader:
        return reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes(), reader.readframes(reader.getnframes())


class CommentsPageTests(WebCase):
    """comments.js: served like app.js, included by the page, both languages, and the API it calls."""

    WEB = ROOT / "tracker4agents" / "web"

    def test_the_comments_script_is_served_and_the_page_includes_it(self):
        status, response, body = self.browser.request("GET", "/web/comments.js")
        self.assertEqual(status, 200)
        self.assertEqual(response.headers["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(response.headers["Content-Security-Policy"], gateway.CSP)
        self.assertIn("script-src 'self'", gateway.CSP)
        self.assertIn(b"ChipLoomComments", body)
        page = (self.WEB / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/web/comments.js" defer></script>', page)
        self.assertLess(page.index("/web/comments.js"), page.index("/web/app.js"))     # deferred scripts run in order
        for element in ('id="cmt-open"', 'id="cmt-editor"', 'id="comments-card"', 'id="comments-body"', 'id="comments-count"', 'id="tab-cmt"'):
            self.assertIn(element, page)
        self.assertIn("window.ChipLoomComments.create(", (self.WEB / "app.js").read_text(encoding="utf-8"))

    def test_comment_text_never_goes_through_inner_html_and_files_stay_small(self):
        script = (self.WEB / "comments.js").read_text(encoding="utf-8").split("*/", 1)[1]    # the code, not the header
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)
        self.assertNotIn("setAttribute(\"style\"", script)
        for name in ("app.js", "comments.js", "cells.js", "index.html"):
            self.assertLess(len((self.WEB / name).read_text(encoding="utf-8").splitlines()), 1500, name)

    def test_every_comment_string_exists_in_both_languages(self):
        import re
        script = (self.WEB / "comments.js").read_text(encoding="utf-8")
        page = (self.WEB / "index.html").read_text(encoding="utf-8")
        tables = {}
        for lang in ("en", "fr"):
            block = re.search(lang + r": \{(.*?)\n    \},", script, re.S).group(1)
            tables[lang] = dict(re.findall(r'"([a-zA-Z_.]+)": "((?:[^"\\]|\\.)*)"', block))
        self.assertEqual(set(tables["en"]), set(tables["fr"]))
        self.assertGreater(len(tables["en"]), 30)
        self.assertTrue(all(tables["fr"].values()))
        used = set(re.findall(r'"(cmt\.[a-z.]+)"', script.split("const STRINGS", 1)[0] + script.split("function create", 1)[1]))
        used |= set(re.findall(r'data-i18n(?:-aria)?="(cmt\.[a-z.]+)"', page))
        self.assertTrue(used)
        self.assertEqual(used - set(tables["en"]), set())
        for key, text in tables["en"].items():                # the placeholders are the same in both languages
            self.assertEqual(sorted(re.findall(r"\{\w+\}", text)), sorted(re.findall(r"\{\w+\}", tables["fr"][key])), key)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_the_scripts_parse_and_the_strings_merge_into_the_page_table(self):
        import subprocess
        for name in ("app.js", "comments.js", "cells.js"):
            done = subprocess.run(["node", "--check", str(self.WEB / name)], capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, (name, done.stderr))
        script = ("const M = require(process.argv[1]); const I18N = {en: {}, fr: {}};\n"
                  "const api = M.create({S: {}, I18N, h() {}, fill() {}, $: () => null, api() {}, t: (k) => k});\n"
                  "console.log(JSON.stringify({en: Object.keys(I18N.en).length, fr: Object.keys(I18N.fr).length,"
                  " max: M.MAX_TEXT, methods: Object.keys(api).sort()}));")
        done = subprocess.run(["node", "-e", script, str(self.WEB / "comments.js")], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        result = json.loads(done.stdout)
        self.assertEqual(result["en"], result["fr"])
        self.assertEqual(result["max"], 1000)
        self.assertEqual(result["methods"], ["load", "onChanges", "onSelection", "onStatus", "paint", "render", "wire"])

    def test_comments_round_trip_through_the_studio_api(self):
        browser = self.joined()
        place = {"pattern": 0, "row": 16, "rows": 16, "channel": 2, "channels": 2}
        status, created, _ = browser.api("comment", {"text": "Track 3 <b>drags</b> here", "place": place})
        self.assertEqual(status, 200, created)
        comment = created["comment"]
        self.assertEqual((comment["author"], comment["place"], comment["text"]), ("human-web", place, "Track 3 <b>drags</b> here"))
        self.assertEqual(browser.api("comment", {"text": "The intro is too long", "place": None})[1]["comment"]["place"], None)
        listed = browser.api("comments", {})[1]["comments"]
        self.assertEqual([item["id"] for item in listed], [comment["id"], "c2"])
        replied = browser.api("reply", {"id": comment["id"], "text": "Still there"})[1]["comment"]
        self.assertEqual(replied["replies"][-1]["author"], "human-web")
        self.assertEqual(browser.api("resolve", {"id": comment["id"]})[1]["comment"]["status"], "resolved")
        self.assertEqual([item["id"] for item in browser.api("comments", {"status": "open"})[1]["comments"]], ["c2"])
        self.assertEqual(len(browser.api("comments", {"status": "all"})[1]["comments"]), 2)
        self.assertEqual(browser.api("resolve", {"id": comment["id"], "reopen": True})[1]["comment"]["status"], "open")
        self.assertEqual(browser.api("status", {})[1]["open_comments"], 2)
        # the page learns about comment changes from `changes`, like edits
        entries = browser.api("changes", {"since": 0})[1]["entries"]
        kinds = [entry["kind"] for entry in entries]
        self.assertEqual(kinds.count("comment"), 5)
        self.assertTrue(all(entry["patterns"] == [] and not entry["structure"] for entry in entries if entry["kind"] == "comment"))
        # the server's checks reach the page as structured errors
        status, error, _ = browser.api("comment", {"text": "x", "place": {"pattern": 0, "row": 99}})
        self.assertEqual((status, error["code"]), (422, "COMMENT_INVALID"))
        status, error, _ = browser.api("reply", {"id": "c99", "text": "x"})
        self.assertEqual(error["code"], "COMMENT_UNKNOWN")
        status, error, _ = browser.api("comment", {"text": "x"}, csrf=None)
        self.assertEqual((status, error["code"]), (403, "LIVE_CSRF"))


@unittest.skipUnless(HAS_XMP, "libxmp is not available")
class RenderTests(WebCase):
    def render(self, **payload):
        browser = self.joined() if not self.browser.cookie else self.browser
        status, response, data = browser.post("/web/api/render", payload)
        return status, response, data

    def test_render_returns_a_valid_wav_within_the_cap(self):
        status, response, data = self.render(order=1, row=0, seconds=3)
        self.assertEqual(status, 200)
        self.assertEqual(response.headers["Content-Type"], "audio/wav")
        channels, width, rate, frames, pcm = read_wav(data)
        self.assertEqual((channels, width, rate), (2, 2, 44100))
        self.assertAlmostEqual(frames / rate, 3, delta=0.2)
        self.assertGreater(max(pcm), 0)
        info = json.loads(response.headers["X-ChipLoom-Render"])
        self.assertEqual((info["engine"], info["order"], info["row"], info["revision"]), ("libxmp", 1, 0, 0))
        self.assertEqual(info["audible"], [True] * 4)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_defaults_start_of_song_and_a_row_inside_an_order(self):
        status, response, data = self.render()
        self.assertEqual(status, 200)
        self.assertAlmostEqual(read_wav(data)[3] / 44100, web_render.DEFAULT_SECONDS, delta=0.2)
        status, response, data = self.render(order=2, row=8, seconds=2)
        info = json.loads(response.headers["X-ChipLoom-Render"])
        self.assertEqual((status, info["order"], info["row"]), (200, 2, 8))

    def test_the_length_is_capped_and_inputs_are_validated(self):
        for payload in ({"seconds": web_render.MAX_SECONDS + 1}, {"seconds": 0}, {"seconds": -3}, {"seconds": "5"}, {"seconds": True},
                        {"seconds": float("inf")}, {"order": 99}, {"order": -1}, {"row": 64}, {"audible": [True]},
                        {"audible": [False] * 4}, {"audible": ["yes"] * 4}, {"bogus": 1}, {"proposal": "p1", "take": "t1"}):
            status, response, data = self.render(**payload) if payload.get("seconds") != float("inf") else (None, None, None)
            if status is None:
                continue
            self.assertEqual(status, 422, payload)
            self.assertIn(json.loads(data)["code"], ("LIVE_RENDER", "LIVE_PARAMS", "INTEGER_RANGE"), payload)
        status, _, data = self.render(seconds=web_render.MAX_SECONDS)
        self.assertEqual(status, 200)
        self.assertLessEqual(read_wav(data)[3] / 44100, web_render.MAX_SECONDS + 0.1)

    def test_muted_channels_change_the_audio(self):
        _, _, everything = self.render(order=1, seconds=3)
        _, response, drums_only = self.render(order=1, seconds=3, audible=[False, False, False, True])
        self.assertEqual(json.loads(response.headers["X-ChipLoom-Render"])["audible"], [False, False, False, True])
        self.assertNotEqual(read_wav(everything)[4], read_wav(drums_only)[4])
        self.session.update_context(audible=[True, False, False, False])           # the window's mutes are the default
        _, response, from_window = self.render(order=1, seconds=3)
        self.assertEqual(json.loads(response.headers["X-ChipLoom-Render"])["audible"], [True, False, False, False])
        self.assertNotEqual(read_wav(from_window)[4], read_wav(everything)[4])
        with self.assertRaises(ValidationError):
            self.session.update_context(audible=[True, True])

    def test_render_follows_edits_and_can_preview_a_proposal_or_a_take(self):
        _, _, before = self.render(order=0, seconds=2)
        self.session.apply_patch([put(0, 0, "C-3 04 C40")], author="bard")
        _, _, after = self.render(order=0, seconds=2)
        self.assertNotEqual(read_wav(before)[4], read_wav(after)[4])
        proposal = self.session.propose([put(2, 0, "C-3 06 C40")], author="bard")
        status, _, preview = self.render(order=0, seconds=2, proposal=proposal["id"])
        self.assertEqual(status, 200)
        self.assertNotEqual(read_wav(preview)[4], read_wav(after)[4])
        self.assertEqual(self.document.module.patterns[0].get(2, 0).text(), "--- 00 000")      # nothing was applied
        take = self.session.add_take(self.project, "Start")
        status, _, listened = self.render(order=0, seconds=2, take=take["id"])
        self.assertEqual(status, 200)
        self.assertEqual(self.render(order=0, take="t9")[0], 422)
        self.assertEqual(self.render(order=0, proposal="p9")[0], 422)

    def test_one_render_at_a_time(self):
        self.joined()
        self.assertTrue(self.server.render_slot.acquire(blocking=False))
        try:
            status, _, data = self.render(seconds=1)
            self.assertEqual((status, json.loads(data)["code"]), (429, "LIVE_BUSY"))
        finally:
            self.server.render_slot.release()
        self.assertEqual(self.render(seconds=1)[0], 200)

    def test_render_does_not_hold_the_session(self):
        self.joined()
        started, results = threading.Event(), []
        original = web_render.render_wav

        def slow(*args, **kwargs):
            started.set()
            threading.Event().wait(0.3)
            return original(*args, **kwargs)

        with mock.patch.object(web_render, "render_wav", slow):
            worker = threading.Thread(target=lambda: results.append(self.render(seconds=1)[0]))
            worker.start()
            self.assertTrue(started.wait(10))
            self.assertTrue(self.session.apply_patch([put(1, 0, "C-2 01 ...")])["changed"])    # not blocked by the render
            worker.join(30)
        self.assertEqual(results, [200])


class RenderEngineTests(unittest.TestCase):
    def setUp(self):
        from tracker4agents import project
        self.module = project.load(EXAMPLE)

    @unittest.skipUnless(HAS_XMP, "libxmp is not available")
    def test_libxmp_engine_directly(self):
        data, info = web_render.render_wav(self.module, 1, 0, 2.0, None, engine="libxmp")
        self.assertEqual(info["engine"], "libxmp")
        self.assertAlmostEqual(read_wav(data)[3] / 44100, 2.0, delta=0.1)
        muted, _ = web_render.render_wav(self.module, 1, 0, 2.0, [True, False, False, False], engine="libxmp")
        self.assertNotEqual(read_wav(data)[4], read_wav(muted)[4])

    @unittest.skipUnless(HAS_FFMPEG, "FFmpeg is not available")
    def test_ffmpeg_fallback_starts_at_the_order_and_honours_mutes(self):
        data, info = web_render.render_wav(self.module, 1, 8, 2.0, None, engine="ffmpeg")
        channels, _, rate, frames, pcm = read_wav(data)
        self.assertEqual((info["engine"], info["row"], channels, rate), ("ffmpeg", 0, 2, 44100))
        self.assertAlmostEqual(frames / rate, 2.0, delta=0.1)
        self.assertIn("note", info)
        muted, _ = web_render.render_wav(self.module, 1, 0, 2.0, [True, False, False, False], engine="ffmpeg")
        self.assertNotEqual(pcm, read_wav(muted)[4])

    def test_nothing_available_is_a_clear_error(self):
        with mock.patch.object(web_render, "engine_name", return_value=None):
            with self.assertRaises(ValidationError) as caught:
                web_render.render_wav(self.module)
        self.assertEqual(caught.exception.code, "LIVE_RENDER_UNAVAILABLE")

    def test_parameters_are_checked_before_any_native_code_runs(self):
        with mock.patch.object(web_render, "_with_libxmp", side_effect=AssertionError("must not run")):
            for kwargs in ({"seconds": 61}, {"order": 99}, {"row": 99}, {"audible": [False] * 4}):
                with self.assertRaises(ValidationError):
                    web_render.render_wav(self.module, **kwargs)


# --- the LAN opt-in -----------------------------------------------------------------------------------------------------

class LanTests(Base):
    """The LAN listener is simulated on 127.0.0.1 (the test machine may have no private address)."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(live, "lan_addresses", lambda: ["127.0.0.1"])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = LiveServer(self.session).start()
        self.addCleanup(self.server.stop)
        self.port = self.server._httpd.server_address[1]

    def test_nothing_listens_on_the_lan_by_default(self):
        self.assertFalse(self.server.lan_enabled)
        self.assertEqual(self.server.web_urls(), {"local": f"http://127.0.0.1:{self.port}/web/", "lan": [], "lan_enabled": False})
        self.assertEqual(self.server._lan, [])
        self.assertIn("note", self.server.web_info())
        self.assertNotIn("warning", self.server.web_info())

    def test_enable_lan_opens_extra_listeners_that_serve_only_the_studio(self):
        urls = self.server.enable_lan(True)
        self.assertEqual(len(urls), 1)
        lan_port = int(urls[0].split(":")[2].split("/")[0])
        self.assertNotEqual(lan_port, self.port)
        self.assertEqual(self.server.web_urls()["lan"], urls)
        self.assertTrue(self.server.lan_enabled)
        self.assertIn("plain HTTP", self.server.web_info()["warning"])
        lan = Browser(self, lan_port)
        self.assertEqual(lan.request("GET", "/web/")[0], 200)
        # The agent API is refused on the LAN listener even with the right bearer token.
        status, _, data = lan.request("POST", "/v1/status", b"{}", {"Content-Length": "2", "Authorization": f"Bearer {self.server.token}"})
        self.assertEqual((status, json.loads(data)["code"]), (403, "LIVE_FORBIDDEN"))
        for method in ("patch", "save", "web_status", "ping"):
            status, _, _ = lan.request("POST", f"/v1/{method}", b"{}", {"Content-Length": "2", "Authorization": f"Bearer {self.server.token}"})
            self.assertEqual(status, 403, method)
        self.assertEqual(LiveClient(self.server.url, self.server.token).call("ping")["ok"], True)   # loopback still works
        # The discovery file never mentions the LAN listener or any token for it.
        record = json.dumps(self.server.info())
        self.assertNotIn(str(lan_port), record)

    def test_every_device_joins_and_tokens_stay_on_their_listener(self):
        lan_port = int(self.server.enable_lan(True)[0].split(":")[2].split("/")[0])
        lan, local = Browser(self, lan_port), Browser(self, self.port)
        self.assertEqual(lan.api("status", {})[0], 401)                           # nothing works before joining
        status, body, response = lan.join()
        self.assertEqual((status, body["device"]["listener"]), (200, "lan"))
        self.assertIn(f"chiploom_web_{lan_port}=", response.headers["Set-Cookie"])
        self.assertEqual(lan.api("status", {})[0], 200)
        self.assertEqual(lan.api("patch", {"ops": [put(1, 0, "C-2 01 ...")], "base_revision": 0})[0], 200)
        self.assertEqual(self.session.changes()["entries"][-1]["author"], "human-web")
        token = lan.cookie.split("=", 1)[1]
        local.cookie, local.csrf = f"chiploom_web_{self.port}={token}", lan.csrf
        self.assertEqual(local.api("status", {})[0], 401)                         # a LAN token is not a loopback token
        self.assertEqual(lan.join()[0], 200)

    def test_turning_the_lan_off_closes_the_listener_and_its_devices(self):
        url = self.server.enable_lan(True)[0]
        lan_port = int(url.split(":")[2].split("/")[0])
        lan, local = Browser(self, lan_port), Browser(self, self.port)
        lan.join()
        local.join()
        self.assertEqual(self.server.enable_lan(False), [])
        self.assertFalse(self.server.lan_enabled)
        with self.assertRaises(OSError):
            lan.request("GET", "/web/")
        self.assertEqual(local.api("status", {})[0], 200)                         # loopback devices stay connected
        self.assertEqual([item["listener"] for item in self.session.web_devices()], ["loopback"])
        self.assertEqual(self.server.web_urls()["lan"], [])

    def test_lan_before_start_and_the_constructor_flag(self):
        with LiveServer(self.session, lan=True, home=self.dir / "other") as other:
            self.assertTrue(other.lan_enabled)
            self.assertEqual(len(other.web_urls()["lan"]), 1)
            self.assertEqual(Browser(self, int(other.web_urls()["lan"][0].split(":")[2].split("/")[0])).request("GET", "/web/")[0], 200)
        late = LiveServer(self.session, home=self.dir / "late")
        late.enable_lan(True)
        self.assertTrue(late.lan_enabled)
        self.assertEqual(late._lan, [])                                           # nothing is bound until start()
        late.start()
        self.addCleanup(late.stop)
        self.assertEqual(len(late.web_urls()["lan"]), 1)

    def test_only_private_addresses_can_be_offered(self):
        for host in ("8.8.8.8", "0.0.0.0", "::", "127.0.0.1", "localhost", "example.com", "169.254.1.1", "224.0.0.1", "::1", "", "192.168.1"):
            with self.assertRaises(ValidationError) as caught:
                self.server.enable_lan(True, host=host)
            self.assertEqual(caught.exception.code, "LIVE_HOST", host)
        self.assertFalse(self.server.lan_enabled)
        for host in ("10.1.2.3", "172.16.0.9", "172.31.255.1", "192.168.0.10"):
            self.assertTrue(live._private_lan_address(host), host)
        for host in ("172.32.0.1", "100.64.0.1", "11.0.0.1", "192.169.0.1", "fe80::1"):
            self.assertFalse(live._private_lan_address(host), host)
        with self.assertRaises(ValidationError):
            LiveServer(self.session, host="0.0.0.0")                              # the agent listener is still loopback-only
        with self.assertRaises(ValidationError):
            LiveServer(self.session, host="192.168.1.20")

    def test_no_private_address_is_a_clear_error_and_leaves_the_server_running(self):
        with mock.patch.object(live, "lan_addresses", lambda: []):
            with self.assertRaises(ValidationError) as caught:
                self.server.enable_lan(True)
        self.assertEqual(caught.exception.code, "LIVE_LAN")
        self.assertEqual(self.server._lan, [])
        self.assertEqual(LiveClient(self.server.url, self.server.token).call("ping")["ok"], True)

    def test_a_busy_port_is_reported(self):
        first = self.server.enable_lan(True)[0]
        busy = int(first.split(":")[2].split("/")[0])
        with LiveServer(self.session, home=self.dir / "second") as second:
            with self.assertRaises(ValidationError) as caught:
                second.enable_lan(True, port=busy)
            self.assertEqual(caught.exception.code, "LIVE_LAN")
            self.assertEqual(second._lan, [])

    def test_lan_peers_must_be_private_and_the_host_header_must_be_ours(self):
        url = self.server.enable_lan(True)[0]
        port = int(url.split(":")[2].split("/")[0])
        lan = Browser(self, port)
        for peer, expected in (("192.168.1.20", 200), ("10.0.0.5", 200), ("169.254.3.4", 200), ("127.0.0.1", 200),
                               ("203.0.113.9", 403), ("8.8.8.8", 403), ("2001:db8::1", 403)):
            with mock.patch.object(live._Handler, "peer", lambda self, peer=peer: peer):
                self.assertEqual(lan.request("GET", "/web/")[0], expected, peer)
        for host in ("evil.example", f"evil.example:{port}", f"192.168.1.20:{port}", "192.168.1.20"):
            self.assertEqual(lan.request("GET", "/web/", None, {"Host": host})[0], 403, host)
        self.assertEqual(lan.request("GET", "/web/", None, {"Host": f"127.0.0.1:{port}"})[0], 200)

    def test_client_allowed_truth_table(self):
        for address, role, expected in (("127.0.0.1", "loopback", True), ("::1", "loopback", True), ("192.168.1.2", "loopback", False),
                                        ("192.168.1.2", "lan", True), ("fe80::1", "lan", True), ("8.8.8.8", "lan", False),
                                        ("::ffff:10.0.0.1", "lan", True), ("::ffff:8.8.8.8", "lan", False), ("garbage", "lan", False)):
            self.assertEqual(gateway.client_allowed(address, role), expected, (address, role))


# --- identity: logo, emblem, palette, type ---------------------------------------------------------------------------------

def luminance(color: str) -> float:
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class IdentityTests(WebCase):
    def test_the_wordmark_is_the_bundled_logo(self):
        status, response, body = self.browser.request("GET", "/web/logo.png")
        self.assertEqual((status, response.headers["Content-Type"]), (200, "image/png"))
        self.assertEqual(body, (ROOT / "tracker4agents" / "assets" / "chiploom-logo.png").read_bytes())
        self.assertIn("max-age", response.headers["Cache-Control"])
        self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])

    def test_the_emblem_favicon_is_generated_from_the_logo_with_the_standard_library(self):
        status, response, body = self.browser.request("GET", "/web/emblem.png")
        self.assertEqual((status, response.headers["Content-Type"]), (200, "image/png"))
        self.assertTrue(body.startswith(bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])))
        width, height, depth, color = __import__("struct").unpack(">IIBB", body[16:26])
        self.assertEqual((width, height, depth, color), (brand.EMBLEM_SIZE, brand.EMBLEM_SIZE, 8, 6))
        pixels = __import__("zlib").decompress(b"".join(chunk for kind, chunk in brand._chunks(body) if kind == b"IDAT"))
        rows = [pixels[i * (1 + width * 4) + 1:(i + 1) * (1 + width * 4)] for i in range(height)]
        opaque = sum(1 for row in rows for i in range(3, len(row), 4) if row[i] > 200)
        clear = sum(1 for row in rows for i in range(3, len(row), 4) if row[i] == 0)
        self.assertGreater(opaque, width * height * 0.4)      # the emblem fills most of the square
        self.assertGreater(clear, 0)                          # and the corners stay transparent
        crop = brand._crop_rgba(brand.logo_png(), brand.EMBLEM_BOX)                    # the desktop's logo.copy(100, 160, 520, 410)
        self.assertEqual((len(crop), len(crop[0])), (410, 520 * 4))
        self.assertEqual(brand.emblem_png(), body)                                       # cached

    def test_the_palette_is_generated_from_themes_py(self):
        status, response, body = self.browser.request("GET", "/web/theme.css")
        css = body.decode("utf-8")
        self.assertEqual((status, response.headers["Content-Type"]), (200, "text/css; charset=utf-8"))
        for name in ("midnight", "light"):
            palette = THEMES[name]
            block = css.split(':root[data-theme="light"]')[1] if name == "light" else css.split(':root[data-theme="light"]')[0]
            for key, value in palette.items():
                if key == "name":
                    continue
                for color in value if key == "channels" else (value,):
                    self.assertIn(color, block, (name, key))
            for index, color in enumerate(palette["channels"], 1):
                self.assertIn(f"--ch{index}: {color};", block)
        self.assertIn("--bg: #101722;", css)                   # Midnight is the default
        self.assertIn("--mint: #56e7c6;", css)
        self.assertIn("--violet: #b09cff;", css)
        with mock.patch.dict(THEMES["midnight"], {"accent": "#123456"}):
            self.assertIn("--accent: #123456;", brand.theme_css().decode())      # follows the desktop at request time

    def test_the_stylesheet_has_no_palette_of_its_own_and_no_web_fonts(self):
        text = (ROOT / "tracker4agents" / "web" / "style.css").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"#[0-9a-fA-F]{3,8}")        # every colour comes from theme.css
        self.assertNotIn("@import", text)
        self.assertNotIn("@font-face", text)
        self.assertNotIn("url(", text)
        self.assertIn("Inter, ui-sans-serif, system-ui, -apple-system, \"Segoe UI\", sans-serif", text)
        self.assertIn("--mono: ui-monospace, Consolas, monospace;", text)
        page = (ROOT / "tracker4agents" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertLess(page.index("/web/theme.css"), page.index("/web/style.css"))
        self.assertIn("<html lang=\"en\">", page)                 # no theme attribute: dark (Midnight) until the script says otherwise
        script = (ROOT / "tracker4agents" / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn(': "dark",', script)

    def test_text_contrast_meets_wcag_aa_in_both_themes(self):
        for name in ("midnight", "light"):
            p = {**THEMES[name], **brand.BRAND[name]}
            for foreground, background in (("text", "panel"), ("text", "bg"), ("text", "button"), ("text", "hover"), ("text", "selected"),
                                           ("text", "header"), ("text", "beat"), ("muted", "panel"), ("muted", "bg"), ("muted", "header"),
                                           ("muted", "beat"), ("primary_text", "primary"), ("accent", "panel"), ("accent", "bg"),
                                           ("accent", "header"), ("error", "panel"), ("text", "agent_change"), ("text", "proposal"),
                                           ("text", "human_change"), ("mint", "bg"), ("mint", "panel"), ("violet", "panel")):
                self.assertGreaterEqual(contrast(p[foreground], p[background]), 4.5, (name, foreground, background))
            for color in p["channels"]:
                for background in ("panel", "beat", "header"):
                    self.assertGreaterEqual(contrast(color, p[background]), 4.5, (name, color, background))


# --- command line --------------------------------------------------------------------------------------------------------

class CliTests(Base):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(live, "lan_addresses", lambda: ["127.0.0.1"])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.parser = argparse.ArgumentParser(prog="chiploom")
        live_cli.add_parser(self.parser.add_subparsers(dest="command", required=True))

    def run_cli(self, *argv, **kwargs):
        return live_cli.run(self.parser.parse_args(["live", *argv]), **kwargs)

    def serve(self, *flags):
        stop, announced, outcome = threading.Event(), [], {}
        args = self.parser.parse_args(["live", "serve", str(self.project), *flags])
        worker = threading.Thread(target=lambda: outcome.update(live_cli.run(args, stop, announced.append)))
        worker.start()

        def finish():
            stop.set()
            worker.join(10)
            return outcome

        for _ in range(200):
            if announced or not worker.is_alive():
                break
            threading.Event().wait(0.05)
        self.assertTrue(announced, "serve did not announce itself")
        return announced[0], finish

    def test_serve_without_web_flags_prints_no_web_block(self):
        info, finish = self.serve()
        try:
            self.assertEqual(info["event"], "listening")
            self.assertNotIn("web", info)
            self.assertTrue(info["web_url"].endswith("/web/"))
            self.assertNotIn("token", info)
        finally:
            finish()

    def test_serve_web_prints_the_address_and_no_code(self):
        info, finish = self.serve("--web")
        try:
            web = info["web"]
            self.assertEqual((web["local"], web["lan"], web["lan_enabled"]), (info["web_url"], [], False))
            self.assertNotIn("pairing", web)
            self.assertEqual(web["message"], f"Open {info['web_url']} in a browser.")
            self.assertNotIn("token", json.dumps(info))
            port = int(info["url"].rsplit(":", 1)[1])
            self.assertEqual(Browser(self, port).join()[0], 200)       # opening the address is enough
        finally:
            finish()

    def test_serve_lan_prints_the_lan_url_and_the_plain_http_warning(self):
        info, finish = self.serve("--lan")
        try:
            web = info["web"]
            self.assertTrue(web["lan_enabled"])
            self.assertEqual(len(web["lan"]), 1)
            self.assertIn(web["lan"][0], web["message"])
            self.assertIn("plain HTTP", web["warning"])
            lan_port = int(web["lan"][0].split(":")[2].split("/")[0])
            self.assertEqual(Browser(self, lan_port).join()[0], 200)
        finally:
            outcome = finish()
        self.assertEqual(outcome["event"], "stopped")

    def test_serve_option_conflicts(self):
        for flags in (["--no-web", "--web"], ["--no-web", "--lan"], ["--lan-host", "10.0.0.2"]):
            with self.assertRaises(ValidationError) as caught:
                self.run_cli("serve", str(self.project), *flags)
            self.assertEqual(caught.exception.code, "LIVE_PARAMS", flags)
        with self.assertRaises(ValidationError) as caught:
            self.run_cli("serve", str(self.project), "--lan", "--lan-host", "8.8.8.8")
        self.assertEqual(caught.exception.code, "LIVE_HOST")

    def test_live_web_prints_the_address_and_lists_connected_browsers(self):
        with LiveServer(self.session) as server:
            result = self.run_cli("web")
            self.assertEqual(result["message"], f"Open {server.web_urls()['local']} in a browser.")
            self.assertNotIn("devices", result)
            self.assertFalse({"code", "display", "ttl", "pairing", "pending_codes"} & set(result))
            self.assertEqual(Browser(self, int(server.url.rsplit(":", 1)[1])).join()[0], 200)
            status = self.run_cli("web", "--status")
            self.assertEqual([item["id"] for item in status["devices"]], ["d1"])

    def test_live_web_has_no_ttl_or_revoke_options(self):
        for flags in (["--ttl", "60"], ["--revoke"]):
            with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
                self.run_cli("web", *flags)

    def test_live_web_refuses_when_the_studio_is_off(self):
        with LiveServer(self.session, web=False):
            with self.assertRaises(ValidationError) as caught:
                self.run_cli("web")
            self.assertEqual(caught.exception.code, "LIVE_WEB_OFF")

    def test_live_web_on_a_lan_session_shows_the_lan_address_first(self):
        with LiveServer(self.session, lan=True) as server:
            result = self.run_cli("web")
            self.assertEqual(result["lan"], server.web_urls()["lan"])
            self.assertIn(result["lan"][0], result["message"])
            self.assertIn("plain HTTP", result["warning"])


# --- wide songs and XM: the grid follows the module ------------------------------------------------------------------------

def build_module(kind: str):
    """pixel_rush as a 4-channel MOD, an 8-channel MOD, or a 6-channel XM with an extra 32-row pattern."""
    from tracker4agents import convert, project
    from tracker4agents.model import Module, Pattern, cell
    base = project.load(EXAMPLE)
    if kind == "mod4":
        return base
    if kind == "mod8":
        module = Module(base.title, base.samples, [Pattern(p.name, dict(p.cells), 64) for p in base.patterns],
                        list(base.orders), base.metadata, 8, "mod")
        module.patterns[0].put(0, 6, cell("C-2", 1, "000"))
        module.patterns[0].put(0, 7, cell("E-2", 1, "C20"))
        return module
    module, _ = convert.mod_to_xm(base)            # its instruments; the patterns below are written for this test
    module.channels = 6
    long = Pattern("Long", {}, 64)
    for row, channel, note in ((0, 0, "C-4"), (0, 1, "E-4"), (4, 2, "G-4"), (8, 3, "C-5"), (12, 0, "D-4")):
        long.put(row, channel, cell(note, 1 + channel, "000", "xm", 0x40))
    short = Pattern("Short", {}, 32)
    short.put(0, 4, cell("C-4", 1, "000", "xm", 0x40))
    short.put(8, 5, cell("E-4", 2, "A0F", "xm", 0))
    module.patterns, module.orders = [long, short], [0, 1]
    return module


class FormatCase(Base):
    kind = "mod4"

    def setUp(self):
        super().setUp()
        from tracker4agents import project
        project.write_json(self.project, project.to_dict(build_module(self.kind)))
        self.document = Document.open(self.project)
        self.session = LiveSession(self.document)
        self.server = LiveServer(self.session).start()
        self.addCleanup(self.server.stop)
        self.port = self.server._httpd.server_address[1]
        self.browser = Browser(self, self.port)
        self.assertEqual(self.browser.join()[0], 200)

    def overview(self):
        return self.browser.api("score", {})[1]

    def pattern(self, index: int):
        rows = self.overview()["patterns"][index]["rows"]
        return self.browser.api("score", {"pattern": index, "start": 0, "rows": rows})[1]

    def render(self, **payload):
        return self.browser.post("/web/api/render", payload)


class FourChannelModTests(FormatCase):
    def test_a_four_channel_mod_is_unchanged(self):
        overview = self.overview()
        profile = overview["profile"]
        self.assertEqual((profile["format"], profile["channels"], profile["volume_column"], profile["key_off"]), ("mod", 4, False, None))
        self.assertEqual((profile["notes"][0], profile["notes"][-1], len(profile["notes"])), ("C-1", "B-3", 36))
        self.assertEqual("".join(profile["effects"]), "012345679ABCDEF")      # no 8xy; E is the extended family
        self.assertEqual((profile["sample_label"], profile["max_transpose"]), ("sample", 35))
        self.assertEqual({item["rows"] for item in overview["patterns"]}, {64})
        lines = self.pattern(0)["lines"]
        self.assertEqual(len(lines), 64)
        self.assertEqual([len(line.split(" | ")) for line in lines[:3]], [5, 5, 5])        # row label + four cells
        self.assertEqual(len(lines[0].split(" | ")[1].split(" ")), 3)                       # NOTE SS EEE
        status = self.browser.api("status", {})[1]
        self.assertEqual((status["format"], status["channels"]), ("mod", 4))
        status, body, _ = self.browser.api("patch", {"ops": [put(1, 0, "C-2 01 C20")], "base_revision": 0})
        self.assertEqual(status, 200)
        self.assertEqual(self.pattern(0)["lines"][1].split(" | ")[1], "C-2 01 C20")
        self.assertEqual(self.browser.api("patch", {"ops": [put(1, 4, "C-2 01 ...")], "base_revision": 1})[0], 422)   # no 5th channel
        self.assertEqual(self.browser.api("patch", {"ops": [put(64, 0, "C-2 01 ...")], "base_revision": 1})[0], 422)  # no row 64

    @unittest.skipUnless(HAS_XMP, "libxmp is not available")
    def test_render_still_takes_four_mutes(self):
        status, response, data = self.render(order=1, seconds=2, audible=[True, False, True, True])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response.headers["X-ChipLoom-Render"])["audible"], [True, False, True, True])
        status, _, data = self.render(order=1, seconds=2, audible=[True] * 8)
        self.assertEqual((status, json.loads(data)["code"]), (422, "LIVE_RENDER"))


class EightChannelModTests(FormatCase):
    kind = "mod8"

    def test_the_grid_has_eight_tracks(self):
        overview = self.overview()
        self.assertEqual((overview["profile"]["channels"], overview["profile"]["format"]), (8, "mod"))
        lines = self.pattern(0)["lines"]
        self.assertEqual(len(lines), 64)
        cells = lines[0].split(" | ")[1:]
        self.assertEqual(len(cells), 8)
        self.assertEqual((cells[6], cells[7]), ("C-2 01 ...", "E-2 01 C20"))
        status = self.browser.api("status", {})[1]
        self.assertEqual((status["format"], status["channels"]), ("mod", 8))

    def test_editing_the_upper_channels(self):
        status, body, _ = self.browser.api("patch", {"ops": [put(3, 7, "G-2 01 C30"), put(4, 5, "A-2 01 ...")], "base_revision": 0, "label": "Wide"})
        self.assertEqual(status, 200, body)
        cells = self.pattern(0)["lines"][3].split(" | ")[1:]
        self.assertEqual(cells[7], "G-2 01 C30")
        entry = self.session.changes()["entries"][-1]
        self.assertEqual(entry["author"], "human-web")
        self.assertEqual({item["channel"] for item in entry["diff"]["cells"]}, {7, 5})
        for op in ({"op": "clear", "pattern": 0, "row": 3, "rows": 2, "channel": 5, "channels": 3},
                   {"op": "copy", "pattern": 0, "row": 3, "rows": 1, "channel": 7, "channels": 1, "to_channel": 0},
                   {"op": "move", "pattern": 0, "row": 4, "rows": 1, "channel": 5, "channels": 1, "to_row": 9, "to_channel": 6},
                   {"op": "transpose", "pattern": 0, "row": 0, "rows": 4, "channel": 6, "channels": 2, "semitones": 12}):
            self.assertEqual(self.browser.api("patch", {"ops": [op], "base_revision": self.session.revision})[0], 200, op)
        self.assertEqual(self.browser.api("patch", {"ops": [{"op": "clear", "pattern": 0, "channel": 7, "channels": 2}], "base_revision": self.session.revision})[0], 422)

    @unittest.skipUnless(HAS_XMP, "libxmp is not available")
    def test_render_with_eight_mutes(self):
        status, response, everything = self.render(order=0, seconds=2)
        info = json.loads(response.headers["X-ChipLoom-Render"])
        self.assertEqual((status, info["audible"]), (200, [True] * 8))
        only_extra = [False] * 6 + [True, True]
        status, response, extra = self.render(order=0, seconds=2, audible=only_extra)
        self.assertEqual((status, json.loads(response.headers["X-ChipLoom-Render"])["audible"]), (200, only_extra))
        self.assertNotEqual(read_wav(everything)[4], read_wav(extra)[4])
        self.assertEqual(self.render(audible=[True] * 4)[0], 422)                 # four states for eight channels
        self.assertEqual(self.render(audible=[False] * 8)[0], 422)
        self.session.update_context(audible=[False] * 7 + [True])                # the window's mutes apply when the length fits
        _, response, _ = self.render(order=0, seconds=1)
        self.assertEqual(json.loads(response.headers["X-ChipLoom-Render"])["audible"], [False] * 7 + [True])
        with self.assertRaises(ValidationError):
            self.session.update_context(audible=[True] * 4)

    @unittest.skipUnless(HAS_FFMPEG, "FFmpeg is not available")
    def test_ffmpeg_fallback_renders_wide_mods(self):
        module = self.session.snapshot()
        data, info = web_render.render_wav(module, 0, 0, 2.0, [True] * 6 + [False, True], engine="ffmpeg")
        self.assertEqual((info["engine"], read_wav(data)[0]), ("ffmpeg", 2))


class XmSongTests(FormatCase):
    kind = "xm"

    def test_profile_and_grid_shape(self):
        overview = self.overview()
        profile = overview["profile"]
        self.assertEqual((profile["format"], profile["channels"], profile["volume_column"], profile["key_off"]), ("xm", 6, True, "==="))
        self.assertEqual((profile["notes"][0], profile["notes"][-1], len(profile["notes"])), ("C-0", "B-7", 96))
        self.assertIn("G", profile["effects"])
        self.assertIn("X", profile["effects"])
        self.assertNotIn("I", profile["effects"])
        self.assertEqual((profile["sample_label"], profile["sample_slots"], profile["max_transpose"]), ("instrument", len(self.session.snapshot().samples), 95))
        rows = [item["rows"] for item in overview["patterns"]]
        self.assertEqual(rows, [64, 32])
        short = self.pattern(len(rows) - 1)
        self.assertEqual(len(short["lines"]), 32)
        first = short["lines"][0].split(" | ")
        self.assertEqual(len(first), 7)                                             # row label + six cells
        self.assertEqual(first[5], "C-4 01 40 ...")                                  # NOTE II VV EEE: four tokens per cell
        self.assertEqual(short["lines"][8].split(" | ")[6], "E-4 02 -- A0F")
        self.assertEqual(len(first[1].split(" ")), 4)
        status = self.browser.api("status", {})[1]
        self.assertEqual((status["format"], status["channels"]), ("xm", 6))

    def test_editing_with_the_volume_column_and_key_off(self):
        last = len(self.overview()["patterns"]) - 1
        status, body, _ = self.browser.api("patch", {"ops": [put(31, 5, "C-4 01 40 A0F", last), put(30, 4, "=== -- -- ...", last),
                                                              put(2, 1, "G#5 03 C8 G40", last), put(3, 0, "C-4 01 X21", last)],
                                                    "base_revision": 0, "label": "XM edit"})
        self.assertEqual(status, 200, body)
        lines = self.pattern(last)["lines"]
        self.assertEqual(lines[31].split(" | ")[6], "C-4 01 40 A0F")
        self.assertEqual(lines[30].split(" | ")[5], "=== -- -- ...")
        self.assertEqual(lines[2].split(" | ")[2], "G#5 03 C8 G40")
        self.assertEqual(lines[3].split(" | ")[1], "C-4 01 -- X21")
        entry = self.session.changes()["entries"][-1]
        self.assertEqual((entry["author"], entry["label"]), ("human-web", "XM edit"))
        self.assertIn("C-4 01 40 A0F", entry["summary"][0] + entry["summary"][1] + entry["summary"][2] + entry["summary"][3])
        # shape and vocabulary errors come back as readable 422s
        for text, code in (("C-4 01 0F ...", "XM_VOLUME_COLUMN"), ("C-4 01 55 ...", "XM_VOLUME_COLUMN"), ("C-4 01 40 I00", "EFFECT_UNSUPPORTED"),
                           ("C-9 01 40 ...", "NOTE_UNKNOWN"), ("C-4 99 40 ...", "SAMPLE_REF"), ("ZZZ", None)):
            status, body, _ = self.browser.api("patch", {"ops": [put(5, 0, text, last)], "base_revision": self.session.revision})
            self.assertEqual(status, 422, text)
            if code:
                self.assertEqual(body["code"], code, text)
        self.assertEqual(self.browser.api("patch", {"ops": [put(32, 0, "C-4 01 ...", last)], "base_revision": self.session.revision})[0], 422)
        self.assertEqual(self.browser.api("patch", {"ops": [put(0, 6, "C-4 01 ...", last)], "base_revision": self.session.revision})[0], 422)
        self.assertEqual(self.browser.api("patch", {"ops": [put(63, 5, "C-4 01 ...", 0)], "base_revision": self.session.revision})[0], 200)   # a 64-row pattern

    def test_block_operations_follow_the_xm_ranges(self):
        last = len(self.overview()["patterns"]) - 1
        base = {"pattern": last, "row": 8, "rows": 1, "channel": 5, "channels": 1}
        for op, expected in (({"op": "transpose", **base, "semitones": 36}, 200), ({"op": "transpose", **base, "semitones": 96}, 422),
                             ({"op": "move", **base, "to_row": 31}, 200), ({"op": "move", **{**base, "row": 31}, "to_row": 32}, 422),
                             ({"op": "copy", **{**base, "row": 31}, "to_pattern": 0, "to_row": 63}, 200)):
            self.assertEqual(self.browser.api("patch", {"ops": [op], "base_revision": self.session.revision})[0], expected, op)

    def test_a_conflict_report_spells_the_xm_cell_with_its_volume_column(self):
        last = len(self.overview()["patterns"]) - 1
        LiveClient(self.server.url, self.server.token).call("patch", ops=[put(4, 0, "D-4 02 30 C20", last)], label="Agent")
        status, body, _ = self.browser.api("patch", {"ops": [put(4, 0, "E-4 02 40 ...", last)], "base_revision": 0})
        self.assertEqual((status, body["code"]), (409, "LIVE_CONFLICT"))
        self.assertEqual((body["conflicts"][0]["current"], body["conflicts"][0]["yours"]), ("D-4 02 30 C20", "E-4 02 40 ..."))

    def test_the_page_offers_no_sample_or_library_edits(self):
        script = (ROOT / "tracker4agents" / "web" / "app.js").read_text(encoding="utf-8")
        import re
        used = set(re.findall(r'op: "([a-z_]+)"', script))
        self.assertTrue(used <= set(WEB_OPS), used)
        status, body, _ = self.browser.api("patch", {"ops": [{"op": "sample_gain", "slot": 1, "db": 3}], "base_revision": 0})
        self.assertEqual((status, body["code"]), (422, "LIVE_PARAMS"))               # the browser may only edit cells
        with self.assertRaises(ValidationError) as caught:                            # and the core refuses MOD sample edits on an XM
            self.session.apply_patch([{"op": "sample_gain", "slot": 1, "db": 3}])
        self.assertEqual(caught.exception.code, "XM_OP_UNSUPPORTED")

    @unittest.skipUnless(HAS_XMP, "libxmp is not available")
    def test_render_xm_from_a_row_with_six_mutes(self):
        last = len(self.overview()["patterns"]) - 1
        order = self.session.snapshot().orders.index(last)
        status, response, everything = self.render(order=order, row=8, seconds=2)
        info = json.loads(response.headers["X-ChipLoom-Render"])
        self.assertEqual((status, info["engine"], info["order"], info["row"], info["audible"]), (200, "libxmp", order, 8, [True] * 6))
        self.assertAlmostEqual(read_wav(everything)[3] / 44100, 2.0, delta=0.2)
        status, response, muted = self.render(order=order, row=0, seconds=2, audible=[False, False, False, False, True, False])
        self.assertEqual(status, 200)
        self.assertEqual(self.render(order=order, row=32, seconds=1)[0], 422)        # the pattern has 32 rows
        self.assertEqual(self.render(order=0, row=63, seconds=1)[0], 200)            # but the first order's pattern has 64
        self.assertEqual(self.render(audible=[True] * 4)[0], 422)
        status, _, data = self.render(order=order, seconds=1, audible=[True] * 5)
        self.assertEqual((status, json.loads(data)["code"]), (422, "LIVE_RENDER"))

    @unittest.skipUnless(HAS_FFMPEG, "FFmpeg is not available")
    def test_ffmpeg_fallback_renders_an_xm(self):
        module = self.session.snapshot()
        data, info = web_render.render_wav(module, 0, 0, 2.0, [True, False] + [True] * 4, engine="ffmpeg")
        self.assertEqual((info["engine"], read_wav(data)[0]), ("ffmpeg", 2))

    def test_muted_copy_keeps_the_shape_and_the_flow_commands(self):
        from tracker4agents.model import Cell
        module = self.session.snapshot()
        last = len(module.patterns) - 1
        module.patterns[last].put(1, 1, Cell(49, 1, 11, 0, 0x40))       # note + volume + Bxx: only the Bxx survives a mute
        module.patterns[last].put(2, 1, Cell(49, 1, 14, 0x62))          # E62: a pattern loop is flow
        module.patterns[last].put(3, 1, Cell(49, 1, 12, 0x20))          # Cxx is not
        copy = web_render._muted_copy(module, (True, False, True, True, True, True))
        self.assertEqual((copy.channels, copy.format, [p.rows for p in copy.patterns][-1]), (6, "xm", 32))
        self.assertEqual(copy.patterns[last].get(1, 1), Cell(0, 0, 11, 0, 0))
        self.assertEqual(copy.patterns[last].get(2, 1), Cell(0, 0, 14, 0x62, 0))
        self.assertEqual(copy.patterns[last].get(3, 1), Cell())
        self.assertEqual(copy.patterns[last].get(0, 4), module.patterns[last].get(0, 4))
        self.assertIs(web_render._muted_copy(module, (True,) * 6), module)


class CellCodecTests(unittest.TestCase):
    """cells.js against patch.cell_text / patch.parse_cell, through Node when it is installed."""

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_the_javascript_codec_agrees_with_the_python_one(self):
        import subprocess
        from tracker4agents.model import Cell, Module, Pattern, Sample
        from tracker4agents.patch import cell_text, parse_cell
        from tracker4agents.web.api import profile
        mod_profile = profile(Module("t", [Sample("", ())] * 31, [Pattern()], [0]))
        xm_profile = profile(Module("t", [Sample("", ())] * 128, [Pattern()], [0], {}, 4, "xm"))
        cases = []
        for text in ("--- -- ...", "C-2 01 ...", "G#3 1F C20", "B-3 0A E5F", "--- 03 037", "A-1 -- D63", "C-1 -- F06"):
            cases.append({"text": text, "profile": mod_profile})
        for cell in (Cell(), Cell(1, 1, 0, 0, 0x10), Cell(97, 0, 0, 0, 0), Cell(61, 2, 16, 0x40, 0xC8), Cell(96, 128, 33, 0x21, 0xF3),
                     Cell(49, 0, 20, 0, 0x50), Cell(50, 5, 29, 0xFF, 0x60), Cell(0, 0, 0, 0, 0x7F), Cell(25, 1, 14, 0x62, 0)):
            cases.append({"text": cell_text(cell, "xm"), "profile": xm_profile})
        cases += [{"text": "C-4 01 40", "profile": xm_profile, "as": "C-4 01 40 ..."}, {"text": "C-4 01 A0F", "profile": xm_profile, "as": "C-4 01 -- A0F"},
                  {"text": "c-4 01 40 a0f", "profile": xm_profile, "as": "C-4 01 40 A0F"}, {"text": "C-2", "profile": mod_profile, "as": "C-2 -- ..."},
                  {"text": "  g#2  0a  c20 ", "profile": mod_profile, "as": "G#2 0A C20"}, {"text": "", "profile": mod_profile, "as": "--- -- ..."}]
        errors = [("C-0 01 ...", mod_profile, "ed.err.note"), ("C-8 01 40 ...", xm_profile, "ed.err.note"), ("C-2 20 ...", mod_profile, "ed.err.sample"),
                  ("C-4 81 40 ...", xm_profile, "ed.err.sample"), ("C-4 01 0F ...", xm_profile, "ed.err.volume"), ("C-4 01 55 ...", xm_profile, "ed.err.volume"),
                  ("C-2 01 800", mod_profile, "ed.err.effect"), ("C-4 01 40 I00", xm_profile, "ed.err.effect"), ("C-2 01 G00", mod_profile, "ed.err.format"),
                  ("C-2 01 ... ...", mod_profile, "ed.err.format"), ("C-2 011 ...", mod_profile, "ed.err.format"), ("C-4 01 40 A0F extra", xm_profile, "ed.err.format"),
                  ("=== -- -- ...", mod_profile, "ed.err.note")]
        cases += [{"text": text, "profile": prof} for text, prof, _ in errors]
        script = ("const C = require(process.argv[1]); const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
                  "console.log(JSON.stringify(input.map(c => { const r = C.parse(c.text, c.profile); "
                  "return r.error ? {error: r.error} : {text: C.format(r.cell, c.profile.format), cell: r.cell}; })));")
        done = subprocess.run(["node", "-e", script, str(ROOT / "tracker4agents" / "web" / "cells.js")], input=json.dumps(cases),
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        results = json.loads(done.stdout)
        expected_errors = {(text, prof["format"]): key for text, prof, key in errors}
        for case, result in zip(cases, results):
            fmt = case["profile"]["format"]
            if (case["text"], fmt) in expected_errors:
                self.assertEqual(result.get("error"), expected_errors[case["text"], fmt], case["text"])
                continue
            self.assertNotIn("error", result, case)
            self.assertEqual(result["text"], case.get("as", case["text"]), case)
            # the Python codec reads the same text to the same cell, and writes the same text back
            self.assertEqual(cell_text(parse_cell(result["text"], fmt), fmt), result["text"], case)

    def test_channel_colours_stay_readable_and_distinct(self):
        for name in ("midnight", "light"):
            palette = THEMES[name]
            self.assertEqual([brand.channel_color(name, i) for i in range(4)], list(palette["channels"]))
            colours = [brand.channel_color(name, i) for i in range(brand.MAX_CHANNELS)]
            self.assertEqual(len(set(colours[:12])), 12)                              # the first twelve tracks are all different
            for index, colour in enumerate(colours):
                for background in ("panel", "beat", "header"):
                    self.assertGreaterEqual(contrast(colour, palette[background]), 4.5, (name, index, background))
        css = brand.theme_css().decode()
        self.assertIn(f"--ch5: {brand.channel_color('midnight', 4)};", css)
        self.assertIn(f"--ch32: {brand.channel_color('light', 31)};", css)
        style = (ROOT / "tracker4agents" / "web" / "style.css").read_text(encoding="utf-8")
        for index in (1, 5, 17, 32):
            self.assertIn(f".c{index}{{--tone:var(--ch{index})}}", style)
        self.assertEqual(brand.mix("#000000", "#ffffff", 0.5), "#808080")


# --- the session API a window uses ---------------------------------------------------------------------------------------

class SessionApiTests(Base):
    def test_snapshot_is_an_independent_copy(self):
        snapshot = self.session.snapshot()
        self.session.apply_patch([put(1, 0, "C-2 01 ...")])
        self.assertEqual(snapshot.patterns[0].get(1, 0).text(), "--- 00 000")
        self.assertEqual(self.session.snapshot().patterns[0].get(1, 0).text(), "C-2 01 000")

    def test_web_devices_have_the_documented_fields(self):
        self.session.web.join(listener="loopback", agent="UA", name="Tablet")
        (device,) = self.session.web_devices()
        self.assertEqual(set(device), {"id", "name", "agent", "listener", "joined_at", "last_seen", "expires_at"})
        self.assertTrue(device["joined_at"].endswith("Z"))
        self.assertFalse(hasattr(self.session, "create_pairing") or hasattr(self.session, "revoke_web"))

    def test_web_edits_count_as_the_owner_in_the_journal_summary(self):
        self.session.apply_patch([put(1, 0, "C-2 01 ...")], author="human-web")
        self.session.apply_patch([put(2, 0, "C-2 01 ...")], author="bard")
        summary = self.session.changes()["summary"]
        self.assertEqual((summary["human"]["entries"], summary["agent"]["entries"], summary["agent"]["authors"]), (1, 1, ["bard"]))

    def test_audible_context_is_validated(self):
        self.session.update_context(audible=[True, False, True, True])
        self.assertEqual(self.session.context()["audible"], [True, False, True, True])
        for bad in ([True] * 3, [1, 0, 1, 1], "yes", [None] * 4):
            with self.assertRaises(ValidationError):
                self.session.update_context(audible=bad)
        self.session.update_context(audible=None)
        self.assertNotIn("audible", self.session.context())


if __name__ == "__main__":
    unittest.main()
