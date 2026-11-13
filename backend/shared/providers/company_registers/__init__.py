"""Official company register providers (DE OpenRegister, GB Companies House, FR Recherche d'entreprises).

Each client exposes ``lookup(query, subject=..., include=[...])`` and returns the
normalized ownership record from ``models.ownership_record`` with private
personal data removed.
"""

from backend.shared.providers.company_registers.companies_house import CompaniesHouseClient
from backend.shared.providers.company_registers.http import provider_api_key
from backend.shared.providers.company_registers.models import RegisterProviderError
from backend.shared.providers.company_registers.openregister import OpenRegisterClient
from backend.shared.providers.company_registers.recherche_entreprises import RechercheEntreprisesClient

__all__ = [
    "CompaniesHouseClient",
    "OpenRegisterClient",
    "RechercheEntreprisesClient",
    "RegisterProviderError",
    "provider_api_key",
]
