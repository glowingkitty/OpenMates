"""The live billing verifier attributes every wallet debit before claiming proof."""

from copy import deepcopy
from io import StringIO
import json
import sys

import pytest

from backend.scripts.verify_llm_cache_cli import (
    full_input_flat_estimate, parse_cli_json, reconcile_new_usage, split_chat_rows,
    summarize_turns,
)
from backend.scripts import verify_llm_cache_cli


def _chat(identifier, credits=8):
    return {"id": identifier, "credits": credits, "app_id": "ai", "skill_id": "ask", "chat_id": "chat"}


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_wallet_proof_accounts_for_project_assessment_separately():
    chat = [_chat("first", 8), _chat("second", 2)]
    assessment = {"id": "assessment", "credits": 1, "app_id": "ai",
                  "skill_id": "project-recommendation", "source": "direct"}
    result = reconcile_new_usage([], chat + [assessment], "chat", chat, 11)
    assert result == {"chat_credits": 10, "project_recommendation_credits": 1,
                      "tool_credits": 0, "wallet_debit": 11, "new_usage_entries": 3}


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_resumed_proof_does_not_charge_the_saved_first_turn_again():
    first, second = _chat("first", 38), _chat("second", 2)
    result = reconcile_new_usage([first], [second, first], "chat", [first, second], 2)
    assert result["chat_credits"] == 2


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_same_chat_skill_is_attributed_but_unrelated_charge_is_rejected():
    ask = _chat("ask", 93)
    search = {"id": "search", "credits": 10, "app_id": "web", "skill_id": "search",
              "chat_id": "chat"}
    project = {"id": "project", "credits": 1, "app_id": "ai",
               "skill_id": "project-recommendation", "source": "direct"}
    asks, tools = split_chat_rows([ask, search], "chat")
    assert ([row["id"] for row in asks], [row["id"] for row in tools]) == (["ask"], ["search"])
    with pytest.raises(RuntimeError, match="did not persist a receipt"):
        summarize_turns([{**ask, "created_at": "2026-10-08T00:00:00Z"}], require_receipts=True)
    result = reconcile_new_usage([], [ask, search, project], "chat", [ask, search], 104)
    assert (result["chat_credits"], result["tool_credits"],
            result["project_recommendation_credits"]) == (93, 10, 1)
    with pytest.raises(RuntimeError, match="Unexpected new usage charge"):
        reconcile_new_usage([], [ask, search, {**search, "id": "other", "chat_id": "elsewhere"}],
                            "chat", [ask, search], 113)
    with pytest.raises(RuntimeError, match="missing from account usage history"):
        reconcile_new_usage([], [ask, project], "chat", [ask, search], 104)


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


