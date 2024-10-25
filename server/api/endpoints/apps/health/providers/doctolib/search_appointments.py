import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import sys
import time
import random

from server.api.endpoints.apps.maps.providers.google_maps.search_place import get_place_details
from server.api.endpoints.apps.travel.providers.google_maps.search_connections import get_connections
from server.api.endpoints.apps.health.providers.doctolib.search_doctors import search_doctors
from server.api.endpoints.apps.health.providers.doctolib.get_next_available_appointment import get_next_available_appointment

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
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            dt = datetime.now()

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError as e:
        logger.error(f"Invalid date format. Please use YYYY-MM-DD. Error: {str(e)}")
        raise ValueError("Invalid date format. Please use YYYY-MM-DD")

def process_doctor_appointments(
    doctors: List[Dict],
    from_date: datetime,
    to_date: datetime,
    total_checked: int
    ) -> List[Dict]:
    """
    Process a list of doctors and get their next available appointments

    Args:
        doctors (List[Dict]): List of doctors to process
        from_date (datetime): Start date for appointment search
        to_date (datetime): End date for appointment search
        total_checked (int): Counter for total doctors checked

    Returns:
        List[Dict]: List of appointments found
    """
    appointments = []

    for doctor in doctors:
        total_checked += 1
        status_line = f"\rChecking doctor {total_checked}: {doctor['name_with_title']:<50}"
        sys.stdout.write(status_line)
        sys.stdout.flush()

        next_slot = get_next_available_appointment(doctor)
        if next_slot:
            appointment_info = {
                'address': doctor.get('address', 'N/A'),
                'city': doctor.get('city', 'N/A'),
                'zipcode': doctor.get('zipcode', 'N/A'),
                'profile_path': doctor.get('profile_path', 'N/A'),
                'name_with_title': doctor.get('name_with_title', 'N/A'),
                'position': doctor.get('position', 'N/A'),
                'next_slot': next_slot
            }

            status_line += f" ✓ (next appointment: {next_slot.strftime('%Y-%m-%d %H:%M')})"
            sys.stdout.write(status_line + "\n")
            sys.stdout.flush()

            if from_date <= next_slot <= to_date:
                appointments.append(appointment_info)
        else:
            status_line += " ✗ (no appointments available)"
            sys.stdout.write(status_line + "\n")
            sys.stdout.flush()

        time.sleep(random.uniform(1, 2))  # Random delay between doctors

    return appointments

def search_appointments(
    patient_address: str,
    doctor_speciality: str,
    doctor_city: str,
    from_date_str: Optional[str] = None,
    to_date_str: Optional[str] = None,
    max_doctors: int = 100
) -> List[Dict]:
    """
    Search for appointments for doctors within specified criteria.

    Args:
        patient_address (str): Patient's address for travel time calculation
        doctor_speciality (str): Medical speciality to search for
        doctor_city (str): City to search in
        from_date_str (str, optional): Start date in YYYY-MM-DD format
        to_date_str (str, optional): End date in YYYY-MM-DD format
        max_doctors (int): Maximum number of doctors to check

    Returns:
        List[Dict]: List of appointments sorted by rating and travel time
    """
    try:
        # Parse dates and set time ranges
        from_date = parse_date(from_date_str)
        to_date = parse_date(to_date_str) if to_date_str else from_date + timedelta(days=5)

        from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
        to_date = to_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        logger.info(f"Searching for appointments between {from_date.date()} and {to_date.date()}")

        # Initialize variables
        page = 1
        total_checked = 0
        all_appointments = []

        # Fetch and process doctors page by page
        while total_checked < max_doctors:
            doctors = search_doctors(speciality=doctor_speciality, city=doctor_city, page=page)
            if not doctors:
                break

            appointments = process_doctor_appointments(doctors=doctors, from_date=from_date, to_date=to_date, total_checked=total_checked)
            all_appointments.extend(appointments)

            total_checked += len(doctors)
            if total_checked >= max_doctors:
                break

            page += 1
            time.sleep(random.uniform(3, 5))  # Random delay between pages

        # Process appointments with ratings and travel times
        logger.info("\nFetching ratings and travel times for appointments...")
        for appointment in all_appointments:
            # Get place details and ratings
            place_details = get_place_details(
                name=appointment['name_with_title'],
                street=appointment.get('address', ''),
                city=appointment.get('city', ''),
                zip_code=appointment.get('zipcode', '')
            )

            if place_details:
                appointment['rating'] = place_details.get('rating', 0)
                appointment['user_ratings_total'] = place_details.get('user_ratings_total', 0)
            else:
                appointment['rating'] = 0
                appointment['user_ratings_total'] = 0

            # Calculate travel time
            connections = get_connections(
                origin=patient_address,
                destination=f"{appointment.get('address', '')}, {appointment.get('zipcode', '')} {appointment.get('city', '')}",
                departure_time=datetime.now()
            )

            if connections and connections['connections']:
                appointment['travel_time_minutes'] = connections['connections'][0]['duration']['minutes']
            else:
                appointment['travel_time_minutes'] = float('inf')

        # Filter and sort appointments
        rated_appointments = [
            apt for apt in all_appointments
            if apt.get('rating', 0) >= 3.5 and apt.get('user_ratings_total', 0) > 0
        ]

        rated_appointments.sort(key=lambda x: x.get('travel_time_minutes', float('inf')))
        return rated_appointments[:10]  # Return top 10 appointments

    except KeyboardInterrupt:
        logger.info("\nSearch canceled by user.")
        return []
    except Exception as e:
        logger.error(f"Error in search_appointments: {str(e)}")
        return []
