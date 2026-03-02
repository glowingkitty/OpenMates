"""
Geo Utilities

Helper functions for geographic detection, primarily used for
payment provider routing (Polar for non-EU, Stripe for EU users).

EU is defined here as EU member states + EEA (Norway, Iceland, Liechtenstein)
+ Switzerland (SEPA zone) + UK (Stripe handles GBP well, similar regulatory
environment post-Brexit). This group defaults to Stripe for payment processing.
All other countries default to Polar as the Merchant of Record.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# All country codes that should default to Stripe (EU + EEA + CH + GB).
# These regions share similar regulatory environments, use EUR/GBP/CHF which
# Stripe handles natively, and where Kleinunternehmer VAT exemption is straightforward.
# All other countries → Polar (handles global tax compliance as MoR).
EU_STRIPE_COUNTRY_CODES = frozenset({
    # European Union member states
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
    # EEA (non-EU but in European Economic Area)
    "NO",  # Norway
    "IS",  # Iceland
    "LI",  # Liechtenstein
    # SEPA zone / close regulatory environment
    "CH",  # Switzerland
    "GB",  # United Kingdom (post-Brexit — Stripe handles GBP natively)
})


def is_eu_stripe_country(country_code: Optional[str]) -> bool:
    """
    Returns True if the country should use Stripe (EU/EEA/CH/GB region).
    Returns False for all other countries, which should default to Polar.

    Args:
        country_code: ISO 3166-1 alpha-2 country code (e.g. "DE", "US")

    Returns:
        True if Stripe should be the default provider, False if Polar should be default
    """
    if not country_code:
        # Unknown country — default to Polar (handles global tax compliance)
        logger.debug("No country code provided for provider detection, defaulting to Polar")
        return False

    result = country_code.upper() in EU_STRIPE_COUNTRY_CODES
    logger.debug(f"Provider routing for country '{country_code.upper()}': {'Stripe (EU)' if result else 'Polar (non-EU)'}")
    return result
