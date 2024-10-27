import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import sys
import time
import random

from server.api.endpoints.apps.maps.providers.google_maps.search_places import search_places
from server.api.endpoints.apps.travel.providers.google_maps.search_connections import search_connections
from server.api.endpoints.apps.health.providers.doctolib.search_doctors import search_doctors
from server.api.endpoints.apps.health.providers.doctolib.get_next_available_appointment import get_next_available_appointment
from server.api.models.apps.maps.skills_maps_search import MapsSearchInput
from server.api.models.apps.travel.skills_travel_search_connections import TravelSearchConnectionsInput
from server.api.models.apps.health.skills_health_search_appointments import (
    HealthSearchAppointmentsInput,
    HealthSearchAppointmentsOutput,
    Doctor,
    AvailableAppointment
)
from server.api.models.apps.health.skills_health_search_doctors import HealthSearchDoctorsInput

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

async def process_doctor_appointments(
    doctors: List[Doctor],
    from_date: datetime,
    to_date: datetime,
    total_checked: int
) -> List[AvailableAppointment]:
    """
    Process a list of doctors and get their next available appointments

    Args:
        doctors (List[Doctor]): List of doctors to process
        from_date (datetime): Start date for appointment search
        to_date (datetime): End date for appointment search
        total_checked (int): Counter for total doctors checked

    Returns:
        List[AvailableAppointment]: List of available appointments with doctor details
    """
    appointments = []

    for doctor in doctors:
        total_checked += 1
        logger.debug(f"Checking doctor {total_checked}: {doctor.name}")

        next_slot = get_next_available_appointment(doctor)
        if next_slot and from_date <= next_slot <= to_date:
            # Create AvailableAppointment directly
            appointment = AvailableAppointment(
                doctor=doctor,
                next_available_appointment=next_slot.isoformat(),
                doctor_id=doctor.doctor_id,
                practice_id=doctor.practice_id,
                speciality_id=doctor.speciality_id
            )
            appointments.append(appointment)
            logger.info(f"Found appointment for {doctor.name} at {next_slot.strftime('%Y-%m-%d %H:%M')}")
        else:
            logger.debug(f"No appointments available for {doctor.name}")

        time.sleep(random.uniform(1, 2))

    return appointments

async def search_appointments(
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
        all_appointments: List[AvailableAppointment] = []

        # Fetch and process doctors page by page
        while total_checked < input.max_doctors_to_check:
            # Now using the new search_doctors function that returns Doctor models
            search_result = search_doctors(
                HealthSearchDoctorsInput(
                    speciality=input.doctor_speciality,
                    city=search_city,
                    page=page
                )
            )

            if not search_result.doctors:
                break

            appointments = await process_doctor_appointments(
                doctors=search_result.doctors,
                from_date=from_date,
                to_date=to_date,
                total_checked=total_checked
            )
            all_appointments.extend(appointments)

            total_checked += len(search_result.doctors)
            if total_checked >= input.max_doctors_to_check:
                break

            page += 1
            time.sleep(random.uniform(3, 5))  # Random delay between pages

        # Process appointments with ratings and travel times
        logger.info("Updating appointments with ratings and travel times...")

        for appointment in all_appointments:
            # Only fetch ratings if minimum_rating is set and greater than 0
            if input.minimum_rating and input.minimum_rating > 0:
                logger.debug(f"Fetching ratings for {appointment.doctor.name}")
                places = await search_places(
                    input=MapsSearchInput(
                        query=appointment.doctor.name + " " + str(appointment.doctor.address)
                    )
                )
                place_details = places.results[0] if places.results else None
                appointment.doctor.rating = place_details.get('rating', 0) if place_details else 0

                # Skip if rating is below minimum
                if appointment.doctor.rating < input.minimum_rating:
                    logger.debug(f"Skipping doctor {appointment.doctor.name} due to low rating: {appointment.doctor.rating}")
                    continue

            # Calculate travel time if requested
            if input.calculate_travel_time and input.patient_address:
                logger.debug(f"Calculating travel time for {appointment.doctor.name}")
                connections = search_connections(
                    input=TravelSearchConnectionsInput(
                        origin=str(input.patient_address),
                        destination=str(appointment.doctor.address),
                        departure_time=datetime.now().isoformat()
                    )
                )

                appointment.doctor.travel_time_minutes = (
                    connections['connections'][0]['duration']['minutes']
                    if connections and connections['connections']
                    else float('inf')
                )
                appointment.doctor.travel_method = input.travel_method

        # Sort appointments
        all_appointments.sort(
            key=lambda x: (
                datetime.fromisoformat(x.next_available_appointment),
                -(x.doctor.rating or 0),
                x.doctor.travel_time_minutes or float('inf')
            )
        )

        return HealthSearchAppointmentsOutput(
            appointments=all_appointments[:input.max_appointments_to_return]
        )

    except KeyboardInterrupt:
        logger.info("Search canceled by user.")
        return HealthSearchAppointmentsOutput(appointments=[])
    except Exception as e:
        logger.error(f"Error in search_appointments: {str(e)}")
        return HealthSearchAppointmentsOutput(appointments=[])
