#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF output helper for the local Anlage EKS calculator.

The official Jobcenter Anlage EKS PDF is an AcroForm with stable field names for
the income and expense tables. This helper fills only deterministic calculation
fields from the CSV audit result and leaves personal/application fields blank.
It imports pypdf lazily so CSV-only runs keep working without PDF dependencies.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


MONEY_QUANT = Decimal("0.01")
PDF_COLUMN_FIELDS = {
    0: "S2",
    1: "S3",
    2: "S4",
    3: "S5",
    4: "S6",
    5: "S7",
}


def write_eks_pdf(
    *,
    template_path: Path,
    output_path: Path,
    period_start: date,
    period_end: date,
    monthly: dict[tuple[str, str], Decimal],
    declaration: str = "final",
    flatten: bool = False,
) -> dict[str, str]:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError(
            "PDF output requires pypdf. Install it in the active Python environment with: "
            "python3 -m pip install pypdf"
        ) from exc

    field_values = build_eks_pdf_fields(
        period_start=period_start,
        period_end=period_end,
        monthly=monthly,
        declaration=declaration,
    )
    reader = PdfReader(str(template_path))
    writer = PdfWriter()
    writer.clone_reader_document_root(reader)
    writer.set_need_appearances_writer(True)
    writer.update_page_form_field_values(
        None,
        field_values,
        auto_regenerate=True,
        flatten=flatten,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as file_handle:
        writer.write(file_handle)
    return field_values


def build_eks_pdf_fields(
    *,
    period_start: date,
    period_end: date,
    monthly: dict[tuple[str, str], Decimal],
    declaration: str = "final",
) -> dict[str, str]:
    months = month_keys(period_start, period_end)
    if len(months) != 6:
        raise ValueError("Anlage EKS PDF output expects exactly 6 calendar months.")

    values: dict[str, str] = {
        "dateBewilligungszeitraumVon": format_date_de(period_start),
        "dateBewilligungszeitraumBis": format_date_de(period_end),
    }
    values.update(declaration_fields(declaration))

    for index, month in enumerate(months):
        column = PDF_COLUMN_FIELDS[index]
        income = monthly_value(monthly, month, "betriebseinnahmen_selbstaendig")
        travel = monthly_value(monthly, month, "betriebsausgaben_reisekosten")
        bank_fees = monthly_value(monthly, month, "betriebsausgaben_bankgebuehren")
        other_expenses = monthly_value(monthly, month, "betriebsausgaben_api_hosting_software")
        expense_refunds = monthly_value(monthly, month, "betriebsausgaben_minderung_rueckerstattung")
        net_other_expenses = other_expenses + expense_refunds
        total_b2 = travel
        total_expenses = total_b2 + bank_fees + net_other_expenses
        profit = income - total_expenses

        values[f"txtfTab_Z1_{column}"] = format_month_de(month)
        values[f"numfTabA_Z2_{column}"] = format_money_de(income)
        values[f"numfTabA_Z9_{column}"] = format_money_de(income)
        values[f"numfTabB1_Z10_{column}"] = format_money_de(Decimal("0.00"))
        values[f"numfTabB2_Z2_{column}"] = format_money_de(Decimal("0.00"))
        values[f"numfTabB2_Z9_{column}"] = format_money_de(travel)
        values[f"numfTabB2_Z15_{column}"] = format_money_de(total_b2)
        values[f"numfTabB3_Z2_{column}"] = format_money_de(total_b2)
        values[f"numfTabB3_Z8_{column}"] = format_money_de(bank_fees)
        values[f"numfTabB3_Z10_{column}"] = format_money_de(net_other_expenses)
        values[f"numfTabB3_Z15_{column}"] = format_money_de(total_expenses)
        values[f"numfTabB3_Z16_{column}"] = format_money_de(profit)

    return values


def declaration_fields(declaration: str) -> dict[str, str]:
    if declaration == "final":
        return {
            "chbxAngabenZeitVorl": "/Off",
            "chbxAngabenZeitAbschl": "/selektiert",
            "chbxTaetigkeitAngabenVorl": "/Off",
            "chbxTaetigkeitAngabenAbschl": "/selektiert",
        }
    if declaration == "preliminary":
        return {
            "chbxAngabenZeitVorl": "/selektiert",
            "chbxAngabenZeitAbschl": "/Off",
            "chbxTaetigkeitAngabenVorl": "/selektiert",
            "chbxTaetigkeitAngabenAbschl": "/Off",
        }
    raise ValueError("PDF declaration must be 'final' or 'preliminary'.")


def month_keys(start: date, end: date) -> list[str]:
    months: list[str] = []
    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def monthly_value(monthly: dict[tuple[str, str], Decimal], month: str, field_id: str) -> Decimal:
    return monthly.get((month, field_id), Decimal("0.00"))


def format_date_de(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def format_month_de(value: str) -> str:
    year, month = value.split("-", 1)
    return f"{month}/{year}"


def format_money_de(value: Decimal) -> str:
    rounded = value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    return f"{rounded:.2f}".replace(".", ",")
