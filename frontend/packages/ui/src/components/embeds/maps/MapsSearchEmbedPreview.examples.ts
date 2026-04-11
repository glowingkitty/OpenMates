/**
 * App-store examples for the maps search skill.
 *
 * Business names are hand-crafted and fictional (marked "(fictional)"),
 * so the app store never promotes a specific real-world café, restaurant
 * or bookstore. Coordinates and street names are REAL and spread across
 * recognisable neighbourhoods in each city so the map renders authentic
 * tiles + markers — that's what makes the preview useful to someone
 * deciding whether to install the maps skill.
 *
 * A "Sample data" banner is rendered above the fullscreen via the
 * is_store_example flag on decodedContent.
 */

export interface MapsSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: MapsSearchStoreExample[] = [
  {
    "id": "store-example-maps-search-1",
    "query": "Best coffee shops in San Francisco",
    "query_translation_key": "settings.app_store_examples.maps.search.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "displayName": "The Foggy Harbor Café (fictional)",
        "formattedAddress": "Valencia Street, San Francisco, CA 94110",
        "location": {
          "latitude": 37.7599,
          "longitude": -122.4214
        },
        "rating": 4.7,
        "userRatingCount": 1850,
        "placeType": "cafe"
      },
      {
        "displayName": "Morning Compass Coffee (fictional)",
        "formattedAddress": "Columbus Avenue, San Francisco, CA 94133",
        "location": {
          "latitude": 37.8024,
          "longitude": -122.41
        },
        "rating": 4.6,
        "userRatingCount": 1240,
        "placeType": "cafe"
      },
      {
        "displayName": "Brightleaf Roasters (fictional)",
        "formattedAddress": "Hayes Street, San Francisco, CA 94102",
        "location": {
          "latitude": 37.776,
          "longitude": -122.4234
        },
        "rating": 4.5,
        "userRatingCount": 980,
        "placeType": "cafe"
      },
      {
        "displayName": "Linden Park Coffee House (fictional)",
        "formattedAddress": "Clement Street, San Francisco, CA 94118",
        "location": {
          "latitude": 37.7825,
          "longitude": -122.4647
        },
        "rating": 4.4,
        "userRatingCount": 760,
        "placeType": "cafe"
      }
    ]
  },
  {
    "id": "store-example-maps-search-2",
    "query": "Italian restaurants near Times Square, New York",
    "query_translation_key": "settings.app_store_examples.maps.search.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "displayName": "Trattoria del Sole (fictional)",
        "formattedAddress": "West 46th Street, New York, NY 10036",
        "location": {
          "latitude": 40.7598,
          "longitude": -73.9873
        },
        "rating": 4.6,
        "userRatingCount": 2140,
        "placeType": "italian_restaurant"
      },
      {
        "displayName": "Osteria Rosetta (fictional)",
        "formattedAddress": "West 55th Street, New York, NY 10019",
        "location": {
          "latitude": 40.7646,
          "longitude": -73.9837
        },
        "rating": 4.5,
        "userRatingCount": 1820,
        "placeType": "italian_restaurant"
      },
      {
        "displayName": "La Piazza Nova (fictional)",
        "formattedAddress": "West 44th Street, New York, NY 10036",
        "location": {
          "latitude": 40.758,
          "longitude": -73.9855
        },
        "rating": 4.4,
        "userRatingCount": 1520,
        "placeType": "italian_restaurant"
      },
      {
        "displayName": "Vico's Tavola (fictional)",
        "formattedAddress": "9th Avenue, New York, NY 10019",
        "location": {
          "latitude": 40.7628,
          "longitude": -73.9914
        },
        "rating": 4.3,
        "userRatingCount": 980,
        "placeType": "italian_restaurant"
      }
    ]
  },
  {
    "id": "store-example-maps-search-3",
    "query": "Bookstores in central London",
    "query_translation_key": "settings.app_store_examples.maps.search.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "displayName": "The Inkwell Bookshop (fictional)",
        "formattedAddress": "Great Russell Street, London WC1B",
        "location": {
          "latitude": 51.5194,
          "longitude": -0.127
        },
        "rating": 4.8,
        "userRatingCount": 2340,
        "placeType": "book_store"
      },
      {
        "displayName": "Maple & Mortar Books (fictional)",
        "formattedAddress": "Long Acre, London WC2E",
        "location": {
          "latitude": 51.5133,
          "longitude": -0.124
        },
        "rating": 4.7,
        "userRatingCount": 1980,
        "placeType": "book_store"
      },
      {
        "displayName": "The Reading Lantern (fictional)",
        "formattedAddress": "Charing Cross Road, London WC2H",
        "location": {
          "latitude": 51.5148,
          "longitude": -0.129
        },
        "rating": 4.6,
        "userRatingCount": 1520,
        "placeType": "book_store"
      },
      {
        "displayName": "Westhaven Books & Tea (fictional)",
        "formattedAddress": "Aldersgate Street, London EC1A",
        "location": {
          "latitude": 51.5203,
          "longitude": -0.0962
        },
        "rating": 4.5,
        "userRatingCount": 1100,
        "placeType": "book_store"
      }
    ]
  }
]

export default examples;
