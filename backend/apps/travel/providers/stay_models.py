"""Provider-independent accommodation result schema."""
from typing import Any, Dict, List, Optional

class StayResult:
    """A single accommodation result for historical accommodation embeds."""

    def __init__(
        self,
        name: str,
        description: Optional[str] = None,
        property_type: str = "hotel",
        link: Optional[str] = None,
        property_token: Optional[str] = None,
        gps_coordinates: Optional[Dict[str, float]] = None,
        hotel_class: Optional[int] = None,
        overall_rating: Optional[float] = None,
        reviews: Optional[int] = None,
        rate_per_night: Optional[str] = None,
        extracted_rate_per_night: Optional[float] = None,
        total_rate: Optional[str] = None,
        extracted_total_rate: Optional[float] = None,
        currency: str = "EUR",
        check_in_time: Optional[str] = None,
        check_out_time: Optional[str] = None,
        amenities: Optional[List[str]] = None,
        images: Optional[List[Dict[str, str]]] = None,
        thumbnail: Optional[str] = None,
        nearby_places: Optional[List[Dict[str, Any]]] = None,
        eco_certified: bool = False,
        free_cancellation: bool = False,
    ):
        self.name = name
        self.description = description
        self.property_type = property_type
        self.link = link
        self.property_token = property_token
        self.gps_coordinates = gps_coordinates
        self.hotel_class = hotel_class
        self.overall_rating = overall_rating
        self.reviews = reviews
        self.rate_per_night = rate_per_night
        self.extracted_rate_per_night = extracted_rate_per_night
        self.total_rate = total_rate
        self.extracted_total_rate = extracted_total_rate
        self.currency = currency
        self.check_in_time = check_in_time
        self.check_out_time = check_out_time
        self.amenities = amenities or []
        self.images = images or []
        self.thumbnail = thumbnail
        self.nearby_places = nearby_places or []
        self.eco_certified = eco_certified
        self.free_cancellation = free_cancellation

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for the skill response / embed content."""
        result: Dict[str, Any] = {
            "type": "stay",
            "name": self.name,
            "property_type": self.property_type,
            "currency": self.currency,
        }
        if self.description:
            result["description"] = self.description
        if self.link:
            result["link"] = self.link
        if self.property_token:
            result["property_token"] = self.property_token
        if self.gps_coordinates:
            result["latitude"] = self.gps_coordinates.get("latitude")
            result["longitude"] = self.gps_coordinates.get("longitude")
        if self.hotel_class is not None:
            result["hotel_class"] = self.hotel_class
        if self.overall_rating is not None:
            result["overall_rating"] = self.overall_rating
        if self.reviews is not None:
            result["reviews"] = self.reviews
        if self.rate_per_night:
            result["rate_per_night"] = self.rate_per_night
        if self.extracted_rate_per_night is not None:
            result["extracted_rate_per_night"] = self.extracted_rate_per_night
        if self.total_rate:
            result["total_rate"] = self.total_rate
        if self.extracted_total_rate is not None:
            result["extracted_total_rate"] = self.extracted_total_rate
        if self.check_in_time:
            result["check_in_time"] = self.check_in_time
        if self.check_out_time:
            result["check_out_time"] = self.check_out_time
        if self.amenities:
            result["amenities"] = self.amenities
        if self.images:
            result["images"] = self.images[:5]  # Limit to 5 images for embed size
        if self.thumbnail:
            result["thumbnail"] = self.thumbnail
        if self.nearby_places:
            result["nearby_places"] = self.nearby_places[:3]  # Limit to 3
        if self.eco_certified:
            result["eco_certified"] = True
        if self.free_cancellation:
            result["free_cancellation"] = True
        return result
