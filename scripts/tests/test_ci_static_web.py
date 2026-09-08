# contract-test-file: tooling
"""Verify byte-exact static serving and SPA routing with synthetic files.

This focused unit fixture starts no OpenMates application, Docker or browser.
Compiled assets must retain correct content and missing assets must fail.
It protects the source-identity check from preview-server transformations.
See docs/architecture/isolated-github-tests.md.
"""

from functools import partial
from http.server import ThreadingHTTPServer
import threading
import urllib.error
import urllib.request

import pytest
from scripts.ci_static_web import StaticAppHandler


def test_static_build_is_byte_exact_and_routes_fall_back(tmp_path):
    html = b"<!doctype html><title>Synthetic candidate</title>"
    (tmp_path / "index.html").write_bytes(html)
    (tmp_path / "_app").mkdir()
    (tmp_path / "_app/main.js").write_text("export const source = 'candidate';")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(StaticAppHandler, directory=str(tmp_path))
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        for route in ("/", "/settings/tasks", "/dev/preview/task?chrome=0"):
            with urllib.request.urlopen(origin + route) as response:
                assert response.read() == html
        with urllib.request.urlopen(origin + "/_app/main.js") as response:
            assert "javascript" in response.headers["Content-Type"]
            assert response.read() == (tmp_path / "_app/main.js").read_bytes()
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(origin + "/_app/missing.js")
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_same_origin_api_preserves_real_request_and_error_response(tmp_path):
    from http.server import BaseHTTPRequestHandler
    observed = {}
    class Api(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.update(path=self.path, cookie=self.headers.get('Cookie'),
                            body=self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(409)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":"version_conflict"}')
    api = ThreadingHTTPServer(('127.0.0.1', 0), Api)
    class Frontend(StaticAppHandler):
        api_port = api.server_port
    web = ThreadingHTTPServer(('127.0.0.1', 0), partial(Frontend, directory=str(tmp_path)))
    workers = [threading.Thread(target=server.serve_forever, daemon=True) for server in (api, web)]
    for worker in workers:
        worker.start()
    try:
        request = urllib.request.Request(f'http://127.0.0.1:{web.server_port}/v1/settings/user/language',
                                         data=b'{"language":"de"}', headers={'Cookie':'synthetic-session=1'})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 409
        assert error.value.read() == b'{"error":"version_conflict"}'
        assert observed == {'path':'/v1/settings/user/language', 'cookie':'synthetic-session=1', 'body':b'{"language":"de"}'}
    finally:
        for server in (web, api):
            server.shutdown()
            server.server_close()
        for worker in workers:
            worker.join()
