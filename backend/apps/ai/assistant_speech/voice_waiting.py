"""One delayed, localized voice prelude through the normal encrypted speech path."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

# No English fallback: an unsupported language stays quiet. These are delivery
# phrases, never a second model answer or a claim that a tool has completed.
WAITING_PHRASES = {
    "en": "Let me think about that.", "de": "Lass mich kurz darüber nachdenken.",
    "es": "Déjame pensar un momento.", "fr": "Laisse-moi y réfléchir un instant.",
    "it": "Fammi pensare un momento.", "pt": "Deixa-me pensar um momento.",
    "nl": "Laat me daar even over nadenken.", "pl": "Daj mi chwilę na zastanowienie.",
    "ru": "Дай мне немного подумать.", "uk": "Дай мені трохи подумати.",
    "zh": "让我想一想。", "ja": "少し考えさせてください。",
    "ko": "잠시 생각해 볼게요.", "ar": "دعني أفكر في ذلك قليلاً.",
    "hi": "मुझे इस बारे में थोड़ा सोचने दें।", "tr": "Biraz düşüneyim.",
    "sv": "Låt mig tänka på det en stund.", "da": "Lad mig tænke lidt over det.",
    "fi": "Anna minun miettiä hetki.", "no": "La meg tenke litt på det.",
    "cs": "Nech mě se na chvíli zamyslet.", "el": "Άσε με να το σκεφτώ λίγο.",
    "he": "תן לי לחשוב על זה רגע.", "id": "Biar saya pikirkan sebentar.",
    "vi": "Để tôi suy nghĩ một chút.", "th": "ขอคิดสักครู่นะ",
}


class DelayedVoiceWaiting:
    def __init__(self, *, language: str, response_ready: Callable[[], bool],
                 dispatch: Callable[[str], None], delay_seconds: float = 1.5) -> None:
        self._phrase = WAITING_PHRASES.get(language.lower().replace("_", "-").split("-")[0])
        self._response_ready = response_ready
        self._dispatch = dispatch
        self._delay = delay_seconds
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._phrase and self._task is None:
            self._task = asyncio.create_task(self._wait())

    async def _wait(self) -> None:
        await asyncio.sleep(self._delay)
        if not self._response_ready():
            self._dispatch(self._phrase)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
