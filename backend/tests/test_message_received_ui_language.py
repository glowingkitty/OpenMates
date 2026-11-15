"""Chat metadata language follows the interface the client displays (issue PT38B).

The account language is not rewritten in Automatic mode or by ?lang=, so a profile
can say "de" while the user reads an English interface. The client sends the
displayed language as `ui_language`; only a well-formed code may override.
"""
from tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()


# contract-test: supporting surface=rest_api assertions=language-preferences.chat-metadata-language
def test_displayed_ui_language_accepts_base_and_regional_codes():
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        displayed_ui_language,
    )

    assert displayed_ui_language("en") == "en"
    assert displayed_ui_language("de") == "de"
    assert displayed_ui_language("pt-BR") == "pt"
    assert displayed_ui_language(" zh-Hans ") == "zh"


# contract-test: supporting surface=rest_api assertions=language-preferences.chat-metadata-language
def test_displayed_ui_language_rejects_missing_or_malformed_values():
    from backend.core.api.app.routes.handlers.websocket_handlers.message_received_handler import (
        displayed_ui_language,
    )

    for value in (None, "", 7, "EN", "english", "en_US", "de; drop", "x" * 40):
        assert displayed_ui_language(value) is None

