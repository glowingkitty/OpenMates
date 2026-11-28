#!/usr/bin/env python3
"""Admit and reconstruct reviewed Personal DevTest sources without credentials."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
import time

if __package__:
    from .ci_candidate_artifact import MAX_PATCH_BYTES, validate_url
else:
    from ci_candidate_artifact import MAX_PATCH_BYTES, validate_url

SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
OWNER = re.compile(r"[A-Za-z0-9_-]{1,64}")
PEM = re.compile(rb"-----BEGIN CERTIFICATE-----[\r\n]+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----[\r\n]*")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the private patch request on the validated artifact origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def certificate(encoded: str) -> tuple[bytes, str]:
    """Validate a single public certificate and return its DER fingerprint."""
    if len(encoded) > 11000:
        raise ValueError("Invalid public evidence certificate")
    try:
        pem = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Invalid public evidence certificate") from None
    if not PEM.fullmatch(pem):
        raise ValueError("Expected a single public evidence certificate")
    for args in (["-checkend", "0", "-noout"], ["-outform", "DER"]):
        result = subprocess.run(
            ["openssl", "x509", *args], input=pem, capture_output=True, check=False,
        )
        if result.returncode:
            raise ValueError("Invalid or expired public evidence certificate")
    return pem, hashlib.sha256(result.stdout).hexdigest()


def admit(env, inputs, fingerprint: str) -> dict:
    """Require GitHub workflow identity and an exact protected pin for patches."""
    if (env.get("GITHUB_REPOSITORY", "").lower() != "glowingkitty/openmates"
            or env.get("GITHUB_REF") != "refs/heads/dev"
            or env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise ValueError("Personal DevTest requires the trusted dev workflow dispatch")
    harness = env.get("GITHUB_SHA", "")
    surface = env.get("DEVTEST_SURFACE")
    if not SHA.fullmatch(harness) or surface not in {"terminal", "web"}:
        raise ValueError("Invalid Personal DevTest harness or surface")
    base, source, tree, owner, digest = (
        env.get(name, "") for name in (
            "DEVTEST_BASE", "DEVTEST_SOURCE", "DEVTEST_TREE", "DEVTEST_OWNER", "DEVTEST_PATCH_SHA256",
        )
    )
    url = inputs.get("candidate_patch_url", "")
    candidate = bool(tree or owner or digest or url)
    identity = {
        "surface": surface,
        "harness": harness,
        "source": source if candidate else harness,
        "recipient_sha256": fingerprint,
        "candidate": candidate,
        "local_web": surface == "web" and (candidate or env.get("DEVTEST_LOCAL_BUILD") == "true"),
    }
    if not candidate:
        return identity
    if (not all(SHA.fullmatch(value) for value in (base, source, tree))
            or not OWNER.fullmatch(owner) or not DIGEST.fullmatch(digest)
            or not isinstance(url, str) or not url):
        raise ValueError("Incomplete Personal DevTest candidate identity")
    validate_url(url)
    actor = env.get("GITHUB_ACTOR")
    if not actor or env.get("GITHUB_TRIGGERING_ACTOR") != actor:
        raise ValueError("Personal DevTest candidate rerun actor must match the reviewed dispatch actor")
    expected = {
        "actor": actor, "surface": surface, "source": source, "base": base,
        "tree": tree, "recipient_sha256": fingerprint,
    }
    try:
        approved = json.loads(env.get("DEVTEST_REVIEW", ""))
    except ValueError:
        raise ValueError("Personal DevTest reviewed pin unavailable") from None
    if approved != expected:
        raise ValueError("Personal DevTest candidate does not match the reviewed pin")
    return {**identity, "base": base, "tree": tree, "owner": owner, "patch_sha256": digest}


def git(subject: Path, *args: str, **options) -> str:
    return subprocess.check_output(["git", "-C", str(subject), *args], text=True, **options).strip()


def reconstruct(subject: Path, identity: dict, patch: bytes) -> None:
    """Rebuild the same detached source identity used by isolated Apple CI."""
    if git(subject, "rev-parse", "HEAD") != identity["base"]:
        raise ValueError("Personal DevTest base mismatch")
    if git(subject, "status", "--porcelain") or len(patch) > MAX_PATCH_BYTES:
        raise ValueError("Personal DevTest source checkout or patch is invalid")
    if hashlib.sha256(patch).hexdigest() != identity["patch_sha256"]:
        raise ValueError("Personal DevTest patch digest mismatch")
    for flags in (("--check",), ()):
        subprocess.run(
            ["git", "-C", str(subject), "apply", "--binary", "--index", *flags, "-"],
            input=patch, check=True,
        )
    tree = git(subject, "write-tree")
    if tree != identity["tree"]:
        raise ValueError("Personal DevTest candidate tree mismatch")
    base = identity["base"]
    timestamp = git(subject, "show", "-s", "--format=%cI", base)
    author = {
        **os.environ,
        "GIT_AUTHOR_NAME": "OpenMates CI", "GIT_AUTHOR_EMAIL": "ci@example.com",
        "GIT_COMMITTER_NAME": "OpenMates CI", "GIT_COMMITTER_EMAIL": "ci@example.com",
        "GIT_AUTHOR_DATE": timestamp, "GIT_COMMITTER_DATE": timestamp,
    }
    rebuilt = git(
        subject, "commit-tree", tree, "-p", base,
        input=f"CI candidate for session {identity['owner']}\n", env=author,
    )
    if rebuilt != identity["source"]:
        raise ValueError("Personal DevTest candidate source mismatch")
    git(subject, "checkout", "--detach", rebuilt)
    if git(subject, "rev-parse", "HEAD^{tree}") != tree:
        raise ValueError("Personal DevTest final checkout tree mismatch")


def verify_web_preview(preview: str, output: Path) -> dict:
    """Attest served SvelteKit entry bytes against the exact build output."""
    if preview != "http://127.0.0.1:5174":
        raise ValueError("Invalid private preview origin")
    opener = urllib.request.build_opener(NoRedirect())
    deadline = time.monotonic() + 40
    while True:
        try:
            with opener.open(preview + "/", timeout=2) as response:
                html = response.read(10 * 1024**2)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    entries = set(re.findall(rb"/_app/immutable/entry/[A-Za-z0-9_.-]+\.js", html))
    if not entries:
        raise ValueError("Private preview is missing built browser entry assets")
    digests = {}
    for entry in sorted(entries):
        path = entry.decode("ascii")
        with opener.open(preview + path, timeout=5) as response:
            data = response.read(10 * 1024**2)
        if data != (output / path.removeprefix("/")).read_bytes():
            raise ValueError("Private preview asset differs from the reviewed build")
        digests[path] = hashlib.sha256(data).hexdigest()
    return {"index_sha256": hashlib.sha256(html).hexdigest(), "entry_sha256": digests}


def workflow_inputs() -> dict:
    return json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()).get("inputs", {})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("admit", "reconstruct", "verify-web"))
    parser.add_argument("--subject", type=Path)
    parser.add_argument("--tooling", type=Path)
    parser.add_argument("--web-output", type=Path)
    args = parser.parse_args()
    runner = Path(os.environ["RUNNER_TEMP"])
    inputs = workflow_inputs()
    try:
        if args.action == "admit":
            pem, fingerprint = certificate(os.environ["DEVTEST_RECIPIENT"])
            identity = admit(os.environ, inputs, fingerprint)
            if args.tooling is None or git(args.tooling, "rev-parse", "HEAD") != identity["harness"]:
                raise ValueError("Trusted workflow harness checkout mismatch")
            harness_tree = git(args.tooling, "rev-parse", "HEAD^{tree}")
            identity["harness_tree"] = harness_tree
            if not identity["candidate"]:
                identity["tree"] = harness_tree
            os.umask(0o077)
            (runner / "personal-devtest-recipient.pem").write_bytes(pem)
            (runner / "personal-devtest-source.json").write_text(json.dumps(identity) + "\n")
        elif args.action == "verify-web":
            source_file = runner / "personal-devtest-source.json"
            identity = json.loads(source_file.read_text())
            if not identity["local_web"] or args.web_output is None:
                raise ValueError("Private web build was not admitted")
            identity["served_web"] = verify_web_preview(os.environ["OPENMATES_PRIVATE_WEB_PREVIEW"], args.web_output)
            source_file.write_text(json.dumps(identity) + "\n")
        else:
            identity = json.loads((runner / "personal-devtest-source.json").read_text())
            if not identity["candidate"] or args.subject is None:
                raise ValueError("Personal DevTest candidate was not admitted")
            url = validate_url(inputs["candidate_patch_url"])
            print(f"::add-mask::{url}", flush=True)
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(url, timeout=120) as response:
                patch = response.read(MAX_PATCH_BYTES + 1)
            reconstruct(args.subject, identity, patch)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError):
        # The short failure never renders URL credentials or private patch bytes.
        raise SystemExit("Personal DevTest source or recipient verification failed") from None


if __name__ == "__main__":
    main()
