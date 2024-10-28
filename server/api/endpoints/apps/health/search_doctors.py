from server.api.models.apps.health.skills_health_search_doctors import HealthSearchDoctorsInput, HealthSearchDoctorsOutput
from server.api.endpoints.apps.health.providers.doctolib.search_doctors import search_doctors as search_doctors_doctolib


async def search_doctors(
        input: HealthSearchDoctorsInput
    ) -> HealthSearchDoctorsOutput:
    """
    Search for doctors
    """
    if input.provider.name == "doctolib":
        return await search_doctors_doctolib(input)
    else:
        raise ValueError(f"Provider {input.provider.name} not supported")
