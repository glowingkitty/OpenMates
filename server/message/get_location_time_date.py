from datetime import datetime

location = {}


def get_location_time_date(update_location_seconds=300):
    location_name = "Berlin, Germany"
    now = datetime.now()

    # return a string with the location, time and date
    output_string = f"It is currently {now.strftime('%I:%M %p')}. {now.strftime('%A, %B %d, %Y')}. In {location_name}."

    return output_string