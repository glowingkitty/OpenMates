"""Live-site abuse: decline without strike, strike only on clear repetition, Browse run guard."""


from backend.apps.ai.processing.request_purpose_policy import evaluate_request_purpose
from backend.shared.providers.browser_run_guard import MASS_ACTION_MESSAGE, RunGuard

OBSERVATION = {
    "url": "https://example.org/signup",
    "controls": [
        {"id": "1", "role": "input", "label": "Email"},
        {"id": "2", "role": "button", "label": "Create account"},
        {"id": "3", "role": "button", "label": "Post comment"},
    ],
}


def decisions(**changes):
    base = {"harmful_purpose": "none", "illegal_category": "none",
            "live_site_abuse": 0.0, "live_site_abuse_repeated_across_sites": 0.0}
    return {**base, **changes}


# contract-test: direct surface=rest_api assertions=safety-strikes.live-site-line
def test_plausible_ownership_claim_declines_without_strike():
    outcome = evaluate_request_purpose(decisions(live_site_abuse=0.9))
    assert outcome.action == "decline" and not outcome.strike


# contract-test: direct surface=rest_api assertions=safety-strikes.live-site-line
def test_repeated_attempts_across_sites_strike():
    outcome = evaluate_request_purpose(decisions(live_site_abuse=0.9, live_site_abuse_repeated_across_sites=0.9))
    assert outcome.strike


# contract-test: direct surface=rest_api assertions=safety-strikes.live-site-line
def test_writing_code_for_the_user_is_not_live_site_abuse():
    assert evaluate_request_purpose(decisions(live_site_abuse=0.1)).action == "allow"


def _submit(target):
    return {"kind": "click", "target": target}


def _guard_observation():
    from backend.shared.providers import browser_planner

    return OBSERVATION if browser_planner.control_index(OBSERVATION) else None


# contract-test: direct surface=rest_api assertions=safety-strikes.live-site-line
def test_single_normal_form_fill_is_allowed():
    guard = RunGuard()
    assert guard.check([{"kind": "type", "target": "1", "text": "a@example.org"}], OBSERVATION, now=0) is None
    assert guard.check([_submit("2")], OBSERVATION, now=10) is None


# contract-test: direct surface=rest_api assertions=safety-strikes.live-site-line
def test_mass_submissions_in_one_run_are_refused():
    guard = RunGuard()
    results = [guard.check([_submit("3")], OBSERVATION, now=10.0 * i) for i in range(1, 6)]
    assert results[:3] == [None, None, None]
    assert results[3] == MASS_ACTION_MESSAGE


# contract-test: direct surface=rest_api assertions=safety-strikes.live-site-line
def test_batch_of_submissions_and_too_fast_repeats_are_refused():
    assert RunGuard().check([_submit("2"), _submit("3"), _submit("2"), _submit("3")], OBSERVATION, now=0) == MASS_ACTION_MESSAGE
    guard = RunGuard()
    assert guard.check([_submit("2")], OBSERVATION, now=0) is None
    assert guard.check([_submit("3")], OBSERVATION, now=0.2) == MASS_ACTION_MESSAGE
