# backend/shared/providers/e2b_embroidery.py
#
# E2B sandbox provider for design.embroidery. One EmbroiderySession owns one
# sandbox created from the Ink/Stitch template (E2B_EMBROIDERY_TEMPLATE), with no
# internet access and no public traffic, and always kills it on exit. It uploads
# the pipeline package (backend/apps/design/embroidery_sandbox, read as data and
# never imported here) plus the untrusted SVG, runs the pipeline under a hard
# 600 s limit and returns the delivered files as bytes. The worker never parses
# the SVG geometry itself.

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async

if TYPE_CHECKING:
    from backend.core.api.app.utils.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)

EMBROIDERY_TEMPLATE_ENV = "E2B_EMBROIDERY_TEMPLATE"  # optional override of the default template
EMBROIDERY_TEMPLATE_NAME = "openmates-embroidery"  # built by backend/scripts/build_embroidery_template.py
PIPELINE_DIR = Path(__file__).resolve().parents[2] / "apps" / "design" / "embroidery_sandbox"
PIPELINE_PACKAGE = "embroidery_sandbox"
SANDBOX_ROOT = "/home/user/embroidery"
RUN_LIMIT_SECONDS = 600
COMMAND_GRACE_SECONDS = 15
# E2B kills the sandbox by itself after this, even if our process dies first. Covers the
# check, one conversion and one more conversion after a model rework.
SANDBOX_LIFETIME_SECONDS = 1500
MAX_SOURCE_SVG_CHARS = 400_000
MAX_FILE_BYTES = 25_000_000
FILE_KEYS = ("dst", "pes", "exp", "jef", "vp3", "preview", "preview_transparent", "prepared_svg", "stitches")
SUMMARY_KEYS = ("width_mm", "height_mm", "stitch_count", "thread_changes", "estimated_minutes",
                "fits_hoop", "threads", "notes")
# border_mm: only when a sew-on border was added. thread_length_m: estimated upper thread in metres.
OPTIONAL_SUMMARY_KEYS = ("border_mm", "thread_length_m")
FINDING_CODES = {"gradient_or_filter", "live_text", "embedded_pixel_image", "detail_below_1mm",
                 "more_than_12_colours"}
HOOPS = {"100x100", "130x180", "160x260", "200x300", "none"}
FABRICS = {"light", "normal", "stretchy"}
MIN_BORDER_MM = 1.0
MAX_BORDER_MM = 8.0
DEFAULT_BORDER_COLOUR = "#000000"
HEX_COLOUR_RE = re.compile(r"^#[0-9a-f]{6}$")
ERROR_CODES = {"unreadable_svg", "nothing_to_sew", "too_many_stitches", "timeout", "sandbox_failed"}
TIMEOUT_EXIT_CODES = {124, 137}
# Started in the background right after creation: the first Ink/Stitch launch and
# the first geometry imports in a fresh sandbox pay a one-off cold load from disk.
WARM_UP_COMMAND = ("python -c 'import shapely, svgelements, PIL' > /dev/null 2>&1 & "
                   "/opt/inkstitch/bin/inkstitch --extension=zip --format-dst=True "
                   "/opt/openmates-warm/warm.svg > /dev/null 2>&1")


