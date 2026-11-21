# backend/apps/audio/assistant_speech/acknowledgements.py
#
# Approved product text for prerecorded assistant-response acknowledgements.
# Text is grouped by locale and preprocessing category so generation tooling
# can create the same three deterministic variants for every mate voice.
# Runtime playback uses generated static assets, never these strings as TTS input.

from __future__ import annotations

import re


ACKNOWLEDGEMENT_ASSET_ROOT = "/audio/assistant-acknowledgements"

# A call turn that starts a new chat has no Mate yet: routing picks one later.
# It is confirmed in a neutral system voice (a short chime is part of the
# recorded clip), never in a Mate voice that may not be the one that answers.
SYSTEM_VOICE_PROFILE_ID = "system"
CHAT_START_CATEGORY = "chat_start"
CHAT_START_TEXTS: dict[str, str] = {
    "en-US": "Starting your chat…",
    "de-DE": "Dein Chat startet…",
    "es-ES": "Iniciando tu chat…",
    "fr-FR": "Ton chat démarre…",
}
ACKNOWLEDGEMENT_TEXTS: dict[str, dict[str, tuple[str, ...]]] = {
    "en-US": {
        "general": (
            "Sure, let's take a look.",
            "Alright, let's work on it.",
            "Okay, I'll help you with that.",
        ),
        "lookup": (
            "Sure, I'll look that up.",
            "Okay, let me check.",
            "Got it, I'll find the details.",
        ),
        "reasoning": (
            "Okay, let me think for a moment.",
            "Sure, I'll work through it step by step.",
            "Got it, I'll take a closer look.",
        ),
        "action": (
            "Okay, I'm on it.",
            "Sure, I'll take care of that.",
            "Got it, I'll get started.",
        ),
    },
    "de-DE": {
        "general": (
            "Klar, schauen wir es uns an.",
            "Alles klar, gehen wir es an.",
            "Okay, ich helfe dir dabei.",
        ),
        "lookup": (
            "Klar, ich schaue das nach.",
            "Okay, ich sehe kurz nach.",
            "Alles klar, ich suche die Details heraus.",
        ),
        "reasoning": (
            "Okay, lass mich kurz nachdenken.",
            "Klar, ich gehe das Schritt für Schritt durch.",
            "Alles klar, ich sehe mir das genauer an.",
        ),
        "action": (
            "Okay, mache ich.",
            "Klar, ich kümmere mich darum.",
            "Alles klar, ich lege los.",
        ),
    },
    "es-ES": {
        "general": (
            "Claro, vamos a verlo.",
            "De acuerdo, pongámonos con ello.",
            "Vale, te ayudo con eso.",
        ),
        "lookup": (
            "Claro, lo busco.",
            "Vale, déjame comprobarlo.",
            "Entendido, buscaré los detalles.",
        ),
        "reasoning": (
            "Vale, déjame pensarlo un momento.",
            "Claro, lo analizaré paso a paso.",
            "Entendido, voy a examinarlo más de cerca.",
        ),
        "action": (
            "Vale, me encargo.",
            "Claro, me ocuparé de eso.",
            "Entendido, empiezo ahora.",
        ),
    },
    "fr-FR": {
        "general": (
            "Bien sûr, regardons ça.",
            "D'accord, allons-y.",
            "Très bien, je vais t'aider.",
        ),
        "lookup": (
            "Bien sûr, je vais vérifier.",
            "D'accord, je regarde.",
            "Très bien, je vais trouver les détails.",
        ),
        "reasoning": (
            "D'accord, laisse-moi réfléchir un instant.",
            "Bien sûr, je vais procéder étape par étape.",
            "Très bien, je vais regarder ça de plus près.",
        ),
        "action": (
            "D'accord, je m'en occupe.",
            "Bien sûr, je vais m'en charger.",
            "Très bien, je commence.",
        ),
    },
}


