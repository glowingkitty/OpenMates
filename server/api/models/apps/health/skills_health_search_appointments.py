from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Literal
from datetime import datetime


class HealthSearchAppointmentsInput(BaseModel):
    databases: List[Literal["doctolib"]] = Field(["doctolib"], description="The databases to search for appointments in")
    doctor_speciality: str = Field(..., description="The speciality of the doctor")
    from_date_str: Optional[str] = Field(None, description="The start date of the search in YYYY-MM-DD format")
    to_date_str: Optional[str] = Field(None, description="The end date of the search in YYYY-MM-DD format")
    patient_insurance: Literal["public", "private"] = Field("public", description="Whether the patient has public or private insurance")
    patient_address: Optional[str] = Field(None, description="The address of the patient")
    city: Optional[str] = Field(None, description="The city where to search for available appointments")
    travel_method: Optional[Literal["car", "public_transport"]] = Field("public_transport", description="The method of travel for calculating the travel time")
    minimum_rating: float = Field(0, description="The minimum rating of the doctor. If set to 0, ratings will not be checked.")
    calculate_travel_time: bool = Field(True, description="Whether to calculate the travel time")
    max_doctors_to_check: int = Field(100, description="The maximum number of doctors to check, before returning results.")
    max_appointments_to_return: int = Field(5, description="The maximum number of appointments to return.")

    # check that from_date_str and to_date_str are valid dates
    @model_validator(mode="after")
    def check_dates(cls, values):
        # Get date strings from values
        from_date = values.get('from_date_str')
        to_date = values.get('to_date_str')

        # Validate date formats if provided
        for date_str in (from_date, to_date):
            if date_str:
                try:
                    datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    raise ValueError("Invalid date format. Please use YYYY-MM-DD format.")

        # If both dates are provided, check that from_date is before to_date
        if from_date and to_date:
            from_date_obj = datetime.strptime(from_date, "%Y-%m-%d")
            to_date_obj = datetime.strptime(to_date, "%Y-%m-%d")
            if from_date_obj > to_date_obj:
                raise ValueError("from_date must be before or equal to to_date")

        return values

    # make sure the minimum_rating is between 0 and 5
    @model_validator(mode="after")
    def check_minimum_rating(cls, values):
        minimum_rating = values.get('minimum_rating')
        if minimum_rating < 0 or minimum_rating > 5:
            raise ValueError("minimum_rating must be between 0 and 5")
        return values

    # make sure max_doctors_to_check is max 500
    @model_validator(mode="after")
    def check_max_doctors_to_check(cls, values):
        max_doctors_to_check = values.get('max_doctors_to_check')
        if max_doctors_to_check > 500:
            raise ValueError("max_doctors_to_check must be max 500")
        return values

    # make sure max_appointments_to_return is max max_doctors_to_check
    @model_validator(mode="after")
    def check_max_appointments_to_return(cls, values):
        max_appointments_to_return = values.get('max_appointments_to_return')
        if max_appointments_to_return > values.get('max_doctors_to_check'):
            raise ValueError("max_appointments_to_return must be less than or equal to max_doctors_to_check")
        return values

    # make sure that either patient_address or city is provided
    @model_validator(mode="after")
    def check_address_or_city(cls, values):
        patient_address = values.get('patient_address')
        city = values.get('city')

        if not patient_address and not city:
            raise ValueError("Either patient_address or city must be provided.")

        return values

health_search_appointments_input_example = {
    "databases": ["doctolib"],
    "doctor_speciality": "Kardiologe",
    "from_date_str": "2024-10-25",
    "to_date_str": "2024-10-31",
    "patient_insurance": "public",
    "patient_address": "Friedrichstraße 123, 10117 Berlin, Deutschland",
    "travel_method": "public_transport",
    "calculate_travel_time": True,
    "max_doctors_to_check": 100,
    "max_appointments_to_return": 5
}

# API endpoint will return a task. But once the task is complete,
# the following details will be added to the task output

class Doctor(BaseModel):
    name: str = Field(..., description="The name of the doctor")
    speciality: str = Field(..., description="The speciality of the doctor")
    address: str = Field(..., description="The address of the doctor")
    link: str = Field(..., description="The link to the doctor's profile, to book an appointment")
    rating: float = Field(..., description="The rating of the doctor")
    travel_time_minutes: int = Field(..., description="The travel time in minutes from the patient's address to the doctor's address")
    travel_method: Literal["car", "public_transport"] = Field(..., description="The method of travel for calculating the travel time")

class AvailableAppointment(BaseModel):
    doctor: Doctor = Field(..., description="The doctor")
    next_available_appointment: str = Field(..., description="The date and time of the next available appointment, ISO 8601 format")

class HealthSearchAppointmentsOutput(BaseModel):
    appointments: List[AvailableAppointment] = Field(..., description="The list of appointments")


health_search_appointments_output_example = {
    "appointments": [
        {
            "doctor": {
                "name": "Dr. Müller",
                "speciality": "Kardiologe",
                "address": "Friedrichstraße 123, 10117 Berlin, Deutschland",
                "link": "https://www.doctolib.de/kardiologe/berlin/dr-mueller",
                "rating": 4.5,
                "travel_time_minutes": 30,
                "travel_method": "public_transport"
            },
            "next_available_appointment": "2024-10-26T10:00:00"
        },
        {
            "doctor": {
                "name": "Dr. Schmidt",
                "speciality": "Kardiologe",
                "address": "Unter den Linden 1, 10117 Berlin, Deutschland",
                "link": "https://www.doctolib.de/kardiologe/berlin/dr-schmidt",
                "rating": 4.2,
                "travel_time_minutes": 25,
                "travel_method": "public_transport"
            },
            "next_available_appointment": "2024-10-27T10:00:00"
        }
    ]
}