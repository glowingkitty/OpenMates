# backend/tests/test_e2b_remotion_renderer.py
#
# Provider tests for the Remotion E2B session of composed videos with a fake
# sandbox: isolation settings (offline, secure), always-kill lifetime, typed
# start failures (missing template), one-time input upload to public/inputs,
# check/render commands with hard limits, error text trimmed and redacted for
# the author, and pinned package versions.
# Specification: feature.app-skill.videos-generate
# (videos-generate.composed.sandbox-render-and-correction).

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from e2b import CommandExitException, NotFoundException, SandboxException

from backend.shared.providers.e2b_remotion_renderer import (
    COMPOSITION_PACKAGES,
    MAX_ERROR_CHARS,
    REMOTION_PACKAGES,
    REMOTION_TEMPLATE_ENV,
    REMOTION_TEMPLATE_NAME,
    REMOTION_WORKDIR,
    ROOT_TSX,
    RUNNER_MJS,
    RemotionAsset,
    RemotionCompositionError,
    RemotionSandboxError,
    RemotionSession,
    package_json,
    redact,
)

META = {"video": {"fps": 30, "durationInFrames": 90, "width": 1280, "height": 720},
        "parts": [{"id": "a", "label": "A", "from": 0, "durationInFrames": 90, "kind": "scene"}]}
ASSET = RemotionAsset(name="input-1.png", data=b"png")


class FakeSandbox:
    """In-memory stand-in for e2b.Sandbox; ``on_run`` decides what each command does."""

    def __init__(self, on_run) -> None:
        self.store: dict[str, bytes] = {}
        self.commands_run: list[tuple[str, dict]] = []
        self.killed = False
        self.on_run = on_run
        self.commands = SimpleNamespace(run=self._run)
        self.files = SimpleNamespace(write_files=self._write_files, read=self._read)

    def _write_files(self, files):
        for item in files:
            self.store[item["path"]] = item["data"]

    def _read(self, path, format="text"):
        if path not in self.store:
            raise SandboxException(f"missing {path}")
        return self.store[path]

    def _run(self, command, **kwargs):
        self.commands_run.append((command, kwargs))
        return self.on_run(self, command)

    def kill(self):
        self.killed = True
        return True


def succeeds(sandbox: FakeSandbox, command: str):
    if "runner.mjs check" in command:
        sandbox.store[f"{REMOTION_WORKDIR}/out/meta.json"] = json.dumps(META).encode()
    else:
        sandbox.store[f"{REMOTION_WORKDIR}/out/video.mp4"] = b"mp4-bytes"
        sandbox.store[f"{REMOTION_WORKDIR}/out/thumbnail.png"] = b"png-bytes"
    return SimpleNamespace(exit_code=0)


def make_session(on_run, created: list | None = None, **kwargs):
    sandbox = FakeSandbox(on_run)

    def factory(**create_kwargs):
        if created is not None:
            created.append(create_kwargs)
        return sandbox

    return RemotionSession(api_key="test-key", sandbox_factory=factory, **kwargs), sandbox


