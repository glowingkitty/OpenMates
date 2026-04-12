/**
 * App-store examples for the events skill.
 *
 * EU-focused everyday queries (farmers markets in Lyon, family weekend events in Vienna, summer concerts in Amsterdam).
 *
 * Names of specific businesses, doctors, venues and organisers are
 * hand-crafted and clearly fictional (most marked "(fictional)") so
 * the app store never promotes real-world entities. Geography and
 * street names are REAL (EU cities) so maps and addresses render
 * authentically. A "Sample data" banner is shown above the fullscreen
 * via the is_store_example flag set by SkillExamplesSection.
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
          "country": "France"
        },
        "organizer": {
          "name": "Marché Collective Sample"
        },
        "rsvp_count": 420,
        "is_paid": false
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
          "country": "France"
        },
        "organizer": {
          "name": "Terroir Sample"
        },
        "rsvp_count": 1120,
        "is_paid": true
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
          "country": "France"
        },
        "organizer": {
          "name": "Atelier Collective Sample"
        },
        "rsvp_count": 45,
        "is_paid": true
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
          "country": "Austria"
        },
        "organizer": {
          "name": "Sample Family Collective"
        },
        "rsvp_count": 520,
        "is_paid": false
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
          "country": "Austria"
        },
        "organizer": {
          "name": "Kindertheater Sample"
        },
        "rsvp_count": 80,
        "is_paid": true
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
          "country": "Austria"
        },
        "organizer": {
          "name": "Sample Running Club"
        },
        "rsvp_count": 720,
        "is_paid": false
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
          "country": "Netherlands"
        },
        "organizer": {
          "name": "Sample Chamber"
        },
        "rsvp_count": 160,
        "is_paid": true
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
          "country": "Netherlands"
        },
        "organizer": {
          "name": "Jazz Collective Sample"
        },
        "rsvp_count": 340,
        "is_paid": false
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
          "country": "Netherlands"
        },
        "organizer": {
          "name": "Zomeravond Sample"
        },
        "rsvp_count": 180,
        "is_paid": true
      }
    ]
  }
]

export default examples;
