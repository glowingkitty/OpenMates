/**
 * App-store examples for the health skill.
 *
 * Captured from real Doctolib/Jameda appointment search responses, trimmed to 5 appointments per query.
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
    "query": "Augenarzt in Berlin",
    "query_translation_key": "settings.app_store_examples.health.search_appointments.1",
    "provider": "Doctolib, Jameda",
    "status": "finished",
    "results": [
      {
        "slot_datetime": "2026-04-13T08:20:00.000+02:00",
        "name": "Augenarzt Kreuzberg - Grauer Star, Grüner Star, AMD & Augenlasern",
        "doctor_type": "ORGANIZATION",
        "speciality": "Augenarzt",
        "address": "Gneisenaustraße 115, 10961 Berlin",
        "gps_coordinates": {
          "latitude": 52.4930835,
          "longitude": 13.3884183
        },
        "languages": [],
        "telehealth": false,
        "insurance": "public",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:00:00.000+02:00",
        "name": "Augenarzt Eastgate - Grauer Star, Grüner Star, AMD & Augenlasern",
        "doctor_type": "ORGANIZATION",
        "speciality": "Augenarzt",
        "address": "Marzahner Promenade 1A, 12679 Berlin",
        "gps_coordinates": {
          "latitude": 52.5436813,
          "longitude": 13.5448268
        },
        "languages": [],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:25:00.000+02:00",
        "name": "Mehmet emin  Sucu",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Augenarzt",
        "address": "Nürnberger Straße 67, 10787 Berlin",
        "gps_coordinates": {
          "latitude": 52.504344,
          "longitude": 13.340916
        },
        "languages": [],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:40:00.000+02:00",
        "name": "Dr. med. Jan Jerrentrup",
        "title": "Dr. med.",
        "gender": "male",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Augenarzt",
        "address": "Rheinbabenallee 12, 14199 Berlin",
        "gps_coordinates": {
          "latitude": 52.47529,
          "longitude": 13.28357010000002
        },
        "languages": [
          "de",
          "gb"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:00:00.000+02:00",
        "name": "Augenarzt Weißensee - Grauer Star, Grüner Star, AMD & Augenlasern",
        "doctor_type": "ORGANIZATION",
        "speciality": "Augenarzt",
        "address": "Schönstraße 5-7, 13086 Berlin",
        "gps_coordinates": {
          "latitude": 52.5534928,
          "longitude": 13.4504461
        },
        "languages": [],
        "telehealth": false,
        "insurance": "unknown",
        "allows_new_patients": true
      }
    ]
  },
  {
    "id": "store-example-health-search-appointments-2",
    "query": "Hautarzt in München",
    "query_translation_key": "settings.app_store_examples.health.search_appointments.2",
    "provider": "Doctolib, Jameda",
    "status": "finished",
    "results": [
      {
        "slot_datetime": "2026-04-13T10:00:00.000+02:00",
        "name": "Dr. Can Cengiz",
        "title": "Dr.",
        "gender": "female",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Hautärztin",
        "address": "Bauseweinallee 2, 81247 München",
        "gps_coordinates": {
          "latitude": 48.1646324,
          "longitude": 11.4767602
        },
        "languages": [
          "de",
          "gb"
        ],
        "telehealth": false,
        "insurance": "public",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:00:00.000+02:00",
        "name": "Prof. Dr. Dr. med. Markus Reinholz - Dermatologie",
        "doctor_type": "ORGANIZATION",
        "speciality": "Hautarzt",
        "address": "Leopoldstraße 102, 80802 München",
        "gps_coordinates": {
          "latitude": 48.1650189,
          "longitude": 11.5867537
        },
        "languages": [
          "de",
          "gb",
          "fr",
          "es"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:10:00.000+02:00",
        "name": "Dr. med. Hannes  Reinhardt  ",
        "title": "Dr. med.",
        "gender": "male",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Hautarzt",
        "address": "Wendl-Dietrich-Straße 6, 80634 München",
        "gps_coordinates": {
          "latitude": 48.1527462,
          "longitude": 11.53125620000003
        },
        "languages": [
          "de",
          "gb",
          "es"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T09:15:00.000+02:00",
        "name": "Dr. med. Julia Walch",
        "title": "Dr. med.",
        "gender": "female",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Hautärztin",
        "address": "Nördliches Schloßrondell 10, 80638 München",
        "gps_coordinates": {
          "latitude": 48.1606181,
          "longitude": 11.506871
        },
        "languages": [
          "de",
          "gb"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T09:25:00.000+02:00",
        "name": "Dr. med. Florian Kapp",
        "title": "Dr. med.",
        "gender": "male",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Hautarzt",
        "address": "Gottfried-Keller-Straße 33, 81245 München",
        "gps_coordinates": {
          "latitude": 48.1505257,
          "longitude": 11.4640658
        },
        "languages": [
          "de",
          "gb"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      }
    ]
  },
  {
    "id": "store-example-health-search-appointments-3",
    "query": "Gynäkologe in Hamburg",
    "query_translation_key": "settings.app_store_examples.health.search_appointments.3",
    "provider": "Doctolib, Jameda",
    "status": "finished",
    "results": [
      {
        "slot_datetime": "2026-04-13T08:00:00.000+02:00",
        "name": "Dr. Christina Schäfer",
        "title": "Dr.",
        "gender": "female",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Frauenärztin",
        "address": "Hoheluftchaussee 52, 20253 Hamburg",
        "gps_coordinates": {
          "latitude": 53.5808768,
          "longitude": 9.9736376
        },
        "languages": [
          "de"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:00:00.000+02:00",
        "name": "André Meidel",
        "title": "",
        "gender": "male",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Frauenarzt",
        "address": "Eppendorfer Baum 35, 20249 Hamburg",
        "gps_coordinates": {
          "latitude": 53.5842214,
          "longitude": 9.9820354
        },
        "languages": [
          "gb",
          "fr"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:00:00.000+02:00",
        "name": "Dr. med. Bastian Radtke",
        "title": "Dr. med.",
        "gender": "male",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Frauenarzt",
        "address": "Bellmannstraße 5, 22607 Hamburg",
        "gps_coordinates": {
          "latitude": 53.560249,
          "longitude": 9.8847877
        },
        "languages": [
          "de",
          "gb"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T08:30:00.000+02:00",
        "name": "Dr. med. Claudia Nawroth",
        "title": "Dr. med.",
        "gender": "female",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Frauenärztin",
        "address": "Wolffstraße 9, 22525 Hamburg",
        "gps_coordinates": {
          "latitude": 53.5793289,
          "longitude": 9.933449999999999
        },
        "languages": [
          "de",
          "gb"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      },
      {
        "slot_datetime": "2026-04-13T09:00:00.000+02:00",
        "name": "Dr. med. Sabine Bachmann",
        "title": "Dr. med.",
        "gender": "female",
        "doctor_type": "INDIVIDUAL_PRACTITIONER",
        "speciality": "Frauenärztin",
        "address": "Neuer Wall 32, 20354 Hamburg",
        "gps_coordinates": {
          "latitude": 53.5519811,
          "longitude": 9.9904227
        },
        "languages": [
          "de",
          "gb"
        ],
        "telehealth": false,
        "insurance": "private",
        "allows_new_patients": true
      }
    ]
  }
]

export default examples;
