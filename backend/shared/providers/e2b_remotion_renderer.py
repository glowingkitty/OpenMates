# backend/shared/providers/e2b_remotion_renderer.py
#
# E2B sandbox provider that renders one Remotion composition module to MP4.
# A RemotionSession owns one sandbox created from the Remotion template
# (E2B_REMOTION_TEMPLATE, built by backend/scripts/build_remotion_template.py)
# with no internet access and no public traffic, and always kills it on exit.
# The template holds the pinned Remotion packages (REMOTION_PACKAGES), Chrome
# headless shell and a fixed set of system fonts (INSTALLED_FONT_FAMILIES);
# nothing is installed or downloaded at request time.
#
# Per request: the pictures/clips are uploaded once to public/inputs/<name>;
# each round writes src/Composition.tsx (model-authored or built by code) and
# runs the fixed runner.mjs in two steps:
#   check   bundle src/index.ts with @remotion/bundler, then selectComposition()
#           in the headless browser; writes {video, parts} read from the
#           module's own exports (no regex parsing) to out/meta.json.
#   render  renderMedia() h264 MP4 and renderStill() PNG thumbnail from that
#           bundle, under a hard 900 s limit.
# A composition that does not build or fails while rendering raises
# RemotionCompositionError with the trimmed, redacted error text, which the
# caller hands back to the author for a correction. Failures that are not the
# composition's fault raise RemotionSandboxError. This module is a pure
# provider: it knows nothing about skills, embeds or billing.

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

REMOTION_TEMPLATE_ENV = "E2B_REMOTION_TEMPLATE"
REMOTION_TEMPLATE_NAME = "openmates-remotion-renderer-dev"  # default in backend/core/docker-compose.yml
REMOTION_WORKDIR = "/home/user/remotion"
REMOTION_VERSION = "4.0.540"
REACT_VERSION = "19.3.1"
# Exact versions installed in the template (backend/scripts/build_remotion_template.py); never "latest".
REMOTION_PACKAGES: dict[str, str] = {
    "remotion": REMOTION_VERSION,
    "@remotion/cli": REMOTION_VERSION,
    "@remotion/bundler": REMOTION_VERSION,
    "@remotion/renderer": REMOTION_VERSION,
    "@remotion/transitions": REMOTION_VERSION,
    "@remotion/shapes": REMOTION_VERSION,
    "@remotion/paths": REMOTION_VERSION,
    "@remotion/noise": REMOTION_VERSION,
    "@remotion/animation-utils": REMOTION_VERSION,
    "@remotion/layout-utils": REMOTION_VERSION,
    "@remotion/media-utils": REMOTION_VERSION,
    "@remotion/media": REMOTION_VERSION,
    "@remotion/motion-blur": REMOTION_VERSION,
    "react": REACT_VERSION,
    "react-dom": REACT_VERSION,
}
# Packages a composition may import; tooling (cli, bundler, renderer) stays off-limits.
COMPOSITION_PACKAGES: frozenset[str] = frozenset({
    "remotion", "react", "@remotion/transitions", "@remotion/shapes", "@remotion/paths", "@remotion/noise",
    "@remotion/animation-utils", "@remotion/layout-utils", "@remotion/media-utils", "@remotion/media",
    "@remotion/motion-blur",
})
# Debian packages installed in the template. @remotion/google-fonts downloads from fonts.gstatic.com at
# render time, which the offline sandbox cannot do, so fonts are system fonts used by CSS fontFamily name.
FONT_APT_PACKAGES = (
    "fonts-inter fonts-roboto fonts-lato fonts-open-sans fonts-noto-core fonts-noto-cjk fonts-noto-color-emoji "
    "fonts-dejavu-core fonts-liberation fonts-bebas-neue fonts-jetbrains-mono fonts-league-spartan fonts-ebgaramond"
)
INSTALLED_FONT_FAMILIES: tuple[str, ...] = (
    "Inter", "Roboto", "Lato", "Open Sans", "Noto Sans", "Noto Serif", "Bebas Neue", "League Spartan",
    "EB Garamond", "JetBrains Mono", "Noto Sans CJK SC", "Noto Color Emoji",
)
SOURCE_FILENAME = "Composition.tsx"
CHECK_LIMIT_SECONDS = 240
RENDER_LIMIT_SECONDS = 900
COMMAND_GRACE_SECONDS = 20
SANDBOX_LIFETIME_SECONDS = 1800  # E2B kills the sandbox by itself after this, even if our process dies first
RENDER_CONCURRENCY = 3
MAX_INPUTS = 12
MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_AUDIO_FILES = 21
MAX_AUDIO_BYTES = 15 * 1024 * 1024
AUDIO_TRACKS_FILE = "audio-tracks.json"
MAX_SOURCE_CHARS = 60_000
MAX_OUTPUT_BYTES = 300 * 1024 * 1024
MAX_ERROR_CHARS = 3000
TIMEOUT_EXIT_CODES = {124, 137}
SANDBOX_ERROR_CODES = {"template_missing", "sandbox_unavailable", "sandbox_failed", "invalid_input"}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[oprsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]
SAFE_INPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

