"""
Geo Utilities

Helper functions for geographic detection, used for payment provider routing.

Two distinct country sets:

1. EU_VAT_COUNTRY_CODES (EU27 only)
   Used for payment flow selection:
   - EU27 → regular Stripe (PaymentIntents + Elements, no VAT collected under
     the Kleinunternehmer / EU VAT OSS 10k EUR cross-border exemption)
   - Everyone else (incl. CH, NO, GB, US…) → Stripe Managed Payments
     (Checkout Sessions, Stripe collects + remits VAT automatically)

2. EU_STRIPE_COUNTRY_CODES (EU27 + EEA + CH + GB) — kept for legacy callers
   that relied on the old Polar vs Stripe routing. Not used by the payment
   flow since Polar was deactivated on 2026-04-23.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# EU27 member states only — the VAT-territory boundary for the EU OSS scheme.
# Switzerland, Norway, Iceland, Liechtenstein, and the UK are NOT in the EU
# VAT territory and therefore go through Managed Payments.
EU_VAT_COUNTRY_CODES = frozenset({
    "AT",  # Austria
    "BE",  # Belgium
    "BG",  # Bulgaria
    "CY",  # Cyprus
    "CZ",  # Czech Republic
    "DE",  # Germany
    "DK",  # Denmark
    "EE",  # Estonia
    "ES",  # Spain
    "FI",  # Finland
    "FR",  # France
    "GR",  # Greece
    "HR",  # Croatia
    "HU",  # Hungary
    "IE",  # Ireland
    "IT",  # Italy
    "LT",  # Lithuania
    "LU",  # Luxembourg
    "LV",  # Latvia
    "MT",  # Malta
    "NL",  # Netherlands
    "PL",  # Poland
    "PT",  # Portugal
    "RO",  # Romania
    "SE",  # Sweden
    "SI",  # Slovenia
    "SK",  # Slovakia
})

# Legacy set — EU27 + EEA + CH + GB.
# Previously used for Polar vs Stripe routing (Polar deactivated 2026-04-23).
# Kept so existing callers of is_eu_stripe_country() don't break.
EU_STRIPE_COUNTRY_CODES = EU_VAT_COUNTRY_CODES | frozenset({
    "NO",  # Norway (EEA)
    "IS",  # Iceland (EEA)
    "LI",  # Liechtenstein (EEA)
    "CH",  # Switzerland (SEPA zone)
    "GB",  # United Kingdom (post-Brexit)
})


def is_eu_vat_country(country_code: Optional[str]) -> bool:
    """
    Returns True if the country is in the EU VAT territory (EU27 only).

    EU27 users pay via regular Stripe (no VAT collected while under the
    EU OSS cross-border threshold). All other countries — including CH,
    NO, IS, LI, GB, and the rest of the world — use Stripe Managed
    Payments, which handles local VAT collection and remittance automatically.

    Args:
        country_code: ISO 3166-1 alpha-2 country code (e.g. "DE", "US")

    Returns:
        True for EU27; False for everything else (including unknown/local IPs,
        which default to EU for safety in development environments).
    """
    if not country_code or country_code == "Local":
        # Unknown or private/Docker IP — default to EU (regular Stripe) so
        # development environments don't accidentally trigger Managed Payments.
        logger.debug("No country code or local/private IP — defaulting to EU (regular Stripe)")
        return True

    result = country_code.upper() in EU_VAT_COUNTRY_CODES
    logger.debug(
        f"Payment routing for '{country_code.upper()}': "
        f"{'EU (regular Stripe)' if result else 'non-EU (Managed Payments)'}"
    )
    return result


def is_eu_stripe_country(country_code: Optional[str]) -> bool:
    """
    Legacy function — returns True for EU27 + EEA + CH + GB.
    Use is_eu_vat_country() for payment flow decisions.
    """
    if not country_code or country_code == "Local":
        logger.debug("No country code or local/private IP — defaulting to Stripe (EU)")
        return True

    result = country_code.upper() in EU_STRIPE_COUNTRY_CODES
    logger.debug(f"Provider routing for country '{country_code.upper()}': {'Stripe (EU)' if result else 'Polar (non-EU)'}")
    return result
