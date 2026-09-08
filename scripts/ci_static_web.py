"""Serve the candidate's adapter-static output on the isolated GitHub runner.

Vite preview serves SvelteKit's server output, which differs from the Docker SPA
artifact. This server uses the built static directory and its index fallback,
matching the self-host web image without compiling or transforming source.
See docs/architecture/isolated-github-tests.md.
"""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPConnection
from pathlib import Path
import sys
from urllib.parse import urlsplit


class StaticAppHandler(SimpleHTTPRequestHandler):
    api_port = 8000
    max_request_bytes = 32 * 1024 * 1024
    hop_headers = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                   "te", "trailer", "transfer-encoding", "upgrade"}

    def api_request(self):
        """Preserve same-origin /v1 requests against the real runner-local API."""
        if self.headers.get("Transfer-Encoding") or self.headers.get("Upgrade"):
            self.send_error(501, "Use the direct runner API for streaming uploads or WebSockets")
            return
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > self.max_request_bytes:
            self.send_error(413)
            return
        body = self.rfile.read(size) if size else None
        headers = {key: value for key, value in self.headers.items()
                   if key.lower() not in self.hop_headers | {"host"}}
        connection = HTTPConnection("127.0.0.1", self.api_port, timeout=60)
        sent_headers = False
        try:
            connection.request(self.command, self.path, body, headers)
            response = connection.getresponse()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in self.hop_headers:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            sent_headers = True
            if self.command != "HEAD":
                while chunk := response.read1(64 * 1024):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except OSError:
            self.log_error("Runner-local API proxy failed")
            if not sent_headers:
                self.send_error(502, "Runner-local API unavailable")
        finally:
            self.close_connection = True
            connection.close()

    def is_api(self):
        return urlsplit(self.path).path.startswith("/v1/")

    def do_GET(self):
        if self.is_api():
            self.api_request()
        else:
            super().do_GET()

    def do_HEAD(self):
        if self.is_api():
            self.api_request()
        else:
            super().do_HEAD()

    def do_POST(self):
        if self.is_api():
            self.api_request()
        else:
            self.send_error(405)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST

    def send_head(self):
        requested = Path(self.translate_path(self.path))
        if requested.is_dir():
            requested = requested / "index.html"
        if not requested.is_file():
            # Missing compiled assets must remain errors, not successful HTML.
            route = urlsplit(self.path).path
            if route.startswith("/_app/") or Path(route).suffix:
                self.send_error(404)
                return None
            self.path = "/index.html"
        return super().send_head()


def main():
    try:
        from ci_environment import require_runner
    except ModuleNotFoundError:
        from scripts.ci_environment import require_runner
    require_runner()
    directory = Path(sys.argv[1]).resolve()
    if not (directory / "index.html").is_file():
        raise RuntimeError("Candidate static web build is missing")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 5173),
        lambda *args, **kwargs: StaticAppHandler(*args, directory=str(directory), **kwargs),
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
