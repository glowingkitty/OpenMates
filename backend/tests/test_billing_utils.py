# backend/tests/test_billing_utils.py
#
# Regression tests for shared credit calculation helpers.
# These helpers are used by chat skill billing and REST skill billing.
# App metadata schemas allow compact numeric pricing shorthands in app.yml.
# The billing layer must normalize those shorthands instead of failing at runtime.

from backend.shared.python_utils.billing_utils import calculate_total_credits


def test_calculate_total_credits_accepts_numeric_fixed_pricing() -> None:
    assert calculate_total_credits(pricing_config={"fixed": 1}) == 1


def test_calculate_total_credits_accepts_numeric_per_minute_pricing() -> None:
    assert calculate_total_credits(
        pricing_config={"per_minute": 3},
        duration_minutes=2,
    ) == 6
