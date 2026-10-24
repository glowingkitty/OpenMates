#!/usr/bin/env python3
"""Wholly internal HTTPS origin for the isolated public-page reader contract.

The caller runs the actual reader against a public-address-shaped Docker peer;
this server never forwards requests and has no provider or account credentials.
"""
from __future__ import annotations

import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
from threading import Lock
from urllib.parse import urlsplit

HOSTNAME = "read-page.ci.test"
ADDRESS = "11.254.77.10"
SUBNET = "11.254.77.0/24"
PARAGRAPHS = [f"Section {index:03d}: The isolated reader preserves this public article paragraph in full, including its numbered evidence and ordinary factual text." for index in range(240)]
HTML = ("<!doctype html><html lang='en'><head><title>Complete public article</title></head>"
        "<body><nav>Fixture navigation</nav><article><h1>PUBLIC ARTICLE BEGIN</h1>" +
        "".join(f"<p>{paragraph}</p>" for paragraph in PARAGRAPHS) +
        "<p>PUBLIC ARTICLE END 7f531b</p></article></body></html>").encode()
_COUNTS: Counter[str] = Counter()
_HEADERS: list[dict] = []
_LOCK = Lock()


def prepare_tls(directory: Path) -> None:
    """Generate one disposable CA and a normally verified DNS-name certificate."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():
        raise RuntimeError("Fixture TLS directory cannot be a symlink")
    directory.chmod(0o700)
    commands = [
        ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=OpenMates disposable CI reader CA", "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-keyout", "ca.key", "-out", "ca.pem"],
        ["req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={HOSTNAME}", "-keyout", "server.key", "-out", "server.csr"],
        ["x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key", "-CAcreateserial", "-days", "2", "-extfile", "server.ext", "-out", "server.crt"],
    ]
    (directory / "server.ext").write_text(f"subjectAltName=DNS:{HOSTNAME}\nextendedKeyUsage=serverAuth\n")
    for command in commands:
        subprocess.run(["openssl", *command], cwd=directory, check=True, capture_output=True)
    for key in ("ca.key", "server.key"):
        (directory / key).chmod(0o600)
    # The signing key is unnecessary once the leaf is issued.
    (directory / "ca.key").unlink()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path not in {"/__audit", "/__health"}:
            with _LOCK:
                _COUNTS[path] += 1
                _HEADERS.append({"path": path, "user_agent": self.headers.get("User-Agent", ""),
                                 "has_authorization": "Authorization" in self.headers,
                                 "has_cookie": "Cookie" in self.headers})
        if path == "/__audit":
            with _LOCK:
                data = json.dumps({"counts": dict(_COUNTS), "headers": list(_HEADERS)}).encode()
            self.reply(200, data, "application/json")
        elif path == "/__health":
            self.reply(200, b"ready", "text/plain")
        elif path == "/robots.txt":
            self.reply(200, b"User-agent: *\nDisallow: /robots-denied\nAllow: /\n", "text/plain")
        elif path == "/allowed":
            self.reply(200, HTML, "text/html; charset=utf-8")
        elif path in {"/blocked", "/captcha"}:
            self.reply(403, b"Access restricted. No automated access or challenge retries.", "text/plain")
        elif path == "/redirect-private":
            self.send_response(302)
            self.send_header("Location", "https://127.0.0.1/private")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.reply(404, b"Not found", "text/plain")

    def reply(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "serve"])
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare_tls(args.directory)
        return
    if os.environ.get("OPENMATES_CI_WEB_READ_FIXTURE") != "github-isolated":
        raise RuntimeError("Fixture server is restricted to the isolated CI profile")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.directory / "server.crt", args.directory / "server.key")
    server = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
