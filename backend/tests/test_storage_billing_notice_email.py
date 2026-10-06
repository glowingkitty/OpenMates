"""Storage billing notices render the same dated remedy contract the job supplies."""

from __future__ import annotations

from backend.core.api.app.services.email_sender_profiles import sender_profile_for_template
from pathlib import Path
from jinja2 import Template
import pytest
from backend.core.api.app.services.translations import TranslationService


def _render_notice(stage: int, lang: str, context: dict) -> str:
    """Render the real MJML/Jinja source with the runtime translation substitution."""
    template_dir = Path(__file__).resolve().parents[1] / "core/api/templates/email"
    source = (template_dir / f"storage-billing-failed-{stage}.mjml").read_text()
    translations = TranslationService().get_translations(lang, variables=context)
    return Template(source).render(**context, t=translations)


# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
def test_four_storage_notices_render_dated_balance_and_remedies() -> None:
    context = {
        "storage_gb": "2.5",
        "credits_needed": 6,
        "outstanding_credits": 24,
        "deadline_date": "2026-11-01",
        "credits_url": "https://openmates.org/#settings/billing",
        "export_url": "https://openmates.org/#settings/account/export",
        "darkmode": False,
    }
    for stage in range(1, 5):
        rendered = _render_notice(stage, "en", context)
        assert "2026-11-01" in rendered
        assert "24 credits" in rendered
        assert "2.5 GiB" in rendered
        assert context["credits_url"] in rendered
        assert context["export_url"] in rendered
        assert "affected chargeable files" in rendered.lower()
        assert "earliest removal date, not a scheduled deletion" in rendered
        assert "{deadline_date}" not in rendered
        assert "permanently deleted" not in rendered
        assert sender_profile_for_template(f"storage-billing-failed-{stage}")[1] == "support@openmates.org"

    final = _render_notice(4, "en", context)
    assert "fourth delivered notice" in final
    assert "They have not been deleted by this notice" in final


# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
def test_final_storage_notice_de_has_deadline_and_export_link() -> None:
    rendered = _render_notice(
        4,
        "de",
        {
            "storage_gb": "2.5",
            "credits_needed": 6,
            "outstanding_credits": 24,
            "deadline_date": "2026-11-01",
            "credits_url": "https://openmates.org/#settings/billing",
            "export_url": "https://openmates.org/#settings/account/export",
            "darkmode": False,
        },
    )
    assert "2026-11-01" in rendered
    assert "24 Credits" in rendered
    assert "frühestens" in rendered
    assert "https://openmates.org/#settings/account/export" in rendered


# contract-test: supporting surface=rest_api assertions=billing.storage.four-warning-expiry
@pytest.mark.parametrize("lang", ["zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv", "he"])
def test_final_notice_has_complete_safe_fallback_copy_in_every_locale(lang: str) -> None:
    rendered = _render_notice(4, lang, {
        "storage_gb": "2.5",
        "credits_needed": 6,
        "outstanding_credits": 24,
        "deadline_date": "2026-11-01",
        "credits_url": "https://openmates.org/#settings/billing",
        "export_url": "https://openmates.org/#settings/account/export",
        "darkmode": False,
    })
    assert "2026-11-01" in rendered
    assert "24 credits" in rendered
    assert "https://openmates.org/#settings/account/export" in rendered
    assert "affected chargeable files" in rendered
    assert "{deadline_date}" not in rendered


# contract-test: supporting surface=rest_api assertions=billing.storage.team-warning-expiry
def test_team_notice_names_the_team_allowance_all_recipients_and_frozen_unit() -> None:
    context = {
        "team_slug": "ci-team", "warning_stage": 4, "storage_gb": 1.5,
        "credits_needed": 3, "outstanding_credits": 12,
        "deadline_date": "2026-11-01", "team_url": "https://openmates.org/#settings/teams",
        "affected_units": [{"kind": "cold_chat", "resource_id": "ci-chat",
                            "oldest_date": "2026-09-01", "size_mib": 5.0}],
        "darkmode": False,
    }
    template_dir = Path(__file__).resolve().parents[1] / "core/api/templates/email"
    source = (template_dir / "team-storage-billing-failed.mjml").read_text()
    translations = TranslationService().get_translations("en", variables=context)
    rendered = Template(source).render(**context, t=translations)
    assert "ci-team" in rendered
    assert "1 GiB free allowance" in rendered
    assert "2026-11-01 UTC" in rendered
    assert "warning 4 of 4" in rendered
    assert "ci-chat" in rendered
    assert context["team_url"] in rendered
    assert sender_profile_for_template("team-storage-billing-failed")[1] == "support@openmates.org"
