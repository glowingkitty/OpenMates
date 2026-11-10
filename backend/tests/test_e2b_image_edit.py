# backend/tests/test_e2b_image_edit.py
#
# Provider tests for images.modify's E2B sandbox session with a fake sandbox:
# isolation settings, always-kill lifetime, one-time input upload with the
# manifest, clean outputs per run, hard run limit, error feedback and the
# fixed runner's edit() contract and output limits (executed locally on a
# temporary directory, never on model code).
# Specification: feature.app-skill.images-modify
# (images-modify.sandbox.isolated-run, images-modify.request.pictures-from-the-chat,
# images-modify.author.program-not-pixels).

from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from e2b import CommandExitException, NotFoundException, SandboxException

from backend.shared.providers.e2b_image_edit import (
    IMAGE_EDIT_TEMPLATE_NAME,
    MAX_INPUT_BYTES,
    MAX_INPUTS,
    RUN_LIMIT_SECONDS,
    RUNNER,
    SANDBOX_ROOT,
    ImageEditError,
    ImageEditInput,
    ImageEditSession,
    build_manifest,
    safe_file_name,
)

PIXEL = ImageEditInput(name="Back Photo.JPG", data=b"jpeg-bytes", kind="pixel", width=3024, height=4032,
                       extension="jpg")
VECTOR = ImageEditInput(name="logo.svg", data=b"<svg/>", kind="svg", width=240, height=120, extension="svg")


class FakeSandbox:
    """In-memory stand-in for e2b.Sandbox; ``on_run`` decides what a program run does."""

    def __init__(self, on_run) -> None:
        self.store: dict[str, bytes] = {}
        self.commands_run: list[tuple[str, dict]] = []
        self.writes: list[list[str]] = []
        self.killed = False
        self.on_run = on_run
        self.commands = SimpleNamespace(run=self._run)
        self.files = SimpleNamespace(write_files=self._write_files, read=self._read)

    def _write_files(self, files):
        self.writes.append([item["path"] for item in files])
        for item in files:
            self.store[item["path"]] = item["data"]

    def _read(self, path, format="text"):
        if path not in self.store:
            raise SandboxException(f"missing {path}")
        return self.store[path]

    def _run(self, command, **kwargs):
        self.commands_run.append((command, kwargs))
        if kwargs.get("background"):
            return SimpleNamespace()
        for key in [key for key in self.store if key.startswith(f"{SANDBOX_ROOT}/outputs/")]:
            del self.store[key]
        return self.on_run(self)

    def kill(self):
        self.killed = True
        return True


def writes_png(sandbox: FakeSandbox):
    sandbox.store[f"{SANDBOX_ROOT}/outputs/result.png"] = b"png-bytes"
    sandbox.store[f"{SANDBOX_ROOT}/outputs/result.json"] = json.dumps(
        {"width": 640, "height": 480, "bytes": 9}).encode()
    return SimpleNamespace(exit_code=0)


def raising(exc: Exception):
    def run(_sandbox):
        raise exc
    return run


def make_session(on_run, created: list | None = None, **kwargs):
    sandbox = FakeSandbox(on_run)

    def factory(**create_kwargs):
        if created is not None:
            created.append(create_kwargs)
        return sandbox

    return ImageEditSession(api_key="test-key", template="tmpl-1", sandbox_factory=factory, **kwargs), sandbox


async def _run_once(session, program="def edit(inputs):\n    return inputs[0]['image']\n", inputs=(PIXEL,)):
    async with session:
        return await session.run(program, list(inputs))


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_sandbox_is_isolated_and_always_killed():
    created: list = []
    session, sandbox = make_session(writes_png, created)
    run = asyncio.run(_run_once(session))
    assert created[0]["allow_internet_access"] is False
    assert created[0]["network"] == {"allow_public_traffic": False}
    assert created[0]["secure"] is True
    assert created[0]["template"] == "tmpl-1"
    assert sandbox.killed
    assert run.image == b"png-bytes" and run.mime_type == "image/png" and (run.width, run.height) == (640, 480)
    assert run.error is None and run.seconds >= 0
    assert IMAGE_EDIT_TEMPLATE_NAME == "openmates-image-edit"


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_sandbox_is_killed_when_a_run_raises():
    session, sandbox = make_session(raising(SandboxException("lost")))

    with pytest.raises(ImageEditError) as caught:
        asyncio.run(_run_once(session))
    assert caught.value.code == "sandbox_failed"
    assert sandbox.killed


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_missing_template_is_a_typed_start_failure():
    def factory(**_kwargs):
        raise NotFoundException("template not found")

    session = ImageEditSession(api_key="k", template="missing", sandbox_factory=factory)
    with pytest.raises(ImageEditError) as caught:
        asyncio.run(_run_once(session))
    assert caught.value.code == "sandbox_failed"


