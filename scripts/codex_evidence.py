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
from pathlib import Path
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
            if digest != item["video_sha256"]:
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
            records.setdefault(record["id"], record)
        state["run_id"] = receipt["run_id"]
        state["source_commit"] = receipt["source_commit"]
    return path


def publish(directory, uploader, now=None):
    try:
        from scripts.codex_orchestration import transaction
    except ModuleNotFoundError:
        from codex_orchestration import transaction
    now = time.time() if now is None else now
    # Serialize artifact uploads. A crash can orphan an upload, but cannot report an
    # unacknowledged upload/delivery as successful or rerun its test.
    with transaction(directory / "codex-evidence.json") as state:
        for record in state.get("records", {}).values():
            if record["recording"] != "available":
                continue
            if (
                record.get("expires_at", 0) > now + 60
                and record["upload"] == "uploaded"
            ):
                continue
            path = directory / record["path"]
            try:
                if (
                    not path.resolve().is_relative_to(directory.resolve())
                    or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]
                ):
                    raise ValueError("Retained artifact identity changed")
                result = uploader(path, alt=f"{record['spec']} {record['kind']}")
                parsed = urlparse(result["url"])
                if (
                    parsed.scheme != "https"
                    or not parsed.netloc
                    or parsed.hostname.endswith(".invalid")
                ):
                    raise ValueError("Uploader did not return a usable HTTPS link")
                record.update(
                    url=result["url"],
                    expires_at=now + result["expires_in"],
                    upload="uploaded",
                    delivery="pending",
                )
                record.pop("upload_error", None)
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                record.update(upload="failed", upload_error=type(exc).__name__)
    return state


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
            if record["upload"] == "uploaded"
            else record.get("reason")
            or f"Upload {record['upload']} — retained artifact"
        )
        rows.append(f"| {label} | {proof} | {record['delivery']} |")
    return "\n".join(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--upload", action="store_true")
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
        from opencode_response_media import upload_file

        publish(directory, upload_file)
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
