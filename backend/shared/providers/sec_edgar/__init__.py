"""SEC EDGAR provider exports.

The provider is intentionally skill-agnostic. App skills import these public
models and client methods while keeping all OpenMates-specific UX decisions in
their own app layer.
"""

from backend.shared.providers.sec_edgar.client import SECEdgarClient, normalize_company_financials
from backend.shared.providers.sec_edgar.models import (
    CompanyFinancialPeriod,
    CompanyFinancialResult,
    ResolvedCompany,
    SECCompanyNotFoundError,
    SECHttpError,
    SECProviderError,
)

__all__ = [
    "CompanyFinancialPeriod",
    "CompanyFinancialResult",
    "ResolvedCompany",
    "SECCompanyNotFoundError",
    "SECEdgarClient",
    "SECHttpError",
    "SECProviderError",
    "normalize_company_financials",
]