@dataclass(frozen=True)
class EmbroideryOptions:
    width_mm: float = 100.0
    hoop: str = "none"        # "100x100" | "130x180" | "160x260" | "200x300" | "none"
    fabric: str = "normal"    # "light" | "normal" | "stretchy"
    border_mm: float | None = None  # sew-on border width at the sewn size; None = no border
    border_colour: str = DEFAULT_BORDER_COLOUR  # "#rrggbb", used only with border_mm
    fit_hoop: bool = False    # size the design (with its border) to fill the hoop; width_mm is then ignored

    def as_dict(self) -> dict[str, object]:
        if isinstance(self.width_mm, bool) or not isinstance(self.width_mm, (int, float)):
            raise ValueError("width_mm must be a number")
        if not 20 <= float(self.width_mm) <= 400:
            raise ValueError("width_mm must be between 20 and 400")
        if self.hoop not in HOOPS:
            raise ValueError(f"unknown hoop {self.hoop!r}")
        if self.fabric not in FABRICS:
            raise ValueError(f"unknown fabric {self.fabric!r}")
        options: dict[str, object] = {"width_mm": float(self.width_mm), "hoop": self.hoop, "fabric": self.fabric}
        if self.border_mm is not None:
            if isinstance(self.border_mm, bool) or not isinstance(self.border_mm, (int, float)):
                raise ValueError("border_mm must be a number")
            if not MIN_BORDER_MM <= float(self.border_mm) <= MAX_BORDER_MM:
                raise ValueError(f"border_mm must be between {MIN_BORDER_MM:g} and {MAX_BORDER_MM:g}")
            if not HEX_COLOUR_RE.match(self.border_colour):
                raise ValueError("border_colour must be a lowercase hex colour like #000000")
            options.update(border_mm=float(self.border_mm), border_colour=self.border_colour)
        if self.fit_hoop:
            if self.hoop == "none":
                raise ValueError("fit_hoop needs a hoop")
            options["fit_hoop"] = True
        return options


@dataclass
class EmbroideryCheck:
    """Result of the fixed check (no conversion)."""

    findings: list[dict]
    colour_count: int
    shape_count: int


@dataclass
class EmbroideryRun:
    """A finished conversion. ``summary`` describes the delivered files."""

    summary: dict
    files: dict[str, bytes]
    findings: list[dict]
    metrics: dict = field(default_factory=dict)  # timings, jumps, trims; for logs only


