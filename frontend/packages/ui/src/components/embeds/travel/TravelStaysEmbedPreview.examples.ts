/**
 * App-store examples for the travel skill.
 *
 * Invented hotel names, ratings and amenities so the app store never promotes specific real-world lodgings.
 *
 * These are hand-crafted synthetic fixtures. All names, addresses,
 * prices and ratings are invented so that the app store never promotes
 * specific real-world businesses, doctors, landlords or venues. The
 * shape matches the real provider response so the preview + fullscreen
 * render identically. A "Sample data" banner is shown at the top of
 * the fullscreen via the is_store_example flag set by SkillExamplesSection.
 */

export interface TravelStaysStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: TravelStaysStoreExample[] = [
  {
    "id": "store-example-travel-search-stays-1",
    "query": "Hotels in Barcelona, Spain",
    "query_translation_key": "settings.app_store_examples.travel.search_stays.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "name": "Harbor Lantern Hotel (fictional)",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.6,
        "reviews": 1820,
        "currency": "EUR",
        "rate_per_night": "185",
        "extracted_rate_per_night": 185,
        "total_rate": "555",
        "amenities": [
          "Free Wi-Fi",
          "Breakfast included",
          "Pool",
          "Air conditioning",
          "Pet friendly"
        ],
        "description": "Invented mid-range hotel on the fictional seafront with classic rooms and a small rooftop pool.",
        "link": "https://example.org/sample-hotel",
        "latitude": 41.383,
        "longitude": 2.186,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "Casa Maréa Boutique (fictional)",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.5,
        "reviews": 1120,
        "currency": "EUR",
        "rate_per_night": "165",
        "extracted_rate_per_night": 165,
        "total_rate": "495",
        "amenities": [
          "Free Wi-Fi",
          "Breakfast included",
          "Bar",
          "Balcony"
        ],
        "description": "Invented boutique stay in the sample old-town quarter, hand-picked art in every room.",
        "link": "https://example.org/sample-hotel",
        "latitude": 41.379,
        "longitude": 2.173,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "The Invented Grand",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.8,
        "reviews": 2650,
        "currency": "EUR",
        "rate_per_night": "320",
        "extracted_rate_per_night": 320,
        "total_rate": "960",
        "amenities": [
          "Free Wi-Fi",
          "Spa",
          "Pool",
          "Fine dining",
          "Concierge"
        ],
        "description": "Invented 5-star hotel with a fictional rooftop garden and spa suite.",
        "link": "https://example.org/sample-hotel",
        "latitude": 41.387,
        "longitude": 2.17,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "Sample Plaza Inn",
        "property_type": "hotel",
        "hotel_class": 3,
        "overall_rating": 4.3,
        "reviews": 620,
        "currency": "EUR",
        "rate_per_night": "98",
        "extracted_rate_per_night": 98,
        "total_rate": "294",
        "amenities": [
          "Free Wi-Fi",
          "Breakfast ($)",
          "Family rooms"
        ],
        "description": "Invented budget hotel close to the sample metro station, friendly for short stays.",
        "link": "https://example.org/sample-hotel",
        "latitude": 41.39,
        "longitude": 2.165,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      }
    ]
  },
  {
    "id": "store-example-travel-search-stays-2",
    "query": "Boutique hotels in Paris, France",
    "query_translation_key": "settings.app_store_examples.travel.search_stays.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "name": "Maison Northbridge (fictional)",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.7,
        "reviews": 2010,
        "currency": "EUR",
        "rate_per_night": "240",
        "extracted_rate_per_night": 240,
        "total_rate": "720",
        "amenities": [
          "Free Wi-Fi",
          "Breakfast included",
          "Garden",
          "Library"
        ],
        "description": "Invented boutique townhouse on an invented quiet street, each room with vintage furniture.",
        "link": "https://example.org/sample-hotel",
        "latitude": 48.856,
        "longitude": 2.352,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "Le Petit Lantern (fictional)",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.6,
        "reviews": 980,
        "currency": "EUR",
        "rate_per_night": "215",
        "extracted_rate_per_night": 215,
        "total_rate": "645",
        "amenities": [
          "Free Wi-Fi",
          "Bar",
          "Spa ($)"
        ],
        "description": "Invented small hotel near the sample river with a cosy reading lounge.",
        "link": "https://example.org/sample-hotel",
        "latitude": 48.858,
        "longitude": 2.342,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "Hôtel Westhaven",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.9,
        "reviews": 3120,
        "currency": "EUR",
        "rate_per_night": "420",
        "extracted_rate_per_night": 420,
        "total_rate": "1260",
        "amenities": [
          "Free Wi-Fi",
          "Spa",
          "Fine dining",
          "Concierge",
          "Fitness center"
        ],
        "description": "Invented luxury boutique with a fictional rooftop restaurant and personal concierge.",
        "link": "https://example.org/sample-hotel",
        "latitude": 48.87,
        "longitude": 2.325,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "The Sample Atelier",
        "property_type": "hotel",
        "hotel_class": 3,
        "overall_rating": 4.4,
        "reviews": 540,
        "currency": "EUR",
        "rate_per_night": "135",
        "extracted_rate_per_night": 135,
        "total_rate": "405",
        "amenities": [
          "Free Wi-Fi",
          "Breakfast ($)"
        ],
        "description": "Invented artsy budget hotel in the sample Marais district.",
        "link": "https://example.org/sample-hotel",
        "latitude": 48.862,
        "longitude": 2.361,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      }
    ]
  },
  {
    "id": "store-example-travel-search-stays-3",
    "query": "Beach resorts in Bali, Indonesia",
    "query_translation_key": "settings.app_store_examples.travel.search_stays.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "name": "Coral Horizon Beach Resort (fictional)",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.8,
        "reviews": 2450,
        "currency": "EUR",
        "rate_per_night": "310",
        "extracted_rate_per_night": 310,
        "total_rate": "930",
        "amenities": [
          "Beach access",
          "Pool",
          "Spa",
          "Breakfast included",
          "Water sports"
        ],
        "description": "Invented 5-star resort with private beach huts and a fictional coral-reef snorkel spot.",
        "link": "https://example.org/sample-hotel",
        "latitude": -8.723,
        "longitude": 115.169,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "Palm Cove Retreat (fictional)",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.6,
        "reviews": 1580,
        "currency": "EUR",
        "rate_per_night": "195",
        "extracted_rate_per_night": 195,
        "total_rate": "585",
        "amenities": [
          "Beach access",
          "Pool",
          "Yoga deck",
          "Breakfast included"
        ],
        "description": "Invented yoga-friendly resort with 12 bungalows around a shared sample lagoon.",
        "link": "https://example.org/sample-hotel",
        "latitude": -8.68,
        "longitude": 115.239,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "Sunset Lantern Villas",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.5,
        "reviews": 860,
        "currency": "EUR",
        "rate_per_night": "170",
        "extracted_rate_per_night": 170,
        "total_rate": "510",
        "amenities": [
          "Pool",
          "Breakfast ($)",
          "Free Wi-Fi"
        ],
        "description": "Invented villa cluster a short walk from an invented quiet beach.",
        "link": "https://example.org/sample-hotel",
        "latitude": -8.672,
        "longitude": 115.263,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      },
      {
        "name": "The Sample Shoreline",
        "property_type": "hotel",
        "hotel_class": 3,
        "overall_rating": 4.3,
        "reviews": 420,
        "currency": "EUR",
        "rate_per_night": "110",
        "extracted_rate_per_night": 110,
        "total_rate": "330",
        "amenities": [
          "Pool",
          "Free Wi-Fi",
          "Restaurant"
        ],
        "description": "Invented budget beach stay with friendly service and a palm-shaded lounging area.",
        "link": "https://example.org/sample-hotel",
        "latitude": -8.71,
        "longitude": 115.175,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": []
      }
    ]
  }
]

export default examples;
