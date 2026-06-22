#!/usr/bin/env python3
"""OpenMates Python SDK example: account, settings, and billing.

Run from the repository root or installed package environment:
  OPENMATES_API_KEY=sk-api-... PYTHONPATH=packages/openmates-python python3 packages/openmates-python/examples/settings_and_billing.py

This uses real API requests. It reads account/billing data and performs a safe
settings write by setting dark mode to its current value.
"""

from __future__ import annotations

import json
import os

from openmates import OpenMates


client = OpenMates(
    api_key=os.getenv("OPENMATES_API_KEY"),
    api_url=os.getenv("OPENMATES_API_URL", "https://api.openmates.org"),
)

account = client.account.info()
dark_mode_write = client.settings.set_dark_mode(bool(account.get("darkmode")))
billing = client.billing.overview()
invoices = client.billing.list_invoices()

print(json.dumps({
    "account": {
        "id": account.get("id"),
        "username": account.get("username"),
        "credits": account.get("credits"),
        "darkmode": bool(account.get("darkmode")),
    },
    "darkModeWrite": dark_mode_write,
    "billing": {
        "paymentTier": billing.get("payment_tier"),
        "autoTopupEnabled": billing.get("auto_topup_enabled"),
    },
    "invoiceCount": len(invoices.get("invoices", [])) if isinstance(invoices.get("invoices"), list) else 0,
}, indent=2))