def _receipt(input_tokens=100, billed_input_tokens=50, cache_read_tokens=50,
             output_tokens=10, charged=7):
    return {"settlement_state": "settled", "credits_charged": charged,
            "usage_source": "provider_reported",
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "cache_creation_input_tokens": 0,
            "entries": [{"model_id": "test/model", "pricing_version": "frozen-v1",
                         "inference_host": "test-host",
                         "billing_mode": "cache_aware", "write_billing": "included_in_input",
                         "input_tokens": input_tokens, "billed_input_tokens": billed_input_tokens,
                         "cache_read_input_tokens": cache_read_tokens,
                         "output_tokens": output_tokens,
                         "rates": {"input": "10", "cache_read": "100", "output": "5",
                                   "cache_write": None, "cache_write_1h": None}}]}


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_three_paid_turns_reconcile_and_use_frozen_receipt_rates():
    rows = [{**_chat(f"turn-{i}", 7), "created_at": f"2026-10-08T00:00:0{i}Z",
             "llm_usage_breakdown": _receipt()} for i in range(3)]
    turns = summarize_turns(rows[::-1], require_receipts=True)
    assert [turn["usage_id"] for turn in turns] == ["turn-0", "turn-1", "turn-2"]
    assert [turn["actual_credits"] for turn in turns] == [7, 7, 7]
    assert [turn["flat_full_input_estimate_credits"] for turn in turns] == [12, 12, 12]
    assert turns[0]["frozen_rates"][0]["rates"]["input"] == "10"
    assessment = {"id": "assessment", "credits": 1, "app_id": "ai",
                  "skill_id": "project-recommendation", "source": "direct"}
    assert reconcile_new_usage([], rows + [assessment], "chat", rows, 22)["project_recommendation_credits"] == 1


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_full_input_comparison_includes_anthropic_writes_and_paid_output():
    receipt = _receipt(input_tokens=160, billed_input_tokens=100,
                       cache_read_tokens=50, output_tokens=20, charged=15)
    entry = receipt["entries"][0]
    entry.update(write_billing="separate", cache_creation_5m_input_tokens=10,
                 cache_creation_1h_input_tokens=0)
    entry["rates"]["cache_write"] = "8"
    # The 10 write tokens appear in the flat input estimate. A legacy charge
    # might have omitted them, so this number cannot be called legacy savings.
    assert full_input_flat_estimate(receipt) == 20


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_per_turn_proof_rejects_unsettled_or_mismatched_charge():
    row = {**_chat("turn", 7), "created_at": "2026-10-08T00:00:00Z",
           "llm_usage_breakdown": _receipt()}
    for broken in ({**_receipt(), "settlement_state": "pending"},
                   {**_receipt(), "credits_charged": 8}):
        with pytest.raises(RuntimeError, match="Receipt category arithmetic"):
            summarize_turns([{**row, "llm_usage_breakdown": broken}], require_receipts=True)


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_activated_proof_rejects_mixed_tariff_attempts_even_when_charge_reconciles():
    receipt = _receipt()
    ordinary = deepcopy(receipt["entries"][0])
    ordinary.update(billing_mode="ordinary_input", input_tokens=0,
                    billed_input_tokens=0, cache_read_input_tokens=0, output_tokens=0)
    receipt["entries"].append(ordinary)
    row = {**_chat("turn", 7), "created_at": "2026-10-08T00:00:00Z",
           "llm_usage_breakdown": receipt}
    assert summarize_turns([row], require_receipts=False)[0]["billing_modes"] == [
        "cache_aware", "ordinary_input"]
    with pytest.raises(RuntimeError, match="every frozen attempt"):
        summarize_turns([row], require_receipts=True)


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_expected_tariff_accepts_reported_ordinary_fallback_with_missing_metric():
    receipt = _receipt(input_tokens=100, billed_input_tokens=100,
                       cache_read_tokens=0, charged=12)
    entry = receipt["entries"][0]
    entry.update(billing_mode="ordinary_input", cache_read_input_tokens=None,
                 cache_creation_input_tokens=None)
    receipt["cache_read_input_tokens"] = None
    receipt["cache_creation_input_tokens"] = None
    row = {**_chat("turn", 12), "created_at": "2026-10-08T00:00:00Z",
           "llm_usage_breakdown": receipt}
    expected = {"test/model": {"pricing_version": "frozen-v1",
                               "eligible_hosts": ["test-host"]}}
    turns = summarize_turns([row], require_receipts=True, expected_tariffs=expected)
    assert turns[0]["ordinary_input_missing_cache_metric_attempts"] == 1
    assert turns[0]["cache_read_input_tokens"] is None
    assert turns[0]["actual_credits"] == turns[0]["flat_full_input_estimate_credits"] == 12

    for change, error in [
        ({"pricing_version": "wrong"}, "Frozen attempt differs"),
        ({"inference_host": "other-host"}, "Frozen attempt differs"),
        ({"cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}, "no missing cache metric"),
    ]:
        altered = deepcopy(receipt)
        altered["entries"][0].update(change)
        with pytest.raises(RuntimeError, match=error):
            summarize_turns([{**row, "llm_usage_breakdown": altered}],
                            require_receipts=True, expected_tariffs=expected)

    estimated = {**receipt, "usage_source": "estimated"}
    with pytest.raises(RuntimeError, match="provider-reported"):
        summarize_turns([{**row, "llm_usage_breakdown": estimated}],
                        require_receipts=True, expected_tariffs=expected)

    mixed = deepcopy(receipt)
    ineligible = deepcopy(entry)
    ineligible.update(inference_host="other-host", input_tokens=0,
                      billed_input_tokens=0, output_tokens=0)
    mixed["entries"].append(ineligible)
    with pytest.raises(RuntimeError, match="eligible host"):
        summarize_turns([{**row, "llm_usage_breakdown": mixed}],
                        require_receipts=True, expected_tariffs=expected)


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_receipt_attempt_must_match_requested_model_even_if_tariff_map_has_both():
    row = {**_chat("ask", 7), "created_at": "2026-10-08T00:00:00Z",
           "llm_usage_breakdown": _receipt()}
    expected = {"test/model": {"pricing_version": "frozen-v1", "eligible_hosts": ["test-host"]},
                "test/other": {"pricing_version": "frozen-v1", "eligible_hosts": ["test-host"]}}
    with pytest.raises(RuntimeError, match="requested model"):
        summarize_turns([row], require_receipts=True, expected_tariffs=expected,
                        requested_model_id="test/other")


# contract-test: supporting surface=cli assertions=billing.usage.receipt-token-breakdown
def test_verify_only_finishes_retained_chat_without_paid_cli_calls(tmp_path, monkeypatch):
    (tmp_path / "test-project.private.json").write_text(json.dumps({"project": {"project_id": "project"}}))
    proof_path = tmp_path / "prior.json"
    proof_path.write_text(json.dumps({
        "chat_id": "chat", "paid_turns": 1, "charges": [{"id": "first", "credits": 7}],
        "project_recommendation": {"credits": 1}, "wallet_before": 775,
        "wallet_after": 767, "turn_wallet_debits": [8],
    }))
    rows = []
    for index, identifier in enumerate(("first", "second")):
        receipt = _receipt()
        receipt["entries"][0]["model_id"] = "openai/gpt-6.1-sol"
        rows.append({**_chat(identifier, 7), "created_at": f"2026-10-08T00:00:0{index}Z",
                     "llm_usage_breakdown": receipt})
    search = {"id": "search", "credits": 10, "app_id": "web", "skill_id": "search",
              "chat_id": "chat", "created_at": "2026-10-08T00:00:02Z"}
    project = {"id": "project-charge", "credits": 1, "app_id": "ai",
               "skill_id": "project-recommendation", "source": "direct"}
    calls = []

    class FakeProcess:
        def __init__(self, invocation, **_kwargs):
            args = invocation[invocation.index("https://api.dev.openmates.org") + 1:-1]
            calls.append(args)
            if args[:2] == ["chats", "show"]:
                result = {"messages": [{"role": "assistant", "content": "answer"},
                                       {"role": "assistant", "content": "follow-up"}]}
            elif args[:4] == ["settings", "billing", "usage", "details"]:
                result = {"entries": rows + [search]}
            elif args[:3] == ["settings", "billing", "usage"]:
                result = {"usage": rows + [search, project]}
            elif args[:3] == ["settings", "billing", "overview"]:
                result = {"held_credits": 0}
            elif args == ["whoami"]:
                result = {"credits": 750}
            else:
                raise AssertionError(f"Unexpected CLI command: {args}")
            self.stdout = StringIO(json.dumps(result))
            self.returncode = 0

        def wait(self, **_kwargs):
            return 0

    monkeypatch.setattr(verify_llm_cache_cli.subprocess, "Popen", FakeProcess)
    monkeypatch.setenv("OPENMATES_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["verify_llm_cache_cli.py", "--phase", "verify",
                                      "--model", "GPT-6.1-Sol", "--followup-count", "1",
                                      "--resume-chat", "chat", "--prior-proof", str(proof_path),
                                      "--verify-only"])
    verify_llm_cache_cli.main()
    assert not any(args[:2] in (["chats", "new"], ["chats", "send"]) for args in calls)
    report = json.loads((tmp_path / "verify" / "report.json").read_text())["models"][0]
    assert report["persisted_credits"] == 14
    assert report["tool_credits"] == 10
    assert report["project_recommendation_credits"] == 1
    assert report["wallet_before"] - report["wallet_after"] == 25
