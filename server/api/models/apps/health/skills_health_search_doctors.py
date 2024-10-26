from pydantic import BaseModel, Field
from typing import List, Dict
from server.api.models.apps.health.skills_health_search_appointments import Doctor

class HealthSearchDoctorsInput(BaseModel):
    """
    Input model for searching for doctors
    """
    speciality: str = Field(..., description="The speciality of the doctor")
    city: str = Field(..., description="The city where to search for doctors")
    page: int = Field(1, description="The page number to fetch")

health_search_doctors_input_example = {
    "speciality": "Facharzt für HNO",
    "city": "München",
    "page": 1
}

class HealthSearchDoctorsOutput(BaseModel):
    """
    Output model for searching for doctors
    """
    doctors: List[Doctor] = Field(..., description="The list of doctors found")

health_search_doctors_output_example = {
    "doctors": [
        {
            "name": "Dr. Müller",
            "speciality": "Kardiologe",
            "address": {
                "street": "Friedrichstraße 123",
                "city": "Berlin",
                "zip_code": "10117"
            },
            "link": "https://www.doctolib.de/kardiologe/berlin/dr-mueller",
            "doctor_id": "1234567890",
            "practice_id": "1234567891",
            "speciality_id": "1234567892"
        }
    ]
}
