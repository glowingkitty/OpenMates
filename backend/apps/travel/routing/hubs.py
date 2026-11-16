"""Public geographic transfer hubs and their selection by detour.

Hubs are towns near borders, at the end of regional networks, or long-distance
hubs. Only geography lives here: names that operators' timetables resolve, a
coordinate and a country. Selection keeps hubs inside the pass area on the
covered side of the trip, with a bounded detour, preferring the hub closest to
the other end and keeping hubs apart from each other.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

MAX_HUBS = 3
MAX_DETOUR_RATIO = 1.6
MIN_HUB_DISTANCE_FROM_END_KM = 30.0
MIN_DISTANCE_BETWEEN_HUBS_KM = 35.0
# A part belongs to a hub only when its hub-side stop lies this close (names can be ambiguous).
HUB_RADIUS_KM = 20.0


@dataclass(frozen=True)
class Hub:
    name: str
    latitude: float
    longitude: float
    country: str


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    country: str


_HUB_ROWS: Tuple[Tuple[str, float, float, str], ...] = (
    # Germany
    ("Lindau (Bodensee)", 47.5527, 9.7036, "DE"), ("Konstanz", 47.6589, 9.1770, "DE"), ("Singen (Hohentwiel)", 47.7592, 8.8404, "DE"),
    ("Friedrichshafen", 47.6533, 9.4734, "DE"), ("Kempten (Allgäu)", 47.7140, 10.3160, "DE"),
    ("Freiburg im Breisgau", 47.9977, 7.8421, "DE"), ("Kehl", 48.5722, 7.8153, "DE"),
    ("Offenburg", 48.4766, 7.9465, "DE"), ("Saarbrücken", 49.2410, 6.9910, "DE"), ("Trier", 49.7570, 6.6513, "DE"),
    ("Aachen", 50.7678, 6.0911, "DE"), ("Bad Bentheim", 52.3036, 7.1597, "DE"), ("Leer", 53.2263, 7.4590, "DE"),
    ("Flensburg", 54.7740, 9.4364, "DE"), ("Hamburg", 53.5530, 10.0069, "DE"), ("Lübeck", 53.8677, 10.6696, "DE"),
    ("Rostock", 54.0782, 12.1310, "DE"), ("Frankfurt (Oder)", 52.3364, 14.5465, "DE"),
    ("Cottbus", 51.7499, 14.3255, "DE"), ("Görlitz", 51.1477, 14.9764, "DE"), ("Dresden", 51.0405, 13.7320, "DE"),
    ("Hof", 50.3080, 11.9220, "DE"), ("Regensburg", 49.0117, 12.0998, "DE"),
    ("Nuremberg", 49.4456, 11.0825, "DE"), ("Passau", 48.5740, 13.4500, "DE"), ("Freilassing", 47.8377, 12.9774, "DE"),
    ("Rosenheim", 47.8500, 12.1190, "DE"), ("Garmisch-Partenkirchen", 47.4920, 11.0960, "DE"),
    ("Munich", 48.1402, 11.5600, "DE"), ("Stuttgart", 48.7840, 9.1817, "DE"), ("Ulm", 48.3994, 9.9829, "DE"),
    ("Karlsruhe", 48.9935, 8.4020, "DE"), ("Mannheim", 49.4794, 8.4695, "DE"),
    ("Frankfurt am Main", 50.1071, 8.6638, "DE"), ("Cologne", 50.9430, 6.9589, "DE"),
    ("Düsseldorf", 51.2199, 6.7943, "DE"), ("Leipzig", 51.3455, 12.3820, "DE"), ("Berlin", 52.5251, 13.3694, "DE"),
    ("Hanover", 52.3767, 9.7410, "DE"), ("Bremen", 53.0830, 8.8130, "DE"),
    # Austria
    ("Vienna", 48.1852, 16.3760, "AT"), ("Salzburg", 47.8130, 13.0450, "AT"), ("Innsbruck", 47.2632, 11.4006, "AT"),
    ("Bregenz", 47.5031, 9.7451, "AT"), ("Feldkirch", 47.2410, 9.6020, "AT"), ("Linz", 48.2903, 14.2914, "AT"),
    ("Graz", 47.0723, 15.4174, "AT"), ("Villach", 46.6180, 13.8480, "AT"), ("Kufstein", 47.5830, 12.1660, "AT"),
    ("Klagenfurt", 46.6160, 14.3130, "AT"),
    # Switzerland
    ("Zurich", 47.3779, 8.5403, "CH"), ("Basel", 47.5476, 7.5897, "CH"), ("Geneva", 46.2102, 6.1424, "CH"),
    ("Chiasso", 45.8320, 9.0310, "CH"), ("Schaffhausen", 47.6980, 8.6330, "CH"),
    ("St. Margrethen", 47.4520, 9.6370, "CH"), ("Kreuzlingen", 47.6500, 9.1750, "CH"),
    ("Buchs SG", 47.1680, 9.4790, "CH"), ("Lugano", 46.0050, 8.9470, "CH"), ("Brig", 46.3190, 7.9880, "CH"),
    ("Bern", 46.9490, 7.4390, "CH"),
)
HUBS: Tuple[Hub, ...] = tuple(Hub(*row) for row in _HUB_ROWS)


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = phi2 - phi1, math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def near_hub(hub: Hub, latitude: object, longitude: object) -> bool:
    """True when the stop is within HUB_RADIUS_KM of the hub, or has no coordinates to check."""
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return True
    return distance_km(hub.latitude, hub.longitude, float(latitude), float(longitude)) <= HUB_RADIUS_KM


def _km(point: GeoPoint, hub: Hub) -> float:
    return distance_km(point.latitude, point.longitude, hub.latitude, hub.longitude)


def select_hubs(covered_end: GeoPoint, other_end: GeoPoint, countries: Iterable[str],
                hubs: Sequence[Hub] = HUBS, limit: int = MAX_HUBS) -> List[Hub]:
    """Hubs in ``countries`` between the covered end and the other end of the trip.

    Ordered by distance to the other end plus the detour through the hub, so the
    pass carries the trip as far as possible without a long way round; hubs next
    to either end or next to an already chosen hub are skipped.
    """
    allowed = {code.upper() for code in countries}
    direct = distance_km(covered_end.latitude, covered_end.longitude, other_end.latitude, other_end.longitude)
    if direct <= MIN_HUB_DISTANCE_FROM_END_KM:
        return []
    candidates = []
    for hub in hubs:
        to_covered, to_other = _km(covered_end, hub), _km(other_end, hub)
        if (hub.country in allowed and to_covered >= MIN_HUB_DISTANCE_FROM_END_KM
                and to_other >= MIN_HUB_DISTANCE_FROM_END_KM
                and (to_covered + to_other) / direct <= MAX_DETOUR_RATIO):
            candidates.append((to_other + max(0.0, to_covered + to_other - direct), hub))
    chosen: List[Hub] = []
    for _, hub in sorted(candidates, key=lambda item: item[0]):
        if all(distance_km(hub.latitude, hub.longitude, other.latitude, other.longitude)
               >= MIN_DISTANCE_BETWEEN_HUBS_KM for other in chosen):
            chosen.append(hub)
        if len(chosen) == limit:
            break
    return chosen
