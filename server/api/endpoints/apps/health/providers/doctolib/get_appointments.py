import requests
import logging
from datetime import datetime
from typing import List, Dict
import json
import time
import random

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_doctors_list() -> List[Dict]:
    """Fetch the list of HNO doctors in Berlin with pagination support"""
    base_url = "https://www.doctolib.de"
    doctors_url = f"{base_url}/facharzt-fur-hno/berlin.json"  # Note the .json extension added

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Accept-Language': 'de,en-US;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://www.doctolib.de/',
    }

    all_doctors = []
    page = 1

    try:
        while len(all_doctors) < 50:  # Continue until we have at least 50 doctors
            params = {
                'page': page,
                'limit': 20  # Maximum allowed per page
            }

            logger.info(f"Fetching page {page} of doctors...")
            response = requests.get(doctors_url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            doctors_on_page = data.get('data', {}).get('doctors', [])
            if not doctors_on_page:  # No more doctors available
                break

            all_doctors.extend(doctors_on_page)
            page += 1

            # Add a small delay between pagination requests
            time.sleep(random.uniform(1, 2))

        logger.info(f"Total doctors fetched: {len(all_doctors)}")
        return all_doctors[:50]  # Return only the first 50 doctors

    except Exception as e:
        logger.error(f"Error fetching doctors list: {str(e)}")
        return []

def get_next_available_slot(doctor: Dict) -> tuple:
    """
    Fetch the next available slot for a specific doctor
    Includes random delay to simulate human behavior
    """
    # Add random delay between 1 and 3 seconds
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
            return (
                datetime.fromisoformat(next_slot.replace('Z', '+00:00')),
                doctor['profile_path'],
                doctor['name_with_title']
            )
        return None
    except Exception as e:
        logger.error(f"Error fetching slots for doctor {doctor['name_with_title']}: {str(e)}")
        return None

def main():
    # Get all doctors
    logger.info("Fetching list of doctors...")
    doctors = get_doctors_list()
    logger.info(f"Found {len(doctors)} doctors")

    # Add initial random delay before starting individual requests
    initial_delay = random.uniform(2, 4)
    logger.debug(f"Initial waiting period: {initial_delay:.2f} seconds")
    time.sleep(initial_delay)

    # Get available slots for each doctor
    available_slots = []
    for i, doctor in enumerate(doctors, 1):
        logger.info(f"Checking availability for {doctor['name_with_title']} ({i}/{len(doctors)})")
        slot_info = get_next_available_slot(doctor)
        if slot_info:
            available_slots.append(slot_info)

    # Sort by date and get top 5
    available_slots.sort(key=lambda x: x[0])
    top_5 = available_slots[:5]

    # Print results
    logger.info("\nTop 5 earliest available appointments:")
    for date, profile_path, doctor_name in top_5:
        logger.info(f"Doctor: {doctor_name}")
        logger.info(f"Next available: {date.strftime('%Y-%m-%d %H:%M')}")
        logger.info(f"Profile: https://www.doctolib.de{profile_path}")
        logger.info("---")

if __name__ == "__main__":
    main()
