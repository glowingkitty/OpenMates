"""Regression coverage for retired public intro-chat recovery.

The login completion handlers must return interrupted early-signup accounts to
the neutral new-chat route. This focused source contract avoids importing the
full API dependency graph in lightweight test environments.
"""

from pathlib import Path


# contract-test: direct surface=rest_api assertions=landing-onboarding.legacy-intros-retired
def test_otp_and_backup_login_reset_early_signup_to_neutral_new_chat():
    login_source = (
        Path(__file__).parent.parent
        / "core/api/app/routes/auth_routes/auth_login.py"
    ).read_text()

    assert 'last_opened_path_otp = "/chat/new"' in login_source
    assert 'last_opened_path_backup = "/chat/new"' in login_source
    assert 'last_opened_path_otp = "demo-for-everyone"' not in login_source
    assert 'last_opened_path_backup = "demo-for-everyone"' not in login_source
