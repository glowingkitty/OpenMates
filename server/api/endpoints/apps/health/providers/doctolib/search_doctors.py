import requests
import logging
from typing import List, Dict
from urllib.parse import quote

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NoDoctorsFoundError(Exception):
    """Custom exception for when no doctors are found"""
    pass

def search_doctors(speciality: str, city: str, page: int = 1) -> List[Dict]:
    """
    Search for doctors for given speciality and city

    Args:
        page (int): Page number to fetch
        speciality (str): Medical speciality (e.g., "Facharzt für HNO")
        city (str): City name (e.g., "München")

    Returns:
        List[Dict]: List of doctors from the requested page

    Raises:
        NoDoctorsFoundError: When no doctors are found for the given criteria
    """
    base_url = "https://www.doctolib.de"

    # Convert to lowercase and URL encode the parameters
    speciality_safe = quote(speciality.lower().replace(" ", "-"))
    city_safe = quote(city.lower())

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
            'page': page,
            'limit': 20  # Maximum allowed per page
        }

        logger.debug(f"Fetching page {page} of doctors...")
        response = requests.get(doctors_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        doctors = data.get('data', {}).get('doctors', [])
        logger.info(f"Found {len(doctors)} doctors on page {page}")

        if page == 1 and not doctors:
            logger.error(f"No doctors found for speciality '{speciality}' in {city}")
            raise NoDoctorsFoundError(f"No doctors found for speciality '{speciality}' in {city}")

        return doctors

    except Exception as e:
        logger.error(f"Error searching for doctors: {str(e)}")
        if isinstance(e, NoDoctorsFoundError):
            raise
        return []
