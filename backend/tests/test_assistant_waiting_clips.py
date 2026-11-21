"""Every locale with a chat-start system clip text also has both waiting-line texts."""

from backend.apps.audio.assistant_speech.acknowledgements import CHAT_START_TEXTS, WAITING_LINE_TEXTS


# contract-test: supporting surface=rest_api assertions=assistant-speech.acknowledgement.deterministic-free
def test_waiting_texts_cover_every_chat_start_locale() -> None:
    for locale in CHAT_START_TEXTS:
        assert set(WAITING_LINE_TEXTS.get(locale, {})) == {"waiting_start", "waiting_resume"}, locale