# Spoken lines of a call request that waits for the user's tap (Memory access
# and other approvals). Recorded once per Mate voice, so they are played with
# no inference and no credits. The client plays the local "needs you" chime
# before the request line, then the reminder at about 15 seconds, the thanks
# after the tap, and for a Memory request the timeout line when it cancels
# itself after about 30 seconds.
PERMISSION_PROMPT_TEXTS: dict[str, dict[str, str]] = {
    "en-US": {
        "needs_memory": "I'd like to use your memories for this. Please tap Allow on your screen.",
        "needs_approval": "I need your OK for this. Please check your screen.",
        "needs_reminder": "I'm still waiting for your OK on the screen.",
        "approval_thanks": "Thanks, I'll continue.",
        "memory_timeout": "No problem, I'll answer without your memories.",
    },
    "de-DE": {
        "needs_memory": "Ich würde dafür gern deine Erinnerungen nutzen. Tippe bitte auf deinem Bildschirm auf Erlauben.",
        "needs_approval": "Dafür brauche ich dein OK. Schau bitte kurz auf deinen Bildschirm.",
        "needs_reminder": "Ich warte noch auf dein OK auf dem Bildschirm.",
        "approval_thanks": "Danke, ich mache weiter.",
        "memory_timeout": "Kein Problem, ich antworte ohne deine Erinnerungen.",
    },
    "es-ES": {
        "needs_memory": "Me gustaría usar tus recuerdos para esto. Toca Permitir en tu pantalla, por favor.",
        "needs_approval": "Necesito tu permiso para esto. Mira tu pantalla, por favor.",
        "needs_reminder": "Sigo esperando tu permiso en la pantalla.",
        "approval_thanks": "Gracias, sigo.",
        "memory_timeout": "No pasa nada, responderé sin tus recuerdos.",
    },
    "fr-FR": {
        "needs_memory": "J'aimerais utiliser tes souvenirs pour ça. Touche Autoriser sur ton écran, s'il te plaît.",
        "needs_approval": "J'ai besoin de ton accord pour ça. Regarde ton écran, s'il te plaît.",
        "needs_reminder": "J'attends toujours ton accord sur l'écran.",
        "approval_thanks": "Merci, je continue.",
        "memory_timeout": "Pas de souci, je réponds sans tes souvenirs.",
    },
}
PERMISSION_PROMPT_VARIANT = 1


def build_acknowledgement_clips(
    *,
    voice_profile_id: str,
    voice_profile_version: int,
    language: str,
) -> list[dict[str, object]]:
    """Build public static clip metadata for one approved mate and locale."""
    locale = _resolve_locale(language)
    if locale is None:
        return []

    clips: list[dict[str, object]] = []
    for category, variants in ACKNOWLEDGEMENT_TEXTS[locale].items():
        for variant, _text in enumerate(variants, start=1):
            clip_id = f"{voice_profile_id}-{locale}-{category}-{variant}"
            clips.append(
                {
                    "clip_id": clip_id,
                    "voice_profile_id": voice_profile_id,
                    "voice_profile_version": voice_profile_version,
                    "language": locale,
                    "request_category": category,
                    "variant": variant,
                    "asset_url": (
                        f"{ACKNOWLEDGEMENT_ASSET_ROOT}/{voice_profile_id}/{locale}/{category}-{variant}.mp3"
                    ),
                }
            )
    return clips


def build_chat_start_clip(*, language: str) -> dict[str, object] | None:
    """Public static metadata of the neutral system "starting your chat" clip."""
    locale = _resolve_locale(language, CHAT_START_TEXTS)
    if locale is None:
        return None
    return {
        "clip_id": f"{SYSTEM_VOICE_PROFILE_ID}-{locale}-{CHAT_START_CATEGORY}-1",
        "voice_profile_id": SYSTEM_VOICE_PROFILE_ID,
        "language": locale,
        "request_category": CHAT_START_CATEGORY,
        "variant": 1,
        "asset_url": f"{ACKNOWLEDGEMENT_ASSET_ROOT}/{SYSTEM_VOICE_PROFILE_ID}/{locale}/{CHAT_START_CATEGORY}-1.mp3",
    }


