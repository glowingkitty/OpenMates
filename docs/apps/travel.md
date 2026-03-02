# Travel app architecture

## Settings and Memories

### Trips

Users can store their trip information including destination, start date, end date, and notes. The system automatically filters trips based on the start_date to identify upcoming trips for recommendations and reminders.

**Schema**:

- `destination` (string): City or country
- `start_date` (date, YYYY-MM-DD): Trip start date
- `end_date` (date, YYYY-MM-DD): Trip end date
- `notes` (string): Additional notes about the trip

### Preferred Airline

Users can specify their preferred airline for flight bookings and recommendations.

### Preferred Activities

Users can list their preferred travel activities and experiences at destinations (e.g., visiting beaches, exploring museums, hiking, trying local food) to get personalized travel recommendations. This is distinct from transport preferences and flight bookings.

## Providers

### Transitous

Consider using Transitous API for getting up to date public transport connection data across the world.

### Allaboard

Use Allaboard (https://allaboard.eu/) for purchasing train tickets across Europe. Provides a comprehensive platform for booking train connections and tickets.