INDEX_TS = "import {registerRoot} from 'remotion';\nimport {Root} from './Root';\n\nregisterRoot(Root);\n"

ROOT_TSX = """import React from 'react';
import {Audio, Composition, Sequence, interpolate, staticFile} from 'remotion';
import Main, {parts, video} from './Composition';
import * as Module from './Composition';

if (!video || typeof video !== 'object') {
  throw new Error('Composition.tsx must export const video = {fps, durationInFrames, width, height}');
}
if (!Array.isArray(parts)) {
  throw new Error('Composition.tsx must export const parts = [...] (an array)');
}
if (typeof Main !== 'function') {
  throw new Error('Composition.tsx must export default the React component');
}

type Track = {file: string; from: number; durationInFrames: number; volume: number; fadeOutFrames: number; loop: boolean};

// The renderer, never the author, adds the sound tracks: one <Audio> per generated clip, passed as input props.
const WithAudio: React.FC<Record<string, unknown>> = (props) => {
  const tracks = (props.openmatesAudio as Track[] | undefined) ?? [];
  return (
    <>
      <Main {...props} />
      {tracks.map((track) => (
        <Sequence key={track.file} from={track.from} durationInFrames={track.durationInFrames}>
          <Audio
            src={staticFile(track.file)}
            loop={track.loop}
            volume={(frame: number) =>
              track.volume *
              (track.fadeOutFrames > 0
                ? interpolate(frame, [track.durationInFrames - track.fadeOutFrames, track.durationInFrames], [1, 0],
                    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
                : 1)}
          />
        </Sequence>
      ))}
    </>
  );
};

export const Root: React.FC = () => (
  <Composition
    id="Main"
    component={WithAudio}
    fps={video.fps}
    durationInFrames={video.durationInFrames}
    width={video.width}
    height={video.height}
    defaultProps={{
      openmatesParts: JSON.parse(JSON.stringify(parts)),
      openmatesAudioPlan: JSON.parse(JSON.stringify((Module as Record<string, unknown>).audio ?? null)),
    }}
  />
);
"""

