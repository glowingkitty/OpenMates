from server.api.models.apps.health.skills_health_search_appointments import HealthSearchAppointmentsInput, HealthSearchAppointmentsOutput
from server.api.endpoints.apps.health.providers.doctolib.search_appointments import search_appointments as search_appointments_doctolib


async def search_appointments(
        input: HealthSearchAppointmentsInput
    ) -> HealthSearchAppointmentsOutput:
    """
    Search for appointments
    """
    if input.provider.name == "doctolib":
        return await search_appointments_doctolib(input)
