from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools.serve_previews import PreviewHandler


class QuietHandler(PreviewHandler):
    def log_message(self, *args):
        pass


class PreviewRangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.payload = bytes(range(256)) * 8
        (Path(cls.temporary.name) / "test.wav").write_bytes(cls.payload)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=cls.temporary.name))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/test.wav"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temporary.cleanup()

    def test_normal_request_and_head_advertise_seek_support(self):
        with urlopen(self.url) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
            self.assertEqual(response.read(), self.payload)
        with urlopen(Request(self.url, method="HEAD")) as response:
            self.assertEqual(int(response.headers["Content-Length"]), len(self.payload))
            self.assertEqual(response.read(), b"")

    def test_partial_request_contains_exact_bytes(self):
        with urlopen(Request(self.url, headers={"Range": "bytes=17-61"})) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers["Content-Range"], "bytes 17-61/2048")
            self.assertEqual(int(response.headers["Content-Length"]), 45)
            self.assertEqual(response.read(), self.payload[17:62])

    def test_suffix_and_open_ended_requests(self):
        for header, expected in (("bytes=-19", self.payload[-19:]), ("bytes=2020-", self.payload[2020:])):
            with self.subTest(header=header), urlopen(Request(self.url, headers={"Range": header})) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), expected)

    def test_invalid_or_out_of_bounds_range_does_not_send_full_wav(self):
        for header in ("bytes=2048-", "bytes=42-20", "bytes=-0", "bytes=0-1,3-4"):
            with self.subTest(header=header), self.assertRaises(HTTPError) as context:
                urlopen(Request(self.url, headers={"Range": header}))
            self.assertEqual(context.exception.code, 416)
            self.assertEqual(context.exception.headers["Content-Range"], "bytes */2048")
            context.exception.close()
