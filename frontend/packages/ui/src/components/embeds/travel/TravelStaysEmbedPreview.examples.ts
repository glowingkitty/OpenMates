/**
 * EU destinations only. Invented hotel names with real coordinates. Photos generated once via Gemini image generation and served as static assets under /store-examples/.
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
    "query": "Hotels in central Lisbon",
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
        "rate_per_night": "145",
        "extracted_rate_per_night": 145,
        "total_rate": "435",
        "amenities": [
          "Free Wi-Fi",
          "Breakfast included",
          "Rooftop terrace",
          "Air conditioning"
        ],
        "description": "Invented mid-range hotel near Praça do Comércio with classic tiled rooms and a small rooftop lounge.",
        "link": "https://example.org/sample-hotel",
        "latitude": 38.708,
        "longitude": -9.137,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-1.webp",
            "original_image": "/store-examples/travel-stays-1.webp"
          }
        ]
      },
      {
        "name": "Casa do Tejo Boutique (fictional)",
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
          "Balcony",
          "Bar"
        ],
        "description": "Invented boutique hotel in Alfama with hand-picked furniture and a quiet inner garden.",
        "link": "https://example.org/sample-hotel",
        "latitude": 38.711,
        "longitude": -9.131,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-1.webp",
            "original_image": "/store-examples/travel-stays-1.webp"
          }
        ]
      },
      {
        "name": "The Invented Grand Lisboa",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.8,
        "reviews": 2650,
        "currency": "EUR",
        "rate_per_night": "290",
        "extracted_rate_per_night": 290,
        "total_rate": "870",
        "amenities": [
          "Free Wi-Fi",
          "Spa",
          "Pool",
          "Fine dining"
        ],
        "description": "Invented 5-star hotel on an invented hillside with sweeping views over the Tagus river.",
        "link": "https://example.org/sample-hotel",
        "latitude": 38.72,
        "longitude": -9.15,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-1.webp",
            "original_image": "/store-examples/travel-stays-1.webp"
          }
        ]
      },
      {
        "name": "Sample Plaza Inn Lisbon",
        "property_type": "hotel",
        "hotel_class": 3,
        "overall_rating": 4.3,
        "reviews": 620,
        "currency": "EUR",
        "rate_per_night": "78",
        "extracted_rate_per_night": 78,
        "total_rate": "234",
        "amenities": [
          "Free Wi-Fi",
          "Breakfast ($)",
          "Family rooms"
        ],
        "description": "Invented budget hotel steps from a sample metro station, family-friendly.",
        "link": "https://example.org/sample-hotel",
        "latitude": 38.714,
        "longitude": -9.141,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-1.webp",
            "original_image": "/store-examples/travel-stays-1.webp"
          }
        ]
      }
    ]
  },
  {
    "id": "store-example-travel-search-stays-2",
    "query": "Mountain cabins in the Austrian Alps",
    "query_translation_key": "settings.app_store_examples.travel.search_stays.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "name": "Alpenglow Chalet (fictional)",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.7,
        "reviews": 950,
        "currency": "EUR",
        "rate_per_night": "220",
        "extracted_rate_per_night": 220,
        "total_rate": "660",
        "amenities": [
          "Mountain view",
          "Sauna",
          "Free Wi-Fi",
          "Breakfast included"
        ],
        "description": "Invented hand-built wooden chalet with a fireplace and private sauna, 10 minutes from the village centre.",
        "link": "https://example.org/sample-hotel",
        "latitude": 47.253,
        "longitude": 11.387,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-2.webp",
            "original_image": "/store-examples/travel-stays-2.webp"
          }
        ]
      },
      {
        "name": "Silberhorn Berghaus (fictional)",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.6,
        "reviews": 780,
        "currency": "EUR",
        "rate_per_night": "195",
        "extracted_rate_per_night": 195,
        "total_rate": "585",
        "amenities": [
          "Mountain view",
          "Sauna",
          "Ski storage",
          "Restaurant"
        ],
        "description": "Invented ski-in cabin with hearty breakfasts and an invented on-site restaurant.",
        "link": "https://example.org/sample-hotel",
        "latitude": 47.273,
        "longitude": 11.396,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-2.webp",
            "original_image": "/store-examples/travel-stays-2.webp"
          }
        ]
      },
      {
        "name": "The Sample Hut",
        "property_type": "hotel",
        "hotel_class": 3,
        "overall_rating": 4.4,
        "reviews": 420,
        "currency": "EUR",
        "rate_per_night": "110",
        "extracted_rate_per_night": 110,
        "total_rate": "330",
        "amenities": [
          "Mountain view",
          "Free Wi-Fi",
          "Shared kitchen"
        ],
        "description": "Invented rustic cabin for small groups, with wood-fired stove and valley views.",
        "link": "https://example.org/sample-hotel",
        "latitude": 47.245,
        "longitude": 11.376,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-2.webp",
            "original_image": "/store-examples/travel-stays-2.webp"
          }
        ]
      },
      {
        "name": "Bergwald Retreat (fictional)",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.9,
        "reviews": 1340,
        "currency": "EUR",
        "rate_per_night": "340",
        "extracted_rate_per_night": 340,
        "total_rate": "1020",
        "amenities": [
          "Mountain view",
          "Spa",
          "Pool",
          "Fine dining",
          "Concierge"
        ],
        "description": "Invented luxury Alpine retreat with a heated outdoor pool and invented fine-dining restaurant.",
        "link": "https://example.org/sample-hotel",
        "latitude": 47.265,
        "longitude": 11.42,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-2.webp",
            "original_image": "/store-examples/travel-stays-2.webp"
          }
        ]
      }
    ]
  },
  {
    "id": "store-example-travel-search-stays-3",
    "query": "Family hotels in the Greek islands",
    "query_translation_key": "settings.app_store_examples.travel.search_stays.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "name": "Coral Horizon Seaside (fictional)",
        "property_type": "hotel",
        "hotel_class": 5,
        "overall_rating": 4.8,
        "reviews": 2450,
        "currency": "EUR",
        "rate_per_night": "245",
        "extracted_rate_per_night": 245,
        "total_rate": "735",
        "amenities": [
          "Beach access",
          "Pool",
          "Kids club",
          "Breakfast included",
          "Family rooms"
        ],
        "description": "Invented family-friendly resort with a shallow kids pool and invented private beach club.",
        "link": "https://example.org/sample-hotel",
        "latitude": 36.395,
        "longitude": 25.461,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-3.webp",
            "original_image": "/store-examples/travel-stays-3.webp"
          }
        ]
      },
      {
        "name": "Palm Cove Aegean Retreat (fictional)",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.6,
        "reviews": 1580,
        "currency": "EUR",
        "rate_per_night": "185",
        "extracted_rate_per_night": 185,
        "total_rate": "555",
        "amenities": [
          "Beach access",
          "Pool",
          "Breakfast included"
        ],
        "description": "Invented whitewashed hotel with family rooms and a small shaded terrace.",
        "link": "https://example.org/sample-hotel",
        "latitude": 36.408,
        "longitude": 25.376,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-3.webp",
            "original_image": "/store-examples/travel-stays-3.webp"
          }
        ]
      },
      {
        "name": "Sunset Lantern Villas",
        "property_type": "hotel",
        "hotel_class": 4,
        "overall_rating": 4.5,
        "reviews": 860,
        "currency": "EUR",
        "rate_per_night": "160",
        "extracted_rate_per_night": 160,
        "total_rate": "480",
        "amenities": [
          "Pool",
          "Breakfast ($)",
          "Free Wi-Fi"
        ],
        "description": "Invented cluster of invented villas a few minutes from a quiet beach.",
        "link": "https://example.org/sample-hotel",
        "latitude": 37.45,
        "longitude": 25.329,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-3.webp",
            "original_image": "/store-examples/travel-stays-3.webp"
          }
        ]
      },
      {
        "name": "The Sample Shoreline Rhodes",
        "property_type": "hotel",
        "hotel_class": 3,
        "overall_rating": 4.3,
        "reviews": 420,
        "currency": "EUR",
        "rate_per_night": "95",
        "extracted_rate_per_night": 95,
        "total_rate": "285",
        "amenities": [
          "Pool",
          "Free Wi-Fi",
          "Restaurant"
        ],
        "description": "Invented family-run budget hotel with a palm-shaded lounging area and daily breakfast buffet.",
        "link": "https://example.org/sample-hotel",
        "latitude": 36.437,
        "longitude": 28.222,
        "check_in_time": "3:00 PM",
        "check_out_time": "11:00 AM",
        "images": [
          {
            "thumbnail": "/store-examples/travel-stays-3.webp",
            "original_image": "/store-examples/travel-stays-3.webp"
          }
        ]
      }
    ]
  }
]

export default examples;
