import requests
import logging
from typing import List, Dict
from urllib.parse import quote
from server.api.models.apps.health.skills_health_search_doctors import (
    HealthSearchDoctorsInput,
    HealthSearchDoctorsOutput,
    Doctor
)
from server.api.models.apps.health.skills_health_search_appointments import Address

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NoDoctorsFoundError(Exception):
    """Custom exception for when no doctors are found"""
    pass

def search_doctors(
    input: HealthSearchDoctorsInput
) -> HealthSearchDoctorsOutput:
    """
    Search for doctors for given speciality and city

    Args:
        input (HealthSearchDoctorsInput): Input model containing search parameters

    Returns:
        HealthSearchDoctorsOutput: Output model containing list of doctors

    Raises:
        NoDoctorsFoundError: When no doctors are found for the given criteria
    """
    base_url = "https://www.doctolib.de"

    # Extract values from input model
    speciality_safe = quote(input.speciality.lower().replace(" ", "-"))
    city_safe = quote(input.city.lower())

    doctors_url = f"{base_url}/{speciality_safe}/{city_safe}.json"

    logger.debug(f"Constructed URL: {doctors_url}")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'de,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://www.doctolib.de/',
    }

    try:
        params = {
            'page': input.page,
            'limit': 20  # Maximum allowed per page
        }

        logger.debug(f"Fetching page {input.page} of doctors...")
        response = requests.get(doctors_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        raw_doctors = data.get('data', {}).get('doctors', [])
        logger.info(f"Found {len(raw_doctors)} doctors on page {input.page}")

        if input.page == 1 and not raw_doctors:
            logger.error(f"No doctors found for speciality '{input.speciality}' in {input.city}")
            raise NoDoctorsFoundError(f"No doctors found for speciality '{input.speciality}' in {input.city}")

        # Convert raw doctors data to Doctor models
        doctors = [Doctor(
            name=doctor.get('name_with_title'),
            speciality=doctor.get('speciality'),
            address=Address(
                street=doctor.get('address'),
                city=doctor.get('city'),
                zip_code=doctor.get('zip_code'),
                lat=doctor.get('position').get('lat') if doctor.get('position') else None,
                lng=doctor.get('position').get('lng') if doctor.get('position') else None,
            ),
            link=doctor.get('link'),
            doctor_id=doctor.get('id'),
            practice_id=doctor.get('practice_id'),
            speciality_id=doctor.get('speciality_id')
        ) for doctor in raw_doctors]
        return HealthSearchDoctorsOutput(doctors=doctors)

    except Exception as e:
        logger.error(f"Error searching for doctors: {str(e)}")
        if isinstance(e, NoDoctorsFoundError):
            raise
        return HealthSearchDoctorsOutput(doctors=[])
