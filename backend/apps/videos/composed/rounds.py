"""One sandbox per composed video and the check-then-render round on it.

``SandboxRunner`` starts the Remotion sandbox in the background (while the
author is still writing), uploads the request's files once, and per round
checks the static contract, bundles the module in the sandbox, validates the
exported timeline and renders the MP4 and thumbnail. A failure caused by the
composition raises ``RoundFailed`` with the stage and the error text for the
author; a failure of the sandbox itself raises ``ComposeFailure``
("sandbox_unavailable"). ``close`` always kills the sandbox.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from backend.apps.videos.composed.contract import (
    InvalidCompositionError,
    build_timeline,
    thumbnail_frame,
    validate_source,
)
from backend.apps.videos.composed.models import ComposedInput, ComposeFailure
from backend.shared.providers.e2b_remotion_renderer import (
    RemotionAsset,
    RemotionCompositionError,
    RemotionRender,
    RemotionSandboxError,
    RemotionSession,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Any]


class RoundFailed(Exception):
    """The composition failed at ``stage`` ("static" | "check" | "timeline" | "render")."""

    def __init__(self, stage: str, error: str) -> None:
        super().__init__(f"{stage}: {error[:300]}")
        self.stage = stage
        self.error = error


@dataclass(frozen=True)
class RoundResult:
    timeline: dict[str, Any]
    render: RemotionRender


def default_session_factory(secrets_manager: Any) -> SessionFactory:
    return lambda: RemotionSession(secrets_manager)


class SandboxRunner:
    """Starts one sandbox in the background; every round waits for it; ``close`` always kills it."""

    def __init__(self, session_factory: SessionFactory, inputs: Sequence[ComposedInput]) -> None:
        self._session = session_factory()
        self._assets = [RemotionAsset(name=item.name, data=item.content) for item in inputs]
        self._names = frozenset(item.name for item in inputs)
        self._entered = False
        self.sandbox_seconds: list[float] = []
        self._started = asyncio.create_task(self._start())

    async def _start(self) -> None:
        await self._session.__aenter__()
        self._entered = True
        await self._session.upload_inputs(self._assets)

    async def _ready(self) -> None:
        try:
            await self._started
        except RemotionSandboxError as exc:
            raise ComposeFailure("sandbox_unavailable", exc.user_message) from exc

    async def run(self, source: str, *, aspect_ratio: Optional[str], duration_seconds: Optional[int]) -> RoundResult:
        """Check and render one composition; raise ``RoundFailed`` when the composition is at fault."""
        try:
            declared = validate_source(source, input_names=self._names, aspect_ratio=aspect_ratio,
                                       duration_seconds=duration_seconds)
        except InvalidCompositionError as exc:
            raise RoundFailed("static", str(exc)) from exc
        await self._ready()
        seconds = 0.0
        try:
            try:
                checked = await self._session.check(source)
                seconds += checked.seconds
            except RemotionCompositionError as exc:
                seconds += exc.seconds
                raise RoundFailed("check", exc.details) from exc
            try:
                timeline = build_timeline(checked.video, checked.parts, declared=declared)
            except InvalidCompositionError as exc:
                raise RoundFailed("timeline", str(exc)) from exc
            try:
                rendered = await self._session.render(thumbnail_frame(timeline))
                seconds += rendered.seconds
            except RemotionCompositionError as exc:
                seconds += exc.seconds
                raise RoundFailed("render", exc.details) from exc
        except RemotionSandboxError as exc:
            raise ComposeFailure("sandbox_unavailable", exc.user_message) from exc
        finally:
            if seconds > 0:
                self.sandbox_seconds.append(seconds)
        return RoundResult(timeline=timeline, render=rendered)

    async def close(self) -> None:
        # The start runs in a worker thread and cannot be cancelled; wait for it so the sandbox is killed.
        await asyncio.wait([self._started])
        if not self._started.cancelled() and self._started.exception() is not None:
            logger.info("Composed-video sandbox start had failed: %s", self._started.exception())
        if self._entered:
            await self._session.__aexit__(None, None, None)
