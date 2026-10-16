"""Canonical mate voice delivery; clients supply category identities only."""
from typing import Any

# Fixed mappings for the existing version-1 mate voice identities. Gemini's
# voice presentation is documented at https://firebase.google.com/docs/ai-logic/live-api/configuration
GEMINI_MATE_VOICES = {
    "ace": "Puck", "burton": "Orus", "colin": "Umbriel", "denise": "Aoede",
    "elton": "Alnilam", "finn": "Schedar", "george": "Sadaltager", "hiro": "Iapetus",
    "leon": "Charon", "lisa": "Sulafat", "makani": "Fenrir", "mark": "Achird",
    "melvin": "Charon", "monika": "Callirrhoe", "scarlett": "Kore", "sophia": "Erinome",
}


def mate_voice_configuration(mate: Any, *, learning_mode: bool = False) -> dict[str, str]:
    profile = mate.voice_profile
    voice = GEMINI_MATE_VOICES.get(profile.key) if profile.version == 1 else None
    if not voice:
        raise ValueError("Mate live voice profile unavailable")
    # Preserve the canonical prompt verbatim. The provider's shared voice
    # overlay handles conversational delivery instead of changing its meaning.
    prompt = mate.learning_mode_system_prompt if learning_mode else mate.default_system_prompt
    if not prompt or not prompt.strip():
        raise ValueError("Mate voice instructions unavailable")
    return {"mate_instruction": f"Your mate identity is {mate.name}.\n\n{prompt}",
            "voice_name": voice, "mate_category": mate.category, "mate_name": mate.name}
