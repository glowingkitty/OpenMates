/**
 * App-store examples for the maps skill.
 *
 * EU-focused everyday queries (bakeries in Paris, family parks in Berlin, tapas bars in Barcelona). Real coordinates and real street names so the map renders authentic neighbourhoods; only the business names are invented.
 *
 * Names of specific businesses, doctors, venues and organisers are
 * hand-crafted and clearly fictional (most marked "(fictional)") so
 * the app store never promotes real-world entities. Geography and
 * street names are REAL (EU cities) so maps and addresses render
 * authentically. A "Sample data" banner is shown above the fullscreen
 * via the is_store_example flag set by SkillExamplesSection.
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
    "query": "Bakeries and cafés in central Paris",
    "query_translation_key": "settings.app_store_examples.maps.search.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "displayName": "Boulangerie des Roses (fictional)",
        "formattedAddress": "Rue Vieille du Temple, 75003 Paris",
        "location": {
          "latitude": 48.8587,
          "longitude": 2.3613
        },
        "rating": 4.7,
        "userRatingCount": 1820,
        "placeType": "bakery"
      },
      {
        "displayName": "Café du Clocher (fictional)",
        "formattedAddress": "Rue des Abbesses, 75018 Paris",
        "location": {
          "latitude": 48.8841,
          "longitude": 2.3379
        },
        "rating": 4.6,
        "userRatingCount": 1420,
        "placeType": "cafe"
      },
      {
        "displayName": "Pâtisserie Petit Marin (fictional)",
        "formattedAddress": "Rue de Buci, 75006 Paris",
        "location": {
          "latitude": 48.853,
          "longitude": 2.3373
        },
        "rating": 4.5,
        "userRatingCount": 980,
        "placeType": "bakery"
      },
      {
        "displayName": "Le Comptoir Noisette (fictional)",
        "formattedAddress": "Quai de Valmy, 75010 Paris",
        "location": {
          "latitude": 48.8716,
          "longitude": 2.366
        },
        "rating": 4.4,
        "userRatingCount": 760,
        "placeType": "cafe"
      }
    ]
  },
  {
    "id": "store-example-maps-search-2",
    "query": "Family-friendly parks in Berlin",
    "query_translation_key": "settings.app_store_examples.maps.search.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "displayName": "Lindenring Park (fictional)",
        "formattedAddress": "Straße des 17. Juni, 10623 Berlin",
        "location": {
          "latitude": 52.5145,
          "longitude": 13.3501
        },
        "rating": 4.8,
        "userRatingCount": 2340,
        "placeType": "park"
      },
      {
        "displayName": "Morgenwiese Spielplatz (fictional)",
        "formattedAddress": "Schönhauser Allee, 10437 Berlin",
        "location": {
          "latitude": 52.5407,
          "longitude": 13.4108
        },
        "rating": 4.7,
        "userRatingCount": 1520,
        "placeType": "park"
      },
      {
        "displayName": "Viktoriahain Family Garden (fictional)",
        "formattedAddress": "Mehringdamm, 10965 Berlin",
        "location": {
          "latitude": 52.4921,
          "longitude": 13.3871
        },
        "rating": 4.6,
        "userRatingCount": 1240,
        "placeType": "park"
      },
      {
        "displayName": "Sonnenbogen Community Garden (fictional)",
        "formattedAddress": "Boxhagener Straße, 10245 Berlin",
        "location": {
          "latitude": 52.5117,
          "longitude": 13.4594
        },
        "rating": 4.5,
        "userRatingCount": 890,
        "placeType": "park"
      }
    ]
  },
  {
    "id": "store-example-maps-search-3",
    "query": "Tapas bars in central Barcelona",
    "query_translation_key": "settings.app_store_examples.maps.search.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "displayName": "La Plaza del Sol (fictional)",
        "formattedAddress": "Passeig de Joan de Borbó, 08003 Barcelona",
        "location": {
          "latitude": 41.3808,
          "longitude": 2.1905
        },
        "rating": 4.7,
        "userRatingCount": 2150,
        "placeType": "tapas_bar"
      },
      {
        "displayName": "Tapas Sant Jordi (fictional)",
        "formattedAddress": "Carrer de la Mercè, 08002 Barcelona",
        "location": {
          "latitude": 41.3817,
          "longitude": 2.1793
        },
        "rating": 4.6,
        "userRatingCount": 1680,
        "placeType": "tapas_bar"
      },
      {
        "displayName": "Bodega del Born (fictional)",
        "formattedAddress": "Passeig del Born, 08003 Barcelona",
        "location": {
          "latitude": 41.3841,
          "longitude": 2.183
        },
        "rating": 4.5,
        "userRatingCount": 1420,
        "placeType": "tapas_bar"
      },
      {
        "displayName": "Taverna Lluna (fictional)",
        "formattedAddress": "Plaça del Sol, 08012 Barcelona",
        "location": {
          "latitude": 41.4033,
          "longitude": 2.1547
        },
        "rating": 4.4,
        "userRatingCount": 980,
        "placeType": "tapas_bar"
      }
    ]
  }
]

export default examples;
