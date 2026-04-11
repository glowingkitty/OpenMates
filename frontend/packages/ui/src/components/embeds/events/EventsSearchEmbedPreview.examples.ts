/**
 * App-store examples for the events skill.
 *
 * Invented events, venues and organisers so the app store never endorses specific real organisations.
 *
 * These are hand-crafted synthetic fixtures. All names, addresses,
 * prices and ratings are invented so that the app store never promotes
 * specific real-world businesses, doctors, landlords or venues. The
 * shape matches the real provider response so the preview + fullscreen
 * render identically. A "Sample data" banner is shown at the top of
 * the fullscreen via the is_store_example flag set by SkillExamplesSection.
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
    "query": "Tech conferences in San Francisco",
    "query_translation_key": "settings.app_store_examples.events.search.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "ev-1-1",
        "provider": "Sample Data",
        "title": "Foundry AI Summit (Sample)",
        "description": "Invented two-day conference on applied AI for startups, with talks by fictional industry speakers.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-06-12T09:00:00",
        "date_end": "2026-06-13T18:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Harbor Tech Pavilion",
          "city": "Sample City",
          "country": "USA"
        },
        "organizer": {
          "name": "Sample Tech Community"
        },
        "rsvp_count": 320,
        "is_paid": true
      },
      {
        "id": "ev-1-2",
        "provider": "Sample Data",
        "title": "Open Source Weekend (Sample)",
        "description": "Invented community hackathon focused on open-source tooling and documentation sprints.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-06-20T10:00:00",
        "date_end": "2026-06-21T18:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Maker Barn Hall",
          "city": "Sample City",
          "country": "USA"
        },
        "organizer": {
          "name": "Open Source Collective Sample"
        },
        "rsvp_count": 180,
        "is_paid": false
      },
      {
        "id": "ev-1-3",
        "provider": "Sample Data",
        "title": "Women in Data Meetup (Sample)",
        "description": "Invented monthly meetup covering data engineering career paths and technical talks.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-06-25T18:30:00",
        "date_end": "2026-06-25T21:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Lantern Studios",
          "city": "Sample City",
          "country": "USA"
        },
        "organizer": {
          "name": "Women in Data Sample Chapter"
        },
        "rsvp_count": 95,
        "is_paid": false
      }
    ]
  },
  {
    "id": "store-example-events-search-2",
    "query": "Live music concerts in Berlin",
    "query_translation_key": "settings.app_store_examples.events.search.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "ev-2-1",
        "provider": "Sample Data",
        "title": "Midnight Glow Live (Sample)",
        "description": "Invented indie band performing original songs plus a string quartet opener.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-07-04T20:00:00",
        "date_end": "2026-07-04T23:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Echo Garden Hall",
          "city": "Sample City",
          "country": "Germany"
        },
        "organizer": {
          "name": "Sample Concerts"
        },
        "rsvp_count": 450,
        "is_paid": true
      },
      {
        "id": "ev-2-2",
        "provider": "Sample Data",
        "title": "Kleine Nacht Jazz (Sample)",
        "description": "Invented jazz trio evening featuring standards and original compositions.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-07-11T19:30:00",
        "date_end": "2026-07-11T22:30:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Blue Lantern Club",
          "city": "Sample City",
          "country": "Germany"
        },
        "organizer": {
          "name": "Nachtklang Sample"
        },
        "rsvp_count": 140,
        "is_paid": true
      },
      {
        "id": "ev-2-3",
        "provider": "Sample Data",
        "title": "Electronic Horizons Open Air (Sample)",
        "description": "Invented open-air electronic music event with invented local DJs.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-07-18T16:00:00",
        "date_end": "2026-07-18T23:59:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Riverside Field",
          "city": "Sample City",
          "country": "Germany"
        },
        "organizer": {
          "name": "Horizons Sample Collective"
        },
        "rsvp_count": 2100,
        "is_paid": true
      }
    ]
  },
  {
    "id": "store-example-events-search-3",
    "query": "Art exhibitions in London",
    "query_translation_key": "settings.app_store_examples.events.search.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "id": "ev-3-1",
        "provider": "Sample Data",
        "title": "Light & Shadow: Contemporary Portraits (Sample)",
        "description": "Invented exhibition of fictional contemporary photographers exploring natural light.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-08-01T10:00:00",
        "date_end": "2026-08-30T18:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Northfield Gallery",
          "city": "Sample City",
          "country": "United Kingdom"
        },
        "organizer": {
          "name": "Northfield Sample Trust"
        },
        "rsvp_count": 0,
        "is_paid": true
      },
      {
        "id": "ev-3-2",
        "provider": "Sample Data",
        "title": "Invented Colour Festival (Sample)",
        "description": "Invented modern art retrospective featuring invented mixed-media sculptors.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-08-05T11:00:00",
        "date_end": "2026-08-18T19:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "The Atrium Hall",
          "city": "Sample City",
          "country": "United Kingdom"
        },
        "organizer": {
          "name": "Atrium Sample"
        },
        "rsvp_count": 0,
        "is_paid": false
      },
      {
        "id": "ev-3-3",
        "provider": "Sample Data",
        "title": "Printmakers in Residence (Sample)",
        "description": "Invented live printmaking demonstrations with a small fictional artist collective.",
        "url": "https://example.org/sample-event",
        "date_start": "2026-08-10T10:00:00",
        "date_end": "2026-08-12T17:00:00",
        "timezone": "Europe/Berlin",
        "event_type": "PHYSICAL",
        "venue": {
          "name": "Westhaven Print Studio",
          "city": "Sample City",
          "country": "United Kingdom"
        },
        "organizer": {
          "name": "Westhaven Sample"
        },
        "rsvp_count": 0,
        "is_paid": false
      }
    ]
  }
]

export default examples;
