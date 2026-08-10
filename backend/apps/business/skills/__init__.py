"""Business app skills.

The Business app exposes public-company research capabilities that are distinct
from personal finance or investment advice. Skills stay read-only unless a
future spec explicitly adds workflow-safe write behavior.
"""

from backend.apps.business.skills.company_financials import CompanyFinancialsSkill

__all__ = ["CompanyFinancialsSkill"]
