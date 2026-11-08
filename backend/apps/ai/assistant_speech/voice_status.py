"""Short spoken status lines for live voice calls.

Three lines keep a caller oriented while the assistant works:

* an instant acknowledgement chosen from pre-recorded clips (no generation wait),
* a fixed announcement when app skills start, and
* a recap built from the skills that actually ran.

Unsupported languages stay silent instead of silently falling back to English.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping

from backend.apps.ai.assistant_speech.projection import select_prerecorded_acknowledgement
from backend.apps.audio.assistant_speech.acknowledgements import build_acknowledgement_clips

# Pre-recorded categories that suit a turn whose needs are not yet known.
_INSTANT_CATEGORIES = ("general", "reasoning")

APP_USE_ANNOUNCEMENTS: dict[str, tuple[str, ...]] = {
    "en": ("I'm going to use some apps for this request.", "I'll use a few apps to answer that."),
    "de": ("Ich nutze für diese Anfrage ein paar Apps.", "Ich verwende dafür kurz ein paar Apps."),
    "es": ("Voy a usar algunas apps para esta petición.", "Usaré unas cuantas apps para responder."),
    "fr": ("Je vais utiliser quelques apps pour cette demande.", "J'utilise quelques apps pour répondre."),
}

# Spoken names for common skills; an unknown skill is summarised generically.
_SKILL_LABELS: dict[str, dict[str, str]] = {
    "en": {"web.search": "web search", "news.search": "news search", "videos.search": "video search",
           "maps.search": "maps search", "images.search": "image search", "web.read": "web reading",
           "travel.search_connections": "travel search", "events.search": "event search"},
    "de": {"web.search": "die Websuche", "news.search": "die Nachrichtensuche", "videos.search": "die Videosuche",
           "maps.search": "die Kartensuche", "images.search": "die Bildersuche", "web.read": "das Lesen von Webseiten",
           "travel.search_connections": "die Reisesuche", "events.search": "die Veranstaltungssuche"},
    "es": {"web.search": "la búsqueda web", "news.search": "la búsqueda de noticias",
           "videos.search": "la búsqueda de vídeos", "maps.search": "la búsqueda de mapas",
           "images.search": "la búsqueda de imágenes", "web.read": "la lectura web",
           "events.search": "la búsqueda de eventos"},
    "fr": {"web.search": "la recherche web", "news.search": "la recherche d'actualités",
           "videos.search": "la recherche de vidéos", "maps.search": "la recherche de cartes",
           "images.search": "la recherche d'images", "web.read": "la lecture web",
           "events.search": "la recherche d'événements"},
}

_RECAP_ONE = {
    "en": "I used {names}.", "de": "Ich habe {names} verwendet.",
    "es": "He usado {names}.", "fr": "J'ai utilisé {names}.",
}
_RECAP_GENERIC = {
    "en": "I used a few apps.", "de": "Ich habe ein paar Apps verwendet.",
    "es": "He usado algunas apps.", "fr": "J'ai utilisé quelques apps.",
}
_AND = {"en": "and", "de": "und", "es": "y", "fr": "et"}


def _base_language(language: str | None) -> str:
    return (language or "").lower().replace("_", "-").split("-")[0]


def _pick(options: tuple[str, ...], seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


# Function words that separate the supported call languages. The detector only
# needs to beat the user's interface language when the spoken turn is clearly
# in another one; ambiguous or short text keeps the preference.
_STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset("the and is are what how why can you please with for this that of to in it my me do does".split()),
    "de": frozenset("der die das und ist nicht bitte wie was warum kannst du mit für ich mir mein eine ein zu den dem auch".split()),
    "es": frozenset("el la los las y es qué cómo por favor puedes con para yo mi una un de en que del también".split()),
    "fr": frozenset("le la les et est quoi comment pourquoi peux tu avec pour je mon une un de du des que aussi s'il".split()),
}


# Characters that appear (almost) only in one supported language.
_CHARACTER_CUES: dict[str, str] = {"de": "äöüß", "es": "ñ¿¡áíóú", "fr": "çœàâêèéëîïôùûÿ"}


def detect_turn_language(text: str, fallback: str | None) -> str | None:
    """Return the clearly dominant supported language of ``text``, else ``fallback``.

    One function word is enough when no other language matches, so short
    phrases ("Wie spät ist es") are recognised; a tie keeps the fallback.
    """
    lowered = (text or "").lower()
    words = [word.strip(".,!?;:\"()¿¡") for word in lowered.split()]
    scores = {
        code: sum(word in vocabulary for word in words) * 2
        + sum(lowered.count(char) for char in _CHARACTER_CUES.get(code, ""))
        for code, vocabulary in _STOPWORDS.items()
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    (best, best_score), (_, runner_up) = ranked[0], ranked[1]
    return best if best_score >= 2 and best_score > runner_up else fallback


def select_instant_acknowledgement(
    *, voice_profile_id: str, voice_profile_version: int, language: str, seed: str,
) -> dict[str, object] | None:
    """Pick one pre-recorded clip without generation; the seed varies it per turn."""
    category = _pick(_INSTANT_CATEGORIES, f"{seed}:category")
    clips = build_acknowledgement_clips(
        voice_profile_id=voice_profile_id, voice_profile_version=voice_profile_version, language=language,
    )
    choice = select_prerecorded_acknowledgement(
        clips=clips, voice_profile_id=voice_profile_id, voice_profile_version=voice_profile_version,
        language=language, request_category=category, selection_seed=seed,
    )
    return choice if choice and choice.get("asset_url") else None


def build_voice_app_use_announcement(language: str | None, seed: str) -> str | None:
    options = APP_USE_ANNOUNCEMENTS.get(_base_language(language))
    return _pick(options, seed) if options else None


def skill_key(app_id: str, skill_id: str) -> str:
    return f"{app_id}.{skill_id}"


def build_skill_recap(skills: Iterable[tuple[str, str]], language: str | None) -> str | None:
    """Name the skills that ran, once each in first-use order; generic if any is unnamed."""
    base = _base_language(language)
    template = _RECAP_ONE.get(base)
    if template is None:
        return None
    ordered = list(dict.fromkeys(skill_key(app_id, skill_id) for app_id, skill_id in skills))
    if not ordered:
        return None
    labels = _SKILL_LABELS.get(base, {})
    names = [labels.get(key) for key in ordered]
    if any(name is None for name in names):
        return _RECAP_GENERIC[base]
    joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} {_AND[base]} {names[-1]}"
    return template.format(names=joined)


def voice_status_segment(metadata: Mapping[str, object], text: str, index: int) -> dict[str, object]:
    """A hidden-from-transcript utterance for the continuous speech track."""
    identity = f"{metadata['chat_id']}:{metadata['assistant_message_id']}:{metadata.get('voice_call_id') or 'voice'}:status:{index}"
    return {**metadata, "segment_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            "sequence": -2 - index, "kind": "voice_status", "speakable_text": text.strip()}