# Fixed runner; uploaded once per sandbox. Exit 3 marks an output limit, exit 1 a composition failure.
RUNNER_MJS = f"""import fs from 'node:fs';
import path from 'node:path';
import {{bundle}} from '@remotion/bundler';
import {{renderMedia, renderStill, selectComposition}} from '@remotion/renderer';

const root = process.cwd();
const serveUrl = path.join(root, 'build');
const browserErrors = [];
const onBrowserLog = (log) => {{
  if (log.type === 'error' || log.type === 'warning') browserErrors.push(log.text);
}};

function fail(error) {{
  const text = (error && (error.stack || error.message)) || String(error);
  process.stderr.write(text + '\\n');
  if (browserErrors.length) process.stderr.write('Browser console:\\n' + browserErrors.slice(-20).join('\\n') + '\\n');
  process.exit(1);
}}

async function check() {{
  fs.rmSync(serveUrl, {{recursive: true, force: true}});
  fs.mkdirSync(path.join(root, 'out'), {{recursive: true}});
  await bundle({{
    entryPoint: path.join(root, 'src/index.ts'),
    outDir: serveUrl,
    publicDir: path.join(root, 'public'),
    enableCaching: true,
    onProgress: () => undefined,
  }});
  const composition = await selectComposition({{serveUrl, id: 'Main', onBrowserLog, logLevel: 'error'}});
  const meta = {{
    video: {{fps: composition.fps, durationInFrames: composition.durationInFrames,
             width: composition.width, height: composition.height}},
    parts: (composition.defaultProps || {{}}).openmatesParts ?? null,
    audio: (composition.defaultProps || {{}}).openmatesAudioPlan ?? null,
  }};
  fs.writeFileSync(path.join(root, 'out/meta.json'), JSON.stringify(meta));
}}

async function render(thumbnailFrame, concurrency) {{
  const tracksFile = path.join(root, 'audio-tracks.json');
  const inputProps = {{openmatesAudio: fs.existsSync(tracksFile) ? JSON.parse(fs.readFileSync(tracksFile, 'utf8')) : []}};
  const composition = await selectComposition({{serveUrl, id: 'Main', inputProps, onBrowserLog, logLevel: 'error'}});
  const video = path.join(root, 'out/video.mp4');
  const thumbnail = path.join(root, 'out/thumbnail.png');
  await renderMedia({{
    composition, serveUrl, inputProps, codec: 'h264', outputLocation: video, concurrency, x264Preset: 'veryfast',
    timeoutInMilliseconds: 60000, onBrowserLog, logLevel: 'error', overwrite: true,
  }});
  await renderStill({{
    composition, serveUrl, output: thumbnail, frame: thumbnailFrame, imageFormat: 'png',
    timeoutInMilliseconds: 60000, onBrowserLog, logLevel: 'error', overwrite: true,
  }});
  const bytes = fs.statSync(video).size;
  if (bytes > {MAX_OUTPUT_BYTES}) {{
    process.stderr.write(`the video file is ${{Math.round(bytes / 1048576)}} MB; at most {MAX_OUTPUT_BYTES // 1048576} MB are allowed\\n`);
    process.exit(3);
  }}
  fs.writeFileSync(path.join(root, 'out/render.json'), JSON.stringify({{bytes}}));
}}

const [mode, frame, concurrency] = process.argv.slice(2);
const job = mode === 'check' ? check() : render(Number(frame), Number(concurrency));
job.then(() => process.exit(0), fail);
"""


@dataclass(frozen=True)
class RemotionAsset:
    """One file uploaded to ``public/inputs/<name>``; the composition reads it via ``staticFile``."""

    name: str
    data: bytes


@dataclass(frozen=True)
class RemotionCheck:
    """What the bundled module declares: ``video``, ``parts`` and ``audio`` (None when absent) as exported."""

    video: dict[str, Any]
    parts: Any
    seconds: float
    audio: Any = None


@dataclass(frozen=True)
class RemotionRender:
    """The rendered MP4 and thumbnail plus the billable wall seconds of the render step."""

    mp4: bytes
    thumbnail_png: bytes
    seconds: float


class RemotionCompositionError(Exception):
    """The composition itself failed (``stage`` is "check" or "render"); ``details`` goes back to the author."""

    def __init__(self, stage: str, details: str, seconds: float) -> None:
        super().__init__(f"{stage} failed: {details[:300]}")
        self.stage = stage
        self.details = details
        self.seconds = seconds


class RemotionSandboxError(Exception):
    """A failure that is not the composition's fault, with a stable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        if code not in SANDBOX_ERROR_CODES:
            raise ValueError(f"unknown Remotion sandbox error code {code!r}")
        super().__init__(f"{code}: {message}")
        self.code = code
        self.user_message = message


SandboxFactory = Callable[..., Any]


def _default_factory(**kwargs: Any) -> Any:
    from e2b import Sandbox

    return Sandbox.create(**kwargs)


def remotion_template_name() -> str:
    """The template the session starts: the env override or the dev default."""
    return os.getenv(REMOTION_TEMPLATE_ENV, "").strip() or REMOTION_TEMPLATE_NAME


def redact(text: str) -> str:
    """Remove secrets, terminal colours and sandbox paths; keep the last ``MAX_ERROR_CHARS`` characters."""
    text = _ANSI.sub("", text or "").replace(REMOTION_WORKDIR + "/", "").strip()
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("<redacted>", text)
    return text[-MAX_ERROR_CHARS:]


def package_json() -> str:
    """The template's package.json with exact versions."""
    return json.dumps({"name": "openmates-remotion", "private": True, "type": "module",
                       "dependencies": dict(REMOTION_PACKAGES)}, indent=1)


