# backend/tests/test_signup_existing_account_email.py
#
# Contract tests for the existing-account signup email path. Auth route modules
# pull in Redis, Directus, and Celery at import time, so these tests use AST and
# source checks to keep the backend contract covered in the lightweight local
# test environment. The CLI runtime flow is covered in openmates-cli signup tests.

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.parent
AUTH_EMAIL_PATH = REPO_ROOT / "backend/core/api/app/routes/auth_routes/auth_email.py"
EMAIL_TASK_INIT_PATH = REPO_ROOT / "backend/core/api/app/tasks/email_tasks/__init__.py"
EMAIL_TEMPLATE_SERVICE_PATH = REPO_ROOT / "backend/core/api/app/services/email_template.py"
EMAIL_TEMPLATE_PATH = REPO_ROOT / "backend/core/api/templates/email/existing-account.mjml"
EMAIL_TRANSLATIONS_PATH = REPO_ROOT / "frontend/packages/ui/src/i18n/sources/email/main.yml"


def test_existing_account_signup_route_queues_guidance_email_task():
    source = AUTH_EMAIL_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(AUTH_EMAIL_PATH))

    assert "EXISTING_ACCOUNT_EMAIL_TASK" in source
    assert "signup_existing_account_email:{hashed_email}" in source
    assert "EXISTING_ACCOUNT_EMAIL_COOLDOWN_SECONDS = 3600" in source

    send_task_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "send_task"
    ]
    matching_calls = []
    for call in send_task_calls:
        keyword_values = {keyword.arg: ast.unparse(keyword.value) for keyword in call.keywords if keyword.arg}
        if keyword_values.get("name") == "EXISTING_ACCOUNT_EMAIL_TASK":
            matching_calls.append(keyword_values)

    assert matching_calls == [
        {
            "name": "EXISTING_ACCOUNT_EMAIL_TASK",
            "kwargs": "{'email': email_request.email, 'language': email_request.language, 'darkmode': email_request.darkmode}",
            "queue": "'email'",
        }
    ]
    assert "message=GENERIC_EMAIL_CODE_MESSAGE" in source


def test_existing_account_email_task_is_registered_and_transactional():
    email_task_init = EMAIL_TASK_INIT_PATH.read_text(encoding="utf-8")
    email_template_service = EMAIL_TEMPLATE_SERVICE_PATH.read_text(encoding="utf-8")

    assert "from . import existing_account_email_task" in email_task_init
    assert "'existing_account_email_task'" in email_task_init
    assert 'elif template == "existing-account":' in email_template_service
    assert 'subject_key = "email.existing_account.subject"' in email_template_service
    assert "'existing-account'" in email_template_service


def test_existing_account_email_template_uses_translation_keys():
    template = EMAIL_TEMPLATE_PATH.read_text(encoding="utf-8")
    translations = EMAIL_TRANSLATIONS_PATH.read_text(encoding="utf-8")

    required_keys = [
        "existing_account.subject",
        "existing_account.title",
        "existing_account.intro",
        "existing_account.saved_logins_title",
        "existing_account.saved_logins_body",
        "existing_account.login_methods_title",
        "existing_account.login_methods_body",
        "existing_account.login_button",
        "existing_account.recovery_key_title",
        "existing_account.recovery_key_body",
        "existing_account.recovery_button",
        "existing_account.reset_warning",
    ]

    for key in required_keys:
        template_key = key.replace("existing_account.", "existing_account.")
        assert f"t.email.{template_key}.text" in template
        assert f"{key}:" in translations

    assert "{{ login_url }}" in template
    assert "{{ account_recovery_url }}" in template
