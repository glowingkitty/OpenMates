/**
 * App-store examples for the health skill.
 *
 * Invented doctors, practices and addresses so the app store never promotes specific real-world medical providers.
 *
 * These are hand-crafted synthetic fixtures. All names, addresses,
 * prices and ratings are invented so that the app store never promotes
 * specific real-world businesses, doctors, landlords or venues. The
 * shape matches the real provider response so the preview + fullscreen
 * render identically. A "Sample data" banner is shown at the top of
 * the fullscreen via the is_store_example flag set by SkillExamplesSection.
 */

export interface HealthSearchStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: HealthSearchStoreExample[] = [
  {
    "id": "store-example-health-search-appointments-1",
    "query": "Eye doctor in Berlin",
    "query_translation_key": "settings.app_store_examples.health.search_appointments.1",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "slot_datetime": "2026-05-04T09:00:00",
        "name": "Dr. Lena Example",
        "title": "Dr. med.",
        "speciality": "Ophthalmology",
        "address": "Sample Allee 12, 10115 Sample City",
        "gps_coordinates": {
          "latitude": 52.53,
          "longitude": 13.385
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.7,
        "rating_count": 312,
        "languages": [
          "de",
          "en"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-04T10:30:00",
        "name": "Dr. Jonas Fictional",
        "title": "Dr. med.",
        "speciality": "Ophthalmology",
        "address": "Beispielstraße 7, 10178 Sample City",
        "gps_coordinates": {
          "latitude": 52.522,
          "longitude": 13.407
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.5,
        "rating_count": 180,
        "languages": [
          "de"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-05T14:00:00",
        "name": "Prof. Dr. Anna Sample",
        "title": "Prof. Dr. med.",
        "speciality": "Ophthalmology",
        "address": "Invented Platz 3, 10245 Sample City",
        "gps_coordinates": {
          "latitude": 52.505,
          "longitude": 13.455
        },
        "insurance": "private",
        "telehealth": true,
        "rating": 4.8,
        "rating_count": 520,
        "languages": [
          "de",
          "en",
          "fr"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-06T11:15:00",
        "name": "Dr. Markus Invented",
        "title": "Dr. med.",
        "speciality": "Ophthalmology",
        "address": "Demo Chaussee 44, 10319 Sample City",
        "gps_coordinates": {
          "latitude": 52.516,
          "longitude": 13.482
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.4,
        "rating_count": 96,
        "languages": [
          "de"
        ],
        "allows_new_patients": true
      }
    ]
  },
  {
    "id": "store-example-health-search-appointments-2",
    "query": "Dermatologist in Munich",
    "query_translation_key": "settings.app_store_examples.health.search_appointments.2",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "slot_datetime": "2026-05-11T08:30:00",
        "name": "Dr. Sophie Example",
        "title": "Dr. med.",
        "speciality": "Dermatology",
        "address": "Sample Straße 5, 80331 Sample City",
        "gps_coordinates": {
          "latitude": 48.137,
          "longitude": 11.575
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.6,
        "rating_count": 245,
        "languages": [
          "de"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-11T10:00:00",
        "name": "Dr. Paul Fictional",
        "title": "Dr. med.",
        "speciality": "Dermatology",
        "address": "Beispiel Platz 2, 80539 Sample City",
        "gps_coordinates": {
          "latitude": 48.14,
          "longitude": 11.581
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.5,
        "rating_count": 182,
        "languages": [
          "de"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-12T15:30:00",
        "name": "Dr. Hanna Sample",
        "title": "Dr. med.",
        "speciality": "Dermatology",
        "address": "Invented Ring 18, 80802 Sample City",
        "gps_coordinates": {
          "latitude": 48.161,
          "longitude": 11.587
        },
        "insurance": "private",
        "telehealth": true,
        "rating": 4.8,
        "rating_count": 430,
        "languages": [
          "de",
          "en"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-13T09:45:00",
        "name": "Dr. Max Invented",
        "title": "Dr. med.",
        "speciality": "Dermatology",
        "address": "Demo Ufer 11, 80469 Sample City",
        "gps_coordinates": {
          "latitude": 48.13,
          "longitude": 11.572
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.3,
        "rating_count": 110,
        "languages": [
          "de"
        ],
        "allows_new_patients": true
      }
    ]
  },
  {
    "id": "store-example-health-search-appointments-3",
    "query": "Gynecologist in Hamburg",
    "query_translation_key": "settings.app_store_examples.health.search_appointments.3",
    "provider": "Sample Data",
    "status": "finished",
    "results": [
      {
        "slot_datetime": "2026-05-18T09:00:00",
        "name": "Dr. Clara Example",
        "title": "Dr. med.",
        "speciality": "Gynecology",
        "address": "Sample Weg 8, 20095 Sample City",
        "gps_coordinates": {
          "latitude": 53.55,
          "longitude": 9.993
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.7,
        "rating_count": 360,
        "languages": [
          "de",
          "en"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-18T11:00:00",
        "name": "Dr. Erika Fictional",
        "title": "Dr. med.",
        "speciality": "Gynecology",
        "address": "Beispiel Allee 22, 20359 Sample City",
        "gps_coordinates": {
          "latitude": 53.557,
          "longitude": 9.975
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.6,
        "rating_count": 240,
        "languages": [
          "de"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-19T15:00:00",
        "name": "Prof. Dr. Maria Sample",
        "title": "Prof. Dr. med.",
        "speciality": "Gynecology",
        "address": "Invented Kai 3, 20457 Sample City",
        "gps_coordinates": {
          "latitude": 53.541,
          "longitude": 9.992
        },
        "insurance": "private",
        "telehealth": true,
        "rating": 4.8,
        "rating_count": 580,
        "languages": [
          "de",
          "en",
          "tr"
        ],
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-05-20T08:30:00",
        "name": "Dr. Linda Invented",
        "title": "Dr. med.",
        "speciality": "Gynecology",
        "address": "Demo Chaussee 77, 20535 Sample City",
        "gps_coordinates": {
          "latitude": 53.563,
          "longitude": 10.03
        },
        "insurance": "public",
        "telehealth": false,
        "rating": 4.4,
        "rating_count": 125,
        "languages": [
          "de"
        ],
        "allows_new_patients": true
      }
    ]
  }
]

export default examples;