def validate_assets(assets: Sequence[RemotionAsset]) -> None:
    """Reject unsafe names, duplicates, empty or oversized files before anything is uploaded."""
    if len(assets) > MAX_INPUTS:
        raise RemotionSandboxError("invalid_input", f"at most {MAX_INPUTS} input files can be used")
    seen: set[str] = set()
    for asset in assets:
        if not SAFE_INPUT_NAME.match(asset.name) or ".." in asset.name:
            raise RemotionSandboxError("invalid_input", f"the input file name {asset.name!r} is not allowed")
        if asset.name in seen:
            raise RemotionSandboxError("invalid_input", f"the input file name {asset.name!r} is used twice")
        seen.add(asset.name)
        if not asset.data or len(asset.data) > MAX_INPUT_BYTES:
            raise RemotionSandboxError("invalid_input", f"the input {asset.name!r} is empty or larger than "
                                                        f"{MAX_INPUT_BYTES // 1048576} MB")


def validate_audio_assets(assets: Sequence[RemotionAsset]) -> None:
    """Same checks as ``validate_assets`` with the audio caps (own limits, picture input cap untouched)."""
    if len(assets) > MAX_AUDIO_FILES:
        raise RemotionSandboxError("invalid_input", f"at most {MAX_AUDIO_FILES} audio files can be used")
    seen: set[str] = set()
    for asset in assets:
        if not SAFE_INPUT_NAME.match(asset.name) or ".." in asset.name:
            raise RemotionSandboxError("invalid_input", f"the audio file name {asset.name!r} is not allowed")
        if asset.name in seen:
            raise RemotionSandboxError("invalid_input", f"the audio file name {asset.name!r} is used twice")
        seen.add(asset.name)
        if not asset.data or len(asset.data) > MAX_AUDIO_BYTES:
            raise RemotionSandboxError("invalid_input", f"the audio {asset.name!r} is empty or larger than "
                                                        f"{MAX_AUDIO_BYTES // 1048576} MB")

