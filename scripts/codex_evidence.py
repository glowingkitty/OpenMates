"""Immutable Codex visual evidence receipts using the existing S3 transport.

Enumerate every Playwright test attempt/profile attachment, including failures.
A recording, its upload and its chat delivery are separate outcomes. Private
logs and auth artifacts are never candidates. Missing video stays explicit.
See docs/architecture/codex-orchestration.md for expiry and acknowledgement.
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import time
from urllib.parse import urlparse

MEDIA_SUFFIXES = {".mp4", ".webm", ".png", ".jpg", ".jpeg"}


def resolve_attachment(directory, name):
    supplied = Path(name)
    if ".." in supplied.parts or any(
        p in {".auth", "ci-private"} or p.startswith(".env") for p in supplied.parts
    ):
        raise ValueError("Private or unsafe evidence path")
    direct = directory / supplied
    if (
        not supplied.is_absolute()
        and direct.is_file()
        and direct.resolve().is_relative_to(directory.resolve())
    ):
        return direct
    # Runner absolute paths differ from downloaded artifact roots; match the longest
    # retained suffix, never choose the first video with a coincidentally equal name.
    candidates = [
        p
        for p in directory.rglob(supplied.name)
        if p.is_file()
        and p.resolve().is_relative_to(directory.resolve())
        and not any(
            part in {".auth", "ci-private"} or part.startswith(".env")
            for part in p.relative_to(directory).parts
        )
    ]
    for length in range(len(supplied.parts), 0, -1):
        matches = [
            p for p in candidates if p.parts[-length:] == supplied.parts[-length:]
        ]
        if len(matches) == 1:
            return matches[0]
        if matches:
            break
    raise ValueError("Recording missing or attachment path ambiguous")


def attempts(report):
    def suites(items):
        for suite in items:
            yield from suites(suite.get("suites", []))
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    for result in test.get("results", []):
                        yield {
                            "spec": spec.get("file") or suite.get("file"),
                            "test": spec.get("id") or spec.get("title"),
                            "profile": test.get("projectName", "default"),
                            "attempt": result.get("retry", 0),
                            "result": result.get("status", "unknown"),
                            "attachments": result.get("attachments", []),
                        }

    yield from suites(report.get("suites", []))


def collect(directory, receipt):
    records = []
    for report_file in sorted(directory.rglob("ci-spec-*.json")):
        for attempt in attempts(json.loads(report_file.read_text())):
            attachments = attempt.pop("attachments")
            has_video = False
            for attachment in attachments:
                name = attachment.get("path", "")
                if Path(name).suffix.lower() not in MEDIA_SUFFIXES:
                    continue
                kind = (
                    "video"
                    if Path(name).suffix.lower() in {".mp4", ".webm"}
                    else "image"
                )
                has_video |= kind == "video"
                record = {
                    **attempt,
                    "kind": kind,
                    "source_commit": receipt["source_commit"],
                    "run_id": receipt["run_id"],
                    "recording": "available",
                    "upload": "pending",
                    "delivery": "pending",
                    "source_attachment": name,
                }
                try:
                    path = resolve_attachment(directory, name)
                    record.update(
                        path=str(path.relative_to(directory)),
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                except ValueError as exc:
                    record.update(
                        recording="unavailable", upload="unavailable", reason=str(exc)
                    )
                record["id"] = hashlib.sha256(
                    json.dumps(record, sort_keys=True).encode()
                ).hexdigest()
                records.append(record)
            if not has_video:
                record = {
                    **attempt,
                    "kind": "video",
                    "run_id": receipt["run_id"],
                    "source_commit": receipt["source_commit"],
                    "recording": "unavailable",
                    "upload": "unavailable",
                    "delivery": "pending",
                    "reason": "No video attachment in this test attempt; capture may not have started",
                }
                record["id"] = hashlib.sha256(
                    json.dumps(record, sort_keys=True).encode()
                ).hexdigest()
                records.append(record)
    covered = {Path(r.get("spec") or "").name for r in records}
    reported = (receipt.get("report") or {}).get("results", [])
    reported = [
        *reported,
        *({"spec": spec} for spec in receipt.get("selected_specs", [])),
    ]
    for result in reported:
        spec = result.get("spec", "")
        if spec.endswith(".spec.ts") and Path(spec).name not in covered:
            record = {
                "spec": spec,
                "run_id": receipt["run_id"],
                "source_commit": receipt["source_commit"],
                "kind": "video",
                "recording": "unavailable",
                "upload": "unavailable",
                "delivery": "pending",
                "reason": "No attempt report returned; inspect the run setup/recording stage",
            }
            record["id"] = hashlib.sha256(
                json.dumps(record, sort_keys=True).encode()
            ).hexdigest()
            records.append(record)
            covered.add(Path(spec).name)
    # CLI E2E captures expose an exact product argv and a real terminal manifest.
    # Generic scripts and arbitrary videos do not acquire a proof obligation.
    try:
        from scripts.cli_video_capture import _is_openmates_cli
    except ModuleNotFoundError:
        from cli_video_capture import _is_openmates_cli
    for manifest in directory.rglob("manifest.json"):
        item = json.loads(manifest.read_text())
        if item.get("capture_kind") != "real_terminal_screen" or not _is_openmates_cli(
            item.get("argv", [])
        ):
            continue
        if item.get("classification") != "cli_e2e":
            continue
        record = {
            "spec": "OpenMates CLI E2E",
            "profile": "terminal",
            "attempt": str(manifest.relative_to(directory)),
            "kind": "video",
            "run_id": receipt["run_id"],
            "source_commit": receipt["source_commit"],
            "result": "passed" if item.get("exit_status") == 0 else "failed",
            "delivery": "pending",
        }
        try:
            path = resolve_attachment(directory, item["video_path"])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item["video_sha256"].removeprefix("sha256:"):
                raise ValueError("CLI video hash mismatch")
            record.update(
                path=str(path.relative_to(directory)),
                sha256=digest,
                recording="available",
                upload="pending",
            )
        except (ValueError, KeyError) as exc:
            record.update(
                recording="unavailable", upload="unavailable", reason=str(exc)
            )
        record["id"] = hashlib.sha256(
            json.dumps(record, sort_keys=True).encode()
        ).hexdigest()
        records.append(record)
    return records


def prepare(directory, receipt):
    try:
        from scripts.codex_orchestration import transaction
    except ModuleNotFoundError:
        from codex_orchestration import transaction
    path = directory / "codex-evidence.json"
    with transaction(path) as state:
        records = state.setdefault("records", {})
        for record in collect(directory, receipt):
            # A deliberately removed local recording still has a durable upload.
            # Do not turn the next inventory pass into a second missing capture.
            if record["recording"] == "unavailable" and any(
                old.get("upload") == "uploaded"
                and all(old.get(key) == record.get(key) for key in
                        ("run_id", "source_commit", "spec", "test", "profile", "attempt", "kind"))
                and ((not old.get("source_attachment") and not record.get("source_attachment"))
                     or old.get("source_attachment") == record.get("source_attachment")
                     or (not old.get("source_attachment") and
                         Path(old.get("path", "")).name == Path(record.get("source_attachment", "")).name))
                for old in records.values()
            ):
                continue
            records.setdefault(record["id"], record)
        state["run_id"] = receipt["run_id"]
        state["source_commit"] = receipt["source_commit"]
    return path


def _retained_video(directory, record):
    """Return an unchanged regular video, without following any symlink."""
    relative = Path(record["path"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() not in {".mp4", ".webm"}:
        raise ValueError("Unsafe retained video path")
    root = directory.resolve()
    path = directory / relative
    for parent in (directory, *relative.parents):
        parent = directory / parent if not parent.is_absolute() else parent
        if parent.is_symlink():
            raise ValueError("Symlink in retained video path")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Retained video escaped artifact directory")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Retained video is not a regular file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.close(fd)
    after = path.lstat()
    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if identity(before) != identity(opened) or identity(before) != identity(after) or digest.hexdigest() != record["sha256"]:
        raise ValueError("Retained artifact identity changed")
    return path, after


def _cleanup_uploaded_videos(directory, state_path, retain_local_videos=False):
    if retain_local_videos:
        return
    try:
        from scripts.codex_orchestration import transaction
    except ModuleNotFoundError:
        from codex_orchestration import transaction
    with transaction(state_path) as state:
        for record in state.get("records", {}).values():
            if record.get("kind") != "video" or record.get("upload") != "uploaded" or record.get("local_video_removed"):
                continue
            if not all(record.get(field) for field in ("bucket", "key", "sha256", "url")):
                continue
            try:
                path, verified = _retained_video(directory, record)
                current = path.lstat()
                if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                    verified.st_dev, verified.st_ino, verified.st_size, verified.st_mtime_ns
                ):
                    raise ValueError("Retained artifact identity changed")
                path.unlink()
                record["local_video_removed"] = True
            except FileNotFoundError:
                # Crash after unlink but before this transaction was saved.
                record["local_video_removed"] = True
            except (OSError, ValueError) as exc:
                record["cleanup_error"] = type(exc).__name__
    return state


def publish(directory, uploader, now=None, *, renewer=None, retain_local_videos=False):
    try:
        from scripts.codex_orchestration import transaction
    except ModuleNotFoundError:
        from codex_orchestration import transaction
    now = time.time() if now is None else now
    # Serialize artifact uploads. A crash can orphan an upload, but cannot report an
    # unacknowledged upload/delivery as successful or rerun its test.
    state_path = directory / "codex-evidence.json"
    with transaction(state_path) as state:
        for record in state.get("records", {}).values():
            if record["recording"] != "available":
                continue
            if (
                record.get("expires_at", 0) > now + 60
                and record["upload"] == "uploaded"
            ):
                continue
            try:
                renewing = record.get("upload") == "uploaded" and all(record.get(k) for k in ("bucket", "key", "sha256"))
                if renewing:
                    if renewer is None:
                        try:
                            from scripts.response_media import renew_uploaded_object
                        except ModuleNotFoundError:
                            from response_media import renew_uploaded_object
                        renewer = renew_uploaded_object
                    result = renewer(bucket=record["bucket"], key=record["key"], sha256=record["sha256"])
                else:
                    path = directory / record["path"]
                    if record["kind"] == "video":
                        path, _verified = _retained_video(directory, record)
                    elif (path.is_symlink() or not path.resolve().is_relative_to(directory.resolve())
                          or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]):
                        raise ValueError("Retained artifact identity changed")
                    result = uploader(path, alt=f"{record['spec']} {record['kind']}")
                parsed = urlparse(result["url"])
                if (
                    parsed.scheme != "https"
                    or not parsed.netloc
                    or not parsed.hostname
                    or parsed.hostname.endswith(".invalid")
                ):
                    raise ValueError("Uploader did not return a usable HTTPS link")
                if not all(result.get(k) for k in ("bucket", "key")) or result.get("sha256", "").removeprefix("sha256:") != record["sha256"]:
                    raise ValueError("Uploader did not confirm S3 object identity")
                if renewing and (result["bucket"], result["key"]) != (record["bucket"], record["key"]):
                    raise ValueError("Renewal returned a different S3 object")
                if not isinstance(result.get("expires_in"), int) or result["expires_in"] <= 0:
                    raise ValueError("Uploader returned an invalid link lifetime")
                record.update(
                    url=result["url"],
                    expires_at=now + result["expires_in"],
                    bucket=result["bucket"],
                    key=result["key"],
                    upload="uploaded",
                    delivery="pending",
                    link_expired=False,
                )
                record.pop("upload_error", None)
                record.pop("renewal_error", None)
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                if record.get("upload") == "uploaded":
                    record["renewal_error"] = type(exc).__name__
                    record["link_expired"] = True
                else:
                    record.update(upload="failed", upload_error=type(exc).__name__)
    _cleanup_uploaded_videos(directory, state_path, retain_local_videos)
    return json.loads(state_path.read_text())


def markdown(state, pending_only=True):
    rows = [
        "| Test / attempt / profile | Recording / image | Delivery |",
        "|---|---|---|",
    ]
    for record in state.get("records", {}).values():
        if pending_only and record["delivery"] == "delivered":
            continue
        label = f"{record['spec']} / {record.get('attempt', '—')} / {record.get('profile', '—')}".replace(
            "|", "\\|"
        )
        proof = (
            f"[{record['kind']}]({record['url']}) · `{record['path']}`"
            if record["upload"] == "uploaded" and not record.get("link_expired")
            else record.get("reason")
            or ("Remote evidence unavailable or expired; local video cleaned"
                if record.get("link_expired") and record.get("local_video_removed")
                else f"Upload {record['upload']} — retained artifact")
        )
        rows.append(f"| {label} | {proof} | {record['delivery']} |")
    return "\n".join(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--upload", action="store_true")
    p.add_argument(
        "--retain-local-videos", action="store_true",
        help="Keep CI recordings for an explicitly requested proof-video edit",
    )
    p.add_argument("--ack", action="append", default=[])
    p.add_argument("--message-id")
    p.add_argument(
        "--json", action="store_true", help="Include receipt IDs for acknowledgement"
    )
    args = p.parse_args()
    directory = args.directory.resolve()
    from codex_orchestration import transaction

    receipt = json.loads((directory / "receipt.json").read_text())
    path = prepare(directory, receipt)
    if args.upload:
        from response_media import upload_file

        publish(
            directory, upload_file,
            retain_local_videos=args.retain_local_videos or receipt.get("retain_local_videos", False),
        )
    if args.ack:
        if not args.message_id:
            p.error("--ack requires the actual delivered chat message ID")
        with transaction(path) as state:
            for identity in args.ack:
                record = state["records"][identity]
                if record["upload"] not in {"uploaded", "unavailable"}:
                    raise ValueError("Undelivered upload cannot be acknowledged")
                record.update(delivery="delivered", message_id=args.message_id)
    state = json.loads(path.read_text())
    print(json.dumps(state, indent=2) if args.json else markdown(state))


if __name__ == "__main__":
    main()
