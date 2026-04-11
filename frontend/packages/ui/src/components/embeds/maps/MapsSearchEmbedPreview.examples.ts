/**
 * App-store examples for the maps skill.
 *
 * Invented business names and addresses so the app store does not promote specific real-world places.
 *
 * These are hand-crafted synthetic fixtures. All names, addresses,
 * prices and ratings are invented so that the app store never promotes
 * specific real-world businesses, doctors, landlords or venues. The
 * shape matches the real provider response so the preview + fullscreen
 * render identically. A "Sample data" banner is shown at the top of
 * the fullscreen via the is_store_example flag set by SkillExamplesSection.
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
        "displayName": "The Foggy Harbor Café",
        "formattedAddress": "123 Sample Street, Sample City 94103",
        "location": {
          "latitude": 37.774,
          "longitude": -122.419
        },
        "rating": 4.7,
        "userRatingCount": 1850,
        "placeType": "cafe"
      },
      {
        "displayName": "Morning Compass Coffee",
        "formattedAddress": "456 Example Avenue, Sample City 94110",
        "location": {
          "latitude": 37.758,
          "longitude": -122.414
        },
        "rating": 4.6,
        "userRatingCount": 1240,
        "placeType": "cafe"
      },
      {
        "displayName": "Brightleaf Roasters",
        "formattedAddress": "789 Demo Lane, Sample City 94117",
        "location": {
          "latitude": 37.769,
          "longitude": -122.447
        },
        "rating": 4.5,
        "userRatingCount": 980,
        "placeType": "cafe"
      },
      {
        "displayName": "Linden Park Coffee House",
        "formattedAddress": "321 Fictional Road, Sample City 94114",
        "location": {
          "latitude": 37.76,
          "longitude": -122.432
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
        "formattedAddress": "100 Example Broadway, Sample City 10036",
        "location": {
          "latitude": 40.758,
          "longitude": -73.985
        },
        "rating": 4.6,
        "userRatingCount": 2140,
        "placeType": "italian_restaurant"
      },
      {
        "displayName": "Osteria Rosetta (fictional)",
        "formattedAddress": "22 Demo 46th Street, Sample City 10036",
        "location": {
          "latitude": 40.757,
          "longitude": -73.984
        },
        "rating": 4.5,
        "userRatingCount": 1820,
        "placeType": "italian_restaurant"
      },
      {
        "displayName": "La Piazza Nova (fictional)",
        "formattedAddress": "88 Sample 42nd Street, Sample City 10036",
        "location": {
          "latitude": 40.756,
          "longitude": -73.988
        },
        "rating": 4.4,
        "userRatingCount": 1520,
        "placeType": "italian_restaurant"
      },
      {
        "displayName": "Vico's Tavola (fictional)",
        "formattedAddress": "15 Example 48th Street, Sample City 10036",
        "location": {
          "latitude": 40.759,
          "longitude": -73.983
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
        "formattedAddress": "12 Example Bloomsbury Street, Sample City WC1B 3QA",
        "location": {
          "latitude": 51.517,
          "longitude": -0.126
        },
        "rating": 4.8,
        "userRatingCount": 2340,
        "placeType": "book_store"
      },
      {
        "displayName": "Maple & Mortar Books (fictional)",
        "formattedAddress": "44 Demo Charing Road, Sample City WC2H 0BL",
        "location": {
          "latitude": 51.514,
          "longitude": -0.128
        },
        "rating": 4.7,
        "userRatingCount": 1980,
        "placeType": "book_store"
      },
      {
        "displayName": "The Reading Lantern (fictional)",
        "formattedAddress": "7 Fictional Great Russell Street, Sample City WC1B 3NH",
        "location": {
          "latitude": 51.518,
          "longitude": -0.127
        },
        "rating": 4.6,
        "userRatingCount": 1520,
        "placeType": "book_store"
      },
      {
        "displayName": "Westhaven Books & Tea (fictional)",
        "formattedAddress": "99 Example Fleet Street, Sample City EC4Y 1HT",
        "location": {
          "latitude": 51.513,
          "longitude": -0.107
        },
        "rating": 4.5,
        "userRatingCount": 1100,
        "placeType": "book_store"
      }
    ]
  }
]

export default examples;
