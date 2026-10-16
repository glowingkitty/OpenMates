"""Confirmation mail handoff without a provider, subscriber, or real token.

Load the production async task without bootstrapping Celery or other mail tasks.
The mocked transport verifies the exact template/context handoff and cleanup.
"""

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "core/api/app/tasks/email_tasks/newsletter_email_task.py"


def load_delivery(secrets_manager, template_service):
    tree = ast.parse(SOURCE.read_text())
    task = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "_async_send_newsletter_confirmation_email")
    namespace = {
        "SecretsManager": lambda: secrets_manager,
        "EmailTemplateService": template_service,
        "_resolve_webapp_base_url": lambda: "https://app.example",
        "_resolve_newsletter_confirmation_url": lambda token, _: f"https://website.example/newsletter/confirm/{token}",
        "quote": quote,
        "logger": logging.getLogger(__name__),
        "event_logger": logging.getLogger(__name__),
    }
    exec(compile(ast.Module(body=[task], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[task.name]


# contract-test: supporting surface=rest_api assertions=newsletter.lifecycle.double-opt-in,newsletter.surface.standalone-confirmation
@pytest.mark.asyncio
@pytest.mark.parametrize("provider_result", [True, False])
async def test_confirmation_task_hands_off_email_and_closes_client(provider_result):
    secrets_manager = SimpleNamespace(initialize=AsyncMock(), aclose=AsyncMock())
    transport = SimpleNamespace(send_email=AsyncMock(return_value=provider_result))
    service_factory = Mock(return_value=transport)
    deliver = load_delivery(secrets_manager, service_factory)

    assert await deliver("recipient@example.com", "fake-recipient-token", "de", True) is provider_result
    secrets_manager.initialize.assert_awaited_once()
    service_factory.assert_called_once_with(secrets_manager=secrets_manager)
    transport.send_email.assert_awaited_once_with(
        template="newsletter-confirmation-request",
        recipient_email="recipient@example.com",
        context={
            "confirm_url": "https://website.example/newsletter/confirm/fake-recipient-token",
            "unsubscribe_url": "https://app.example/#settings/email/block/recipient%40example.com",
            "darkmode": True,
        },
        lang="de",
    )
    secrets_manager.aclose.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=newsletter.lifecycle.double-opt-in
@pytest.mark.asyncio
async def test_confirmation_task_closes_client_on_initialization_failure():
    secrets_manager = SimpleNamespace(initialize=AsyncMock(side_effect=RuntimeError("fake initialization failure")), aclose=AsyncMock())
    service_factory = Mock()
    deliver = load_delivery(secrets_manager, service_factory)

    assert await deliver("recipient@example.com", "fake-recipient-token") is False
    service_factory.assert_not_called()
    secrets_manager.aclose.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=newsletter.lifecycle.double-opt-in
@pytest.mark.asyncio
async def test_confirmation_task_closes_client_on_transport_failure():
    secrets_manager = SimpleNamespace(initialize=AsyncMock(), aclose=AsyncMock())
    transport = SimpleNamespace(send_email=AsyncMock(side_effect=RuntimeError("fake provider failure")))
    deliver = load_delivery(secrets_manager, Mock(return_value=transport))

    assert await deliver("recipient@example.com", "fake-recipient-token") is False
    transport.send_email.assert_awaited_once()
    secrets_manager.aclose.assert_awaited_once()
