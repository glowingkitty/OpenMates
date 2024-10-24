import requests
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict
import json
import time
import random
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_date(date_str: str = None) -> datetime:
    """
    Parse date string in YYYY-MM-DD format to timezone-aware datetime object
    
    Args:
        date_str (str, optional): Date string in YYYY-MM-DD format
        
    Returns:
        datetime: Parsed datetime object with time set to 00:00:00 UTC
    """
    try:
        if date_str:
            # Parse the date and make it timezone-aware (UTC)
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            dt = datetime.now()
        
        # Make timezone-aware if it isn't already
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as e:
        logger.error(f"Invalid date format. Please use YYYY-MM-DD. Error: {str(e)}")
        raise ValueError("Invalid date format. Please use YYYY-MM-DD")

def get_doctors_list(page: int = 1) -> List[Dict]:
    """
    Fetch a single page of HNO doctors in Berlin
    
    Args:
        page (int): Page number to fetch
        
    Returns:
        List[Dict]: List of doctors from the requested page
    """
    base_url = "https://www.doctolib.de"
    doctors_url = f"{base_url}/facharzt-fur-hno/berlin.json"

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

        logger.info(f"Fetching page {page} of doctors...")
        response = requests.get(doctors_url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        doctors = data.get('data', {}).get('doctors', [])
        logger.info(f"Found {len(doctors)} doctors on page {page}")
        return doctors

    except Exception as e:
        logger.error(f"Error fetching doctors list: {str(e)}")
        return []

def get_next_available_slot(doctor: Dict, from_date: datetime, to_date: datetime) -> Dict:
    """
    Fetch the next available slot for a specific doctor.
    
    This function retrieves the next available appointment slot for the given doctor,
    regardless of whether it falls within the specified date range.

    Args:
        doctor (Dict): Doctor information dictionary
        from_date (datetime): Start date for appointment search
        to_date (datetime): End date for appointment search

    Returns:
        Dict: Appointment information if found, None otherwise
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
            slot_date = datetime.fromisoformat(next_slot.replace('Z', '+00:00'))

            # Ensure from_date and to_date are timezone-aware
            if from_date.tzinfo is None:
                from_date = from_date.replace(tzinfo=timezone.utc)
            if to_date.tzinfo is None:
                to_date = to_date.replace(tzinfo=timezone.utc)

            return {
                'address': doctor.get('address', 'N/A'),
                'city': doctor.get('city', 'N/A'),
                'zipcode': doctor.get('zipcode', 'N/A'),
                'profile_path': doctor.get('profile_path', 'N/A'),
                'name_with_title': doctor.get('name_with_title', 'N/A'),
                'position': doctor.get('position', 'N/A'),
                'next_slot': slot_date
            }
        return None
    except Exception as e:
        logger.error(f"Error fetching slots for doctor {doctor['name_with_title']}: {str(e)}")
        return None

def main(from_date_str: str = None, to_date_str: str = None):
    """
    Main function to find the first available appointment within a date range

    Args:
        from_date_str (str, optional): Start date for appointment search (YYYY-MM-DD)
        to_date_str (str, optional): End date for appointment search (YYYY-MM-DD)
    """
    try:
        # Convert string dates to timezone-aware datetime objects
        from_date = parse_date(from_date_str)

        # If to_date not provided, set to 5 days from from_date
        if not to_date_str:
            to_date = from_date + timedelta(days=5)
        else:
            to_date = parse_date(to_date_str)

        # Set time to start of day for from_date and end of day for to_date
        from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
        to_date = to_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        logger.info(f"Searching for appointments between {from_date.date()} and {to_date.date()}")

        page = 1
        closest_appointments = []
        total_checked = 0
        max_doctors = 100  # Limit to the first 100 doctors

        while total_checked < max_doctors:
            try:
                doctors = get_doctors_list(page)
                if not doctors:
                    break

                # Random delay between pages to prevent rate limiting
                time.sleep(random.uniform(3, 5))

                for i, doctor in enumerate(doctors, 1):
                    total_checked += 1
                    if total_checked > max_doctors:
                        break

                    # Create initial status line
                    status_line = f"\rChecking doctor {total_checked}: {doctor['name_with_title']:<50}"
                    sys.stdout.write(status_line)
                    sys.stdout.flush()

                    appointment_info = get_next_available_slot(doctor, from_date, to_date)

                    if appointment_info:
                        slot_date = appointment_info['next_slot']

                        # Update status line with success and date
                        status_line += f" ✓ (next appointment: {slot_date.strftime('%Y-%m-%d %H:%M')})"
                        sys.stdout.write(status_line + "\n")
                        sys.stdout.flush()

                        # Check if this slot is within the desired date range
                        if from_date <= slot_date <= to_date:
                            logger.info("\nFound matching appointment!")
                            logger.info(f"Doctor: {appointment_info['name_with_title']}")
                            logger.info(f"Next available: {slot_date.strftime('%Y-%m-%d %H:%M')}")
                            logger.info(f"Profile: https://www.doctolib.de{appointment_info['profile_path']}")
                            return appointment_info
                        else:
                            # Add to closest appointments list
                            closest_appointments.append(appointment_info)
                            # Sort and keep only top 3 closest appointments
                            closest_appointments.sort(key=lambda x: abs((x['next_slot'] - from_date).days))
                            closest_appointments = closest_appointments[:3]
                    else:
                        # Update status line with failure
                        status_line += " ✗ (no appointments available)"
                        sys.stdout.write(status_line + "\n")
                        sys.stdout.flush()

                page += 1
                time.sleep(random.uniform(1, 2))

            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {str(e)}")
                break

        # Final summary if no appointments found within range
        sys.stdout.write("\n")
        logger.info("No appointments found within the specified date range")

        if closest_appointments:
            logger.info("\nTop 3 closest available appointments found:")
            for appointment in closest_appointments:
                logger.info(f"Doctor: {appointment['name_with_title']}")
                logger.info(f"Date: {appointment['next_slot'].strftime('%Y-%m-%d %H:%M')}")
                logger.info(f"Profile: https://www.doctolib.de{appointment['profile_path']}")

        return closest_appointments

    except ValueError as e:
        logger.error(f"Date parsing error: {str(e)}")
        return None
    except KeyboardInterrupt:
        logger.info("Search canceled by user.")
        if closest_appointments:
            logger.info("\nTop 3 closest available appointments found before cancellation:")
            for appointment in closest_appointments:
                logger.info(f"Doctor: {appointment['name_with_title']}")
                logger.info(f"Date: {appointment['next_slot'].strftime('%Y-%m-%d %H:%M')}")
                logger.info(f"Profile: https://www.doctolib.de{appointment['profile_path']}")
        return None

if __name__ == "__main__":
    # Example usage with date strings
    # main(from_date_str="2024-10-20", to_date_str="2024-03-25")
    # Or use defaults (today to 5 days from today)
    main()
