# backend/tests/test_e2b_embroidery.py
#
# Provider tests for design.embroidery's E2B sandbox session with a fake
# sandbox: isolation settings, always-kill lifetime, upload of the pipeline,
# hard run limit, file download, summary validation and error mapping.
# Specification: feature.app-skill.design-embroidery
# (design-embroidery.convert.sandbox-inkstitch, design-embroidery.privacy.stored-like-generated-media,
# design-embroidery.result.complete-and-truthful).

from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace

import pytest
from e2b import AuthenticationException, CommandExitException, NotFoundException, SandboxException, TimeoutException

from backend.apps.design.embroidery_sandbox import UPLOADED_MODULES
from backend.shared.providers.e2b_embroidery import (
    EMBROIDERY_TEMPLATE_NAME,
    FILE_KEYS,
    MAX_SOURCE_SVG_CHARS,
    EmbroideryError,
    EmbroideryOptions,
    EmbroiderySession,
    pipeline_files,
)

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><path d="M1 1H9V9Z"/></svg>'
SUMMARY = {
    "width_mm": 90.4, "height_mm": 74.0, "stitch_count": 5816, "thread_changes": 2, "estimated_minutes": 12,
    "fits_hoop": "yes",
    "threads": [{"colour_hex": "#e76f51", "name": "#e76f51", "stitch_count": 3121},
                {"colour_hex": "#ffffff", "name": "#ffffff", "stitch_count": 580},
                {"colour_hex": "#1d3557", "name": "#1d3557", "stitch_count": 2115}],
    "notes": [{"code": "background_removed", "text": "Background left out"}],
}


class FakeSandbox:
    """In-memory stand-in for e2b.Sandbox; ``on_run`` decides what a pipeline run does."""

    def __init__(self, on_run) -> None:
        self.store: dict[str, bytes] = {}
        self.commands_run: list[tuple[str, dict]] = []
        self.killed = False
        self.on_run = on_run
        self.commands = SimpleNamespace(run=self._run)
        self.files = SimpleNamespace(write_files=self._write_files, read=self._read)

    def _write_files(self, files):
        for item in files:
            data = item["data"]
            self.store[item["path"]] = data.encode() if isinstance(data, str) else data

    def _read(self, path, format="text"):
        if path not in self.store:
            raise SandboxException(f"missing {path}")
        return self.store[path]

    def _run(self, command, **kwargs):
        self.commands_run.append((command, kwargs))
        if kwargs.get("background"):
            return SimpleNamespace()
        workdir = re.search(r"pipeline (check|convert) (\S+)$", command).group(2)
        return self.on_run(self, workdir)

    def kill(self):
        self.killed = True
        return True


def ok_convert(sandbox: FakeSandbox, workdir: str):
    files = {key: f"out/{key}.bin" for key in FILE_KEYS}
    for key, path in files.items():
        sandbox.store[f"{workdir}/{path}"] = f"{key}-bytes".encode()
    sandbox.store[f"{workdir}/result.json"] = json.dumps({
        "ok": True, "summary": SUMMARY, "findings": [], "files": files, "metrics": {"jumps": 3},
    }).encode()
    return SimpleNamespace(exit_code=0)


def failing(code: str):
    def run(sandbox: FakeSandbox, workdir: str):
        sandbox.store[f"{workdir}/result.json"] = json.dumps(
            {"ok": False, "error": {"code": code, "message": "Plain words."}}).encode()
        return SimpleNamespace(exit_code=0)
    return run


def raising(exc: Exception):
    def run(_sandbox, _workdir):
        raise exc
    return run