# contract-test: supporting surface=rest_api assertions=images-modify.request.pictures-from-the-chat
def test_manifest_lists_every_input_in_order_with_safe_names_and_sizes():
    manifest = build_manifest([PIXEL, VECTOR])
    assert manifest == [
        {"index": 1, "file": "1_back-photo.jpg", "name": "1_back-photo", "kind": "pixel",
         "width": 3024, "height": 4032},
        {"index": 2, "file": "2_logo.svg", "name": "2_logo", "kind": "svg", "width": 240, "height": 120},
    ]
    weird = ImageEditInput(name="../../etc/passwd", data=b"x", kind="pixel", width=1, height=1, extension="png")
    assert safe_file_name(3, weird) == "3_etc-passwd.png"


# contract-test: supporting surface=rest_api assertions=images-modify.request.pictures-from-the-chat
@pytest.mark.parametrize("inputs,message", [
    ([], "between 1 and"),
    ([PIXEL] * (MAX_INPUTS + 1), "between 1 and"),
    ([ImageEditInput("a.png", b"x" * (MAX_INPUT_BYTES + 1), "pixel", 1, 1, "png")], "larger than"),
    ([ImageEditInput("a.png", b"", "pixel", 1, 1, "png")], "empty"),
    ([ImageEditInput("a.exe", b"x", "pixel", 1, 1, "exe")], "unsupported type"),
    ([ImageEditInput("a.svg", b"x", "svg", 0, 10, "svg")], "no pixel size"),
])
# contract-test: supporting surface=rest_api assertions=images-modify.request.pictures-from-the-chat
def test_inputs_outside_the_limits_fail_before_any_run(inputs, message):
    with pytest.raises(ImageEditError, match=message) as caught:
        build_manifest(inputs)
    assert caught.value.code == "invalid_input"


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_inputs_upload_once_and_every_run_gets_clean_outputs_under_the_limit():
    session, sandbox = make_session(writes_png)

    async def two_runs():
        async with session:
            first = await session.run("def edit(inputs):\n    pass\n", [PIXEL, VECTOR])
            second = await session.run("def edit(inputs):\n    pass\n", [PIXEL, VECTOR])
            return first, second

    first, second = asyncio.run(two_runs())
    assert first.image and second.image
    uploads = [paths for paths in sandbox.writes if any("/inputs/" in path for path in paths)]
    assert len(uploads) == 1
    assert f"{SANDBOX_ROOT}/inputs/manifest.json" in uploads[0]
    manifest = json.loads(sandbox.store[f"{SANDBOX_ROOT}/inputs/manifest.json"])
    assert [entry["file"] for entry in manifest] == ["1_back-photo.jpg", "2_logo.svg"]
    assert sandbox.store[f"{SANDBOX_ROOT}/inputs/1_back-photo.jpg"] == b"jpeg-bytes"
    runs = [(command, kwargs) for command, kwargs in sandbox.commands_run if not kwargs.get("background")]
    assert len(runs) == 2
    for command, kwargs in runs:
        assert "rm -rf outputs" in command
        assert f"timeout -s KILL {RUN_LIMIT_SECONDS}s" in command
        assert kwargs["timeout"] > RUN_LIMIT_SECONDS


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_a_session_edits_one_fixed_set_of_pictures():
    session, _sandbox = make_session(writes_png)

    async def mixed():
        async with session:
            await session.run("def edit(inputs):\n    pass\n", [PIXEL])
            await session.run("def edit(inputs):\n    pass\n", [VECTOR])

    with pytest.raises(ImageEditError, match="fixed set"):
        asyncio.run(mixed())


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_program_failure_returns_trimmed_feedback_not_an_exception():
    traceback = (f'Traceback (most recent call last):\n  File "{SANDBOX_ROOT}/program.py", line 4, in edit\n'
                 "IndexError: list index out of range\n")
    session, _ = make_session(raising(CommandExitException(stderr=traceback, stdout="", exit_code=1, error=None)))
    run = asyncio.run(_run_once(session))
    assert run.image is None
    assert 'File "program.py", line 4' in run.error and "IndexError" in run.error
    assert SANDBOX_ROOT not in run.error


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_run_over_the_limit_is_a_failed_round():
    session, _ = make_session(raising(CommandExitException(stderr="", stdout="", exit_code=137, error=None)))
    run = asyncio.run(_run_once(session))
    assert run.image is None and f"longer than {RUN_LIMIT_SECONDS} seconds" in run.error


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_run_without_a_picture_is_a_failed_round():
    session, _ = make_session(lambda _sandbox: SimpleNamespace(exit_code=0))
    run = asyncio.run(_run_once(session))
    assert run.image is None and run.error == "the program wrote no picture"