class EmbroideryError(Exception):
    """A conversion failure with a stable ``code`` and a plain-English ``user_message``."""

    def __init__(self, code: str, user_message: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unknown embroidery error code {code!r}")
        super().__init__(f"{code}: {user_message}")
        self.code = code
        self.user_message = user_message


SandboxFactory = Callable[..., Any]


def _default_factory(**kwargs: Any) -> Any:
    from e2b import Sandbox

    return Sandbox.create(**kwargs)


def pipeline_files(pipeline_dir: Path = PIPELINE_DIR) -> dict[str, bytes]:
    """The pipeline modules to upload, keyed by file name (never imported here)."""
    files = {path.name: path.read_bytes() for path in sorted(pipeline_dir.glob("*.py"))}
    if "pipeline.py" not in files or "__init__.py" not in files:
        raise RuntimeError(f"embroidery pipeline package is incomplete in {pipeline_dir}")
    return files


def _validate_findings(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise EmbroideryError("sandbox_failed", "The converter returned malformed findings.")
    findings = []
    for item in raw:
        if not isinstance(item, dict) or item.get("code") not in FINDING_CODES:
            raise EmbroideryError("sandbox_failed", "The converter returned an unknown finding.")
        findings.append({"code": item["code"], "detail": str(item.get("detail", ""))})
    return findings


def _validate_summary(raw: object) -> dict:
    if not isinstance(raw, dict) or not set(SUMMARY_KEYS) <= set(raw) <= {*SUMMARY_KEYS, *OPTIONAL_SUMMARY_KEYS}:
        raise EmbroideryError("sandbox_failed", "The converter returned an incomplete summary.")
    border = raw.get("border_mm")
    if "border_mm" in raw and (isinstance(border, bool) or not isinstance(border, (int, float))):
        raise EmbroideryError("sandbox_failed", "The converter returned an invalid border width.")
    numbers_ok = all(isinstance(raw[key], (int, float)) and not isinstance(raw[key], bool)
                     for key in ("width_mm", "height_mm"))
    ints_ok = all(isinstance(raw[key], int) and not isinstance(raw[key], bool) and raw[key] >= 0
                  for key in ("stitch_count", "thread_changes", "estimated_minutes"))
    threads_ok = ints_ok and isinstance(raw["threads"], list) and len(raw["threads"]) == raw["thread_changes"] + 1
    if not (numbers_ok and threads_ok and raw["fits_hoop"] in {"yes", "no", "not_checked"}
            and isinstance(raw["notes"], list)):
        raise EmbroideryError("sandbox_failed", "The converter returned an inconsistent summary.")
    return raw


class EmbroiderySession:
    """One sandbox for a check and one or more conversions of the same request.

    Use as ``async with EmbroiderySession(secrets_manager) as session``. The
    sandbox is created on enter and always killed on exit; ``sandbox_seconds``
    is the wall time since creation (frozen at kill) for billing.
    """

    def __init__(self, secrets_manager: "SecretsManager | None" = None, *, api_key: str | None = None,
                 template: str | None = None, sandbox_factory: SandboxFactory | None = None,
                 pipeline_dir: Path = PIPELINE_DIR, run_limit_seconds: int = RUN_LIMIT_SECONDS) -> None:
        self._secrets_manager = secrets_manager
        self._api_key = api_key
        self._template = template
        self._factory = sandbox_factory or _default_factory
        self._pipeline_dir = pipeline_dir
        self._run_limit = run_limit_seconds
        self._sandbox: Any = None
        self._created_at: float | None = None
        self._ended_at: float | None = None
        self._runs = 0

    @property
    def sandbox_seconds(self) -> float:
        if self._created_at is None:
            return 0.0
        end = self._ended_at if self._ended_at is not None else time.monotonic()
        return max(0.0, end - self._created_at)

    async def __aenter__(self) -> "EmbroiderySession":
        template = self._template or os.getenv(EMBROIDERY_TEMPLATE_ENV, "").strip() or EMBROIDERY_TEMPLATE_NAME
        api_key = self._api_key or await get_e2b_api_key_async(self._secrets_manager)
        files = pipeline_files(self._pipeline_dir)
        from e2b import AuthenticationException, SandboxException

        started = time.monotonic()
        try:
            self._sandbox = await asyncio.to_thread(
                self._factory, template=template, api_key=api_key, secure=True,
                allow_internet_access=False, network={"allow_public_traffic": False},
                timeout=SANDBOX_LIFETIME_SECONDS, metadata={"openmates_purpose": "design_embroidery"},
            )
        except (SandboxException, AuthenticationException) as exc:
            # A template missing from the E2B account surfaces here as NotFoundException.
            logger.error("Embroidery sandbox could not be created from template %r: %s", template, exc)
            raise EmbroideryError("sandbox_failed", "The embroidery converter could not be started.") from exc
        self._created_at = started
        try:
            await asyncio.to_thread(self._sandbox.commands.run, WARM_UP_COMMAND, background=True)
            await asyncio.to_thread(self._sandbox.files.write_files, [
                {"path": f"{SANDBOX_ROOT}/{PIPELINE_PACKAGE}/{name}", "data": data}
                for name, data in files.items()
            ])
        except SandboxException as exc:
            await self._kill()
            raise EmbroideryError("sandbox_failed", "The embroidery converter could not be prepared.") from exc
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
            logger.warning("Embroidery sandbox kill failed; E2B lifetime limit of %ss applies",
                           SANDBOX_LIFETIME_SECONDS, exc_info=True)
        finally:
            self._ended_at = time.monotonic()

    async def check(self, svg: str, options: EmbroideryOptions) -> EmbroideryCheck:
        result = await self._run("check", svg, options)
        colours, shapes = result.get("colour_count"), result.get("shape_count")
        if not isinstance(colours, int) or not isinstance(shapes, int):
            raise EmbroideryError("sandbox_failed", "The converter returned malformed check counts.")
        return EmbroideryCheck(findings=_validate_findings(result.get("findings")),
                               colour_count=colours, shape_count=shapes)

    async def convert(self, svg: str, options: EmbroideryOptions) -> EmbroideryRun:
        result = await self._run("convert", svg, options)
        summary = _validate_summary(result.get("summary"))
        findings = _validate_findings(result.get("findings"))
        paths = result.get("files")
        if not isinstance(paths, dict) or set(paths) != set(FILE_KEYS):
            raise EmbroideryError("sandbox_failed", "The converter did not list all result files.")
        workdir = result["_workdir"]
        files: dict[str, bytes] = {}
        from e2b import SandboxException

        for key in FILE_KEYS:
            relative = str(paths[key])
            if relative.startswith("/") or ".." in relative.split("/"):
                raise EmbroideryError("sandbox_failed", "The converter listed an unsafe file path.")

        async def download(key: str) -> bytes:
            try:
                return bytes(await asyncio.to_thread(self._sandbox.files.read, f"{workdir}/{paths[key]}",
                                                     format="bytes"))
            except SandboxException as exc:
                raise EmbroideryError("sandbox_failed", f"The {key} file could not be downloaded.") from exc

        for key, data in zip(FILE_KEYS, await asyncio.gather(*(download(key) for key in FILE_KEYS))):
            if not data or len(data) > MAX_FILE_BYTES:
                raise EmbroideryError("sandbox_failed", f"The {key} file is empty or too large.")
            files[key] = data
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        return EmbroideryRun(summary=summary, files=files, findings=findings, metrics=metrics)

    async def _run(self, mode: str, svg: str, options: EmbroideryOptions) -> dict:
        if self._sandbox is None:
            raise RuntimeError("EmbroiderySession must be entered before use")
        if len(svg) > MAX_SOURCE_SVG_CHARS:
            raise EmbroideryError("unreadable_svg", f"The graphic is larger than {MAX_SOURCE_SVG_CHARS:,} "
                                                    "characters and cannot be converted.")
        options_json = json.dumps(options.as_dict())
        self._runs += 1
        workdir = f"{SANDBOX_ROOT}/run{self._runs}"
        command = (f"cd {shlex.quote(SANDBOX_ROOT)} && timeout -s KILL {self._run_limit}s "
                   f"python -m {PIPELINE_PACKAGE}.pipeline {mode} {shlex.quote(workdir)}")
        from e2b import CommandExitException, SandboxException, TimeoutException

        try:
            await asyncio.to_thread(self._sandbox.files.write_files, [
                {"path": f"{workdir}/input.svg", "data": svg.encode("utf-8")},
                {"path": f"{workdir}/options.json", "data": options_json.encode("utf-8")},
            ])
            await asyncio.to_thread(self._sandbox.commands.run, command,
                                    timeout=self._run_limit + COMMAND_GRACE_SECONDS)
            raw = bytes(await asyncio.to_thread(self._sandbox.files.read, f"{workdir}/result.json",
                                                format="bytes"))
        except CommandExitException as exc:
            if exc.exit_code in TIMEOUT_EXIT_CODES:
                raise EmbroideryError("timeout", "The conversion took longer than the 10 minute limit "
                                                 "and was stopped.") from exc
            logger.warning("Embroidery pipeline exited with %s: %s", exc.exit_code, (exc.stderr or "")[-2000:])
            raise EmbroideryError("sandbox_failed", "The embroidery converter failed unexpectedly.") from exc
        except TimeoutException as exc:
            raise EmbroideryError("timeout", "The conversion took longer than the 10 minute limit "
                                             "and was stopped.") from exc
        except SandboxException as exc:
            raise EmbroideryError("sandbox_failed", "The embroidery converter failed unexpectedly.") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EmbroideryError("sandbox_failed", "The converter returned an unreadable result.") from exc
        if not isinstance(result, dict):
            raise EmbroideryError("sandbox_failed", "The converter returned an unreadable result.")
        if not result.get("ok"):
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            code = error.get("code") if error.get("code") in ERROR_CODES else "sandbox_failed"
            raise EmbroideryError(code, str(error.get("message") or "The embroidery converter failed."))
        result["_workdir"] = workdir
        return result