def make_session(on_run, created: list | None = None, **kwargs):
    sandbox = FakeSandbox(on_run)

    def factory(**create_kwargs):
        if created is not None:
            created.append(create_kwargs)
        return sandbox

    session = EmbroiderySession(api_key="test-key", template="tmpl-123", sandbox_factory=factory, **kwargs)
    return session, sandbox


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_convert_runs_isolated_and_always_kills_the_sandbox() -> None:
    created: list[dict] = []
    session, sandbox = make_session(ok_convert, created)

    async def scenario():
        async with session:
            return await session.convert(SVG, EmbroideryOptions(width_mm=90, hoop="130x180"))

    run = asyncio.run(scenario())
    assert created == [{
        "template": "tmpl-123", "api_key": "test-key", "secure": True, "allow_internet_access": False,
        "network": {"allow_public_traffic": False}, "timeout": 900,
        "metadata": {"openmates_purpose": "design_embroidery"},
    }]
    assert sandbox.killed
    assert set(run.files) == set(FILE_KEYS)
    assert run.files["pes"] == b"pes-bytes"
    assert run.summary == SUMMARY and run.findings == [] and run.metrics == {"jumps": 3}
    uploaded = {path.rsplit("/", 1)[-1] for path in sandbox.store if "/embroidery_sandbox/" in path}
    assert uploaded == set(UPLOADED_MODULES)
    command, kwargs = sandbox.commands_run[-1]
    assert "timeout -s KILL 180s python -m embroidery_sandbox.pipeline convert" in command
    assert kwargs["timeout"] == 195
    options = json.loads(sandbox.store["/home/user/embroidery/run1/options.json"])
    assert options == {"width_mm": 90.0, "hoop": "130x180", "fabric": "normal"}
    seconds = session.sandbox_seconds
    assert seconds >= 0 and session.sandbox_seconds == seconds  # frozen after kill


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_check_returns_findings_and_counts() -> None:
    def on_run(sandbox, workdir):
        sandbox.store[f"{workdir}/result.json"] = json.dumps({
            "ok": True, "findings": [{"code": "live_text", "detail": "Live text"}],
            "colour_count": 3, "shape_count": 7}).encode()

    session, _ = make_session(on_run)

    async def scenario():
        async with session:
            return await session.check(SVG, EmbroideryOptions())

    check = asyncio.run(scenario())
    assert check.findings == [{"code": "live_text", "detail": "Live text"}]
    assert (check.colour_count, check.shape_count) == (3, 7)


@pytest.mark.parametrize(("on_run", "code"), [
    (failing("too_many_stitches"), "too_many_stitches"),
    (failing("nothing_to_sew"), "nothing_to_sew"),
    (failing("made_up"), "sandbox_failed"),
    (raising(CommandExitException(stderr="", stdout="", exit_code=137, error=None)), "timeout"),
    (raising(CommandExitException(stderr="Traceback", stdout="", exit_code=1, error=None)), "sandbox_failed"),
    (raising(TimeoutException("deadline")), "timeout"),
    (raising(SandboxException("gone")), "sandbox_failed"),
])
# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_failures_map_to_codes_and_still_kill(on_run, code: str) -> None:
    session, sandbox = make_session(on_run)

    async def scenario():
        async with session:
            await session.convert(SVG, EmbroideryOptions())

    with pytest.raises(EmbroideryError) as error:
        asyncio.run(scenario())
    assert error.value.code == code
    assert error.value.user_message
    assert sandbox.killed


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_oversized_svg_is_rejected_without_running() -> None:
    session, sandbox = make_session(ok_convert)

    async def scenario():
        async with session:
            await session.convert("x" * (MAX_SOURCE_SVG_CHARS + 1), EmbroideryOptions())

    with pytest.raises(EmbroideryError) as error:
        asyncio.run(scenario())
    assert error.value.code == "unreadable_svg"
    assert all(kwargs.get("background") for _, kwargs in sandbox.commands_run)


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_incomplete_results_are_never_returned() -> None:
    def missing_file(sandbox, workdir):
        ok_convert(sandbox, workdir)
        del sandbox.store[f"{workdir}/out/vp3.bin"]

    def bad_summary(sandbox, workdir):
        ok_convert(sandbox, workdir)
        payload = json.loads(sandbox.store[f"{workdir}/result.json"])
        payload["summary"]["threads"] = payload["summary"]["threads"][:1]
        sandbox.store[f"{workdir}/result.json"] = json.dumps(payload).encode()

    def unsafe_path(sandbox, workdir):
        ok_convert(sandbox, workdir)
        payload = json.loads(sandbox.store[f"{workdir}/result.json"])
        payload["files"]["dst"] = "../../etc/passwd"
        sandbox.store[f"{workdir}/result.json"] = json.dumps(payload).encode()

    for on_run in (missing_file, bad_summary, unsafe_path):
        session, sandbox = make_session(on_run)

        async def scenario():
            async with session:
                await session.convert(SVG, EmbroideryOptions())

        with pytest.raises(EmbroideryError) as error:
            asyncio.run(scenario())
        assert error.value.code == "sandbox_failed"
        assert sandbox.killed


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_default_template_is_the_named_one_and_env_overrides_it(monkeypatch) -> None:
    monkeypatch.delenv("E2B_EMBROIDERY_TEMPLATE", raising=False)
    for env, expected in ((None, EMBROIDERY_TEMPLATE_NAME), ("custom-id", "custom-id")):
        if env:
            monkeypatch.setenv("E2B_EMBROIDERY_TEMPLATE", env)
        created: list[dict] = []

        def factory(**kwargs):
            created.append(kwargs)
            return FakeSandbox(ok_convert)

        async def scenario():
            async with EmbroiderySession(api_key="k", sandbox_factory=factory):
                pass

        asyncio.run(scenario())
        assert created[0]["template"] == expected


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
@pytest.mark.parametrize("failure", [NotFoundException("template not found"), AuthenticationException("bad key")])
def test_failed_sandbox_creation_surfaces_as_sandbox_failed(failure) -> None:
    def factory(**_kwargs):
        raise failure

    session = EmbroiderySession(api_key="k", sandbox_factory=factory)

    async def scenario():
        async with session:
            pass

    with pytest.raises(EmbroideryError) as error:
        asyncio.run(scenario())
    assert error.value.code == "sandbox_failed" and error.value.user_message
    assert session.sandbox_seconds == 0.0


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_invalid_options_are_rejected() -> None:
    for options in (EmbroideryOptions(width_mm=10), EmbroideryOptions(hoop="1x1"), EmbroideryOptions(fabric="x")):
        with pytest.raises(ValueError):
            options.as_dict()