async def _check_and_render(session, source="export default () => null;"):
    async with session:
        await session.upload_inputs([ASSET])
        checked = await session.check(source)
        rendered = await session.render(45)
        return checked, rendered


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_sandbox_is_offline_secure_from_the_template_and_always_killed(monkeypatch):
    monkeypatch.delenv(REMOTION_TEMPLATE_ENV, raising=False)
    created: list = []
    session, sandbox = make_session(succeeds, created)
    checked, rendered = asyncio.run(_check_and_render(session))
    assert created[0]["template"] == REMOTION_TEMPLATE_NAME == "openmates-remotion-renderer-dev"
    assert created[0]["allow_internet_access"] is False
    assert created[0]["network"] == {"allow_public_traffic": False}
    assert created[0]["secure"] is True
    assert sandbox.killed
    assert checked.video == META["video"] and checked.parts == META["parts"]
    assert rendered.mp4 == b"mp4-bytes" and rendered.thumbnail_png == b"png-bytes" and rendered.seconds >= 0
    assert sandbox.store[f"{REMOTION_WORKDIR}/public/inputs/input-1.png"] == b"png"
    assert sandbox.store[f"{REMOTION_WORKDIR}/src/Composition.tsx"] == b"export default () => null;"
    for name in ("runner.mjs", "src/index.ts", "src/Root.tsx"):
        assert f"{REMOTION_WORKDIR}/{name}" in sandbox.store


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_template_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv(REMOTION_TEMPLATE_ENV, "remotion-other")
    created: list = []
    session, _sandbox = make_session(succeeds, created)
    asyncio.run(_check_and_render(session))
    assert created[0]["template"] == "remotion-other"


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_check_and_render_commands_have_hard_limits():
    session, sandbox = make_session(succeeds, check_limit_seconds=100, render_limit_seconds=900, concurrency=3)
    asyncio.run(_check_and_render(session))
    (check, check_kwargs), (render, render_kwargs) = sandbox.commands_run
    assert "timeout -s KILL 100s node runner.mjs check" in check and check_kwargs["timeout"] > 100
    assert "timeout -s KILL 900s node runner.mjs render 45 3" in render and render_kwargs["timeout"] > 900


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_missing_template_is_a_typed_start_failure():
    def factory(**_kwargs):
        raise NotFoundException("template not found")

    session = RemotionSession(api_key="k", template="missing", sandbox_factory=factory)
    with pytest.raises(RemotionSandboxError) as caught:
        asyncio.run(_check_and_render(session))
    assert caught.value.code == "template_missing"


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_unreachable_sandbox_is_a_typed_start_failure():
    def factory(**_kwargs):
        raise SandboxException("quota")

    session = RemotionSession(api_key="k", sandbox_factory=factory)
    with pytest.raises(RemotionSandboxError) as caught:
        asyncio.run(_check_and_render(session))
    assert caught.value.code == "sandbox_unavailable"


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_build_error_is_returned_trimmed_and_redacted_and_the_sandbox_killed():
    secret = "sk-" + "a" * 30
    stderr = "x" * 5000 + f"\n{REMOTION_WORKDIR}/src/Composition.tsx: Unexpected token {secret}\x1b[31m red\x1b[0m"

    def fails(_sandbox, _command):
        raise CommandExitException(stderr=stderr, stdout="", exit_code=1, error="exit 1")

    session, sandbox = make_session(fails)
    with pytest.raises(RemotionCompositionError) as caught:
        asyncio.run(_check_and_render(session))
    assert caught.value.stage == "check"
    details = caught.value.details
    assert len(details) <= MAX_ERROR_CHARS
    assert "src/Composition.tsx: Unexpected token <redacted> red" in details
    assert secret not in details and REMOTION_WORKDIR not in details and "\x1b" not in details
    assert sandbox.killed


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_render_timeout_is_a_composition_failure():
    def render_times_out(sandbox, command):
        if "render" in command:
            raise CommandExitException(stderr="", stdout="", exit_code=137, error="killed")
        return succeeds(sandbox, command)

    session, _sandbox = make_session(render_times_out)
    with pytest.raises(RemotionCompositionError) as caught:
        asyncio.run(_check_and_render(session))
    assert caught.value.stage == "render" and "longer than 900 seconds" in caught.value.details


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_render_without_output_files_is_a_composition_failure():
    def writes_nothing(sandbox, command):
        if "check" in command:
            return succeeds(sandbox, command)
        return SimpleNamespace(exit_code=0)

    session, _sandbox = make_session(writes_nothing)
    with pytest.raises(RemotionCompositionError, match="no video"):
        asyncio.run(_check_and_render(session))


@pytest.mark.parametrize("assets, message", [
    ([RemotionAsset(name="../x.png", data=b"1")], "not allowed"),
    ([RemotionAsset(name="a.png", data=b"1"), RemotionAsset(name="a.png", data=b"2")], "used twice"),
    ([RemotionAsset(name="a.png", data=b"")], "empty"),
])
# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_unsafe_inputs_are_rejected_before_upload(assets, message):
    session, sandbox = make_session(succeeds)

    async def upload():
        async with session:
            await session.upload_inputs(assets)

    with pytest.raises(RemotionSandboxError, match=message):
        asyncio.run(upload())
    assert not any("/public/inputs/" in path for path in sandbox.store)
    assert sandbox.killed


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_one_session_renders_one_fixed_set_of_inputs():
    session, _sandbox = make_session(succeeds)

    async def upload_twice():
        async with session:
            await session.upload_inputs([ASSET])
            await session.upload_inputs([ASSET])  # same files: no-op
            await session.upload_inputs([RemotionAsset(name="other.png", data=b"x")])

    with pytest.raises(RemotionSandboxError, match="one fixed set"):
        asyncio.run(upload_twice())


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_render_requires_a_successful_check():
    session, _sandbox = make_session(succeeds)

    async def render_first():
        async with session:
            await session.upload_inputs([ASSET])
            await session.render(0)

    with pytest.raises(RuntimeError, match="check must succeed"):
        asyncio.run(render_first())


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_packages_are_pinned_and_composition_packages_are_installed():
    assert all(version[0].isdigit() and version.count(".") == 2 for version in REMOTION_PACKAGES.values())
    assert "latest" not in package_json()
    assert COMPOSITION_PACKAGES <= set(REMOTION_PACKAGES)
    assert "@remotion/google-fonts" not in COMPOSITION_PACKAGES  # downloads fonts at render time; sandbox is offline
    assert {REMOTION_PACKAGES[name] for name in REMOTION_PACKAGES if "remotion" in name} == {REMOTION_PACKAGES["remotion"]}


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_root_and_runner_follow_the_module_contract():
    assert "import Main, {parts, video} from './Composition'" in ROOT_TSX
    assert "durationInFrames={video.durationInFrames}" in ROOT_TSX and "width={video.width}" in ROOT_TSX
    assert "openmatesParts" in ROOT_TSX and "openmatesParts" in RUNNER_MJS
    assert "codec: 'h264'" in RUNNER_MJS and "renderStill" in RUNNER_MJS and "selectComposition" in RUNNER_MJS


# contract-test: supporting surface=gui.web assertions=videos-generate.composed.sandbox-render-and-correction
def test_redact_keeps_the_end_of_long_errors():
    assert redact("a" * 10 + "b" * MAX_ERROR_CHARS) == "b" * MAX_ERROR_CHARS
