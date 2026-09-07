"""Serve the candidate's adapter-static output on the isolated GitHub runner.

Vite preview serves SvelteKit's server output, which differs from the Docker SPA
artifact. This server uses the built static directory and its index fallback,
matching the self-host web image without compiling or transforming source.
See docs/architecture/isolated-github-tests.md.
"""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import urlsplit


class StaticAppHandler(SimpleHTTPRequestHandler):
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
