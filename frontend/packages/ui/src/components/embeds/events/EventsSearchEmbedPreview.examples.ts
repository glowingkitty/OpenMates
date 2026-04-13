/**
 * Invented events with real venue coordinates across EU cities. Photos generated via Gemini and served as static assets under /store-examples/.
 */

export interface EventsSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: EventsSearchStoreExample[] = [
  {
    "id": "store-example-events-search-1",
    "query": "Farmers markets and food festivals in Lyon",
    "query_translation_key": "settings.app_store_examples.events.search.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "ev-1-1",
        "provider": "Sample Data",
        "title": "Marché du Printemps (fictional)",
        "description": "Invented weekly farmers market with local produce, cheeses and charcuterie from small regional farms.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-05-09T08:00:00",
        "date_end": "2026-05-09T14:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Place Sample",
          "city": "Lyon",
          "country": "France",
          "lat": 45.764,
          "lon": 4.8357
        },
        "organizer": {
          "name": "Marché Collective Sample"
        },
        "rsvp_count": 420,
        "is_paid": false,
        "image_url": "/store-examples/events-1.webp",
        "cover_url": "/store-examples/events-1.webp"
      },
      {
        "id": "ev-1-2",
        "provider": "Sample Data",
        "title": "Festival du Terroir (fictional)",
        "description": "Invented two-day food festival celebrating invented regional specialities with tastings and cooking workshops.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-05-16T10:00:00",
        "date_end": "2026-05-17T22:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Parc Invented",
          "city": "Lyon",
          "country": "France",
          "lat": 45.7715,
          "lon": 4.8486
        },
        "organizer": {
          "name": "Terroir Sample"
        },
        "rsvp_count": 1120,
        "is_paid": true,
        "image_url": "/store-examples/events-1.webp",
        "cover_url": "/store-examples/events-1.webp"
      },
      {
        "id": "ev-1-3",
        "provider": "Sample Data",
        "title": "Atelier Pain & Pâtisserie (fictional)",
        "description": "Invented beginner-friendly bread and pastry workshop run by a fictional local baker.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-05-23T10:00:00",
        "date_end": "2026-05-23T13:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Atelier Sample",
          "city": "Lyon",
          "country": "France",
          "lat": 45.7578,
          "lon": 4.832
        },
        "organizer": {
          "name": "Atelier Collective Sample"
        },
        "rsvp_count": 45,
        "is_paid": true,
        "image_url": "/store-examples/events-1.webp",
        "cover_url": "/store-examples/events-1.webp"
      }
    ]
  },
  {
    "id": "store-example-events-search-2",
    "query": "Family weekend events in Vienna",
    "query_translation_key": "settings.app_store_examples.events.search.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "ev-2-1",
        "provider": "Sample Data",
        "title": "Familienfest am Invented Park (fictional)",
        "description": "Invented outdoor family day with games, face painting and a small petting zoo.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-06-06T11:00:00",
        "date_end": "2026-06-06T17:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Sample Park",
          "city": "Vienna",
          "country": "Austria",
          "lat": 48.2047,
          "lon": 16.4142
        },
        "organizer": {
          "name": "Sample Family Collective"
        },
        "rsvp_count": 520,
        "is_paid": false,
        "image_url": "/store-examples/events-2.webp",
        "cover_url": "/store-examples/events-2.webp"
      },
      {
        "id": "ev-2-2",
        "provider": "Sample Data",
        "title": "Kindertheater: Der Goldene Stern (fictional)",
        "description": "Invented live puppet theatre show for children aged 4-10, runs every Saturday in June.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-06-13T15:00:00",
        "date_end": "2026-06-13T16:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Kleine Bühne Sample",
          "city": "Vienna",
          "country": "Austria",
          "lat": 48.2092,
          "lon": 16.3728
        },
        "organizer": {
          "name": "Kindertheater Sample"
        },
        "rsvp_count": 80,
        "is_paid": true,
        "image_url": "/store-examples/events-2.webp",
        "cover_url": "/store-examples/events-2.webp"
      },
      {
        "id": "ev-2-3",
        "provider": "Sample Data",
        "title": "Donauinsel Sommerlauf (fictional)",
        "description": "Invented 5 km family fun run along the Donauinsel with a small afterparty.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-06-20T09:00:00",
        "date_end": "2026-06-20T12:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Donauinsel Sample",
          "city": "Vienna",
          "country": "Austria",
          "lat": 48.2306,
          "lon": 16.4128
        },
        "organizer": {
          "name": "Sample Running Club"
        },
        "rsvp_count": 720,
        "is_paid": false,
        "image_url": "/store-examples/events-2.webp",
        "cover_url": "/store-examples/events-2.webp"
      }
    ]
  },
  {
    "id": "store-example-events-search-3",
    "query": "Summer concerts in Amsterdam",
    "query_translation_key": "settings.app_store_examples.events.search.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "ev-3-1",
        "provider": "Sample Data",
        "title": "Canal Garden Concert (fictional)",
        "description": "Invented open-air string quartet performance in an invented canal-side garden.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-07-04T19:30:00",
        "date_end": "2026-07-04T21:30:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Sample Garden",
          "city": "Amsterdam",
          "country": "Netherlands",
          "lat": 52.3676,
          "lon": 4.8833
        },
        "organizer": {
          "name": "Sample Chamber"
        },
        "rsvp_count": 160,
        "is_paid": true,
        "image_url": "/store-examples/events-3.webp",
        "cover_url": "/store-examples/events-3.webp"
      },
      {
        "id": "ev-3-2",
        "provider": "Sample Data",
        "title": "Jazz op de Gracht (fictional)",
        "description": "Invented free outdoor jazz afternoon featuring three fictional local jazz trios.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-07-11T14:00:00",
        "date_end": "2026-07-11T18:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Invented Brug",
          "city": "Amsterdam",
          "country": "Netherlands",
          "lat": 52.372,
          "lon": 4.892
        },
        "organizer": {
          "name": "Jazz Collective Sample"
        },
        "rsvp_count": 340,
        "is_paid": false,
        "image_url": "/store-examples/events-3.webp",
        "cover_url": "/store-examples/events-3.webp"
      },
      {
        "id": "ev-3-3",
        "provider": "Sample Data",
        "title": "Zomeravond Choir Night (fictional)",
        "description": "Invented choir evening in an invented historic church with a small candlelight reception.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-07-18T20:00:00",
        "date_end": "2026-07-18T22:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Sample Kerk",
          "city": "Amsterdam",
          "country": "Netherlands",
          "lat": 52.3738,
          "lon": 4.891
        },
        "organizer": {
          "name": "Zomeravond Sample"
        },
        "rsvp_count": 180,
        "is_paid": true,
        "image_url": "/store-examples/events-3.webp",
        "cover_url": "/store-examples/events-3.webp"
      }
    ]
  }
]

export default examples;
