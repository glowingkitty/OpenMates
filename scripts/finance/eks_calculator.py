#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deterministic Anlage EKS calculator for local bank statement exports.

This standalone MVP reads Revolut Business CSV exports, applies an explicit
JSON mapping, and writes EKS-ready totals plus an audit trail. It is local-only:
no bank data is uploaded and no external services are called. The module is
kept independent so a future finance app skill can wrap the same core logic.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


REVOLUT_REQUIRED_COLUMNS = {
    "Date completed (UTC)",
    "ID",
    "Type",
    "State",
    "Description",
    "Reference",
    "Payment currency",
    "Amount",
    "Total amount",
    "Fee",
    "Fee currency",
    "Beneficiary name",
    "Sender name",
}

MONEY_QUANT = Decimal("0.01")
SUPPORTED_EFFECTS = {"income", "expense", "income_refund", "expense_refund", "ignore"}


class EksError(RuntimeError):
    """Raised when the EKS calculator cannot produce reliable output."""


@dataclass(frozen=True)
class SourceFile:
    path: Path
    sha256: str


@dataclass(frozen=True)
class Transaction:
    source_file: str
    row_number: int
    transaction_id: str
    completed_date: date
    transaction_type: str
    state: str
    description: str
    reference: str
    sender_name: str
    beneficiary_name: str
    amount: Decimal
    currency: str
    total_amount: Decimal
    fee: Decimal
    raw: dict[str, str]

    @property
    def month(self) -> str:
        return self.completed_date.strftime("%Y-%m")

    @property
    def party(self) -> str:
        return self.sender_name or self.beneficiary_name or ""


@dataclass(frozen=True)
class MatchResult:
    field_id: str
    label: str
    eks_section: str
    effect: str
    rule_name: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate Anlage EKS totals from local bank statement CSV files."
    )
    parser.add_argument(
        "--statements",
        nargs="+",
        required=True,
        help="One or more bank statement CSV paths.",
    )
    parser.add_argument(
        "--mapping",
        required=True,
        help="JSON mapping file defining deterministic transaction categories.",
    )
    parser.add_argument("--period-start", required=True, help="Inclusive start date, YYYY-MM-DD.")
    parser.add_argument("--period-end", required=True, help="Inclusive end date, YYYY-MM-DD.")
    parser.add_argument("--out-dir", required=True, help="Directory for generated CSV/JSON outputs.")
    parser.add_argument(
        "--pdf-template",
        help="Optional official Anlage EKS PDF template path. Requires pypdf when used.",
    )
    parser.add_argument(
        "--pdf-output",
        help="Optional filled Anlage EKS PDF output path. Requires --pdf-template.",
    )
    parser.add_argument(
        "--pdf-flatten",
        action="store_true",
        help="Flatten filled PDF fields into page content where supported by pypdf.",
    )
    parser.add_argument(
        "--pdf-declaration",
        default="final",
        choices=["final", "preliminary"],
        help="Declaration checkbox mode for the filled PDF. Defaults to final.",
    )
    parser.add_argument(
        "--bank-format",
        default="revolut_business_csv",
        choices=["revolut_business_csv"],
        help="Input bank statement format. MVP supports Revolut Business CSV.",
    )
    return parser.parse_args()


