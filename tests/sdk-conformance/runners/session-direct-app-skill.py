"""Genuine PyO3 + maintained API-key SDK, one shared independent wire peer."""

# contract-test-file: tooling
# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
from __future__ import annotations
import argparse
import asyncio
import json
import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/sdk-conformance"))
from session_direct_app_skill_peer import DirectSkillPeer  # noqa: E402


def session(suite, endpoint):
    a = suite["account"]
    return {
        "api_url": endpoint,
        "session_id": a["session_id"],
        "cookies": {"auth_refresh_token": a["cookie"]},
        "ws_token": None,
        "master_key": a["master_key"],
        "hashed_email": "synthetic-email-hash",
        "user_email_salt": "synthetic-salt",
        "email_encryption_key": None,
        "created_at": 1,
        "paired_session_expires_at": None,
        "active_team_id": None,
    }


async def run_vector(suite, vector):
    from openmates import OpenMates, SessionClient, SessionClientError

    peer = DirectSkillPeer(suite, vector, "pip").start()
    c = None
    old_origin = os.environ.get("OPENMATES_APP_URL")
    os.environ["OPENMATES_APP_URL"] = peer.endpoint

    async def refused(operation, code=vector.get("expected_error", "cancelled")):
        try:
            await operation()
        except SessionClientError as error:
            assert error.code == code and "synthetic-private" not in str(error)
        else:
            raise AssertionError("expected fixed typed refusal")

    async def wait_posts():
        for _ in range(500):
            report = peer.status()
            assert report["failure"] is None
            if report["skill_posts"] == 1:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("actual dispatch barrier")

    def release(output):
        try:
            raw = output.release_json()
            try:
                output.release_json()
            except Exception as error:
                assert json.loads(str(error))["code"] == "cancelled"
            else:
                raise AssertionError("opaque released twice")
            return json.loads(raw)
        finally:
            output.discard()

    def deny(output):
        try:
            output.release_json()
        except Exception as error:
            assert json.loads(str(error))["code"] == "cancelled"
            assert "synthetic-private" not in str(error)
        else:
            raise AssertionError("retired output allocated")
        finally:
            output.discard()

    try:
        request, mode = suite["request"], vector["mode"]
        if vector["credential"] == "api_key":
            sdk = OpenMates(
                api_key=suite["account"]["api_key"],
                api_url=peer.endpoint,
                device_id=suite["account"]["device_id"],
            )
            result = await asyncio.to_thread(sdk.apps.web.search, request["input"])
            assert result == vector["expected"]
        else:
            c = SessionClient(
                api_url=peer.endpoint,
                app_url=peer.endpoint,
                enhanced_privacy=False,
                allow_private_operations=True,
            )
            explicit = session(suite, peer.endpoint)
            await c.import_session(explicit)
            if mode.startswith("queued_"):
                held = await c._native.run_skill_prepare(
                    request["app"], request["skill"], json.dumps(request["input"])
                )
                if mode == "queued_successor":
                    successor = await c._native.run_skill_prepare(
                        request["app"],
                        request["skill"],
                        json.dumps({"query": "synthetic explicit successor B"}),
                    )
                    deny(held)
                    assert release(successor) == suite["sync_expected"]
                else:
                    if mode == "queued_cancel":
                        c.cancel()
                    elif mode == "queued_import":
                        await c.import_session(explicit)
                    elif mode == "queued_malformed":
                        await refused(lambda: c.import_session({}), "invalid_argument")
                    elif mode == "queued_close":
                        await c.close()
                    deny(held)
            elif mode == "cancel_after_dispatch":
                call = asyncio.create_task(
                    c.run_skill(request["app"], request["skill"], request["input"])
                )
                await wait_posts()
                c.cancel()
                peer.release.set()
                await refused(lambda: call)
            elif "expected_error" in vector:
                await refused(
                    lambda: c.run_skill(
                        request["app"], request["skill"], request["input"]
                    )
                )
            else:
                result = await c.run_skill(
                    request["app"], request["skill"], request["input"]
                )
                assert result == vector["expected"]
                snapshot = await c.export_session(include_secrets=True)
                assert snapshot["session"]["master_key"] == explicit["master_key"]
                assert snapshot["session"]["session_id"] == explicit["session_id"]
        report = peer.status()
        assert report["failure"] is None
        assert report["skill_posts"] == vector["expected_skill_posts"]
        assert report["downloads"] == vector["expected_downloads"] == 0
        assert report["retention_posts"] == vector["expected_retention_posts"] == 0
        if mode == "pending_a_failed_b":
            assert report["polls"].get("task_a") == report["polls"].get("task_b") == 1
        if vector["credential"] == "cookie" and report["skill_posts"]:
            assert report["auth"] >= 3
        return {
            "id": vector["id"],
            "status": "passed",
            "evidence": "genuine-PyO3"
            if vector["credential"] == "cookie"
            else "maintained-API-key",
            "peer": report,
        }
    finally:
        peer.release.set()
        if c is not None:
            await c.close()
        peer.stop()
        if old_origin is None:
            os.environ.pop("OPENMATES_APP_URL", None)
        else:
            os.environ["OPENMATES_APP_URL"] = old_origin


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", choices=["sdk.apps"], default="sdk.apps")
    parser.add_argument("--language", choices=["python", "rust"], default="python")
    parser.add_argument(
        "--fixture",
        default=str(
            ROOT / "tests/sdk-conformance/fixtures/session-direct-app-skill.json"
        ),
    )
    args = parser.parse_args()
    raw = Path(args.fixture).read_bytes()
    fixture_hash = hashlib.sha256(raw).hexdigest()
    suite = json.loads(raw)["capabilities"]["sdk.apps"]
    if args.language == "rust":
        import subprocess

        assert (
            Path(args.fixture).resolve()
            == (
                ROOT / "tests/sdk-conformance/fixtures/session-direct-app-skill.json"
            ).resolve()
        )
        command = [
            "cargo",
            "test",
            "--locked",
            "--manifest-path",
            str(ROOT / "packages/openmates-session-bindings/Cargo.toml"),
            "--lib",
            "session::app_skill::tests::shared_direct_skill_vectors",
            "--",
            "--exact",
            "--nocapture",
        ]
        run = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, timeout=300
        )
        marker = "OPENMATES_DIRECT_SKILL_CONFORMANCE="
        values = [
            json.loads(line.split(marker, 1)[1])
            for line in run.stdout.splitlines()
            if marker in line
        ]
        if (
            run.returncode != 0
            or "test result: ok. 1 passed; 0 failed; 0 ignored;" not in run.stdout
        ):
            raise RuntimeError(
                "Fixed Rust direct-skill suite did not execute exactly once.\n"
                + run.stdout[-6000:]
                + run.stderr[-6000:]
            )
        assert len(values) == 1
        result = values[0]
        assert (
            result["capability"] == "sdk.apps"
            and result["language"] == "rust"
            and result["status"] == "passed"
            and result["fixtureSha256"] == fixture_hash
        )
        assert [v["id"] for v in result["results"]] == [
            v["id"] for v in suite["vectors"]
        ]
        for actual, expected in zip(result["results"], suite["vectors"]):
            assert actual["status"] == "passed" and actual["evidence"] in {
                "actual-private-opaque-final-allocation",
                "actual-public-inflight-cancellation",
                "actual-public-cookie-operation",
                "maintained-public-api-key-library",
            }
            assert actual["peer"]["skill_posts"] == expected["expected_skill_posts"]
            assert (
                actual["peer"]["failure"] is None
                and actual["peer"]["downloads"]
                == actual["peer"]["retention_posts"]
                == 0
            )
        print(json.dumps(result))
        return
    results = [
        await asyncio.wait_for(run_vector(suite, vector), 30)
        for vector in suite["vectors"]
    ]
    assert len(results) == 18
    print(
        json.dumps(
            {
                "capability": "sdk.apps",
                "language": "python",
                "status": "passed",
                "fixtureSha256": fixture_hash,
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
