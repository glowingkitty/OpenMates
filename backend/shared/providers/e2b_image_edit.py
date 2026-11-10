# backend/shared/providers/e2b_image_edit.py
#
# E2B sandbox provider for images.modify. One ImageEditSession owns one sandbox
# created from the image-edit template (E2B_IMAGE_EDIT_TEMPLATE, built by
# backend/scripts/build_image_edit_template.py), with no internet access and no
# public traffic, and always kills it on exit. The input pictures are uploaded
# once as bytes; each run writes a model-authored program module, executes it
# through a fixed runner under a hard 60 s limit and downloads the single
# output picture. The model's code never runs in a worker process.
#
# Program contract (the runner calls it once per run):
#
#     def edit(inputs: list[dict]) -> PIL.Image.Image
#
# ``inputs`` follows the order of the request. Every item has
#   index   1-based position of the picture in the request
#   name    the safe file name stem the picture was uploaded under
#   kind    "pixel" or "svg"
#   width, height   exact pixel size (pixel: after EXIF orientation; svg: intrinsic size)
#   path    absolute path of the uploaded file (read-only use)
#   image   pixel: PIL image in RGB or RGBA (RGBA when the file has transparency),
#           EXIF orientation already applied; svg: None
#   svg     svg: the SVG source text; pixel: None
# ``random`` and ``numpy.random`` are seeded with 0 before the call, so the same
# program on the same inputs gives the same picture.
#
# Output: the returned image is saved as PNG (RGB/RGBA/L kept, other modes as
# RGBA) or JPEG (RGB; transparency flattened on white). A result whose longest
# side exceeds 4096 px or whose file exceeds 20 MB fails the run with a clear
# message instead of being shrunk silently: the Specification counts such a run
# as a failed round that the author corrects, and the size stays the author's
# decision.
#
# Sandbox layout: <root>/inputs/<n>_<safe-name>.<ext> plus inputs/manifest.json
# (list of {"index", "file", "kind", "width", "height"}), <root>/runner.py,
# <root>/program.py (rewritten per run) and <root>/outputs/ (emptied per run).

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence

from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

