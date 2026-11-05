"""Pure lifecycle harness: real owned child processes, no SDK/backend/listener."""

# contract-test-file: tooling
import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "first_page_owned_lifecycle",
    ROOT / "tests/sdk-conformance/runners/support/owned_lifecycle.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


async def child():
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        "-c",
        'import time; print("malformed-readiness",flush=True); time.sleep(60)',
        stdout=asyncio.subprocess.PIPE,
    )


def test_malformed_readiness_failure_reaps_child_and_releases_tempdir():
    async def run():
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            peer = await child()
            try:
                assert (
                    await asyncio.wait_for(peer.stdout.readline(), 1)
                    == b"malformed-readiness\n"
                )
                raise ValueError("malformed readiness")
            except ValueError:
                pass
            finally:
                await module.cleanup_owned(peer, None)
            assert peer.returncode is not None
        assert not directory.exists()

    asyncio.run(run())


def test_hung_native_close_cannot_delay_peer_termination():
    async def run():
        peer = await child()
        await asyncio.wait_for(peer.stdout.readline(), 1)

        class Hung:
            async def close(self):
                await asyncio.Event().wait()

        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError):
            await module.cleanup_owned(
                peer, Hung(), close_seconds=0.05, grace_seconds=0.05
            )
        assert peer.returncode is not None and time.monotonic() - started < 1

    asyncio.run(run())


def test_cancelled_read_runs_cleanup_before_cancellation_returns():
    async def run():
        peer = await child()
        await asyncio.wait_for(peer.stdout.readline(), 1)
        entered = asyncio.Event()
        cleaned = False

        async def vector():
            nonlocal cleaned
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                await module.cleanup_owned(peer, None)
                cleaned = True

        task = asyncio.create_task(vector())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned and peer.returncode is not None

    asyncio.run(run())
