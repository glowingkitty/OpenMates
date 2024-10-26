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
from server.api.models.apps.health.skills_health_search_appointments import (
    HealthSearchAppointmentsInput,
    HealthSearchAppointmentsOutput,
    Doctor,
    AvailableAppointment,
    Address
)

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
        logger.debug(f"Checking doctor {total_checked}: {doctor['name_with_title']}")

        next_slot = get_next_available_appointment(doctor)
        if next_slot:
            # Create structured address for the doctor
            doctor_address = Address(
                street=doctor.get('address', ''),
                city=doctor.get('city', ''),
                zip_code=doctor.get('zipcode', '')
            )

            appointment_info = {
                'address': doctor_address,
                'name': doctor.get('name_with_title', 'N/A'),
                'speciality': doctor.get('position', 'N/A'),
                'link': f"https://www.doctolib.de{doctor.get('profile_path', '')}",
                'next_slot': next_slot
            }

            logger.info(f"Found appointment for {doctor['name_with_title']} at {next_slot.strftime('%Y-%m-%d %H:%M')}")

            if from_date <= next_slot <= to_date:
                appointments.append(appointment_info)
        else:
            logger.debug(f"No appointments available for {doctor['name_with_title']}")

        time.sleep(random.uniform(1, 2))  # Random delay between doctors

    return appointments

def search_appointments(
    input: HealthSearchAppointmentsInput
) -> HealthSearchAppointmentsOutput:
    """
    Search for appointments for doctors within specified criteria.

    Args:
        input: HealthSearchAppointmentsInput model containing all search parameters

    Returns:
        HealthSearchAppointmentsOutput: Structured output containing found appointments
    """
    try:
        # Parse dates and set time ranges
        from_date = parse_date(input.from_date_str)
        to_date = parse_date(input.to_date_str) if input.to_date_str else from_date + timedelta(days=5)

        from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
        to_date = to_date.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Determine search city
        search_city = input.city if input.city else input.patient_address.city

        logger.info(f"Searching for appointments between {from_date.date()} and {to_date.date()}")
        logger.info(f"Searching in city: {search_city}")

        # Initialize variables
        page = 1
        total_checked = 0
        all_appointments = []

        # Fetch and process doctors page by page
        while total_checked < input.max_doctors_to_check:
            doctors = search_doctors(
                speciality=input.doctor_speciality,
                city=search_city,
                page=page
            )
            if not doctors:
                break

            appointments = process_doctor_appointments(
                doctors=doctors,
                from_date=from_date,
                to_date=to_date,
                total_checked=total_checked
            )
            all_appointments.extend(appointments)

            total_checked += len(doctors)
            if total_checked >= input.max_doctors_to_check:
                break

            page += 1
            time.sleep(random.uniform(3, 5))  # Random delay between pages

        # Process appointments with ratings and travel times
        formatted_appointments = []
        logger.info("Fetching ratings and travel times for appointments...")

        for appointment in all_appointments:
            rating = 0
            # Only fetch ratings if minimum_rating is set and greater than 0
            if input.minimum_rating and input.minimum_rating > 0:
                # Get place details and ratings
                place_details = get_place_details(
                    name=appointment['name'],
                    street=str(appointment['address'])  # Use Address.__str__ method
                )
                rating = place_details.get('rating', 0) if place_details else 0

                # Skip if rating is below minimum
                if rating < input.minimum_rating:
                    logger.debug(f"Skipping doctor {appointment['name']} due to low rating: {rating}")
                    continue

            # Calculate travel time if requested
            travel_time = 0
            if input.calculate_travel_time and input.patient_address:
                connections = get_connections(
                    origin=str(input.patient_address),  # Use Address.__str__ method
                    destination=str(appointment['address']),
                    departure_time=datetime.now()
                )

                travel_time = (
                    connections['connections'][0]['duration']['minutes']
                    if connections and connections['connections']
                    else float('inf')
                )

            # Create Doctor model
            doctor = Doctor(
                name=appointment['name'],
                speciality=input.doctor_speciality,
                address=appointment['address'],  # Already an Address model
                link=appointment['link'],
                rating=rating,
                travel_time_minutes=travel_time,
                travel_method=input.travel_method
            )

            # Create AvailableAppointment model
            available_appointment = AvailableAppointment(
                doctor=doctor,
                next_available_appointment=appointment['next_slot'].isoformat()
            )

            formatted_appointments.append(available_appointment)

        # Sort appointments by:
        # 1. earliest appointment date
        # 2. highest rating
        # 3. shortest travel time
        formatted_appointments.sort(
            key=lambda x: (
                datetime.fromisoformat(x.next_available_appointment),
                -x.doctor.rating,
                x.doctor.travel_time_minutes
            )
        )

        return HealthSearchAppointmentsOutput(
            appointments=formatted_appointments[:input.max_appointments_to_return]
        )

    except KeyboardInterrupt:
        logger.info("Search canceled by user.")
        return HealthSearchAppointmentsOutput(appointments=[])
    except Exception as e:
        logger.error(f"Error in search_appointments: {str(e)}")
        return HealthSearchAppointmentsOutput(appointments=[])
