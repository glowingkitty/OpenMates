"""The live billing verifier attributes every wallet debit before claiming proof."""

import pytest

from backend.scripts.verify_llm_cache_cli import parse_cli_json, reconcile_new_usage


def _chat(identifier, credits=8):
    return {"id": identifier, "credits": credits, "app_id": "ai", "skill_id": "ask", "chat_id": "chat"}


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_wallet_proof_accounts_for_project_assessment_separately():
    chat = [_chat("first", 8), _chat("second", 2)]
    assessment = {"id": "assessment", "credits": 1, "app_id": "ai",
                  "skill_id": "project-recommendation", "source": "direct"}
    result = reconcile_new_usage([], chat + [assessment], "chat", chat, 11)
    assert result == {"chat_credits": 10, "project_recommendation_credits": 1,
                      "wallet_debit": 11, "new_usage_entries": 3}


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_resumed_proof_does_not_charge_the_saved_first_turn_again():
    first, second = _chat("first", 38), _chat("second", 2)
    result = reconcile_new_usage([first], [second, first], "chat", [first, second], 2)
    assert result["chat_credits"] == 2


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_resumed_proof_handles_first_charge_older_than_the_account_history_page():
    first, second = _chat("first", 38), _chat("second", 2)
    history = [_chat(f"older-{number}") for number in range(10)]
    result = reconcile_new_usage(
        history, [second, *history[:9]], "chat", [first, second], 2,
        known_prior_chat_ids={first["id"]},
    )
    assert result["chat_credits"] == 2


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
@pytest.mark.parametrize("failure", ["unexplained-debit", "unrelated-chat", "missing-row", "history-rollover"])
def test_wallet_proof_rejects_incomplete_or_unrelated_attribution(failure):
    before = [_chat("old")]
    new = _chat("new")
    after, debit = [before[0], new], 8
    if failure == "unexplained-debit":
        debit = 9
    elif failure == "unrelated-chat":
        after.append({**_chat("other"), "chat_id": "someone-else"})
    elif failure == "missing-row":
        after = before
    else:
        after = [_chat(f"unknown-{number}") for number in range(10)]
    with pytest.raises(RuntimeError):
        reconcile_new_usage(before, after, "chat", [new], debit)


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_cli_json_parser_accepts_only_known_warning_prefix():
    result = parse_cli_json('(node:42) MaxListenersExceededWarning: listeners\n'
                            '(Use `node --trace-warnings ...` to show where the warning was created)\n'
                            '{"status":"completed"}\n')
    assert result["status"] == "completed"
    with pytest.raises(ValueError):
        parse_cli_json('unexpected failure\n{"status":"completed"}')
