"""
Airline IATA code to booking URL mapping for the travel app.

Maps IATA 2-letter carrier codes to airline booking website URLs.
Used to generate direct deep links to airline booking pages from
flight search results.

Deep link strategy:
- For airlines with known booking URL patterns, we construct a direct
  booking search URL with origin, destination, and date parameters.
- For unknown airlines, we fall back to the airline's homepage or
  a Skyscanner redirect as a universal fallback.

The URL templates use Python format placeholders:
  {origin}      - Origin IATA airport code (e.g., 'MUC')
  {destination}  - Destination IATA airport code (e.g., 'LHR')
  {date}         - Departure date as YYYY-MM-DD
  {date_compact} - Departure date as YYMMDD (for airlines using that format)
  {day}          - Day of month (e.g., '07')
  {month}        - Month (e.g., '03')
  {year}         - Full year (e.g., '2026')
  {pax}          - Number of adult passengers
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Airline data: IATA code -> (airline name, booking URL template or homepage)
# ---------------------------------------------------------------------------
# URL templates use {origin}, {destination}, {date}, {year}, {month}, {day},
# {date_compact}, {pax} placeholders. If no template is available, only the
# homepage is provided and we link directly to it.
#
# Sources: airline websites, public booking URL patterns (2024/2025)
# ---------------------------------------------------------------------------

AIRLINE_DATA: dict[str, tuple[str, str]] = {
    # --- Major European carriers ---
    "LH": ("Lufthansa", "https://www.lufthansa.com/us/en/flight-search?searchType=ONEWAY&cabinClass=economy&journeyType=OW&origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "LX": ("SWISS", "https://www.swiss.com/us/en/book/flights?searchType=ONEWAY&origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "OS": ("Austrian Airlines", "https://www.austrian.com/us/en/flight-search?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "SN": ("Brussels Airlines", "https://www.brusselsairlines.com/us/en/flight-search?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "BA": ("British Airways", "https://www.britishairways.com/travel/book/public/en_us?eId=111069&from={origin}&to={destination}&depDate={date}&cabin=M&ad={pax}&ch=0&inf=0"),
    "AF": ("Air France", "https://www.airfrance.us/search/offers?pax={pax}ADT&cabinClass=ECONOMY&activeConnection=0&connections={origin}>{destination}:{date}"),
    "KL": ("KLM", "https://www.klm.us/search/offers?pax={pax}ADT&cabinClass=ECONOMY&activeConnection=0&connections={origin}>{destination}:{date}"),
    "IB": ("Iberia", "https://www.iberia.com/us/flights/{origin}/{destination}/?market=US&language=en&adults={pax}&departureDate={date}"),
    "AY": ("Finnair", "https://www.finnair.com/us-en/flights/{origin}-{destination}?adults={pax}&departureDate={date}"),
    "SK": ("SAS", "https://www.flysas.com/us-en/book/flights?origin={origin}&destination={destination}&outDate={date}&adt={pax}"),
    "TP": ("TAP Air Portugal", "https://www.flytap.com/en-us/flights?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "AZ": ("ITA Airways", "https://www.ita-airways.com/en_us/homepage.html"),
    "EI": ("Aer Lingus", "https://www.aerlingus.com/booking/select-flights?adult={pax}&departure={origin}&destination={destination}&date_out={date}"),
    "LO": ("LOT Polish Airlines", "https://www.lot.com/us/en/booking/flight-search?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "OK": ("Czech Airlines", "https://www.csa.cz/en/"),
    "RO": ("TAROM", "https://www.tarom.ro/en"),
    "JU": ("Air Serbia", "https://www.airserbia.com/en"),
    "OU": ("Croatia Airlines", "https://www.croatiaairlines.com/"),
    "BT": ("airBaltic", "https://www.airbaltic.com/en/index?a_departure={origin}&a_destination={destination}&a_departureDate={date}&a_adults={pax}"),
    "A3": ("Aegean Airlines", "https://en.aegeanair.com/flight-search/?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "U2": ("easyJet", "https://www.easyjet.com/en/booking/select-flight?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "FR": ("Ryanair", "https://www.ryanair.com/gb/en/trip/flights/select?adults={pax}&dateOut={date}&originIata={origin}&destinationIata={destination}"),
    "W6": ("Wizz Air", "https://wizzair.com/en-gb/flights/{origin}/{destination}/{date}"),
    "VY": ("Vueling", "https://www.vueling.com/en/booking/select?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "DY": ("Norwegian", "https://www.norwegian.com/us/booking/flight-offers?AdultCount={pax}&OriginAirportCode={origin}&DestinationAirportCode={destination}&OutboundDate={date}"),
    "PC": ("Pegasus Airlines", "https://www.flypgs.com/en"),
    "TK": ("Turkish Airlines", "https://www.turkishairlines.com/en-us/flights/?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),

    # --- North American carriers ---
    "AA": ("American Airlines", "https://www.aa.com/booking/search?locale=en_US&pax={pax}&adult={pax}&type=OneWay&searchType=Award&origin={origin}&destination={destination}&departureDate={date}"),
    "DL": ("Delta Air Lines", "https://www.delta.com/flight-search/book-a-flight?cacheKeySuffix=be17f74c&tripType=ONE_WAY&origin={origin}&destination={destination}&departureDate={date}&paxCount={pax}"),
    "UA": ("United Airlines", "https://www.united.com/en/us/fsr/choose-flights?f={origin}&t={destination}&d={date}&tt=1&at=1&sc=7&px={pax}&taxng=1&newHP=True&clm=7&st=bestmatches"),
    "WN": ("Southwest Airlines", "https://www.southwest.com/air/booking/select.html?adultPassengersCount={pax}&originationAirportCode={origin}&destinationAirportCode={destination}&departureDate={date}"),
    "B6": ("JetBlue", "https://www.jetblue.com/booking/flights?from={origin}&to={destination}&depart={date}&pax={pax}"),
    "AS": ("Alaska Airlines", "https://www.alaskaair.com/shopping/flights?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "WS": ("WestJet", "https://www.westjet.com/en-ca/flights"),
    "AC": ("Air Canada", "https://www.aircanada.com/en-ca/flights?orig1={origin}&dest1={destination}&depart1={date}&adults={pax}"),
    "AM": ("Aeromexico", "https://www.aeromexico.com/en-us/booking?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),

    # --- Middle East carriers ---
    "EK": ("Emirates", "https://www.emirates.com/us/english/book/?origin={origin}&destination={destination}&departureDate={date}&adults={pax}&class=Economy"),
    "QR": ("Qatar Airways", "https://www.qatarairways.com/en/booking/book-flights.html?origins={origin}&destinations={destination}&departureDates={date}&adults={pax}"),
    "EY": ("Etihad Airways", "https://www.etihad.com/en-us/fly-etihad/book-a-flight?departure={origin}&arrival={destination}&date={date}&adults={pax}"),
    "GF": ("Gulf Air", "https://www.gulfair.com/en/book-a-flight?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "WY": ("Oman Air", "https://www.omanair.com/en"),
    "SV": ("Saudia", "https://www.saudia.com/en/booking?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "RJ": ("Royal Jordanian", "https://www.rj.com/en"),
    "MS": ("EgyptAir", "https://www.egyptair.com/en/pages/homepage.aspx"),

    # --- Asian carriers ---
    "SQ": ("Singapore Airlines", "https://www.singaporeair.com/en_UK/plan-and-book/booking/?origin={origin}&destination={destination}&departureDate={date}&adults={pax}&cabinClass=Y"),
    "CX": ("Cathay Pacific", "https://www.cathaypacific.com/cx/en_US/book-a-trip/flight-search.html?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "JL": ("Japan Airlines", "https://www.jal.co.jp/en/"),
    "NH": ("ANA", "https://www.ana.co.jp/en/us/"),
    "TG": ("Thai Airways", "https://www.thaiairways.com/en_US/index.page"),
    "MH": ("Malaysia Airlines", "https://www.malaysiaairlines.com/"),
    "GA": ("Garuda Indonesia", "https://www.garuda-indonesia.com/"),
    "PR": ("Philippine Airlines", "https://www.philippineairlines.com/"),
    "VN": ("Vietnam Airlines", "https://www.vietnamairlines.com/"),
    "CI": ("China Airlines", "https://www.china-airlines.com/us/en"),
    "BR": ("EVA Air", "https://www.evaair.com/en-us/"),
    "OZ": ("Asiana Airlines", "https://www.flyasiana.com/"),
    "KE": ("Korean Air", "https://www.koreanair.com/us/en/booking/flight-search?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "CA": ("Air China", "https://www.airchina.com.cn/en/"),
    "CZ": ("China Southern Airlines", "https://www.csair.com/en/"),
    "MU": ("China Eastern Airlines", "https://us.ceair.com/"),
    "HU": ("Hainan Airlines", "https://www.hainanairlines.com/"),
    "AI": ("Air India", "https://www.airindia.com/in/en/book.html?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "6E": ("IndiGo", "https://www.goindigo.in/"),
    "AK": ("AirAsia", "https://www.airasia.com/flights/{origin}-{destination}?departureDate={date}&adults={pax}"),
    "FD": ("Thai AirAsia", "https://www.airasia.com/flights/{origin}-{destination}?departureDate={date}&adults={pax}"),
    "TR": ("Scoot", "https://www.flyscoot.com/en"),
    "3K": ("Jetstar Asia", "https://www.jetstar.com/"),
    "QZ": ("Indonesia AirAsia", "https://www.airasia.com/"),

    # --- Oceania ---
    "QF": ("Qantas", "https://www.qantas.com/us/en/flights.html?from={origin}&to={destination}&departure={date}&adults={pax}"),
    "NZ": ("Air New Zealand", "https://www.airnewzealand.com/book?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "VA": ("Virgin Australia", "https://www.virginaustralia.com/au/en/"),

    # --- Africa ---
    "ET": ("Ethiopian Airlines", "https://www.ethiopianairlines.com/en"),
    "SA": ("South African Airways", "https://www.flysaa.com/"),
    "KQ": ("Kenya Airways", "https://www.kenya-airways.com/"),
    "AT": ("Royal Air Maroc", "https://www.royalairmaroc.com/"),
    "WB": ("RwandAir", "https://www.rwandair.com/"),

    # --- South America ---
    "LA": ("LATAM Airlines", "https://www.latamairlines.com/us/en/flights?origin={origin}&destination={destination}&outbound={date}&adt={pax}"),
    "AV": ("Avianca", "https://www.avianca.com/us/en/booking/?origin={origin}&destination={destination}&departureDate={date}&adults={pax}"),
    "G3": ("Gol", "https://www.voegol.com.br/en"),
    "CM": ("Copa Airlines", "https://www.copaair.com/en-us/"),
    "AR": ("Aerolineas Argentinas", "https://www.aerolineas.com.ar/en-us"),
}

# Skyscanner fallback URL template for airlines without direct booking links
_SKYSCANNER_FALLBACK_TEMPLATE = (
    "https://www.skyscanner.com/transport/flights/{origin_lower}/{destination_lower}/{date_compact}/"
    "?adultsv2={pax}&cabinclass=economy"
)


def get_airline_booking_url(
    carrier_code: str,
    origin_iata: str,
    destination_iata: str,
    departure_date: str,
    passengers: int = 1,
) -> tuple[Optional[str], str]:
    """
    Generate a booking URL for the given airline and route.

    Args:
        carrier_code: IATA 2-letter airline code (e.g., 'LH').
        origin_iata: Origin airport IATA code (e.g., 'MUC').
        destination_iata: Destination airport IATA code (e.g., 'LHR').
        departure_date: Departure date as 'YYYY-MM-DD'.
        passengers: Number of adult passengers.

    Returns:
        Tuple of (booking_url, airline_name).
        booking_url is the direct airline URL if available, or Skyscanner fallback.
        airline_name is the display name of the airline.
    """
    # Parse date components for templates
    try:
        year, month, day = departure_date.split("-")
        date_compact = f"{year[2:]}{month}{day}"  # e.g., '260307'
    except (ValueError, IndexError):
        year = month = day = ""
        date_compact = ""

    airline_entry = AIRLINE_DATA.get(carrier_code)
    airline_name = airline_entry[0] if airline_entry else carrier_code

    if airline_entry:
        _name, url_template = airline_entry
        # Check if template has route placeholders (direct deep link)
        if "{origin}" in url_template:
            try:
                url = url_template.format(
                    origin=origin_iata,
                    destination=destination_iata,
                    date=departure_date,
                    date_compact=date_compact,
                    year=year,
                    month=month,
                    day=day,
                    pax=passengers,
                )
                return (url, airline_name)
            except (KeyError, ValueError) as e:
                logger.warning(f"Failed to format booking URL for {carrier_code}: {e}")
                # Fall through to homepage
        # Homepage-only entry (no route params in URL)
        return (url_template, airline_name)

    # Unknown airline: use Skyscanner as universal fallback
    try:
        fallback_url = _SKYSCANNER_FALLBACK_TEMPLATE.format(
            origin_lower=origin_iata.lower(),
            destination_lower=destination_iata.lower(),
            date_compact=date_compact,
            pax=passengers,
        )
        return (fallback_url, f"Skyscanner ({carrier_code})")
    except (KeyError, ValueError):
        return (None, airline_name)


def get_airline_name(carrier_code: str) -> str:
    """
    Get the display name for an airline by its IATA carrier code.

    Args:
        carrier_code: IATA 2-letter airline code.

    Returns:
        Airline name or the carrier code itself if unknown.
    """
    entry = AIRLINE_DATA.get(carrier_code)
    return entry[0] if entry else carrier_code