def build_permission_prompt_clips(*, voice_profile_id: str, language: str) -> dict[str, str] | None:
    """Static asset URLs of the waiting-for-your-tap lines in one Mate voice, or None.

    None (unsupported language) keeps the call silent instead of guessing English.
    """
    locale = _resolve_locale(language, PERMISSION_PROMPT_TEXTS)
    if locale is None:
        return None
    return {
        kind: f"{ACKNOWLEDGEMENT_ASSET_ROOT}/{voice_profile_id}/{locale}/{kind}-{PERMISSION_PROMPT_VARIANT}.mp3"
        for kind in PERMISSION_PROMPT_TEXTS[locale]
    }


def _resolve_locale(language: str, catalog: dict[str, object] = ACKNOWLEDGEMENT_TEXTS) -> str | None:
    if language in catalog:
        return language
    base_language = language.split("-", maxsplit=1)[0].lower()
    return next(
        (
            locale
            for locale in catalog
            if locale.split("-", maxsplit=1)[0].lower() == base_language
        ),
        None,
    )


# Ready-made voice-call waiting lines: played and shown with no inference and no
# credits. Category == the `line` id the voice-call server sends.
WAITING_LINE_TEXTS: dict[str, dict[str, str]] = {
    "en-US": {"waiting_start": "Okay, I'm waiting.", "waiting_resume": "Okay, go on."},
    "de-DE": {"waiting_start": "Okay, ich warte.", "waiting_resume": "Okay, sprich weiter."},
    "es-ES": {"waiting_start": "Vale, espero.", "waiting_resume": "Vale, continúa."},
    "fr-FR": {"waiting_start": "D'accord, j'attends.", "waiting_resume": "D'accord, je t'écoute."},
}


def build_waiting_line_clip(*, line: str, language: str) -> dict[str, object] | None:
    """Public static metadata of one neutral system waiting line, or None."""
    locale = _resolve_locale(language, WAITING_LINE_TEXTS)
    if locale is None or line not in WAITING_LINE_TEXTS[locale]:
        return None
    return {
        "clip_id": f"{SYSTEM_VOICE_PROFILE_ID}-{locale}-{line}-1",
        "voice_profile_id": SYSTEM_VOICE_PROFILE_ID,
        "language": locale,
        "request_category": line,
        "variant": 1,
        "text": WAITING_LINE_TEXTS[locale][line],
        "asset_url": f"{ACKNOWLEDGEMENT_ASSET_ROOT}/{SYSTEM_VOICE_PROFILE_ID}/{locale}/{line}-1.mp3",
    }


_CLIP_ASSET = re.compile(
    rf"^{re.escape(ACKNOWLEDGEMENT_ASSET_ROOT)}/[A-Za-z0-9_-]{{1,64}}/"
    r"(?P<locale>[a-z]{2}-[A-Z]{2})/(?P<category>[a-z_]{1,32})-(?P<variant>[1-9][0-9]?)\.mp3$"
)


def prerecorded_clip_text(asset_url: str) -> str:
    """Approved words of a static clip, from its public asset path, or "".

    A live call reports the clip it is playing; the server compares the
    caller's transcript with these words to recognise microphone echo (EYHC5).
    """
    match = _CLIP_ASSET.fullmatch(asset_url)
    if match is None:
        return ""
    locale, category, variant = match["locale"], match["category"], int(match["variant"])
    if category == CHAT_START_CATEGORY:
        return CHAT_START_TEXTS.get(locale, "")
    for catalog in (WAITING_LINE_TEXTS, PERMISSION_PROMPT_TEXTS):
        if category in catalog.get(locale, {}):
            return catalog[locale][category]
    variants = ACKNOWLEDGEMENT_TEXTS.get(locale, {}).get(category, ())
    return variants[variant - 1] if variant <= len(variants) else ""
