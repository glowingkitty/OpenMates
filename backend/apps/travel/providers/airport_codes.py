"""Local airport-code resolution; never performs network requests."""
import re
from typing import Dict, Optional

_CITY_IATA_FALLBACK: Dict[str, str] = {
    # Europe
    "london": "LHR", "london heathrow": "LHR", "london gatwick": "LGW",
    "london stansted": "STN", "london luton": "LTN", "london city": "LCY",
    "paris": "CDG", "paris charles de gaulle": "CDG", "paris orly": "ORY",
    "berlin": "BER", "munich": "MUC", "frankfurt": "FRA", "hamburg": "HAM",
    "düsseldorf": "DUS", "dusseldorf": "DUS", "cologne": "CGN", "köln": "CGN",
    "stuttgart": "STR", "nuremberg": "NUE", "nürnberg": "NUE",
    "hannover": "HAJ", "hanover": "HAJ", "leipzig": "LEJ", "dresden": "DRS",
    "amsterdam": "AMS", "brussels": "BRU", "zurich": "ZRH", "zürich": "ZRH",
    "geneva": "GVA", "genf": "GVA", "vienna": "VIE", "wien": "VIE",
    "rome": "FCO", "milan": "MXP", "milano": "MXP", "venice": "VCE",
    "florence": "FLR", "naples": "NAP", "bologna": "BLQ", "turin": "TRN",
    "madrid": "MAD", "barcelona": "BCN", "lisbon": "LIS", "porto": "OPO",
    "malaga": "AGP", "seville": "SVQ", "valencia": "VLC", "palma": "PMI",
    "palma de mallorca": "PMI", "ibiza": "IBZ", "tenerife": "TFS",
    "dublin": "DUB", "edinburgh": "EDI", "manchester": "MAN",
    "birmingham": "BHX", "glasgow": "GLA", "bristol": "BRS",
    "copenhagen": "CPH", "stockholm": "ARN", "oslo": "OSL", "helsinki": "HEL",
    "warsaw": "WAW", "krakow": "KRK", "prague": "PRG", "budapest": "BUD",
    "bucharest": "OTP", "sofia": "SOF", "belgrade": "BEG", "zagreb": "ZAG",
    "athens": "ATH", "thessaloniki": "SKG", "istanbul": "IST",
    "ankara": "ESB", "antalya": "AYT", "izmir": "ADB",
    "moscow": "SVO", "saint petersburg": "LED", "st petersburg": "LED",
    "reykjavik": "KEF", "riga": "RIX", "vilnius": "VNO", "tallinn": "TLL",
    "nice": "NCE", "lyon": "LYS", "marseille": "MRS", "toulouse": "TLS",
    "bordeaux": "BOD",
    # North America
    "new york": "JFK", "new york city": "JFK", "nyc": "JFK",
    "newark": "EWR", "laguardia": "LGA",
    "los angeles": "LAX", "la": "LAX",
    "san francisco": "SFO", "chicago": "ORD", "miami": "MIA",
    "dallas": "DFW", "houston": "IAH", "atlanta": "ATL",
    "boston": "BOS", "washington": "IAD", "washington dc": "IAD",
    "seattle": "SEA", "denver": "DEN", "las vegas": "LAS",
    "orlando": "MCO", "phoenix": "PHX", "philadelphia": "PHL",
    "san diego": "SAN", "minneapolis": "MSP", "detroit": "DTW",
    "charlotte": "CLT", "tampa": "TPA", "portland": "PDX",
    "toronto": "YYZ", "montreal": "YUL", "vancouver": "YVR",
    "calgary": "YYC", "ottawa": "YOW",
    "mexico city": "MEX", "cancun": "CUN",
    # Asia
    "tokyo": "NRT", "tokyo narita": "NRT", "tokyo haneda": "HND",
    "osaka": "KIX", "seoul": "ICN", "incheon": "ICN",
    "beijing": "PEK", "shanghai": "PVG", "hong kong": "HKG",
    "taipei": "TPE", "singapore": "SIN", "bangkok": "BKK",
    "kuala lumpur": "KUL", "jakarta": "CGK",
    "delhi": "DEL", "new delhi": "DEL", "mumbai": "BOM", "bangalore": "BLR",
    "chennai": "MAA", "kolkata": "CCU", "hyderabad": "HYD",
    "dubai": "DXB", "abu dhabi": "AUH", "doha": "DOH", "riyadh": "RUH",
    "jeddah": "JED", "tel aviv": "TLV", "amman": "AMM", "beirut": "BEY",
    "manila": "MNL", "hanoi": "HAN", "ho chi minh city": "SGN",
    "saigon": "SGN",
    # Oceania
    "sydney": "SYD", "melbourne": "MEL", "brisbane": "BNE",
    "perth": "PER", "auckland": "AKL",
    # Africa
    "cairo": "CAI", "johannesburg": "JNB", "cape town": "CPT",
    "nairobi": "NBO", "lagos": "LOS", "casablanca": "CMN",
    "marrakech": "RAK", "tunis": "TUN", "accra": "ACC",
    # South America
    "sao paulo": "GRU", "são paulo": "GRU", "rio de janeiro": "GIG",
    "buenos aires": "EZE", "bogota": "BOG", "lima": "LIM",
    "santiago": "SCL", "medellin": "MDE", "quito": "UIO",
    "caracas": "CCS", "montevideo": "MVD",
}

def resolve_iata_code(location: str) -> Optional[str]:
    value = location.strip()
    if re.fullmatch(r"[A-Z]{2,4}", value):
        return value
    return _CITY_IATA_FALLBACK.get(value.lower())
