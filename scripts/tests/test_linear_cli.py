"""Tests for the OpenMates Linear CLI helper.

These tests import scripts/linear.py without calling the real Linear API.
They cover argument-independent helpers that build GraphQL mutation input,
so future CLI field additions stay easy to verify locally.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
LINEAR_CLI_PATH = ROOT / "scripts/linear.py"


def load_linear_cli():
    spec = importlib.util.spec_from_file_location("openmates_linear_cli", LINEAR_CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_apply_due_date_input_sets_iso_date() -> None:
    linear_cli = load_linear_cli()
    input_data: dict[str, object] = {}

    linear_cli.apply_due_date_input(input_data, "2026-07-14")

    assert input_data == {"dueDate": "2026-07-14"}


@pytest.mark.parametrize("clear_value", ["", "clear", "none", "null", " CLEAR "])
def test_apply_due_date_input_clears_date(clear_value: str) -> None:
    linear_cli = load_linear_cli()
    input_data = {"dueDate": "2026-07-14"}

    linear_cli.apply_due_date_input(input_data, clear_value)

    assert input_data == {"dueDate": None}


@pytest.mark.parametrize("invalid_value", ["2026-7-14", "14-07-2026", "next week"])
def test_apply_due_date_input_rejects_non_iso_dates(invalid_value: str) -> None:
    linear_cli = load_linear_cli()

    with pytest.raises(linear_cli.LinearError, match="--due-date must be YYYY-MM-DD"):
        linear_cli.apply_due_date_input({}, invalid_value)


def test_parser_accepts_due_date_on_create_and_update() -> None:
    linear_cli = load_linear_cli()
    parser = linear_cli.build_parser()

    create_args = parser.parse_args(["create", "--title", "Example", "--due-date", "2026-07-14"])
    update_args = parser.parse_args(["update", "OPE-575", "--due-date", "clear"])

    assert create_args.due_date == "2026-07-14"
    assert update_args.due_date == "clear"
