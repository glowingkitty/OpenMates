"""Session videos of AI test users: private S3 objects deleted after 7 days, linked from findings,
reports and Discord pushes.

Every persona's browser session is recorded (`video.webm`). The link is signed before the worker
starts, so reports filed during the session can carry it; the upload follows when the worker ends.
Uploads reuse the response-media S3 transport (Vault credentials inside the api container) with a
bucket of its own, because a bucket's expiry rule covers the whole bucket and the response-media
bucket keeps objects for 2 days. Signed links last as long as the objects (7 days).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import response_media as media

BUCKET = "openmates-ai-test-user-videos"
LIFECYCLE_DAYS = 7
LINK_SECONDS = LIFECYCLE_DAYS * 24 * 3600  # the S3 maximum for a signed link
KEY_PART = re.compile(r"[^A-Za-z0-9._-]")

SIGN_CODE = r'''
import asyncio, json, os
import boto3
from botocore.config import Config
from backend.core.api.app.utils.secrets_manager import SecretsManager

REQUEST = json.loads(os.environ["AI_TEST_USER_VIDEO_REQUEST"])

async def main():
    manager = SecretsManager()
    await manager.initialize()
    get = lambda key: manager.get_secret(secret_path="kv/data/providers/hetzner", secret_key=key)
    access_key, secret_key = await get("s3_access_key"), await get("s3_secret_key")
    region = await get("s3_region_name") or "nbg1"
    if not access_key or not secret_key:
        raise RuntimeError("Hetzner S3 credentials are unavailable in Vault")
    client = boto3.client("s3", region_name=region, endpoint_url=f"https://{region}.your-objectstorage.com",
                          aws_access_key_id=access_key, aws_secret_access_key=secret_key,
                          config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
    print(json.dumps({"urls": [client.generate_presigned_url(
        "get_object", Params={"Bucket": REQUEST["bucket"], "Key": key}, ExpiresIn=REQUEST["expires_in"])
        for key in REQUEST["keys"]]}))

asyncio.run(main())
'''


def object_key(run_id: str, target: str, persona_id: str) -> str:
    return "ai-test-users/" + "/".join(KEY_PART.sub("_", part) for part in (run_id, target, persona_id)) + ".webm"


def sign(keys: list[str], container: str = media.DEFAULT_CONTAINER) -> list[str]:
    """Signed GET links for objects that may not exist yet (valid once uploaded, for 7 days)."""
    env = {**os.environ, "AI_TEST_USER_VIDEO_REQUEST": json.dumps(
        {"bucket": BUCKET, "keys": keys, "expires_in": LINK_SECONDS})}
    run = media.run_command(["docker", "exec", "-e", "AI_TEST_USER_VIDEO_REQUEST", container,
                             "python", "-c", SIGN_CODE], env=env)
    lines = [line for line in run.stdout.splitlines() if line.startswith("{")]
    if run.returncode or not lines:
        raise RuntimeError(f"video link signing failed: {(run.stderr or run.stdout).strip()[-300:]}")
    return json.loads(lines[-1])["urls"]


def upload(path: Path, key: str, container: str = media.DEFAULT_CONTAINER, content_type: str = "video/webm") -> dict:
    """Upload one file (a session video, or push proof from push_proof.py) to the 7-day bucket.

    Returns bucket, key and a fresh signed url."""
    content = path.read_bytes()
    if len(content) > media.MAX_MEDIA_BYTES:
        raise RuntimeError(f"video too large ({len(content)} bytes)")
    request = {
        "bucket": BUCKET, "dev_bucket": BUCKET, "key": key,
        "container_path": media.container_path_for(path, key),
        "content_type": content_type, "media_kind": media.media_kind(content_type),
        "sha256": hashlib.sha256(content).hexdigest(),
        "lifecycle_days": LIFECYCLE_DAYS, "expires_in": LINK_SECONDS,
    }
    try:
        return media.upload_via_api_container(source=path, container=container, request=request)
    finally:
        media.run_command(["docker", "exec", container, "rm", "-f", str(request["container_path"])])


def moment(url: str, seconds: object) -> str:
    """The link opened at `seconds` when known (`#t=` media fragment), plus a readable time."""
    if not url or not isinstance(seconds, (int, float)):
        return url
    whole = max(0, int(seconds))
    return f"{url}#t={whole} (at {whole // 60}:{whole % 60:02d})"


def estimated_offset(result: dict) -> float:
    """Runs before the offset was recorded: steps start right after the signup and gift card stages."""
    return round(sum((result.get(stage) or {}).get("seconds") or 0 for stage in ("signup", "gift_card")), 1)


def attach_run(run_dir: Path, uploader=upload) -> dict:
    """Upload the recordings of an earlier run and add the links (and finding moments) to run.json/report.md.

    Persona folders without a recording keep `video_error`; earlier uploads are reused."""
    import ai_test_users_report as reporting
    import ai_test_users_scenarios as scenarios

    run = json.loads((run_dir / "run.json").read_text())
    for r in run["personas"]:
        folder = run_dir / r["target"] / r["persona"]
        if not (r.get("video") or {}).get("url"):
            if not (folder / "video.webm").exists():
                r["video_error"] = r.get("video_error") or "no recording"
                continue
            key = object_key(run_dir.name, r["target"], r["persona"])
            r["video"] = {"url": uploader(folder / "video.webm", key)["url"], "key": key}
            r.pop("video_error", None)
        if r.get("findings") is None and (folder / "result.json").exists():
            result = json.loads((folder / "result.json").read_text())
            offset = result.get("video_offset_seconds")
            if offset is None:
                offset, r["video_offset_estimated"] = estimated_offset(result), True
            transcript = folder / "transcript.json"
            at = {e["step"]: e.get("at_seconds") for e in json.loads(transcript.read_text())} if transcript.exists() else {}
            r["video_offset_seconds"] = offset
            r["findings"] = [{**{k: f.get(k) for k in ("title", "severity", "step", "kept")},
                              "video_seconds": round(offset + at[f["step"]], 1)
                              if isinstance(at.get(f.get("step")), (int, float)) else None}
                             for f in result.get("findings") or []]
    run["problems"] = reporting.problems(run["personas"], run.get("undeleted", 0))
    if run.get("flows"):
        run["flows"] = scenarios.flow_verdicts(run["personas"])
    (run_dir / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    (run_dir / "report.md").write_text(reporting.report_markdown(run, run_dir))
    return run