def parse_date(value: str, label: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise EksError(f"Invalid {label}: {value!r}. Expected YYYY-MM-DD.") from exc


def parse_money(value: str, *, column: str, row_number: int) -> Decimal:
    normalized = (value or "0").strip().replace(",", "")
    if not normalized:
        normalized = "0"
    try:
        return Decimal(normalized).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise EksError(f"Invalid money value in row {row_number}, column {column}: {value!r}") from exc


def money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_mapping(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file_handle:
            mapping = json.load(file_handle)
    except json.JSONDecodeError as exc:
        raise EksError(f"Mapping file is not valid JSON: {path}") from exc

    if mapping.get("version") != 1:
        raise EksError("Mapping version must be 1.")
    if mapping.get("bank_format") != "revolut_business_csv":
        raise EksError("MVP mapping must use bank_format=revolut_business_csv.")
    fields = mapping.get("fields")
    if not isinstance(fields, list) or not fields:
        raise EksError("Mapping must contain a non-empty fields list.")
    for field in fields:
        field_id = field.get("id")
        effect = field.get("effect")
        rules = field.get("rules")
        if not field_id or effect not in SUPPORTED_EFFECTS or not isinstance(rules, list) or not rules:
            raise EksError(
                "Each mapping field needs id, supported effect, and a non-empty rules list. "
                f"Invalid field: {field!r}"
            )
    return mapping


def read_revolut_csv(path: Path) -> tuple[SourceFile, list[Transaction]]:
    if not path.exists():
        raise EksError(f"Statement file does not exist: {path}")

    transactions: list[Transaction] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(REVOLUT_REQUIRED_COLUMNS - columns)
        if missing:
            raise EksError(f"{path} is missing required Revolut columns: {', '.join(missing)}")

        for row_number, row in enumerate(reader, start=2):
            completed_raw = (row.get("Date completed (UTC)") or "").strip()
            if not completed_raw:
                continue
            transactions.append(
                Transaction(
                    source_file=str(path),
                    row_number=row_number,
                    transaction_id=(row.get("ID") or "").strip(),
                    completed_date=parse_date(completed_raw, f"Date completed in row {row_number}"),
                    transaction_type=(row.get("Type") or "").strip(),
                    state=(row.get("State") or "").strip(),
                    description=(row.get("Description") or "").strip(),
                    reference=(row.get("Reference") or "").strip(),
                    sender_name=(row.get("Sender name") or "").strip(),
                    beneficiary_name=(row.get("Beneficiary name") or "").strip(),
                    amount=parse_money(row.get("Amount") or "0", column="Amount", row_number=row_number),
                    currency=(row.get("Payment currency") or "").strip(),
                    total_amount=parse_money(
                        row.get("Total amount") or "0", column="Total amount", row_number=row_number
                    ),
                    fee=parse_money(row.get("Fee") or "0", column="Fee", row_number=row_number),
                    raw={key: value or "" for key, value in row.items()},
                )
            )
    return SourceFile(path=path, sha256=file_sha256(path)), transactions


def deduplicate_transactions(transactions: list[Transaction]) -> list[Transaction]:
    seen: dict[str, Transaction] = {}
    deduped: list[Transaction] = []
    for transaction in transactions:
        key = transaction.transaction_id or transaction_hash(transaction)
        previous = seen.get(key)
        if previous is None:
            seen[key] = transaction
            deduped.append(transaction)
            continue
        if previous.raw != transaction.raw:
            raise EksError(
                "Duplicate transaction ID has conflicting data: "
                f"{key} in {previous.source_file}:{previous.row_number} and "
                f"{transaction.source_file}:{transaction.row_number}"
            )
    return deduped


def transaction_hash(transaction: Transaction) -> str:
    payload = "|".join(
        [
            transaction.completed_date.isoformat(),
            transaction.transaction_type,
            transaction.description,
            transaction.reference,
            transaction.sender_name,
            transaction.beneficiary_name,
            money(transaction.amount),
            transaction.currency,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def in_period(transaction: Transaction, start: date, end: date) -> bool:
    return start <= transaction.completed_date <= end and transaction.state.upper() == "COMPLETED"


def match_transaction(transaction: Transaction, mapping: dict[str, Any]) -> MatchResult | None:
    for field in mapping["fields"]:
        for rule in field["rules"]:
            condition = rule.get("match")
            if not isinstance(condition, dict):
                raise EksError(f"Rule {rule!r} must contain a match object.")
            if evaluate_condition(condition, transaction):
                return MatchResult(
                    field_id=field["id"],
                    label=field.get("label", field["id"]),
                    eks_section=field.get("eks_section", ""),
                    effect=field["effect"],
                    rule_name=rule.get("name", field["id"]),
                )
    return None


def evaluate_condition(condition: dict[str, Any], transaction: Transaction) -> bool:
    if "all" in condition:
        return all(evaluate_condition(item, transaction) for item in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(item, transaction) for item in condition["any"])
    if "not" in condition:
        return not evaluate_condition(condition["not"], transaction)

    field_name = condition.get("field")
    if not isinstance(field_name, str):
        raise EksError(f"Leaf condition needs a field name: {condition!r}")
    value = field_value(transaction, field_name)

    if "equals" in condition:
        return value.casefold() == str(condition["equals"]).casefold()
    if "contains" in condition:
        return str(condition["contains"]).casefold() in value.casefold()
    if "starts_with" in condition:
        return value.casefold().startswith(str(condition["starts_with"]).casefold())
    if "ends_with" in condition:
        return value.casefold().endswith(str(condition["ends_with"]).casefold())
    if "regex" in condition:
        return re.search(str(condition["regex"]), value, flags=re.IGNORECASE) is not None
    if "amount_gt" in condition:
        return transaction.amount > Decimal(str(condition["amount_gt"]))
    if "amount_lt" in condition:
        return transaction.amount < Decimal(str(condition["amount_lt"]))

    raise EksError(f"Unsupported match condition: {condition!r}")


def field_value(transaction: Transaction, field_name: str) -> str:
    normalized = field_name.strip()
    direct_fields = {
        "amount": money(transaction.amount),
        "currency": transaction.currency,
        "completed_date": transaction.completed_date.isoformat(),
        "description": transaction.description,
        "reference": transaction.reference,
        "sender_name": transaction.sender_name,
        "beneficiary_name": transaction.beneficiary_name,
        "party": transaction.party,
        "state": transaction.state,
        "type": transaction.transaction_type,
        "transaction_id": transaction.transaction_id,
    }
    if normalized in direct_fields:
        return direct_fields[normalized]
    return transaction.raw.get(normalized, "")


def effect_amount(transaction: Transaction, effect: str) -> Decimal:
    absolute = abs(transaction.amount)
    if effect == "income":
        if transaction.amount < 0:
            raise EksError(f"Income rule matched negative transaction {transaction.transaction_id}")
        return absolute
    if effect == "expense":
        if transaction.amount > 0:
            raise EksError(f"Expense rule matched positive transaction {transaction.transaction_id}")
        return absolute
    if effect == "income_refund":
        return -absolute
    if effect == "expense_refund":
        return -absolute
    if effect == "ignore":
        return Decimal("0.00")
    raise EksError(f"Unsupported effect: {effect}")


def write_outputs(
    *,
    out_dir: Path,
    start: date,
    end: date,
    source_files: list[SourceFile],
    all_rows_count: int,
    included: list[tuple[Transaction, MatchResult, Decimal]],
    mapping: dict[str, Any],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fields_by_id = {field["id"]: field for field in mapping["fields"]}
    totals, monthly = calculate_totals(mapping, included)

    write_audit_csv(out_dir / "eks-audit.csv", included)
    write_summary_csv(out_dir / "eks-summary.csv", fields_by_id, totals)
    write_monthly_csv(out_dir / "eks-monthly.csv", fields_by_id, monthly)
    write_run_json(
        out_dir / "eks-run.json",
        start=start,
        end=end,
        source_files=source_files,
        all_rows_count=all_rows_count,
        included_count=len(included),
        totals=totals,
        mapping=mapping,
    )


def calculate_totals(
    mapping: dict[str, Any], included: list[tuple[Transaction, MatchResult, Decimal]]
) -> tuple[dict[str, Decimal], dict[tuple[str, str], Decimal]]:
    totals: dict[str, Decimal] = {field["id"]: Decimal("0.00") for field in mapping["fields"]}
    monthly: dict[tuple[str, str], Decimal] = {}
    for transaction, match, amount in included:
        totals[match.field_id] += amount
        key = (transaction.month, match.field_id)
        monthly[key] = monthly.get(key, Decimal("0.00")) + amount
    return totals, monthly


def write_audit_csv(path: Path, included: list[tuple[Transaction, MatchResult, Decimal]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "source_file",
                "row_number",
                "transaction_id",
                "completed_date",
                "month",
                "type",
                "state",
                "description",
                "reference",
                "party",
                "sender_name",
                "beneficiary_name",
                "amount",
                "currency",
                "eks_section",
                "eks_field",
                "eks_label",
                "effect",
                "matched_rule",
                "eks_amount",
            ],
        )
        writer.writeheader()
        for transaction, match, amount in included:
            writer.writerow(
                {
                    "source_file": transaction.source_file,
                    "row_number": transaction.row_number,
                    "transaction_id": transaction.transaction_id,
                    "completed_date": transaction.completed_date.isoformat(),
                    "month": transaction.month,
                    "type": transaction.transaction_type,
                    "state": transaction.state,
                    "description": transaction.description,
                    "reference": transaction.reference,
                    "party": transaction.party,
                    "sender_name": transaction.sender_name,
                    "beneficiary_name": transaction.beneficiary_name,
                    "amount": money(transaction.amount),
                    "currency": transaction.currency,
                    "eks_section": match.eks_section,
                    "eks_field": match.field_id,
                    "eks_label": match.label,
                    "effect": match.effect,
                    "matched_rule": match.rule_name,
                    "eks_amount": money(amount),
                }
            )


def write_summary_csv(path: Path, fields_by_id: dict[str, dict[str, Any]], totals: dict[str, Decimal]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=["eks_section", "eks_field", "label", "effect", "total"],
        )
        writer.writeheader()
        for field_id, total in totals.items():
            field = fields_by_id[field_id]
            writer.writerow(
                {
                    "eks_section": field.get("eks_section", ""),
                    "eks_field": field_id,
                    "label": field.get("label", field_id),
                    "effect": field.get("effect", ""),
                    "total": money(total),
                }
            )


def write_monthly_csv(
    path: Path, fields_by_id: dict[str, dict[str, Any]], monthly: dict[tuple[str, str], Decimal]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=["month", "eks_section", "eks_field", "label", "effect", "total"],
        )
        writer.writeheader()
        for month, field_id in sorted(monthly):
            field = fields_by_id[field_id]
            writer.writerow(
                {
                    "month": month,
                    "eks_section": field.get("eks_section", ""),
                    "eks_field": field_id,
                    "label": field.get("label", field_id),
                    "effect": field.get("effect", ""),
                    "total": money(monthly[(month, field_id)]),
                }
            )


def write_run_json(
    path: Path,
    *,
    start: date,
    end: date,
    source_files: list[SourceFile],
    all_rows_count: int,
    included_count: int,
    totals: dict[str, Decimal],
    mapping: dict[str, Any],
) -> None:
    payload = {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "bank_format": mapping.get("bank_format"),
        "source_files": [
            {"path": str(source.path), "sha256": source.sha256} for source in source_files
        ],
        "rows_read": all_rows_count,
        "transactions_in_period": included_count,
        "totals": {field_id: money(total) for field_id, total in totals.items()},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_unmapped(out_dir: Path, unmapped: list[Transaction]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "eks-unmapped.csv"
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "source_file",
                "row_number",
                "transaction_id",
                "completed_date",
                "type",
                "description",
                "reference",
                "party",
                "amount",
                "currency",
            ],
        )
        writer.writeheader()
        for transaction in unmapped:
            writer.writerow(
                {
                    "source_file": transaction.source_file,
                    "row_number": transaction.row_number,
                    "transaction_id": transaction.transaction_id,
                    "completed_date": transaction.completed_date.isoformat(),
                    "type": transaction.transaction_type,
                    "description": transaction.description,
                    "reference": transaction.reference,
                    "party": transaction.party,
                    "amount": money(transaction.amount),
                    "currency": transaction.currency,
                }
            )
    return path


def print_success(out_dir: Path, included: list[tuple[Transaction, MatchResult, Decimal]]) -> None:
    income = sum((amount for _, match, amount in included if match.effect == "income"), Decimal("0.00"))
    expenses = sum((amount for _, match, amount in included if match.effect == "expense"), Decimal("0.00"))
    expense_refunds = sum(
        (amount for _, match, amount in included if match.effect == "expense_refund"), Decimal("0.00")
    )
    net_expenses = expenses + expense_refunds
    profit = income - net_expenses
    print(f"Wrote EKS outputs to {out_dir}")
    print(f"Betriebseinnahmen: {money(income)} EUR")
    print(f"Betriebsausgaben: {money(net_expenses)} EUR")
    print(f"Vorläufiger Gewinn: {money(profit)} EUR")


def run() -> int:
    args = parse_args()
    start = parse_date(args.period_start, "period start")
    end = parse_date(args.period_end, "period end")
    if start > end:
        raise EksError("period-start must be before or equal to period-end.")
    if args.pdf_output and not args.pdf_template:
        raise EksError("--pdf-output requires --pdf-template.")

    mapping = load_mapping(Path(args.mapping))
    source_files: list[SourceFile] = []
    transactions: list[Transaction] = []
    for statement in args.statements:
        source, rows = read_revolut_csv(Path(statement))
        source_files.append(source)
        transactions.extend(rows)

    deduped = deduplicate_transactions(transactions)
    scoped = [transaction for transaction in deduped if in_period(transaction, start, end)]
    matched: list[tuple[Transaction, MatchResult, Decimal]] = []
    unmapped: list[Transaction] = []

    for transaction in scoped:
        match = match_transaction(transaction, mapping)
        if match is None:
            unmapped.append(transaction)
            continue
        matched.append((transaction, match, effect_amount(transaction, match.effect)))

    out_dir = Path(args.out_dir)
    if unmapped:
        unmapped_path = write_unmapped(out_dir, unmapped)
        print(f"ERROR: {len(unmapped)} transactions are not mapped.", file=sys.stderr)
        print(f"Review and map them in: {unmapped_path}", file=sys.stderr)
        return 2

    write_outputs(
        out_dir=out_dir,
        start=start,
        end=end,
        source_files=source_files,
        all_rows_count=len(transactions),
        included=matched,
        mapping=mapping,
    )
    if args.pdf_output:
        from eks_pdf import write_eks_pdf

        _, monthly = calculate_totals(mapping, matched)
        write_eks_pdf(
            template_path=Path(args.pdf_template),
            output_path=Path(args.pdf_output),
            period_start=start,
            period_end=end,
            monthly=monthly,
            declaration=args.pdf_declaration,
            flatten=args.pdf_flatten,
        )
    print_success(out_dir, matched)
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except EksError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
