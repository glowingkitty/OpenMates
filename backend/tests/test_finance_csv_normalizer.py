# backend/tests/test_finance_csv_normalizer.py
#
# Contract tests for the Finance canonical CSV/TSV normalizer.
# These tests intentionally use raw merchant names in fixtures to prove the
# normalized output replaces them before persistence or LLM context.
#
# Spec: docs/specs/finance-check-accounts-v1/spec.yml

"""Finance CSV normalizer contract tests.

These tests define the canonical OpenMates bank-statement CSV/TSV template for
the Finance Check accounts skill. Raw counterparty text may enter parsing, but
normalized outputs must use category-aware placeholders before persistence or
LLM context.
"""

from __future__ import annotations

import json

import pytest

from backend.shared.python_utils.finance_accounts import (
    FinanceCSVTemplateError,
    FinancePrivacyRedactor,
    parse_bank_statement_text,
)


CSV_STATEMENT = """transaction_id,account_id,account_label,posted_at,description,amount,currency,direction,balance_after,category_hint,counterparty_type,source_name,notes
txn-1,checking,Main checking,2026-01-03,Spotify Premium,-12.99,EUR,expense,987.01,streaming,merchant,bank export,
txn-2,checking,Main checking,2026-01-05,Acme Payroll,2500.00,EUR,income,3487.01,payroll,payer,bank export,
txn-3,savings,Savings,2026-01-10,Grocery Mart,-74.30,EUR,,3412.71,groceries,merchant,bank export,
"""


TSV_STATEMENT = """transaction_id\taccount_id\taccount_label\tposted_at\tdescription\tamount\tcurrency
txn-4\tchecking\tMain checking\t2026-01-11\tCoffee Shop\t-4.20\tEUR
"""


def test_parse_canonical_csv_and_tsv_to_normalized_redacted_transactions() -> None:
    redactor = FinancePrivacyRedactor()

    csv_result = parse_bank_statement_text(
        CSV_STATEMENT,
        filename="statement.csv",
        source_ref="csv:statement",
        redactor=redactor,
    )
    tsv_result = parse_bank_statement_text(
        TSV_STATEMENT,
        filename="statement.tsv",
        source_ref="csv:statement-tsv",
        redactor=redactor,
    )

    assert [account.account_ref for account in csv_result.accounts] == ["checking", "savings"]
    assert csv_result.transactions[0].counterparty_placeholder == "[MERCHANT_STREAMING_001]"
    assert csv_result.transactions[0].category == "streaming"
    assert csv_result.transactions[0].direction == "expense"
    assert csv_result.transactions[1].counterparty_placeholder == "[PAYER_PAYROLL_001]"
    assert csv_result.transactions[2].direction == "expense"
    assert tsv_result.transactions[0].counterparty_placeholder == "[MERCHANT_UNCATEGORIZED_001]"

    payload = json.dumps(
        {
            "csv": csv_result.model_dump(),
            "tsv": tsv_result.model_dump(),
        }
    )
    for raw_name in ["Spotify", "Acme", "Grocery", "Coffee"]:
        assert raw_name not in payload


def test_non_template_csv_fails_with_actionable_error() -> None:
    with pytest.raises(FinanceCSVTemplateError, match="canonical OpenMates bank-statement template"):
        parse_bank_statement_text(
            "Date,Payee,Debit\n2026-01-03,Spotify Premium,12.99\n",
            filename="bank-export.csv",
        )
