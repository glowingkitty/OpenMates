import requests
import logging
from datetime import datetime, timezone
import time
import random

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_next_available_appointment(doctor: dict) -> datetime:
    """
    Fetch the next available appointment datetime for a specific doctor.

    Args:
        doctor (dict): Doctor information dictionary containing id and speciality_id

    Returns:
        datetime: Next available appointment datetime if found, None otherwise
    """
    # Add random delay between 1 and 3 seconds to avoid rate limiting
    delay = random.uniform(1, 3)
    time.sleep(delay)
    logger.debug(f"Waiting for {delay:.2f} seconds before requesting data for {doctor['name_with_title']}")

    url = f"https://www.doctolib.de/search_results/{doctor['id']}.json"
    params = {
        'speciality_id': doctor['speciality_id'],
        'limit': 6,
        'search_result_rank': 1
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'de,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://www.doctolib.de/',
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        next_slot = data.get('next_slot')
        if next_slot:
            # Parse the ISO format datetime and ensure it's timezone-aware
            return datetime.fromisoformat(next_slot.replace('Z', '+00:00'))
        return None
    except Exception as e:
        logger.error(f"Error fetching slots for doctor {doctor['name_with_title']}: {str(e)}")
        return None