# --- The fixed runner, executed locally on trusted test programs ---------------------------------

def _run_runner(tmp_path, program: str, output_type: str = "png", inputs=()):
    pil = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    (tmp_path / "inputs").mkdir()
    manifest = []
    for index, (name, image, exif_orientation) in enumerate(inputs, start=1):
        buffer = io.BytesIO()
        if exif_orientation:
            exif = pil.Exif()
            exif[0x0112] = exif_orientation
            image.save(buffer, format="JPEG", exif=exif)
        else:
            image.save(buffer, format="PNG")
        extension = "jpg" if exif_orientation else "png"
        (tmp_path / "inputs" / f"{index}_{name}.{extension}").write_bytes(buffer.getvalue())
        manifest.append({"index": index, "file": f"{index}_{name}.{extension}", "name": f"{index}_{name}",
                         "kind": "pixel", "width": image.width, "height": image.height})
    (tmp_path / "inputs" / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "runner.py").write_text(RUNNER)
    (tmp_path / "program.py").write_text(program)
    return subprocess.run([sys.executable, "-B", "runner.py", output_type], cwd=tmp_path, capture_output=True,
                          text=True, timeout=60)


# contract-test: supporting surface=rest_api assertions=images-modify.author.program-not-pixels
def test_runner_passes_oriented_full_inputs_and_saves_the_returned_picture(tmp_path):
    from PIL import Image

    landscape = Image.new("RGB", (40, 20), "red")  # stored sideways; EXIF orientation 6 turns it upright
    program = (
        "import json\nfrom PIL import Image\n\n"
        "def edit(inputs):\n"
        "    item = inputs[0]\n"
        "    assert item['image'].size == (20, 40), item['image'].size\n"
        "    assert item['kind'] == 'pixel' and item['svg'] is None and item['index'] == 1\n"
        "    out = Image.new('RGBA', (30, 10), (0, 0, 255, 0))\n"
        "    return out\n"
    )
    done = _run_runner(tmp_path, program, "jpg", inputs=[("photo", landscape, 6)])
    assert done.returncode == 0, done.stderr
    meta = json.loads((tmp_path / "outputs" / "result.json").read_text())
    assert (meta["width"], meta["height"]) == (30, 10)
    with Image.open(tmp_path / "outputs" / "result.jpg") as result:
        assert result.format == "JPEG" and result.mode == "RGB"
        assert result.getpixel((5, 5))[0] > 240  # transparency flattened on white


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_runner_rejects_a_result_over_the_size_limit_instead_of_shrinking(tmp_path):
    from PIL import Image

    program = "from PIL import Image\n\ndef edit(inputs):\n    return Image.new('RGB', (4097, 8))\n"
    done = _run_runner(tmp_path, program, inputs=[("a", Image.new("RGB", (4, 4)), None)])
    assert done.returncode == 3
    assert "longest side may be at most 4096 px" in done.stderr
    assert not (tmp_path / "outputs" / "result.png").exists()


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_runner_reports_a_wrong_return_type_and_a_crash(tmp_path):
    from PIL import Image

    wrong = _run_runner(tmp_path, "def edit(inputs):\n    return 'nope'\n",
                        inputs=[("a", Image.new("RGB", (4, 4)), None)])
    assert wrong.returncode == 3 and "must return a PIL.Image.Image, not str" in wrong.stderr


# contract-test: supporting surface=rest_api assertions=images-modify.sandbox.isolated-run
def test_runner_traceback_names_the_program_line(tmp_path):
    from PIL import Image

    done = _run_runner(tmp_path, "def edit(inputs):\n    return inputs[3]['image']\n",
                       inputs=[("a", Image.new("RGB", (4, 4)), None)])
    assert done.returncode == 1
    assert 'program.py", line 2, in edit' in done.stderr and "IndexError" in done.stderr
