"""Newsletter confirmation destination compatibility tests.

The worker module cannot be imported without Celery in this local runner, so
these tests load its small production URL resolver directly from source.
No email is sent and no subscriber or token state is created.
The website destination remains server-configured and exact-origin validated.
"""

import ast
import os
from pathlib import Path
from urllib.parse import quote

import pytest

from backend.core.api.app.utils.newsletter_public_origin import get_newsletter_website_origin


SOURCE = Path(__file__).resolve().parents[1] / "core/api/app/tasks/email_tasks/newsletter_email_task.py"


def confirmation_url(token: str, app_base_url: str) -> str:
    tree = ast.parse(SOURCE.read_text())
    resolver = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_newsletter_confirmation_url"
    )
    namespace = {"os": os, "quote": quote, "get_newsletter_website_origin": get_newsletter_website_origin}
    exec(compile(ast.Module(body=[resolver], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[resolver.name](token, app_base_url)


# contract-test: direct surface=rest_api assertions=newsletter.surface.standalone-confirmation
def test_unconfigured_website_keeps_existing_app_confirmation_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWSLETTER_PUBLIC_WEBSITE_ORIGIN", raising=False)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")

    assert confirmation_url("recipient-token", "https://app.dev.openmates.org") == (
        "https://app.dev.openmates.org/#settings/newsletter/confirm/recipient-token"
    )


# contract-test: direct surface=rest_api assertions=newsletter.surface.standalone-confirmation,newsletter.privacy.identity-and-token-boundary
def test_configured_website_uses_validated_public_confirmation_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWSLETTER_PUBLIC_WEBSITE_ORIGIN", "https://landing.dev.openmates.org")

    assert confirmation_url("recipient-token", "https://app.dev.openmates.org") == (
        "https://landing.dev.openmates.org/newsletter/confirm/recipient-token"
    )
    monkeypatch.setenv("NEWSLETTER_PUBLIC_WEBSITE_ORIGIN", "https://other.example/path")
    with pytest.raises(ValueError):
        confirmation_url("recipient-token", "https://app.dev.openmates.org")
