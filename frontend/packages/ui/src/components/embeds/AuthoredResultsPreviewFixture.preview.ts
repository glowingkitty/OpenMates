/** Account-free saved-content fixtures generated from the real backend
 * authored_results.json catalogue through normalize_authored_results_source.
 * Static presentation input only; does not establish encrypted persistence. */
import type { AuthoredResultsContent } from '../../types/authoredResult';

interface SavedChild { embed_id: string; content: Record<string, unknown> & { title: string; type: string; app_id: string; skill_id: string; embed_ref: string; authoring: { kind: string; [key: string]: unknown } }; }
const children: SavedChild[] = [
  {
    "embed_id": "777d0000-0000-4000-8000-000000000001",
    "content": {
      "date_start": "2027-01-30",
      "date_end": "2027-01-31",
      "timezone": "Europe/Brussels",
      "venue": {
        "name": "ULB",
        "city": "Brussels",
        "lat": 50.813,
        "lon": 4.382
      },
      "organizer": {
        "name": "Community organizers"
      },
      "fee": {
        "amount": 0,
        "currency": "EUR"
      },
      "url": "https://example.org/conference",
      "image_url": "https://example.org/conference.jpg",
      "title": "Supplied: events.event",
      "type": "event",
      "authoring": {
        "schema_version": 1,
        "kind": "events.event",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "events",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-01-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000002",
    "content": {
      "price_label": "EUR 1,400 / month",
      "size_sqm": 62,
      "rooms": 2,
      "city": "Berlin",
      "location_precision": "approximate",
      "location_approximate": true,
      "location_area": {
        "name": "Moabit",
        "lat": 52.532,
        "lon": 13.34,
        "radius_m": 500
      },
      "rent_components": {
        "base_rent": 1200,
        "utilities": 200,
        "currency": "EUR",
        "period": "month"
      },
      "available_from": "2027-02-01",
      "amenities": [
        "Balcony"
      ],
      "title": "Supplied: home.listing",
      "type": "listing",
      "authoring": {
        "schema_version": 1,
        "kind": "home.listing",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "home",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-02-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000003",
    "content": {
      "doctor_name": "Dr Example",
      "speciality": "Dermatology",
      "telehealth": true,
      "slot_datetime": "2027-02-01T09:00:00+01:00",
      "timezone": "Europe/Berlin",
      "booking_url": "https://example.org/clinic",
      "title": "Supplied: health.appointment",
      "type": "appointment",
      "authoring": {
        "schema_version": 1,
        "kind": "health.appointment",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "health",
      "skill_id": "search_appointments",
      "status": "finished",
      "embed_ref": "record-03-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000004",
    "content": {
      "origin": {
        "name": "Berlin Hbf",
        "lat": 52.525,
        "lon": 13.369
      },
      "destination": {
        "name": "Brussels Midi",
        "lat": 50.836,
        "lon": 4.336
      },
      "departure": "2027-01-29T07:00:00+01:00",
      "arrival": "2027-01-29T14:00:00+01:00",
      "transport_method": "train",
      "price": 120,
      "currency": "EUR",
      "legs": [
        {
          "origin": "Berlin Hbf",
          "destination": "Cologne Hbf",
          "departure": "2027-01-29T07:00:00+01:00",
          "arrival": "2027-01-29T11:00:00+01:00"
        }
      ],
      "title": "Supplied: travel.connection",
      "type": "connection",
      "authoring": {
        "schema_version": 1,
        "kind": "travel.connection",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "travel",
      "skill_id": "search_connections",
      "status": "finished",
      "embed_ref": "record-04-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000005",
    "content": {
      "name": "Example guesthouse",
      "check_in": "2027-01-29",
      "check_out": "2027-02-01",
      "currency": "EUR",
      "rate_per_night": {
        "amount": 90
      },
      "amenities": [
        "Wi-Fi"
      ],
      "title": "Supplied: travel.stay",
      "type": "stay",
      "authoring": {
        "schema_version": 1,
        "kind": "travel.stay",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "travel",
      "skill_id": "search_stays",
      "status": "finished",
      "embed_ref": "record-05-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000006",
    "content": {
      "display_name": "Example cafe",
      "coordinates": {
        "lat": 50.85,
        "lon": 4.35
      },
      "category": "cafe",
      "title": "Supplied: maps.place",
      "type": "place",
      "authoring": {
        "schema_version": 1,
        "kind": "maps.place",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "maps",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-06-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000007",
    "content": {
      "name": "Example studio",
      "city": "Brussels",
      "disciplines": [
        "Yoga"
      ],
      "title": "Supplied: fitness.location",
      "type": "location",
      "authoring": {
        "schema_version": 1,
        "kind": "fitness.location",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "fitness",
      "skill_id": "search_locations",
      "status": "finished",
      "embed_ref": "record-07-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000008",
    "content": {
      "name": "Morning yoga",
      "date": "2027-01-30",
      "time_range": "08:00–09:00",
      "venue_name": "Example studio",
      "spots_left": 3,
      "title": "Supplied: fitness.class",
      "type": "class",
      "authoring": {
        "schema_version": 1,
        "kind": "fitness.class",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "fitness",
      "skill_id": "search_classes",
      "status": "finished",
      "embed_ref": "record-08-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000009",
    "content": {
      "title": "Supplied: shopping.product",
      "brand": "Example",
      "price_cents": 2499,
      "currency_symbol": "€",
      "specifications": [
        {
          "name": "Capacity",
          "value": "1.5 L"
        }
      ],
      "type": "product",
      "authoring": {
        "schema_version": 1,
        "kind": "shopping.product",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "shopping",
      "skill_id": "search_products",
      "status": "finished",
      "embed_ref": "record-09-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000010",
    "content": {
      "title": "Supplied: jobs.job_result",
      "company": "Example",
      "remote": true,
      "work_arrangement": "Remote",
      "salary": {
        "min": 60000,
        "max": 80000,
        "currency": "EUR",
        "basis": "annual"
      },
      "type": "job_result",
      "authoring": {
        "schema_version": 1,
        "kind": "jobs.job_result",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "jobs",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-10-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000011",
    "content": {
      "title": "Draft: nutrition.recipe",
      "servings": 2,
      "total_time_minutes": 30,
      "ingredients": [
        {
          "name": "Red lentils",
          "amount": 150,
          "unit": "g"
        }
      ],
      "instructions": [
        "Rinse lentils.",
        "Simmer until tender."
      ],
      "type": "recipe",
      "authoring": {
        "schema_version": 1,
        "kind": "nutrition.recipe",
        "origin": "draft",
        "sources": []
      },
      "app_id": "nutrition",
      "skill_id": "search_recipes",
      "status": "finished",
      "embed_ref": "record-11-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000012",
    "content": {
      "url": "https://github.com/example/project",
      "full_name": "example/project",
      "primary_language": "Rust",
      "license_spdx_id": "MIT",
      "stars": 42,
      "title": "Supplied: code.repo",
      "type": "repo",
      "authoring": {
        "schema_version": 1,
        "kind": "code.repo",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "code",
      "skill_id": "search_repos",
      "status": "finished",
      "embed_ref": "record-12-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000013",
    "content": {
      "url": "https://example.org/reference",
      "description": "Reference supplied by the user.",
      "title": "Supplied: web.website",
      "type": "website",
      "authoring": {
        "schema_version": 1,
        "kind": "web.website",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "web",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-13-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000014",
    "content": {
      "url": "https://example.org/news",
      "published_at": "2026-10-26T10:00:00Z",
      "description": "Dated announcement.",
      "title": "Supplied: news.website",
      "type": "website",
      "authoring": {
        "schema_version": 1,
        "kind": "news.website",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "news",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-14-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000015",
    "content": {
      "title": "Supplied: electronics.component",
      "part_number": "EX123",
      "topology": "Buck",
      "efficiency_percent": 92,
      "bom_count": 8,
      "type": "component",
      "authoring": {
        "schema_version": 1,
        "kind": "electronics.component",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "electronics",
      "skill_id": "search_components",
      "status": "finished",
      "embed_ref": "record-15-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000016",
    "content": {
      "company": "Example plc",
      "fiscal_year": 2025,
      "period_type": "annual",
      "currency": "EUR",
      "revenue": 2000000,
      "net_income": -20000,
      "filed": "2026-03-01",
      "title": "Supplied: business.company_financial_result",
      "type": "company_financial_result",
      "authoring": {
        "schema_version": 1,
        "kind": "business.company_financial_result",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "business",
      "skill_id": "company_financials",
      "status": "finished",
      "embed_ref": "record-16-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000017",
    "content": {
      "date": "2026-10-27",
      "location_name": "Brussels",
      "temperature_min_c": 8,
      "temperature_max_c": 14,
      "hourly": [
        {
          "time": "09:00",
          "temperature_c": 10
        }
      ],
      "title": "Supplied: weather.weather_day",
      "type": "weather_day",
      "authoring": {
        "schema_version": 1,
        "kind": "weather.weather_day",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "weather",
      "skill_id": "forecast",
      "status": "finished",
      "embed_ref": "record-17-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000018",
    "content": {
      "domain_ascii": "example.org",
      "availability": "registered",
      "checked_at": "2026-10-26T10:00:00Z",
      "registration_tiers": [
        {
          "years": 1,
          "price": 12,
          "currency": "EUR"
        }
      ],
      "title": "Supplied: hosting.hosting_domain",
      "type": "hosting_domain",
      "authoring": {
        "schema_version": 1,
        "kind": "hosting.hosting_domain",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "hosting",
      "skill_id": "search_domains",
      "status": "finished",
      "embed_ref": "record-18-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000019",
    "content": {
      "body": "Draft proposal: join our community workshop.",
      "platform": "Mastodon",
      "title": "Draft: social_media.social_post",
      "type": "social_post",
      "authoring": {
        "schema_version": 1,
        "kind": "social_media.social_post",
        "origin": "draft",
        "sources": []
      },
      "app_id": "social_media",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-19-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000020",
    "content": {
      "icon_id": "mdi:calendar",
      "prefix": "mdi",
      "name": "calendar",
      "license_spdx": "Apache-2.0",
      "title": "Supplied: design.icon_result",
      "type": "icon_result",
      "authoring": {
        "schema_version": 1,
        "kind": "design.icon_result",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "design",
      "skill_id": "search_icons",
      "status": "finished",
      "embed_ref": "record-20-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000021",
    "content": {
      "image_url": "https://example.org/real-image.jpg",
      "thumbnail_url": "https://example.org/thumb.jpg",
      "attribution": "Photographer supplied by user",
      "title": "Supplied: images.image_result",
      "type": "image_result",
      "authoring": {
        "schema_version": 1,
        "kind": "images.image_result",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "images",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-21-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000022",
    "content": {
      "url": "https://example.org/video",
      "video_id": "supplied-video",
      "channel": "Example",
      "duration_seconds": 120,
      "title": "Supplied: videos.video",
      "type": "video",
      "authoring": {
        "schema_version": 1,
        "kind": "videos.video",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "videos",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-22-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000023",
    "content": {
      "source_page_url": "https://example.org/model",
      "provider": "User source",
      "creator_name": "Example",
      "license": "CC BY 4.0",
      "files_count": 2,
      "title": "Supplied: models3d.model_result",
      "type": "model_result",
      "authoring": {
        "schema_version": 1,
        "kind": "models3d.model_result",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "models3d",
      "skill_id": "search",
      "status": "finished",
      "embed_ref": "record-23-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000024",
    "content": {
      "synopsis": "A supplied film synopsis.",
      "release_date": "2026-09-15",
      "year": 2026,
      "runtime_minutes": 112,
      "genres": [
        "Drama"
      ],
      "directors": [
        "Example Director"
      ],
      "cast": [
        "Example Actor"
      ],
      "original_language": "en",
      "country_codes": [
        "GB"
      ],
      "content_rating": "12A",
      "poster_url": "https://example.org/movie-poster.jpg",
      "source_url": "https://example.org/movie",
      "score": {
        "value": 8.2,
        "scale": 10,
        "source_url": "https://example.org/movie-score",
        "source_label": "Supplied score",
        "votes": 1200,
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "title": "Supplied: tv.movie",
      "type": "tv_movie",
      "authoring": {
        "schema_version": 1,
        "kind": "tv.movie",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "tv",
      "skill_id": "movie",
      "status": "finished",
      "embed_ref": "record-24-fixture"
    }
  },
  {
    "embed_id": "777d0000-0000-4000-8000-000000000025",
    "content": {
      "synopsis": "A supplied series synopsis.",
      "first_air_date": "2023-03-01",
      "start_year": 2023,
      "last_air_date": "2026-10-01",
      "end_year": 2026,
      "series_status": "Ended",
      "genres": [
        "Comedy"
      ],
      "creators": [
        "Example Creator"
      ],
      "cast": [
        "Example Actor"
      ],
      "original_language": "en",
      "content_rating": "TV-14",
      "episode_runtime_minutes": 25,
      "season_count": 4,
      "episode_count": 30,
      "poster_url": "https://example.org/series-poster.jpg",
      "source_url": "https://example.org/series",
      "seasons": [
        {
          "season_number": 0,
          "title": "Specials",
          "episode_count": 2
        },
        {
          "season_number": 1,
          "title": "Season one",
          "synopsis": "Supplied first-season synopsis.",
          "first_air_date": "2023-03-01",
          "episode_count": 8,
          "poster_url": "https://example.org/season-one.jpg"
        }
      ],
      "title": "Supplied: tv.series",
      "type": "tv_series",
      "authoring": {
        "schema_version": 1,
        "kind": "tv.series",
        "origin": "user_provided",
        "sources": [
          {
            "url": "https://example.org/reference",
            "label": "Supplied test reference"
          }
        ],
        "observed_at": "2026-10-26T10:00:00Z"
      },
      "app_id": "tv",
      "skill_id": "series",
      "status": "finished",
      "embed_ref": "record-25-fixture"
    }
  }
];
const carrierId = '777d0000-0000-4000-8000-000000001000';
function fixture(selected: typeof children, mode: 'auto' | 'cards' | 'map' = 'cards', pendingCount = 0) {
  const content: AuthoredResultsContent = { type: 'authored_results', app_id: 'ai', skill_id: 'authored_results',
    schema_version: 1, title: 'Supplied typed records', status: 'finished',
    embed_ids: selected.map(child => child.embed_id),
    items: selected.map(child => ({ embed_id: child.embed_id, kind: child.content.authoring.kind,
      title: child.content.title, embed_ref: child.content.embed_ref })),
    view: { mode, embeds: selected.map(child => child.embed_id) },
    ...(pendingCount > 0 ? { pending_count: pendingCount } : {}) };
  return { id: carrierId, content, children: selected };
}
const event = children.find(child => child.content.authoring.kind === 'events.event')!;
const mixed = children.filter(child => ['home.listing', 'health.appointment', 'tv.movie'].includes(child.content.authoring.kind));
const mapped = children.filter(child => ['home.listing', 'health.appointment', 'tv.movie', 'travel.connection'].includes(child.content.authoring.kind));
const timed = { ...event, content: { ...event.content, date_start: '2027-01-30T09:00:00+01:00',
  date_end: undefined, title: 'Supplied event with unknown end' } };
const dateOnly = { ...event, content: { ...event.content, date_start: '2027-01-30',
  date_end: undefined, title: 'Supplied date-only event' } };
// Two dated conference cards. Each is a distinct stored embed with its own reference.
function conference(suffix: string, title: string, date: string, venue: Record<string, unknown>): SavedChild {
  return { embed_id: `777d0000-0000-4000-8000-0000000000${suffix}`,
    content: { ...event.content, title, date_start: date, date_end: undefined, venue,
      image_url: undefined, embed_ref: `conference-${suffix}-fixture` } };
}
const mappedVenue = { name: 'ULB', city: 'Brussels', lat: 50.813, lon: 4.382 };
const calendarAndMap = [
  conference('e1', 'Open source conference: opening day', '2027-01-30', mappedVenue),
  conference('e2', 'Open source conference: workshops', '2027-01-31', { ...mappedVenue, name: 'Solbosch campus', lat: 50.81, lon: 4.38 }),
];
const calendarOnly = [
  conference('e3', 'Online talk series: first session', '2027-01-30', { name: 'Online', city: 'Online' }),
  conference('e4', 'Online talk series: second session', '2027-01-31', { name: 'Online', city: 'Online' }),
];
const partial = fixture([event], 'auto');
partial.content.validation = { status: 'partial', warnings: [{ code: 'invalid_item', path: 'items[1]' }] };
const streaming = { ...fixture([], 'auto'), children: [event],
  content: { ...fixture([], 'auto').content, status: 'processing' as const },
  hydrateContent: fixture([event], 'auto').content };
const tv = fixture(children.filter(child => ['tv.movie', 'tv.series'].includes(child.content.authoring.kind)));
// Deliberately conflicting legacy media and explicit authored media: the
// mounted projection must win without rewriting the saved record.
function overrideChild(kind: string, details: Record<string, unknown>) {
  const child = children.find(value => value.content.authoring.kind === kind)!;
  return { ...child, content: { ...child.content, ...details } };
}
const projectedImages = ['events.event', 'tv.movie', 'home.listing', 'health.appointment'].map(kind => {
  const child = children.find(value => value.content.authoring.kind === kind)!;
  return overrideChild(kind, {
    ...(kind === 'home.listing' ? { image_url: 'https://example.org/legacy-home.jpg',
      image_urls: ['https://example.org/legacy-home.jpg'] } : {}),
    ...(kind === 'health.appointment' ? { image_url: 'https://example.org/legacy-health.jpg' } : {}),
    authoring: { ...child.content.authoring,
      images: [{ url: `https://example.org/authored-${kind}.jpg`, caption: 'Explicit supplied image' }] } });
});
const numericFinancial = overrideChild('business.company_financial_result', {
  fiscal_quarter: 2, period_type: 'quarterly', cash_flow: 0,
});
const zeroWeather = overrideChild('weather.weather_day', {
  temperature_min_c: 0, temperature_max_c: 0,
  precipitation: { total_mm: 0, probability_percent: 0 },
  hourly: [{ time: '09:00', temperature_c: 0, precipitation: 0,
    precipitation_probability: 0, wind_speed_kmh: 0, humidity: 0 }],
});
export default fixture(children);
export const variants = {
  projectedImages: fixture(projectedImages),
  numericObservations: fixture([numericFinancial, zeroWeather]),
  partial, partialFullscreen: { ...partial, initialFullscreen: true }, streaming,
  tvNavigation: { ...tv, navigation: true },
  groupSource: { ...fixture([event], 'auto'), renderViaGroup: true, sourceChatId: '777d0000-0000-4000-8000-000000002000' },
  calendarAndMap: fixture(calendarAndMap, 'auto'),
  calendarOnly: fixture(calendarOnly, 'auto'),
  pending: fixture(calendarAndMap, 'auto', 2),
  matrix25: fixture(children), singleevent: fixture([event], 'auto'),
  mixed: fixture(mixed), mixedmap: fixture(mapped, 'map'),
  dateOnly: fixture([dateOnly], 'auto'), timedNoEnd: fixture([timed], 'auto'),
  processing: { ...fixture([], 'auto'), content: { ...fixture([], 'auto').content, status: 'processing' } },
  error: { ...fixture([], 'auto'), content: { ...fixture([], 'auto').content, status: 'error' } },
  cancelled: { ...fixture([], 'auto'), content: { ...fixture([], 'auto').content, status: 'cancelled' } },
};
