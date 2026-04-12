/**
 * Invented listings, real neighbourhood coordinates. Photos generated via Gemini and served as static assets under /store-examples/.
 */

export interface HomeSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: HomeSearchStoreExample[] = [
  {
    "id": "store-example-home-search-1",
    "query": "Apartments for rent in Berlin",
    "query_translation_key": "settings.app_store_examples.home.search.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "hl-1-1",
        "title": "Bright 2-room apartment near Sample Park",
        "price": 850,
        "price_label": "850 EUR/month",
        "size_sqm": 55,
        "rooms": 2,
        "address": "Sample Straße 12, 10961 Berlin",
        "image_url": "/store-examples/home-1.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Listings",
        "listing_type": "rent",
        "latitude": 52.493,
        "longitude": 13.4,
        "furnished": false
      },
      {
        "id": "hl-1-2",
        "title": "Sunny 3-room flat with balcony",
        "price": 1200,
        "price_label": "1,200 EUR/month",
        "size_sqm": 82,
        "rooms": 3,
        "address": "Beispiel Allee 7, 10245 Berlin",
        "image_url": "/store-examples/home-1.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Listings",
        "listing_type": "rent",
        "latitude": 52.508,
        "longitude": 13.454,
        "furnished": false
      },
      {
        "id": "hl-1-3",
        "title": "Shared apartment room in Invented District",
        "price": 520,
        "price_label": "520 EUR/month",
        "size_sqm": 18,
        "rooms": 1,
        "address": "Invented Platz 2, 10437 Berlin",
        "image_url": "/store-examples/home-1.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Flatshare",
        "listing_type": "rent",
        "latitude": 52.538,
        "longitude": 13.418,
        "furnished": false
      },
      {
        "id": "hl-1-4",
        "title": "Compact studio, quiet side-street",
        "price": 680,
        "price_label": "680 EUR/month",
        "size_sqm": 32,
        "rooms": 1,
        "address": "Demo Straße 44, 10315 Berlin",
        "image_url": "/store-examples/home-1.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Listings",
        "listing_type": "rent",
        "latitude": 52.516,
        "longitude": 13.473,
        "furnished": false
      }
    ]
  },
  {
    "id": "store-example-home-search-2",
    "query": "Apartments to buy in Munich",
    "query_translation_key": "settings.app_store_examples.home.search.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "hl-2-1",
        "title": "Modern 3-room apartment with rooftop terrace",
        "price": 685000,
        "price_label": "685,000 EUR",
        "size_sqm": 98,
        "rooms": 3,
        "address": "Sample Weg 5, 80331 Munich",
        "image_url": "/store-examples/home-2.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Real Estate",
        "listing_type": "buy",
        "latitude": 48.135,
        "longitude": 11.575,
        "furnished": false
      },
      {
        "id": "hl-2-2",
        "title": "Refurbished old-building 4-room apartment",
        "price": 920000,
        "price_label": "920,000 EUR",
        "size_sqm": 132,
        "rooms": 4,
        "address": "Beispiel Ring 22, 80539 Munich",
        "image_url": "/store-examples/home-2.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Real Estate",
        "listing_type": "buy",
        "latitude": 48.144,
        "longitude": 11.582,
        "furnished": false
      },
      {
        "id": "hl-2-3",
        "title": "Light 2-room apartment near fictional park",
        "price": 495000,
        "price_label": "495,000 EUR",
        "size_sqm": 62,
        "rooms": 2,
        "address": "Invented Straße 88, 80802 Munich",
        "image_url": "/store-examples/home-2.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Real Estate",
        "listing_type": "buy",
        "latitude": 48.162,
        "longitude": 11.588,
        "furnished": false
      },
      {
        "id": "hl-2-4",
        "title": "Spacious 5-room penthouse with city view",
        "price": 1450000,
        "price_label": "1,450,000 EUR",
        "size_sqm": 168,
        "rooms": 5,
        "address": "Demo Allee 3, 80469 Munich",
        "image_url": "/store-examples/home-2.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Real Estate",
        "listing_type": "buy",
        "latitude": 48.129,
        "longitude": 11.571,
        "furnished": false
      }
    ]
  },
  {
    "id": "store-example-home-search-3",
    "query": "Homes in Hamburg Altstadt",
    "query_translation_key": "settings.app_store_examples.home.search.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "hl-3-1",
        "title": "Harbor-view 2-room apartment",
        "price": 1380,
        "price_label": "1,380 EUR/month",
        "size_sqm": 65,
        "rooms": 2,
        "address": "Sample Kai 1, 20457 Hamburg",
        "image_url": "/store-examples/home-3.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Listings",
        "listing_type": "rent",
        "latitude": 53.541,
        "longitude": 9.992,
        "furnished": false
      },
      {
        "id": "hl-3-2",
        "title": "Historic loft with brick walls",
        "price": 1650,
        "price_label": "1,650 EUR/month",
        "size_sqm": 85,
        "rooms": 2,
        "address": "Beispiel Chaussee 11, 20095 Hamburg",
        "image_url": "/store-examples/home-3.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Listings",
        "listing_type": "rent",
        "latitude": 53.55,
        "longitude": 9.993,
        "furnished": false
      },
      {
        "id": "hl-3-3",
        "title": "Studio in pedestrian zone",
        "price": 780,
        "price_label": "780 EUR/month",
        "size_sqm": 38,
        "rooms": 1,
        "address": "Invented Gasse 7, 20095 Hamburg",
        "image_url": "/store-examples/home-3.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Listings",
        "listing_type": "rent",
        "latitude": 53.552,
        "longitude": 9.995,
        "furnished": false
      },
      {
        "id": "hl-3-4",
        "title": "Family 4-room apartment with garden",
        "price": 2200,
        "price_label": "2,200 EUR/month",
        "size_sqm": 118,
        "rooms": 4,
        "address": "Demo Weg 42, 20359 Hamburg",
        "image_url": "/store-examples/home-3.webp",
        "url": "https://example.org/sample-listing",
        "provider": "Sample Listings",
        "listing_type": "rent",
        "latitude": 53.558,
        "longitude": 9.976,
        "furnished": false
      }
    ]
  }
]

export default examples;
