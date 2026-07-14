"""Payment environment predicates.

Payment routes import heavy provider SDKs, so small environment decisions live
here where focused guardrail tests can run without Stripe or Docker services.
The EU threshold predicate keeps legacy revenue-limit protection production-only
while allowing dev/test Stripe test-mode purchases for automated coverage.
"""

from __future__ import annotations

import os


def should_enforce_eu_revenue_threshold(is_eu: bool) -> bool:
    return is_eu and os.getenv("SERVER_ENVIRONMENT", "development") == "production"
