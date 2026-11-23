"""Code execution is billed per second: ceil(seconds * rate), at least 1 credit once started."""

from decimal import Decimal

import pytest

from backend.shared.python_utils.catalog_unit_prices import skill_price
from backend.shared.python_utils.metered_author_billing import code_execution_credits, sandbox_run_credits

CODE_RUN_RATE = skill_price("code", "run", "per_second")


# contract-test: direct surface=rest_api assertions=code-run.billing.rate-limits
def test_code_run_catalog_rate_is_three_credits_per_minute_per_second() -> None:
    assert CODE_RUN_RATE == Decimal("0.05")


@pytest.mark.parametrize(
    ("seconds", "credits"),
    [
        (0, 0),  # never started
        (-1.0, 0),
        (0.3, 1),  # sub-second run still costs the 1-credit minimum
        (59, 3),
        (60, 3),
        (61, 4),  # ceil(3.05)
        (3600, 180),  # exact arithmetic, no float drift to 181
    ],
)
# contract-test: direct surface=rest_api assertions=code-run.billing.rate-limits
def test_code_execution_credits(seconds: float, credits: int) -> None:
    assert code_execution_credits(seconds, CODE_RUN_RATE) == credits


# contract-test: direct surface=rest_api assertions=code-run.billing.rate-limits
def test_sandbox_run_credits_uses_per_minute_rate_per_second() -> None:
    assert sandbox_run_credits(0.3, credits_per_started_minute=3) == 1
    assert sandbox_run_credits(61, credits_per_started_minute=3) == 4
    assert sandbox_run_credits(3600, credits_per_started_minute=3) == 180
    assert sandbox_run_credits(0, credits_per_started_minute=3) == 0
