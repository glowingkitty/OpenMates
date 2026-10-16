"""No live provider connection may escape isolated CI or test recipient policy."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from backend.core.api.app.services.email.brevo_provider import BrevoProvider
from backend.shared.python_utils.live_email_policy import (
    email_type_for_template,
    live_email_policy,
)


@pytest.mark.parametrize(
    "flag", ["CI_MAIL_CAPTURE", "OPENMATES_CI_MAIL_CAPTURE", "OPENMATES_CI_ISOLATED"]
)
# contract-test: supporting surface=rest_api assertions=auth.signup.current-flow,notifications.delivery.email-enabled
def test_isolated_mail_always_rejects_live_provider(flag):
    decision = live_email_policy(
        "admin@example.org", admin_report=True, environ={flag: "1"}
    )
    assert not decision.allowed
    assert decision.reason == "isolated_mail_capture"


@pytest.mark.parametrize(
    "recipient",
    ["old@ae20drx9.mailosaur.net", "old@other.mailosaur.net", "old@mailosaur.net"],
)
# contract-test: supporting surface=rest_api assertions=auth.signup.current-flow,notifications.delivery.email-enabled
def test_retired_inboxes_cannot_be_allowlisted(recipient):
    decision = live_email_policy(
        recipient,
        environ={
            "SERVER_ENVIRONMENT": "production",
            "OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST": recipient,
        },
    )
    assert not decision.allowed
    assert decision.reason == "retired_test_inbox"


# contract-test: supporting surface=rest_api assertions=auth.signup.current-flow,notifications.delivery.email-enabled
def test_exact_dedicated_alias_allowlist_cannot_expand_to_other_gmail_aliases():
    env = {
        "SERVER_ENVIRONMENT": "development",
        "SIGNUP_TEST_EMAIL_DOMAINS": "gmail.com",
        "OPENMATES_TEST_ACCOUNT_1_EMAIL": "dedicated+e2e@gmail.com",
    }
    assert not live_email_policy("dedicated+e2e@gmail.com", environ=env).allowed
    env["OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST"] = "dedicated+e2e@gmail.com"
    allowed = live_email_policy(
        "DEDICATED+E2E@gmail.com", email_type="confirm-email", environ=env
    )
    assert allowed.allowed and "audience:test" in allowed.tags
    assert not live_email_policy("dedicated+e2e-other@gmail.com", environ=env).allowed
    assert live_email_policy("ordinary@gmail.com", environ=env).allowed
    assert live_email_policy("admin@gmail.com", admin_report=True, environ=env).allowed


# contract-test: supporting surface=rest_api assertions=auth.signup.current-flow,notifications.delivery.email-enabled
def test_ci_test_traffic_requires_allowlist_but_admin_report_can_notify():
    env = {"CI": "true"}
    assert not live_email_policy("outside@example.org", environ=env).allowed
    assert live_email_policy(
        "admin@example.org", admin_report=True, environ=env
    ).allowed
    env["OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST"] = "dedicated+ci@gmail.com"
    assert live_email_policy("dedicated+ci@gmail.com", environ=env).allowed


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_metadata_cannot_embed_recipient_or_arbitrary_context():
    decision = live_email_policy(
        "ordinary@example.org",
        email_type="private@example.org",
        environ={
            "SERVER_ENVIRONMENT": "customer-specific-secret",
        },
    )
    assert decision.tags == ("environment:other", "email-type:other", "audience:user")
    assert email_type_for_template("newsletter") == "newsletter"
    assert email_type_for_template("newsletter/../../private") == "other"


def _provider_args(recipient="ordinary@example.org"):
    return dict(
        sender_name="OpenMates",
        sender_email="noreply@example.org",
        recipient_email=recipient,
        recipient_name="Test",
        subject="Test",
        html_content="<p>Test</p>",
        plain_text_content="Test",
        email_headers={"X-OpenMates-Email-Type": "newsletter"},
        attachments=None,
    )


@pytest.mark.parametrize(
    "recipient,capture",
    [("ordinary@example.org", True), ("old@ae20drx9.mailosaur.net", False)],
)
# contract-test: supporting surface=rest_api assertions=auth.signup.current-flow,notifications.delivery.email-enabled
def test_mistaken_live_transport_selection_has_no_network_side_effect(
    monkeypatch, recipient, capture
):
    # This also runs inside isolated CI, with its Mailpit environment retained.
    if capture:
        monkeypatch.setenv("OPENMATES_CI_MAIL_CAPTURE", "1")
    connections = []

    def forbidden_connection():
        connections.append(True)
        raise AssertionError("live HTTP connection opened")

    monkeypatch.setattr(
        "backend.core.api.app.services.email.brevo_provider.aiohttp.ClientSession",
        forbidden_connection,
    )
    assert not asyncio.run(
        BrevoProvider("placeholder").send_email(**_provider_args(recipient))
    )
    assert not connections


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_permitted_transport_sends_bounded_tags_and_keeps_provider_receipt(monkeypatch):
    for name in (
        "CI",
        "CI_MAIL_CAPTURE",
        "OPENMATES_CI_MAIL_CAPTURE",
        "OPENMATES_CI_ISOLATED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    captured = []
    receipts = []

    class Response:
        status = 201

        async def text(self):
            return '{"messageId": "provider-receipt"}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def post(self, url, *, headers, data):
            captured.append(json.loads(data))
            return Response()

    async def receipt(message_id):
        receipts.append(message_id)

    monkeypatch.setattr(
        "backend.core.api.app.services.email.brevo_provider.aiohttp.ClientSession",
        Session,
    )
    assert asyncio.run(
        BrevoProvider("placeholder").send_email(
            **_provider_args(), accepted_message_id=receipt
        )
    )
    assert captured[0]["tags"] == [
        "environment:development",
        "email-type:newsletter",
        "audience:user",
    ]
    assert receipts == ["provider-receipt"]


@pytest.mark.parametrize(
    "module,attachment",
    [
        ("run_contract_audits", "report_path"),
        ("run_accessibility_weekly", "markdown_path"),
    ],
)
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_direct_admin_report_rejects_before_attachment_or_http(
    monkeypatch, module, attachment, tmp_path
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    report_module = importlib.import_module(module)
    attempted = []
    monkeypatch.setattr(
        report_module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: attempted.append(True),
    )
    with pytest.raises(ValueError, match="retired_test_inbox"):
        report_module._send_brevo_email(
            api_key="placeholder",
            recipient="old@ae20drx9.mailosaur.net",
            subject="Test",
            text="Test",
            html_body="<p>Test</p>",
            sender_email="noreply@example.org",
            sender_name="OpenMates",
            email_environment={},
            **{attachment: tmp_path / "absent.txt"},
        )
    assert not attempted


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_daily_runner_cannot_bypass_guard_through_internal_queue(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    runner = importlib.import_module("run_tests")
    notifier = runner.NotificationService.__new__(runner.NotificationService)
    notifier.dot_env = {"OPENMATES_CI_MAIL_CAPTURE": "1"}
    notifier.admin_email = "admin@example.org"
    notifier.brevo_api_key = "placeholder"
    notifier.internal_api_url = "https://api.example.org"
    notifier.internal_token = "placeholder"
    attempts = []
    monkeypatch.setattr(
        runner.urllib.request, "urlopen", lambda *args, **kwargs: attempts.append(True)
    )
    assert not notifier._send_via_brevo("Test", "Test")
    assert not notifier._send_via_internal_api("dispatch-test-summary-email", {})
    assert not attempts


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_github_failure_action_obeys_same_recipient_policy(monkeypatch):
    import yaml

    action_path = (
        Path(__file__).resolve().parents[2]
        / ".github/actions/notify-test-failure/action.yml"
    )
    action = yaml.safe_load(action_path.read_text())
    shell_script = next(
        step["run"]
        for step in action["runs"]["steps"]
        if step["name"] == "Send Brevo email"
    )
    python_script = shell_script.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    for name, value in {
        "GITHUB_WORKSPACE": str(Path(__file__).resolve().parents[2]),
        "BREVO_API_KEY": "placeholder",
        "EMAIL_TO": "old@ae20drx9.mailosaur.net",
        "RUN_LABEL": "isolated safety probe",
        "RUN_URL": "https://example.org",
        "FAILURE_SUMMARY": "Test",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("OPENMATES_CI_MAIL_CAPTURE", raising=False)
    monkeypatch.delenv("CI_MAIL_CAPTURE", raising=False)
    monkeypatch.delenv("OPENMATES_CI_ISOLATED", raising=False)
    attempts = []
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda *args, **kwargs: attempts.append(True)
    )
    with pytest.raises(SystemExit) as exc:
        exec(compile(python_script, str(action_path), "exec"), {})
    assert exc.value.code == 1
    assert not attempts


@pytest.mark.parametrize("admin_report", [False, True])
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,newsletter.campaign.eligible-idempotent-delivery
def test_explicit_preview_requires_exact_allowlist_for_ordinary_recipient(admin_report):
    from backend.shared.python_utils.live_email_policy import require_live_email

    env = {"SERVER_ENVIRONMENT": "production"}
    assert live_email_policy(
        "ordinary@gmail.com", admin_report=admin_report, environ=env
    ).allowed
    with pytest.raises(ValueError, match="test_recipient_not_allowlisted"):
        require_live_email(
            "ordinary@gmail.com",
            email_type="newsletter",
            test_traffic=True,
            admin_report=admin_report,
            environ=env,
        )
    env["OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST"] = "ordinary@gmail.com"
    tags = require_live_email(
        "ordinary@gmail.com",
        email_type="newsletter",
        test_traffic=True,
        admin_report=admin_report,
        environ=env,
    )
    assert tags == ["environment:production", "email-type:newsletter", "audience:test"]


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,newsletter.campaign.eligible-idempotent-delivery
def test_provider_honors_explicit_preview_header_before_http(monkeypatch):
    for name in (
        "CI",
        "CI_MAIL_CAPTURE",
        "OPENMATES_CI_MAIL_CAPTURE",
        "OPENMATES_CI_ISOLATED",
        "OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    connections = []

    def forbidden_connection():
        connections.append(True)
        raise AssertionError("preview opened live HTTP without approved recipient")

    monkeypatch.setattr(
        "backend.core.api.app.services.email.brevo_provider.aiohttp.ClientSession",
        forbidden_connection,
    )
    args = _provider_args("ordinary@gmail.com")
    args["email_headers"]["X-OpenMates-Email-Audience"] = "test"
    assert not asyncio.run(BrevoProvider("placeholder").send_email(**args))
    assert not connections


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,auth.signup.current-flow
def test_live_signup_smoke_alias_is_never_misclassified_as_ordinary_user():
    decision = live_email_policy(
        "dedicated+live-signup-2026-10-14@gmail.com",
        email_type="confirm-email",
        environ={"SERVER_ENVIRONMENT": "development"},
    )
    assert not decision.allowed
    assert decision.reason == "test_recipient_not_allowlisted"
    assert "audience:test" in decision.tags


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,auth.signup.current-flow
def test_daily_signup_alias_requires_explicit_opt_in_and_stays_test_tagged():
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date().isoformat()
    alias = f"dedicated+live-signup-{today}@gmail.com"
    env = {
        "SERVER_ENVIRONMENT": "development",
        "GMAIL_TEST_ADDRESS": "dedicated@gmail.com",
        "OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST": "dedicated@gmail.com",
    }
    assert not live_email_policy(alias, email_type="confirm-email", environ=env).allowed
    env["OPENMATES_LIVE_SIGNUP_SMOKE_ALIAS_ENABLED"] = "1"
    decision = live_email_policy(alias, email_type="confirm-email", environ=env)
    assert decision.allowed
    assert decision.tags == (
        "environment:development",
        "email-type:confirm-email",
        "audience:test",
    )


@pytest.mark.parametrize(
    "boundary",
    [
        "old_date",
        "manual_run_id",
        "wrong_template",
        "production",
        "unallowlisted_base",
        "capture",
        "spoof_base",
        "other_alias",
        "non_gmail",
    ],
)
# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled,auth.signup.current-flow
def test_daily_signup_compatibility_cannot_expand_live_recipient_scope(boundary):
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    alias = f"dedicated+live-signup-{today.isoformat()}@gmail.com"
    email_type = "confirm-email"
    env = {
        "SERVER_ENVIRONMENT": "development",
        "GMAIL_TEST_ADDRESS": "dedicated@gmail.com",
        "OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST": "dedicated@gmail.com",
        "OPENMATES_LIVE_SIGNUP_SMOKE_ALIAS_ENABLED": "1",
    }
    if boundary == "old_date":
        alias = (
            f"dedicated+live-signup-{(today - timedelta(days=1)).isoformat()}@gmail.com"
        )
    elif boundary == "manual_run_id":
        alias = "dedicated+live-signup-manual-run@gmail.com"
    elif boundary == "wrong_template":
        email_type = "newsletter"
    elif boundary == "production":
        env["SERVER_ENVIRONMENT"] = "production"
    elif boundary == "unallowlisted_base":
        env["OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST"] = ""
    elif boundary == "capture":
        env["OPENMATES_CI_MAIL_CAPTURE"] = "1"
    elif boundary == "spoof_base":
        alias = f"dedicated-other+live-signup-{today.isoformat()}@gmail.com"
    elif boundary == "other_alias":
        alias = "dedicated+e2e@gmail.com"
    elif boundary == "non_gmail":
        env["GMAIL_TEST_ADDRESS"] = "dedicated@example.org"
        env["OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST"] = "dedicated@example.org"
        alias = f"dedicated+live-signup-{today.isoformat()}@example.org"
    decision = live_email_policy(
        alias, email_type=email_type, environ=env
    )
    assert not decision.allowed
    assert "audience:test" in decision.tags