# contract-test: supporting surface=rest_api assertions=design-embroidery.convert.sandbox-inkstitch
def test_pipeline_files_contains_every_uploaded_module() -> None:
    assert set(pipeline_files()) == set(UPLOADED_MODULES)


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border
def test_border_options_are_sent_only_when_set_and_validated() -> None:
    assert "border_mm" not in EmbroideryOptions().as_dict()
    assert EmbroideryOptions(border_mm=3).as_dict() == {
        "width_mm": 100.0, "hoop": "none", "fabric": "normal", "border_mm": 3.0, "border_colour": "#000000"}
    for options in (EmbroideryOptions(border_mm=0.5), EmbroideryOptions(border_mm=9),
                    EmbroideryOptions(border_mm=True), EmbroideryOptions(border_mm=3, border_colour="black")):
        with pytest.raises(ValueError):
            options.as_dict()


# contract-test: supporting surface=rest_api assertions=design-embroidery.prepare.sew-on-border,design-embroidery.result.complete-and-truthful
def test_border_width_and_transparent_preview_come_back_with_the_run() -> None:
    def convert_with_border(sandbox: FakeSandbox, workdir: str):
        ok_convert(sandbox, workdir)
        result = json.loads(sandbox.store[f"{workdir}/result.json"])
        result["summary"] = {**result["summary"], "border_mm": 3.0}
        sandbox.store[f"{workdir}/result.json"] = json.dumps(result).encode()
        return SimpleNamespace(exit_code=0)

    async def scenario(on_run):
        session, _ = make_session(on_run)
        async with session:
            return await session.convert(SVG, EmbroideryOptions(border_mm=3.0))

    run = asyncio.run(scenario(convert_with_border))
    assert run.summary["border_mm"] == 3.0
    assert run.files["preview_transparent"] == b"preview_transparent-bytes"

    def convert_with_text_border(sandbox: FakeSandbox, workdir: str):
        ok_convert(sandbox, workdir)
        result = json.loads(sandbox.store[f"{workdir}/result.json"])
        result["summary"] = {**result["summary"], "border_mm": "3"}
        sandbox.store[f"{workdir}/result.json"] = json.dumps(result).encode()
        return SimpleNamespace(exit_code=0)

    with pytest.raises(EmbroideryError) as error:
        asyncio.run(scenario(convert_with_text_border))
    assert error.value.code == "sandbox_failed"
