#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for the local Anlage EKS CSV calculator MVP.

The fixtures are synthetic and contain no real bank data. They cover the core
contracts needed before the script is wrapped by a future finance app skill:
strict classification, deduplication, and signed EKS totals.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "finance"))

from eks_pdf import build_eks_pdf_fields  # noqa: E402


SCRIPT = ROOT / "scripts" / "finance" / "eks_calculator.py"


HEADER = [
    "Date started (UTC)",
    "Date completed (UTC)",
    "ID",
    "Type",
    "State",
    "Description",
    "Reference",
    "Payer",
    "Card number",
    "Card label",
    "Card state",
    "Orig currency",
    "Orig amount",
    "Payment currency",
    "Amount",
    "Total amount",
    "Exchange rate",
    "Fee",
    "Fee currency",
    "Balance",
    "Account",
    "International account number",
    "Beneficiary account number",
    "Beneficiary sort code or routing number",
    "Beneficiary IBAN",
    "Beneficiary BIC",
    "Beneficiary name",
    "MCC",
    "Related transaction id",
    "Spend program",
    "Sender account",
    "Sender name",
    "Card references",
]


def write_statement(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=HEADER)
        writer.writeheader()
        for row in rows:
            full_row = {key: "" for key in HEADER}
            full_row.update(row)
            writer.writerow(full_row)


def write_mapping(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "bank_format": "revolut_business_csv",
                "fields": [
                    {
                        "id": "income",
                        "label": "Income",
                        "eks_section": "G.43",
                        "effect": "income",
                        "rules": [
                            {"name": "stripe", "match": {"field": "Sender name", "contains": "STRIPE"}}
                        ],
                    },
                    {
                        "id": "expenses",
                        "label": "Expenses",
                        "eks_section": "G.45/G.48",
                        "effect": "expense",
                        "rules": [
                            {
                                "name": "server costs",
                                "match": {"field": "Card label", "contains": "API & Server costs"},
                            }
                        ],
                    },
                    {
                        "id": "expense_refunds",
                        "label": "Expense refunds",
                        "eks_section": "G.45/G.48",
                        "effect": "expense_refund",
                        "rules": [
                            {"name": "refunds", "match": {"field": "Type", "equals": "CARD_REFUND"}}
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def run_calculator(tmp_path: Path, statement: Path, mapping: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--statements",
            str(statement),
            "--mapping",
            str(mapping),
            "--period-start",
            "2026-01-01",
            "--period-end",
            "2026-03-31",
            "--out-dir",
            str(tmp_path / "out"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_calculator_writes_summary_and_audit(tmp_path: Path) -> None:
    statement = tmp_path / "statement.csv"
    mapping = tmp_path / "mapping.json"
    write_mapping(mapping)
    write_statement(
        statement,
        [
            {
                "Date completed (UTC)": "2026-01-05",
                "ID": "tx-income",
                "Type": "TOPUP",
                "State": "COMPLETED",
                "Description": "Money added from STRIPE",
                "Payment currency": "EUR",
                "Amount": "100.00",
                "Total amount": "100.00",
                "Sender name": "STRIPE",
            },
            {
                "Date completed (UTC)": "2026-01-06",
                "ID": "tx-expense",
                "Type": "CARD_PAYMENT",
                "State": "COMPLETED",
                "Description": "Hosting",
                "Card label": "API & Server costs",
                "Payment currency": "EUR",
                "Amount": "-40.00",
                "Total amount": "-40.00",
            },
            {
                "Date completed (UTC)": "2026-01-07",
                "ID": "tx-refund",
                "Type": "CARD_REFUND",
                "State": "COMPLETED",
                "Description": "Refund from Hosting",
                "Payment currency": "EUR",
                "Amount": "10.00",
                "Total amount": "10.00",
            },
        ],
    )

    result = run_calculator(tmp_path, statement, mapping)

    assert result.returncode == 0, result.stderr
    summary = (tmp_path / "out" / "eks-summary.csv").read_text(encoding="utf-8")
    assert "income,Income,income,100.00" in summary
    assert "expenses,Expenses,expense,40.00" in summary
    assert "expense_refunds,Expense refunds,expense_refund,-10.00" in summary
    audit = (tmp_path / "out" / "eks-audit.csv").read_text(encoding="utf-8")
    assert "tx-income" in audit
    assert "tx-expense" in audit
    assert "tx-refund" in audit


def test_calculator_fails_on_unmapped_transaction(tmp_path: Path) -> None:
    statement = tmp_path / "statement.csv"
    mapping = tmp_path / "mapping.json"
    write_mapping(mapping)
    write_statement(
        statement,
        [
            {
                "Date completed (UTC)": "2026-01-05",
                "ID": "tx-unknown",
                "Type": "TRANSFER",
                "State": "COMPLETED",
                "Description": "Unknown incoming transfer",
                "Payment currency": "EUR",
                "Amount": "10.00",
                "Total amount": "10.00",
            }
        ],
    )

    result = run_calculator(tmp_path, statement, mapping)

    assert result.returncode == 2
    assert "transactions are not mapped" in result.stderr
    assert (tmp_path / "out" / "eks-unmapped.csv").exists()


def test_duplicate_identical_transaction_is_counted_once(tmp_path: Path) -> None:
    statement = tmp_path / "statement.csv"
    mapping = tmp_path / "mapping.json"
    write_mapping(mapping)
    row = {
        "Date completed (UTC)": "2026-01-05",
        "ID": "tx-income",
        "Type": "TOPUP",
        "State": "COMPLETED",
        "Description": "Money added from STRIPE",
        "Payment currency": "EUR",
        "Amount": "100.00",
        "Total amount": "100.00",
        "Sender name": "STRIPE",
    }
    write_statement(statement, [row, row])

    result = run_calculator(tmp_path, statement, mapping)

    assert result.returncode == 0, result.stderr
    run_metadata = json.loads((tmp_path / "out" / "eks-run.json").read_text(encoding="utf-8"))
    assert run_metadata["rows_read"] == 2
    assert run_metadata["transactions_in_period"] == 1
    assert run_metadata["totals"]["income"] == "100.00"


def test_build_eks_pdf_fields_maps_income_expenses_and_profit() -> None:
    from datetime import date
    from decimal import Decimal

    fields = build_eks_pdf_fields(
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        monthly={
            ("2026-01", "betriebseinnahmen_selbstaendig"): Decimal("100.00"),
            ("2026-01", "betriebsausgaben_api_hosting_software"): Decimal("40.00"),
            ("2026-01", "betriebsausgaben_bankgebuehren"): Decimal("10.00"),
            ("2026-01", "betriebsausgaben_reisekosten"): Decimal("20.00"),
        },
    )

    assert fields["dateBewilligungszeitraumVon"] == "01.01.2026"
    assert fields["dateBewilligungszeitraumBis"] == "30.06.2026"
    assert fields["chbxAngabenZeitAbschl"] == "/selektiert"
    assert fields["chbxTaetigkeitAngabenAbschl"] == "/selektiert"
    assert fields["txtfTab_Z1_S2"] == "01/2026"
    assert fields["numfTabA_Z2_S2"] == "100,00"
    assert fields["numfTabA_Z9_S2"] == "100,00"
    assert fields["numfTabB2_Z9_S2"] == "20,00"
    assert fields["numfTabB3_Z8_S2"] == "10,00"
    assert fields["numfTabB3_Z10_S2"] == "40,00"
    assert fields["numfTabB3_Z15_S2"] == "70,00"
    assert fields["numfTabB3_Z16_S2"] == "30,00"
