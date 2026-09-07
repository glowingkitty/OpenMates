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