class RemotionSession:
    """One sandbox for every round of one composed video.

    Use as ``async with RemotionSession(secrets_manager) as session``; call
    ``upload_inputs`` once, then per round ``check(source)`` and, when the
    declared timeline is accepted, ``render(thumbnail_frame)``. The sandbox is
    always killed on exit.
    """

    def __init__(self, secrets_manager: "SecretsManager | None" = None, *, api_key: str | None = None,
                 template: str | None = None, sandbox_factory: SandboxFactory | None = None,
                 check_limit_seconds: int = CHECK_LIMIT_SECONDS, render_limit_seconds: int = RENDER_LIMIT_SECONDS,
                 concurrency: int = RENDER_CONCURRENCY) -> None:
        self._secrets_manager = secrets_manager
        self._api_key = api_key
        self._template = template
        self._factory = sandbox_factory or _default_factory
        self._check_limit = check_limit_seconds
        self._render_limit = render_limit_seconds
        self._concurrency = concurrency
        self._sandbox: Any = None
        self._uploaded: Optional[str] = None
        self._checked = False

    @property
    def sandbox_id(self) -> str:
        return str(getattr(self._sandbox, "sandbox_id", "") or "")

    async def __aenter__(self) -> "RemotionSession":
        template = self._template or remotion_template_name()
        api_key = self._api_key or await get_e2b_api_key_async(self._secrets_manager)
        from e2b import AuthenticationException, NotFoundException, SandboxException

        try:
            self._sandbox = await asyncio.to_thread(
                self._factory, template=template, api_key=api_key, secure=True,
                allow_internet_access=False, network={"allow_public_traffic": False},
                timeout=SANDBOX_LIFETIME_SECONDS, metadata={"openmates_purpose": "videos_composed"},
            )
        except NotFoundException as exc:
            logger.error("Remotion sandbox template %r does not exist in the E2B account: %s", template, exc)
            raise RemotionSandboxError("template_missing", f"the video renderer template {template!r} "
                                                           "is not available") from exc
        except (SandboxException, AuthenticationException) as exc:
            logger.error("Remotion sandbox could not be created from template %r: %s", template, exc)
            raise RemotionSandboxError("sandbox_unavailable", "The video renderer could not be started.") from exc
        try:
            await asyncio.to_thread(self._sandbox.files.write_files, [
                {"path": f"{REMOTION_WORKDIR}/runner.mjs", "data": RUNNER_MJS.encode("utf-8")},
                {"path": f"{REMOTION_WORKDIR}/src/index.ts", "data": INDEX_TS.encode("utf-8")},
                {"path": f"{REMOTION_WORKDIR}/src/Root.tsx", "data": ROOT_TSX.encode("utf-8")},
            ])
        except SandboxException as exc:
            await self._kill()
            raise RemotionSandboxError("sandbox_failed", "The video renderer could not be prepared.") from exc
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
            logger.warning("Remotion sandbox kill failed; E2B lifetime limit of %ss applies",
                           SANDBOX_LIFETIME_SECONDS, exc_info=True)

    def _require(self) -> Any:
        if self._sandbox is None:
            raise RuntimeError("RemotionSession must be entered before use")
        return self._sandbox

    async def upload_inputs(self, assets: Sequence[RemotionAsset]) -> None:
        """Upload the request's files once; a second call must pass the same files."""
        sandbox = self._require()
        validate_assets(assets)
        digest = hashlib.sha256(b"".join(asset.name.encode() + hashlib.sha256(asset.data).digest()
                                         for asset in assets)).hexdigest()
        if self._uploaded == digest:
            return
        if self._uploaded is not None:
            raise RemotionSandboxError("invalid_input", "one session renders one fixed set of inputs")
        from e2b import SandboxException

        files = [{"path": f"{REMOTION_WORKDIR}/public/inputs/{asset.name}", "data": asset.data} for asset in assets]
        try:
            if files:
                await asyncio.to_thread(sandbox.files.write_files, files)
        except SandboxException as exc:
            raise RemotionSandboxError("sandbox_failed", "The inputs could not be uploaded to the renderer.") from exc
        self._uploaded = digest

    async def upload_audio(self, assets: Sequence[RemotionAsset], tracks: Sequence[dict[str, Any]]) -> None:
        """Upload generated audio to ``public/audio/`` and the track list the renderer mixes in.

        Call after a successful ``check`` and before ``render``; every ``check`` clears the audio again, so a
        corrected composition needs a new call. ``tracks`` entries (see ``composed/audio_clips.py``) name their
        file as ``audio/<asset name>``. No call means a silent video.
        """
        sandbox = self._require()
        if not self._checked:
            raise RuntimeError("check must succeed before upload_audio")
        validate_audio_assets(assets)
        from e2b import SandboxException

        # The bundle holds its own copy of public/, so the files go to both places for this render.
        files = [{"path": f"{REMOTION_WORKDIR}/{prefix}audio/{asset.name}", "data": asset.data}
                 for asset in assets for prefix in ("public/", "build/public/")]
        files.append({"path": f"{REMOTION_WORKDIR}/{AUDIO_TRACKS_FILE}",
                      "data": json.dumps(list(tracks)).encode("utf-8")})
        try:
            await asyncio.to_thread(sandbox.files.write_files, files)
        except SandboxException as exc:
            raise RemotionSandboxError("sandbox_failed", "The audio could not be uploaded to the renderer.") from exc

    async def _run(self, stage: str, command: str, limit: int) -> float:
        sandbox = self._require()
        from e2b import CommandExitException, SandboxException, TimeoutException

        started = time.monotonic()
        try:
            await asyncio.to_thread(sandbox.commands.run, command, timeout=limit + COMMAND_GRACE_SECONDS)
        except CommandExitException as exc:
            seconds = time.monotonic() - started
            if exc.exit_code in TIMEOUT_EXIT_CODES:
                raise RemotionCompositionError(stage, f"the {stage} step ran longer than {limit} seconds and was "
                                                      "stopped", seconds) from exc
            details = redact(exc.stderr or exc.stdout or "") or f"the {stage} step exited with code {exc.exit_code}"
            raise RemotionCompositionError(stage, details, seconds) from exc
        except TimeoutException as exc:
            raise RemotionCompositionError(stage, f"the {stage} step ran longer than {limit} seconds and was stopped",
                                           time.monotonic() - started) from exc
        except SandboxException as exc:
            raise RemotionSandboxError("sandbox_failed", "The video renderer failed unexpectedly.") from exc
        return time.monotonic() - started

    async def _read(self, path: str) -> Optional[bytes]:
        from e2b import SandboxException

        try:
            return bytes(await asyncio.to_thread(self._require().files.read, f"{REMOTION_WORKDIR}/{path}",
                                                 format="bytes"))
        except SandboxException:
            return None

    async def check(self, source: str) -> RemotionCheck:
        """Write the module, bundle it and read the declared ``video`` and ``parts``."""
        if self._uploaded is None:
            raise RuntimeError("upload_inputs must run before check")
        if not source.strip() or len(source) > MAX_SOURCE_CHARS:
            raise RemotionCompositionError("check", f"the composition is empty or longer than {MAX_SOURCE_CHARS} "
                                                    "characters", 0.0)
        from e2b import SandboxException

        self._checked = False
        try:
            await asyncio.to_thread(self._require().files.write_files, [
                {"path": f"{REMOTION_WORKDIR}/src/{SOURCE_FILENAME}", "data": source.encode("utf-8")},
            ])
        except SandboxException as exc:
            raise RemotionSandboxError("sandbox_failed", "The composition could not be uploaded.") from exc
        command = (f"cd {shlex.quote(REMOTION_WORKDIR)} && rm -rf out public/audio {AUDIO_TRACKS_FILE} && mkdir out && "
                   f"timeout -s KILL {self._check_limit}s node runner.mjs check")
        seconds = await self._run("check", command, self._check_limit)
        raw = await self._read("out/meta.json")
        if raw is None:
            raise RemotionCompositionError("check", "the composition did not report its video and parts", seconds)
        try:
            meta = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemotionSandboxError("sandbox_failed", "The renderer returned unreadable metadata.") from exc
        if not isinstance(meta, dict) or not isinstance(meta.get("video"), dict):
            raise RemotionSandboxError("sandbox_failed", "The renderer returned inconsistent metadata.")
        self._checked = True
        return RemotionCheck(video=meta["video"], parts=meta.get("parts"), seconds=seconds, audio=meta.get("audio"))

    async def render(self, thumbnail_frame: int) -> RemotionRender:
        """Render the checked composition to MP4 plus a PNG thumbnail of ``thumbnail_frame``."""
        if not self._checked:
            raise RuntimeError("check must succeed before render")
        command = (f"cd {shlex.quote(REMOTION_WORKDIR)} && timeout -s KILL {self._render_limit}s "
                   f"node runner.mjs render {int(thumbnail_frame)} {int(self._concurrency)}")
        seconds = await self._run("render", command, self._render_limit)
        mp4 = await self._read("out/video.mp4")
        thumbnail = await self._read("out/thumbnail.png")
        if not mp4 or not thumbnail:
            raise RemotionCompositionError("render", "the render wrote no video or no thumbnail", seconds)
        if len(mp4) > MAX_OUTPUT_BYTES:
            raise RemotionSandboxError("sandbox_failed", "The renderer returned an oversized video.")
        return RemotionRender(mp4=mp4, thumbnail_png=thumbnail, seconds=seconds)


def kill_remotion_sandbox_in_e2b(*, sandbox_id: str, api_key: str) -> bool:
    """Kill a Remotion sandbox by id (when a render must be cancelled from outside its session)."""
    try:
        from e2b import Sandbox
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise RuntimeError("E2B SDK is not installed in the API worker image") from exc
    if not sandbox_id.strip():
        raise RuntimeError("E2B sandbox id is required")
    if not api_key.strip():
        raise RuntimeError("E2B API key is not configured")
    return bool(Sandbox.kill(sandbox_id=sandbox_id, api_key=api_key))