IMAGE_EDIT_TEMPLATE_ENV = "E2B_IMAGE_EDIT_TEMPLATE"  # optional override of the default template
IMAGE_EDIT_TEMPLATE_NAME = "openmates-image-edit"  # built by backend/scripts/build_image_edit_template.py
SANDBOX_ROOT = "/home/user/edit"
RUN_LIMIT_SECONDS = 60
COMMAND_GRACE_SECONDS = 15
# E2B kills the sandbox by itself after this, even if our process dies first.
SANDBOX_LIFETIME_SECONDS = 600
MAX_INPUTS = 6
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_OUTPUT_SIDE = 4096
MAX_OUTPUT_BYTES = 20 * 1024 * 1024
MAX_PROGRAM_CHARS = 60_000
MAX_ERROR_CHARS = 1500
OUTPUT_TYPES = {"png": "image/png", "jpg": "image/jpeg"}
INPUT_KINDS = {"pixel", "svg"}
TIMEOUT_EXIT_CODES = {124, 137}
ERROR_CODES = {"invalid_input", "sandbox_failed"}
_EXTENSIONS = {"pixel": {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"}, "svg": {"svg"}}
_SAFE_NAME = re.compile(r"[^a-z0-9]+")
# Started in the background right after creation: the first import of the image libraries in a
# fresh sandbox pays a one-off cold load from disk (measured about 4 s), which the first run then skips.
WARM_UP_COMMAND = "python -c 'import numpy, cv2, cairosvg; from PIL import Image, ImageFont' > /dev/null 2>&1"

# Fixed runner; uploaded once per sandbox. Exit 3 marks a contract violation by the program.
RUNNER = f'''import json, os, random, sys, traceback
import numpy
from PIL import Image, ImageOps

MAX_SIDE = {MAX_OUTPUT_SIDE}
MAX_BYTES = {MAX_OUTPUT_BYTES}


def fail(message):
    sys.stderr.write(message + "\\n")
    sys.exit(3)


def load(entry):
    path = os.path.abspath(os.path.join("inputs", entry["file"]))
    item = {{"index": entry["index"], "name": entry["name"], "kind": entry["kind"],
            "width": entry["width"], "height": entry["height"], "path": path, "image": None, "svg": None}}
    if entry["kind"] == "svg":
        with open(path, encoding="utf-8") as handle:
            item["svg"] = handle.read()
        return item
    with Image.open(path) as source:
        source.load()
        image = ImageOps.exif_transpose(source)
    alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    image = image.convert("RGBA" if alpha else "RGB")
    item["image"] = image
    return item


def main():
    output_type = sys.argv[1]
    with open(os.path.join("inputs", "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    inputs = [load(entry) for entry in manifest]
    random.seed(0)
    numpy.random.seed(0)
    import program
    if not callable(getattr(program, "edit", None)):
        fail("the program does not define edit(inputs)")
    try:
        result = program.edit(inputs)
    except Exception:  # sandbox-side: any program failure becomes correction feedback

        lines = traceback.format_exc().replace(os.getcwd() + "/", "")
        sys.stderr.write(lines)
        sys.exit(1)
    if not isinstance(result, Image.Image):
        fail(f"edit(inputs) must return a PIL.Image.Image, not {{type(result).__name__}}")
    width, height = result.size
    if width < 1 or height < 1:
        fail("edit(inputs) returned an empty picture")
    if max(width, height) > MAX_SIDE:
        fail(f"the result is {{width}}x{{height}} px; the longest side may be at most {{MAX_SIDE}} px")
    os.makedirs("outputs", exist_ok=True)
    target = os.path.join("outputs", "result." + output_type)
    if output_type == "jpg":
        if result.mode in ("RGBA", "LA", "PA") or "transparency" in result.info:
            rgba = result.convert("RGBA")
            flat = Image.new("RGB", rgba.size, "white")
            flat.paste(rgba, mask=rgba.getchannel("A"))
            result = flat
        else:
            result = result.convert("RGB")
        result.save(target, format="JPEG", quality=92, subsampling=0)
    else:
        if result.mode not in ("RGB", "RGBA", "L"):
            result = result.convert("RGBA")
        result.save(target, format="PNG", optimize=False, compress_level=6)
    size = os.path.getsize(target)
    if size > MAX_BYTES:
        os.remove(target)
        fail(f"the result file is {{size // 1048576}} MB; at most {{MAX_BYTES // 1048576}} MB are allowed")
    with open(os.path.join("outputs", "result.json"), "w", encoding="utf-8") as handle:
        json.dump({{"width": width, "height": height, "bytes": size}}, handle)


main()
'''


@dataclass(frozen=True)
class ImageEditInput:
    """One input picture as uploaded to the sandbox; ``width``/``height`` are the oriented pixel size."""

    name: str
    data: bytes
    kind: str  # "pixel" | "svg"
    width: int
    height: int
    extension: str  # file extension without dot, e.g. "jpg", "png", "svg"


@dataclass(frozen=True)
class ImageEditRun:
    """Outcome of one program run: the picture or the error text, and the billable run time."""

    image: Optional[bytes]
    mime_type: Optional[str]
    width: int
    height: int
    seconds: float
    error: Optional[str] = None


class ImageEditError(Exception):
    """A failure that is not the program's fault, with a stable ``code`` and a plain message."""

    def __init__(self, code: str, user_message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown image edit error code {code!r}")
        super().__init__(f"{code}: {user_message}")
        self.code = code
        self.user_message = user_message


SandboxFactory = Callable[..., Any]


def _default_factory(**kwargs: Any) -> Any:
    from e2b import Sandbox

    return Sandbox.create(**kwargs)


def safe_file_name(index: int, item: ImageEditInput) -> str:
    """Return the sandbox file name ``<n>_<safe-name>.<ext>`` of one input."""
    stem = os.path.splitext(item.name)[0].lower()
    safe = _SAFE_NAME.sub("-", stem).strip("-")[:40] or "picture"
    return f"{index}_{safe}.{item.extension}"


def build_manifest(inputs: Sequence[ImageEditInput]) -> list[dict[str, Any]]:
    """Validate the inputs and return the manifest the runner reads (one entry per picture, in order)."""
    if not 1 <= len(inputs) <= MAX_INPUTS:
        raise ImageEditError("invalid_input", f"between 1 and {MAX_INPUTS} pictures can be edited")
    manifest: list[dict[str, Any]] = []
    for index, item in enumerate(inputs, start=1):
        if item.kind not in INPUT_KINDS or item.extension not in _EXTENSIONS[item.kind]:
            raise ImageEditError("invalid_input", f"picture {index} has an unsupported type")
        if not item.data or len(item.data) > MAX_INPUT_BYTES:
            raise ImageEditError("invalid_input", f"picture {index} is empty or larger than "
                                                  f"{MAX_INPUT_BYTES // 1048576} MB")
        if item.width < 1 or item.height < 1:
            raise ImageEditError("invalid_input", f"picture {index} has no pixel size")
        file_name = safe_file_name(index, item)
        manifest.append({"index": index, "file": file_name, "name": os.path.splitext(file_name)[0],
                         "kind": item.kind, "width": int(item.width), "height": int(item.height)})
    return manifest


def _trim_error(text: str) -> str:
    text = (text or "").replace(SANDBOX_ROOT + "/", "").strip()
    return text[-MAX_ERROR_CHARS:]


class ImageEditSession:
    """One sandbox for every program run of one images.modify request.

    Use as ``async with ImageEditSession(secrets_manager) as session`` and call
    ``await session.run(program, inputs)`` once per round. The inputs are
    uploaded on the first run; later runs must pass the same inputs and get a
    clean ``outputs`` directory. The sandbox is always killed on exit.
    """

    def __init__(self, secrets_manager: "SecretsManager | None" = None, *, api_key: str | None = None,
                 template: str | None = None, sandbox_factory: SandboxFactory | None = None,
                 run_limit_seconds: int = RUN_LIMIT_SECONDS, output_type: str = "png") -> None:
        if output_type not in OUTPUT_TYPES:
            raise ValueError(f"unknown output type {output_type!r}")
        self._secrets_manager = secrets_manager
        self._api_key = api_key
        self._template = template
        self._factory = sandbox_factory or _default_factory
        self._run_limit = run_limit_seconds
        self._output_type = output_type
        self._sandbox: Any = None
        self._uploaded: Optional[str] = None

    async def __aenter__(self) -> "ImageEditSession":
        template = self._template or os.getenv(IMAGE_EDIT_TEMPLATE_ENV, "").strip() or IMAGE_EDIT_TEMPLATE_NAME
        api_key = self._api_key or await get_e2b_api_key_async(self._secrets_manager)
        from e2b import AuthenticationException, SandboxException

        try:
            self._sandbox = await asyncio.to_thread(
                self._factory, template=template, api_key=api_key, secure=True,
                allow_internet_access=False, network={"allow_public_traffic": False},
                timeout=SANDBOX_LIFETIME_SECONDS, metadata={"openmates_purpose": "images_modify"},
            )
        except (SandboxException, AuthenticationException) as exc:
            # A template missing from the E2B account surfaces here as NotFoundException.
            logger.error("Image edit sandbox could not be created from template %r: %s", template, exc)
            raise ImageEditError("sandbox_failed", "The picture editor could not be started.") from exc
        try:
            await asyncio.to_thread(self._sandbox.commands.run, WARM_UP_COMMAND, background=True)
            await asyncio.to_thread(self._sandbox.files.write_files, [
                {"path": f"{SANDBOX_ROOT}/runner.py", "data": RUNNER.encode("utf-8")},
            ])
        except SandboxException as exc:
            await self._kill()
            raise ImageEditError("sandbox_failed", "The picture editor could not be prepared.") from exc
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self._kill()

    async def _kill(self) -> None:
        sandbox, self._sandbox = self._sandbox, None
        if sandbox is None:
            return
        from e2b import SandboxException

        try:
            await asyncio.to_thread(sandbox.kill)
        except SandboxException:
            logger.warning("Image edit sandbox kill failed; E2B lifetime limit of %ss applies",
                           SANDBOX_LIFETIME_SECONDS, exc_info=True)

    async def _upload_inputs(self, inputs: Sequence[ImageEditInput]) -> None:
        manifest = build_manifest(inputs)
        digest = hashlib.sha256(json.dumps(manifest).encode() + b"".join(
            hashlib.sha256(item.data).digest() for item in inputs)).hexdigest()
        if self._uploaded == digest:
            return
        if self._uploaded is not None:
            raise ImageEditError("invalid_input", "one session edits one fixed set of pictures")
        from e2b import SandboxException

        files = [{"path": f"{SANDBOX_ROOT}/inputs/{entry['file']}", "data": item.data}
                 for entry, item in zip(manifest, inputs)]
        files.append({"path": f"{SANDBOX_ROOT}/inputs/manifest.json",
                      "data": json.dumps(manifest, indent=1).encode("utf-8")})
        try:
            await asyncio.to_thread(self._sandbox.files.write_files, files)
        except SandboxException as exc:
            raise ImageEditError("sandbox_failed", "The pictures could not be uploaded to the editor.") from exc
        self._uploaded = digest

    async def run(self, program: str, inputs: Sequence[ImageEditInput]) -> ImageEditRun:
        """Run one program on the inputs; a failure of the program is returned as ``error``."""
        if self._sandbox is None:
            raise RuntimeError("ImageEditSession must be entered before use")
        if not program.strip() or len(program) > MAX_PROGRAM_CHARS:
            return ImageEditRun(None, None, 0, 0, 0.0, f"the program is empty or longer than {MAX_PROGRAM_CHARS} "
                                                        "characters")
        await self._upload_inputs(inputs)
        command = (f"cd {shlex.quote(SANDBOX_ROOT)} && rm -rf outputs __pycache__ && mkdir outputs && "
                   f"timeout -s KILL {self._run_limit}s python -B -s runner.py {self._output_type}")
        from e2b import CommandExitException, SandboxException, TimeoutException

        try:
            await asyncio.to_thread(self._sandbox.files.write_files, [
                {"path": f"{SANDBOX_ROOT}/program.py", "data": program.encode("utf-8")},
            ])
        except SandboxException as exc:
            raise ImageEditError("sandbox_failed", "The program could not be uploaded to the editor.") from exc
        started = time.monotonic()
        try:
            await asyncio.to_thread(self._sandbox.commands.run, command,
                                    timeout=self._run_limit + COMMAND_GRACE_SECONDS)
        except CommandExitException as exc:
            seconds = time.monotonic() - started
            if exc.exit_code in TIMEOUT_EXIT_CODES:
                return ImageEditRun(None, None, 0, 0, seconds,
                                    f"the program ran longer than {self._run_limit} seconds and was stopped")
            return ImageEditRun(None, None, 0, 0, seconds,
                                _trim_error(exc.stderr or "") or f"the program exited with code {exc.exit_code}")
        except TimeoutException:
            return ImageEditRun(None, None, 0, 0, time.monotonic() - started,
                                f"the program ran longer than {self._run_limit} seconds and was stopped")
        except SandboxException as exc:
            raise ImageEditError("sandbox_failed", "The picture editor failed unexpectedly.") from exc
        seconds = time.monotonic() - started
        return await self._download(seconds)

    async def _download(self, seconds: float) -> ImageEditRun:
        from e2b import SandboxException

        try:
            raw = bytes(await asyncio.to_thread(self._sandbox.files.read, f"{SANDBOX_ROOT}/outputs/result.json",
                                                format="bytes"))
            image = bytes(await asyncio.to_thread(
                self._sandbox.files.read, f"{SANDBOX_ROOT}/outputs/result.{self._output_type}", format="bytes"))
        except SandboxException:
            return ImageEditRun(None, None, 0, 0, seconds, "the program wrote no picture")
        try:
            meta = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImageEditError("sandbox_failed", "The picture editor returned an unreadable result.") from exc
        if not isinstance(meta, dict):
            raise ImageEditError("sandbox_failed", "The picture editor returned an unreadable result.")
        width, height = meta.get("width"), meta.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or not image or len(image) > MAX_OUTPUT_BYTES:
            raise ImageEditError("sandbox_failed", "The picture editor returned an inconsistent result.")
        return ImageEditRun(image, OUTPUT_TYPES[self._output_type], width, height, seconds)
