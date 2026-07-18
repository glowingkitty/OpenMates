/*
 * Generated OpenMates SDK app-skill namespaces.
 * Source: backend app metadata files
 * Regenerate with: python3 scripts/generate_sdk_app_skills.py
 */

export type AppSkillRunner = <T = unknown>(appId: string, skillId: string, input: unknown) => Promise<T>;
export type SkillInput = Record<string, unknown>;

export const APP_SKILL_METADATA = [
  {
    "app_id": "ai",
    "skill_id": "ask",
    "app_namespace_ts": "ai",
    "skill_method_ts": "ask",
    "app_namespace_py": "ai",
    "skill_method_py": "ask",
    "description_key": "ai.ask.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {
        "prompt": {
          "type": "string",
          "description": "The question or task for the Workflow AI step."
        },
        "conversation": {
          "type": "string",
          "description": "Optional run-local conversation name for retaining previous Workflow AI context in the same run."
        }
      },
      "required": [
        "prompt"
      ]
    }
  },
  {
    "app_id": "books",
    "skill_id": "translate",
    "app_namespace_ts": "books",
    "skill_method_ts": "translate",
    "app_namespace_py": "books",
    "skill_method_py": "translate",
    "description_key": "books.translate.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {}
    }
  },
  {
    "app_id": "code",
    "skill_id": "search_repos",
    "app_namespace_ts": "code",
    "skill_method_ts": "searchRepos",
    "app_namespace_py": "code",
    "skill_method_py": "search_repos",
    "description_key": "code.search_repos.description",
    "description": "Search GitHub repositories. Use this instead of web.search whenever the user asks to find GitHub repos, repositories, open-source libraries, starred repos, or repo examples by topic, language, framework, or project need. Returns licensed repository embeds. Costs 10 credits per search.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of repository search requests. Each request searches GitHub for public licensed repositories matching the query.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Repository search query, e.g. \"svelte markdown editor\", \"python cli framework\", or \"rust web server\".\n"
              },
              "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 6,
                "description": "Number of repositories to return."
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "code",
    "skill_id": "get_docs",
    "app_namespace_ts": "code",
    "skill_method_ts": "getDocs",
    "app_namespace_py": "code",
    "skill_method_py": "get_docs",
    "description_key": "code.get_docs.description",
    "description": "Get latest documentation for programming libraries, frameworks, APIs, SDKs. Use for ANY programming-related query about a specific library or framework.",
    "schema": {
      "type": "object",
      "properties": {
        "library": {
          "type": "string",
          "description": "Library name to search for (e.g., \"Svelte 5\", \"React\", \"FastAPI\", \"Miro API\", etc.).\n"
        },
        "question": {
          "type": "string",
          "description": "Natural language question about the documentation needed\n(e.g., \"How to use useState hook?\", \"How to setup routing?\").\n"
        }
      },
      "required": [
        "library",
        "question"
      ]
    }
  },
  {
    "app_id": "code",
    "skill_id": "clean_repo",
    "app_namespace_ts": "code",
    "skill_method_ts": "cleanRepo",
    "app_namespace_py": "code",
    "skill_method_py": "clean_repo",
    "description_key": "code.clean_repo.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {}
    }
  },
  {
    "app_id": "code",
    "skill_id": "get_issues",
    "app_namespace_ts": "code",
    "skill_method_ts": "getIssues",
    "app_namespace_py": "code",
    "skill_method_py": "get_issues",
    "description_key": "code.get_issues.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {}
    }
  },
  {
    "app_id": "code",
    "skill_id": "add_issue",
    "app_namespace_ts": "code",
    "skill_method_ts": "addIssue",
    "app_namespace_py": "code",
    "skill_method_py": "add_issue",
    "description_key": "code.add_issue.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {}
    }
  },
  {
    "app_id": "code",
    "skill_id": "remove_secrets",
    "app_namespace_ts": "code",
    "skill_method_ts": "removeSecrets",
    "app_namespace_py": "code",
    "skill_method_py": "remove_secrets",
    "description_key": "code.remove_secrets.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {}
    }
  },
  {
    "app_id": "code",
    "skill_id": "get_project_overview",
    "app_namespace_ts": "code",
    "skill_method_ts": "getProjectOverview",
    "app_namespace_py": "code",
    "skill_method_py": "get_project_overview",
    "description_key": "code.get_project_overview.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {}
    }
  },
  {
    "app_id": "design",
    "skill_id": "search_icons",
    "app_namespace_ts": "design",
    "skill_method_ts": "searchIcons",
    "app_namespace_py": "design",
    "skill_method_py": "search_icons",
    "description_key": "app_skills.design.search_icons.description",
    "description": "Search for free SVG icons for UI, product, interface, or graphic design. Use this when the user asks to find icons by name, concept, object, or action. Do not use it for brand-logo search or generated icon creation.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of icon search requests backed by Iconify.",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query, e.g. \"home\", \"calendar\", or \"settings\"."
              },
              "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 24,
                "description": "Maximum number of icon results to return."
              },
              "license_policy": {
                "type": "string",
                "enum": [
                  "permissive",
                  "all"
                ],
                "default": "permissive",
                "description": "Filter to permissive/no-attribution licenses by default."
              },
              "include_prefixes": {
                "type": "array",
                "items": {
                  "type": "string"
                },
                "description": "Optional Iconify collection prefixes to include."
              },
              "exclude_prefixes": {
                "type": "array",
                "items": {
                  "type": "string"
                },
                "description": "Optional Iconify collection prefixes to exclude."
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "electronics",
    "skill_id": "search_components",
    "app_namespace_ts": "electronics",
    "skill_method_ts": "searchComponents",
    "app_namespace_py": "electronics",
    "skill_method_py": "search_components",
    "description_key": "electronics.search_components.description",
    "description": "Use this skill when the user asks to find electronic components, especially power converters or voltage regulators matching input voltage, output voltage, output current, efficiency, BOM cost, footprint, or topology requirements. Currently supports category power_converters via Texas Instruments WEBENCH Power Designer.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Component search requests. Use one request per distinct power rail or component category.\n",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "description": "Optional caller-supplied ID for correlating responses."
              },
              "category": {
                "type": "string",
                "enum": [
                  "power_converters"
                ],
                "description": "Component category. Currently only power_converters is supported."
              },
              "input_voltage_min": {
                "type": "number",
                "description": "Minimum input voltage in volts. For fixed input voltage, use the same value as input_voltage_max."
              },
              "input_voltage_max": {
                "type": "number",
                "description": "Maximum input voltage in volts. For fixed input voltage, use the same value as input_voltage_min."
              },
              "output_voltage": {
                "type": "number",
                "description": "Target output voltage in volts."
              },
              "output_current_max": {
                "type": "number",
                "description": "Maximum output current in amps."
              },
              "supply_type": {
                "type": "string",
                "enum": [
                  "dc",
                  "ac"
                ],
                "default": "dc",
                "description": "dc for DC/DC converters, ac for AC/DC converters."
              },
              "isolated": {
                "type": "boolean",
                "default": false,
                "description": "Whether the design should be isolated."
              },
              "ambient_temp_c": {
                "type": "number",
                "default": 30,
                "description": "Maximum ambient temperature in degrees Celsius."
              },
              "optimization": {
                "type": "string",
                "enum": [
                  "balanced",
                  "low_cost",
                  "high_efficiency",
                  "small_footprint"
                ],
                "default": "balanced",
                "description": "Optimization goal for WEBENCH ranking."
              },
              "max_results": {
                "type": "integer",
                "default": 10,
                "description": "Maximum number of candidate components to return."
              }
            },
            "required": [
              "category",
              "input_voltage_min",
              "input_voltage_max",
              "output_voltage",
              "output_current_max"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "events",
    "skill_id": "search",
    "app_namespace_ts": "events",
    "skill_method_ts": "search",
    "app_namespace_py": "events",
    "skill_method_py": "search",
    "description_key": "events.search.description",
    "description": "Search for local or online events, meetups, hackathons, conferences, workshops, networking events, parties, concerts, or any community gathering. Use ONLY this skill for event searches \u2014 do NOT additionally call web.search or any other search skill for the same query. Sources: Meetup, Luma, Eventbrite, Google Events, Resident Advisor (electronic music/clubs), Siegess\u00e4ule (Berlin LGBTQ+ events), Berlin Philharmonic (classical concerts in Berlin), and official event schedules for GPN24, 39C3, 38C3",
    "schema": {
      "type": "object",
      "properties": {
        "provider": {
          "type": "string",
          "description": "The event provider to use. 'auto' (default) queries all providers in parallel for best coverage. Use specific providers when the user asks about a particular platform/type: 'Eventbrite' for Eventbrite-only results, 'Resident Advisor' for electronic music/clubs, 'Siegess\u00e4ule' for Berlin LGBTQ+ events, 'GPN24', '39C3', '38C3', or '37C3' for official schedules of those events.\n",
          "enum": [
            "auto",
            "Meetup",
            "Luma",
            "Eventbrite",
            "Google Events",
            "Resident Advisor",
            "Siegess\u00e4ule",
            "Berlin Philharmonic",
            "GPN24",
            "39C3",
            "38C3",
            "37C3"
          ]
        },
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of event search request objects for parallel processing.\nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single search.\nExample for single search: {\"requests\": [{\"query\": \"AI\", \"location\": \"Berlin, Germany\"}]}\nExample for multiple searches: {\"requests\": [{\"query\": \"AI\", \"location\": \"Berlin\"}, {\"query\": \"Python\", \"location\": \"Munich\"}]}\nEach object must contain 'query' and either 'location' (or lat/lon) for city searches,\nor 'conference' for GPN/Congress schedule searches. All other parameters are optional.\nNote: The 'id' field is auto-generated if not provided.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Topic or theme of events to search for (e.g. 'AI', 'Python', 'hackathon', 'startup', 'networking'). Do NOT include platform or app names such as 'meetup', 'luma', or 'eventbrite' \u2014 these are stripped automatically and reduce result quality.\n"
              },
              "location": {
                "type": "string",
                "description": "City name or 'city, country' string (e.g. 'Berlin, Germany', 'New York', 'Paris'). Used if lat/lon are not provided. Not required when using a GPN/Congress event schedule provider with a conference value."
              },
              "lat": {
                "type": "number",
                "description": "Latitude of search center (decimal degrees). Overrides location string if provided."
              },
              "lon": {
                "type": "number",
                "description": "Longitude of search center (decimal degrees). Overrides location string if provided."
              },
              "start_date": {
                "type": "string",
                "description": "Start of date range in ISO 8601 format. Include timezone if known (e.g. '2026-03-01T00:00:00+01:00[Europe/Berlin]'). If omitted, defaults to now."
              },
              "end_date": {
                "type": "string",
                "description": "End of date range in ISO 8601 format (same format as start_date). If omitted, no upper bound is applied."
              },
              "event_type": {
                "type": "string",
                "description": "Filter by event type. Use 'PHYSICAL' when user searches for events in a city (default for location-based searches). Use 'ONLINE' when user explicitly asks for virtual/online/remote events. Omit only when user wants both types.",
                "enum": [
                  "PHYSICAL",
                  "ONLINE"
                ]
              },
              "radius_miles": {
                "type": "number",
                "description": "Search radius in miles from the center coordinates (default: 25, ~40 km). Only applies to PHYSICAL events.",
                "default": 25
              },
              "count": {
                "type": "integer",
                "description": "Maximum number of events to return (default: 10, max: 50). Use 10 unless the user asks for more results.",
                "minimum": 1,
                "maximum": 50,
                "default": 10
              },
              "provider": {
                "type": "string",
                "description": "Provider for this request. Overrides the top-level provider when set.",
                "enum": [
                  "auto",
                  "Meetup",
                  "Luma",
                  "Eventbrite",
                  "Google Events",
                  "Resident Advisor",
                  "Siegess\u00e4ule",
                  "Berlin Philharmonic",
                  "GPN24",
                  "39C3",
                  "38C3",
                  "37C3"
                ]
              },
              "providers": {
                "type": "array",
                "items": {
                  "type": "string",
                  "enum": [
                    "Meetup",
                    "Luma",
                    "Eventbrite",
                    "Google Events",
                    "Resident Advisor",
                    "Siegess\u00e4ule",
                    "Berlin Philharmonic",
                    "GPN24",
                    "39C3",
                    "38C3",
                    "37C3"
                  ]
                },
                "description": "Specific providers for this request. Use only when the user asks to search multiple named event platforms."
              },
              "conference": {
                "type": "string",
                "description": "Known GPN/Congress schedule to search. Supported values: GPN24, 39C3, 38C3, 37C3.",
                "enum": [
                  "GPN24",
                  "39C3",
                  "38C3",
                  "37C3"
                ]
              },
              "past_events": {
                "type": "boolean",
                "description": "Default false. Set true only when the user explicitly asks to include past/completed conference sessions.",
                "default": false
              },
              "concert_tags": {
                "type": "array",
                "items": {
                  "type": "string"
                },
                "description": "Optional tag filters for the Berlin Philharmonic provider. Use when the user asks about classical concerts in Berlin. Known values: Piano, Chamber Music, Jazz, Organ, Modern, Lunch Concerts, Singers, Children and Family, World. Ignored by all other providers.\n"
              }
            }
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "fitness",
    "skill_id": "search_locations",
    "app_namespace_ts": "fitness",
    "skill_method_ts": "searchLocations",
    "app_namespace_py": "fitness",
    "skill_method_py": "search_locations",
    "description_key": "fitness.search_locations.description",
    "description": "Search Urban Sports Club public fitness locations. Use this when the user asks for gyms, studios, pools, or Urban Sports locations near a city, address, or radius. Do not use it for class availability; use fitness.search_classes for dated class searches.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string"
              },
              "city": {
                "type": "string"
              },
              "address": {
                "type": "string"
              },
              "lat": {
                "type": "number"
              },
              "lon": {
                "type": "number"
              },
              "radius_km": {
                "type": "number"
              },
              "plan": {
                "type": "string"
              },
              "category": {
                "type": "string"
              },
              "limit": {
                "type": "number"
              }
            }
          },
          "description": "Location search requests."
        }
      }
    }
  },
  {
    "app_id": "fitness",
    "skill_id": "search_classes",
    "app_namespace_ts": "fitness",
    "skill_method_ts": "searchClasses",
    "app_namespace_py": "fitness",
    "skill_method_py": "search_classes",
    "description_key": "fitness.search_classes.description",
    "description": "Search available Urban Sports Club public fitness classes. Use this when the user asks for dated fitness classes, course availability, free spots, on-site classes, online classes, or plan-filtered Urban Sports classes. Omit plan unless the user explicitly asks for Essential, Classic, Premium, or Max.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string"
              },
              "city": {
                "type": "string"
              },
              "address": {
                "type": "string"
              },
              "lat": {
                "type": "number"
              },
              "lon": {
                "type": "number"
              },
              "radius_km": {
                "type": "number"
              },
              "start_date": {
                "type": "string"
              },
              "end_date": {
                "type": "string"
              },
              "days": {
                "type": "number"
              },
              "plan": {
                "type": "string"
              },
              "attendance_mode": {
                "type": "string"
              },
              "min_spots": {
                "type": "number"
              },
              "category": {
                "type": "string"
              },
              "venue_id": {
                "type": "string"
              },
              "limit": {
                "type": "number"
              }
            }
          },
          "description": "Class search requests."
        }
      }
    }
  },
  {
    "app_id": "health",
    "skill_id": "search_appointments",
    "app_namespace_ts": "health",
    "skill_method_ts": "searchAppointments",
    "app_namespace_py": "health",
    "skill_method_py": "search_appointments",
    "description_key": "app_skills.health.search_appointments.description",
    "description": "Search available medical appointments at German doctors/specialists by speciality and city. Covers any medical booking \u2014 general practitioners, specialists (e.g. dentist, dermatologist, gynecologist), scans and imaging (e.g. MRT/MRI, CT, R\u00f6ntgen, Ultraschall), vaccinations, check-ups, blood tests, and other examinations. Note: \"Termin\" in a medical context means appointment, not event \u2014 route here instead of events-search. Sources: Doctolib, Jameda (Germany only).",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of appointment search requests. Each request searches for available doctor appointments for a given speciality and city.\n",
          "items": {
            "type": "object",
            "properties": {
              "speciality": {
                "type": "string",
                "description": "Doctor speciality or type. Supports German and English names. Examples: \"augenarzt\", \"hautarzt\", \"allgemeinmedizin\", \"zahnarzt\", \"gyn\u00e4kologie\", \"kardiologie\", \"orthop\u00e4die\", \"neurologie\", \"kinderarzt\", \"hno\", \"physiotherapie\", \"urologie\", \"ophthalmologist\", \"dermatologist\", \"general_practitioner\", \"dentist\", \"cardiologist\", \"neurologist\", \"pediatrician\".\n"
              },
              "city": {
                "type": "string",
                "description": "City where to search for appointments. Supports German and English city names. Examples: \"Berlin\", \"M\u00fcnchen\", \"Munich\", \"Hamburg\", \"K\u00f6ln\", \"Frankfurt\", \"Stuttgart\", \"D\u00fcsseldorf\", \"Dresden\", \"Leipzig\", \"Hannover\", \"N\u00fcrnberg\", \"Bonn\", \"Heidelberg\".\n"
              },
              "provider_platform": {
                "type": "string",
                "description": "Booking platform to search. \"both\" (default) searches Doctolib and Jameda in parallel and merges results sorted by soonest slot. \"doctolib_de\" for Doctolib Germany only. \"jameda\" for Jameda Germany only (includes ratings, prices, direct booking URLs).\n",
                "enum": [
                  "both",
                  "doctolib_de",
                  "jameda"
                ],
                "default": "both"
              },
              "insurance_sector": {
                "type": "string",
                "description": "Insurance type filter. \"public\" for gesetzliche Krankenversicherung (GKV), \"private\" for private Krankenversicherung (PKV). Omit to show results for all insurance types.\n",
                "enum": [
                  "public",
                  "private"
                ]
              },
              "telehealth": {
                "type": "boolean",
                "description": "If true, only return doctors offering telehealth (video consultation) appointments. Defaults to false.\n",
                "default": false
              },
              "language": {
                "type": "string",
                "description": "Filter for doctors who speak a specific language. Language codes: \"de\" (German), \"gb\" (English), \"ru\" (Russian), \"tr\" (Turkish), \"ar\" (Arabic), \"fr\" (French), \"es\" (Spanish), \"it\" (Italian), \"pl\" (Polish), \"ro\" (Romanian), \"zh\" (Chinese).\n"
              },
              "days_ahead": {
                "type": "integer",
                "description": "How many days ahead to search for appointments. Must be one of 1, 3, or 7 (Doctolib API caps availability queries at 7 days). Defaults to 7.\n",
                "enum": [
                  1,
                  3,
                  7
                ],
                "default": 7
              },
              "max_doctors": {
                "type": "integer",
                "description": "Maximum number of doctors to check for availability. Higher values return more results but take longer. Defaults to 10.\n",
                "default": 10
              },
              "visit_motive_category": {
                "type": "string",
                "description": "Filter results by appointment type category. When set, the skill searches a larger pool of doctors and filters by the Doctolib visit motive name to return only relevant appointment types. \"general\" = consultation, acute visit, new patient examination. \"checkup\" = preventive screening, health check, cancer screening. \"vaccination\" = immunisation appointments. \"followup\" = follow-up visit, existing patient, check-up after treatment.\n",
                "enum": [
                  "general",
                  "checkup",
                  "vaccination",
                  "followup"
                ]
              }
            },
            "required": [
              "speciality",
              "city"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "health",
    "skill_id": "create_report",
    "app_namespace_ts": "health",
    "skill_method_ts": "createReport",
    "app_namespace_py": "health",
    "skill_method_py": "create_report",
    "description_key": "health.create_report.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {}
    }
  },
  {
    "app_id": "home",
    "skill_id": "search",
    "app_namespace_ts": "home",
    "skill_method_ts": "search",
    "app_namespace_py": "home",
    "skill_method_py": "search",
    "description_key": "app_skills.home.search.description",
    "description": "Search for apartments, houses, and WG rooms in German cities. Searches ImmoScout24, Kleinanzeigen, and WG-Gesucht simultaneously. Returns listings with prices, sizes, rooms, addresses, and direct links. Costs 10 credits per search. Use when user asks about finding housing in Germany.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of housing search requests. Each request searches for apartments and rooms in a German city across multiple platforms.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "City or location name to search in, e.g. \"Berlin\", \"Munich\", \"Hamburg\".\n"
              },
              "listing_type": {
                "type": "string",
                "description": "Type of listing. \"rent\" for rentals (default), \"buy\" for purchases. Note: WG-Gesucht only has rentals and is skipped for \"buy\".\n",
                "enum": [
                  "rent",
                  "buy"
                ],
                "default": "rent"
              },
              "providers": {
                "type": "array",
                "description": "Optional list of providers to search. Defaults to all three.\n",
                "items": {
                  "type": "string",
                  "enum": [
                    "ImmoScout24",
                    "Kleinanzeigen",
                    "WG-Gesucht"
                  ]
                }
              },
              "max_results": {
                "type": "integer",
                "description": "Maximum number of listings to return (1-20, default 10).",
                "default": 10,
                "minimum": 1,
                "maximum": 20
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "images",
    "skill_id": "generate",
    "app_namespace_ts": "images",
    "skill_method_ts": "generate",
    "app_namespace_py": "images",
    "skill_method_py": "generate",
    "description_key": "images.generate.description",
    "description": "Generate high-quality images from text prompts and/or reference images (image-to-image editing). Also use for: mockups, design concepts, visual mockup creation, logo mockups, product mockups, illustration requests, visual design, concept art, posters, banners, thumbnails, or any request that implies creating a visual output. Use output_filetype=\"svg\" for logos, icons, illustrations, and any other vector graphics that need to be scalable or editable. When the user provides uploaded images as refe",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of image generation request objects for parallel processing (up to 5 requests).\nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single image.\nExample for single image: {\"requests\": [{\"prompt\": \"a cute cat\"}]}\nEach object must contain 'prompt' (detailed description), and can include optional\n'aspect_ratio', 'output_filetype', and 'quality'.\n",
          "items": {
            "type": "object",
            "properties": {
              "prompt": {
                "type": "string",
                "description": "Detailed description of the image to generate"
              },
              "aspect_ratio": {
                "type": "string",
                "description": "Aspect ratio of the generated image",
                "enum": [
                  "1:1",
                  "16:9",
                  "4:3",
                  "3:2",
                  "2:3",
                  "9:16"
                ],
                "default": "1:1"
              },
              "output_filetype": {
                "type": "string",
                "description": "Output file format. Use \"svg\" to generate a scalable vector graphic (SVG) via\nRecraft V4.1 \u2014 ideal for logos, icons, illustrations, and any graphic that needs\nto be scalable, editable in design tools, or used at any size without quality loss.\nUse \"png\" or \"jpg\" for photos, realistic scenes, and detailed raster images.\nWhen a Recraft model is selected, Recraft V4 is used for raster output as well.\n",
                "enum": [
                  "png",
                  "jpg",
                  "svg"
                ],
                "default": "png"
              },
              "quality": {
                "type": "string",
                "description": "Generation quality. Controls which model tier is used when Recraft is the provider.\nFor SVG output (output_filetype=\"svg\"):\n  \"default\" uses Recraft V4.1 Vector (100 credits \u2014 good for web/UI use).\n  \"max\" uses Recraft V4.1 Pro Vector (300 credits \u2014 best for print, large-format,\n  or highly detailed vector illustrations).\nFor raster output (output_filetype=\"png\"/\"jpg\") with a Recraft model selected:\n  \"default\" uses Recraft V4.1 (50 credits \u2014 fast, cost-effective).\n  \"max\" uses Recraft V4.1 Pro (250 credits \u2014 high-resolution, print-ready).\nFor other raster models (Google Gemini, GPT Image 2, FLUX), quality may be handled by the provider.\n",
                "enum": [
                  "default",
                  "max"
                ],
                "default": "default"
              },
              "reference_images": {
                "type": "array",
                "description": "Optional list of reference image filenames (embed_refs) to use as visual\nreferences for this generation. Pass the exact embed_ref values (original\nfilenames, e.g. \"my_photo.jpg\") from the toon blocks in the conversation.\nThe server resolves all cryptographic and storage details automatically.\nSupports up to 14 reference images. When provided, enables image-to-image\nediting/style-transfer mode (Google Gemini: same endpoint; FLUX: switches\nto the 4B edit model). Ignored for SVG/Recraft output.\n",
                "items": {
                  "type": "string",
                  "description": "Original filename (embed_ref) of an uploaded image"
                }
              }
            },
            "required": [
              "prompt"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "images",
    "skill_id": "generate_draft",
    "app_namespace_ts": "images",
    "skill_method_ts": "generateDraft",
    "app_namespace_py": "images",
    "skill_method_py": "generate_draft",
    "description_key": "images.generate_draft.description",
    "description": "Quickly generate a draft/preview image from a text prompt and/or reference images (image-to-image). Also use for: quick mockups, rough design concepts, draft illustrations, sketches, quick visual previews, or any request for a fast/rough image. When the user provides uploaded images as references (embed_refs), pass them via reference_images. Do not use this for scam, spam, fake-document, fake-endorsement, public-figure impersonation, or watermark/detection-evasion requests.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of image generation request objects for parallel processing (up to 5 requests).\nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single image.\nExample for single image: {\"requests\": [{\"prompt\": \"a cute cat\"}]}\nEach object must contain 'prompt' (description of the image).\n",
          "items": {
            "type": "object",
            "properties": {
              "prompt": {
                "type": "string",
                "description": "Description of the image to generate"
              },
              "reference_images": {
                "type": "array",
                "description": "Optional list of reference image filenames (embed_refs) to use as visual\nreferences for this generation. Pass the exact embed_ref values (original\nfilenames, e.g. \"my_photo.jpg\") from the toon blocks in the conversation.\nThe server resolves all cryptographic and storage details automatically.\nSupports up to 4 reference images. When provided, automatically switches to\nthe FLUX.2 [klein] 4B edit model (image-to-image, 27 credits).\n",
                "items": {
                  "type": "string",
                  "description": "Original filename (embed_ref) of an uploaded image"
                }
              }
            },
            "required": [
              "prompt"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "mail",
    "skill_id": "search",
    "app_namespace_ts": "mail",
    "skill_method_ts": "search",
    "app_namespace_py": "mail",
    "skill_method_py": "search",
    "description_key": "app_skills.mail.search.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of mail search request objects.\nThe query field is optional. If omitted or empty, newest emails are returned first.\nExample: {\"requests\": [{\"query\": \"invoice\", \"limit\": 10}]}\nExample recent-first: {\"requests\": [{\"limit\": 10}]}\n",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "type": [
                  "string",
                  "integer"
                ],
                "description": "Optional request id echoed in results"
              },
              "query": {
                "type": "string",
                "description": "Optional search text (subject/from/body). Empty means recent-first listing."
              },
              "mailbox": {
                "type": "string",
                "description": "Optional mailbox name (defaults to INBOX)"
              },
              "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 10,
                "description": "Maximum number of email results to return"
              }
            }
          },
          "minItems": 1
        }
      },
      "required": [
        "requests"
      ],
      "additionalProperties": false
    }
  },
  {
    "app_id": "maps",
    "skill_id": "search",
    "app_namespace_ts": "maps",
    "skill_method_ts": "search",
    "app_namespace_py": "maps",
    "skill_method_py": "search",
    "description_key": "maps.search.description",
    "description": "Search for places, businesses, restaurants, directions, locations.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of search request objects for parallel processing (up to 5 requests). \nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single search.\nExample for single search: {\"requests\": [{\"query\": \"restaurants in Berlin\"}]}\nExample for multiple searches: {\"requests\": [{\"query\": \"restaurants in Berlin\"}, {\"query\": \"museums in Berlin\"}]}\nEach object must contain 'query' (search query string), and can include optional parameters (pageSize, languageCode, locationBias, includedType, minRating, openNow, includeReviews).\nNote: The 'id' field is auto-generated if not provided - you don't need to include it.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Text query string to search for places (e.g., \"restaurants in Berlin\", \"museums near Times Square\")"
              },
              "pageSize": {
                "type": "integer",
                "description": "Number of results to return per request (max 20)",
                "minimum": 1,
                "maximum": 20,
                "default": 10
              },
              "languageCode": {
                "type": "string",
                "description": "Language code for results (ISO 639-1, e.g., 'en', 'es', 'fr', 'de'). Defaults to 'en' if not specified.",
                "default": "en"
              },
              "locationBias": {
                "type": "object",
                "description": "Optional location bias to prioritize results near a specific area. Can be a circle (center + radius) or rectangle (viewport).",
                "properties": {
                  "circle": {
                    "type": "object",
                    "properties": {
                      "center": {
                        "type": "object",
                        "properties": {
                          "latitude": {
                            "type": "number"
                          },
                          "longitude": {
                            "type": "number"
                          }
                        }
                      },
                      "radius": {
                        "type": "number",
                        "description": "Radius in meters (0.0 to 50000.0)"
                      }
                    }
                  },
                  "rectangle": {
                    "type": "object",
                    "properties": {
                      "low": {
                        "type": "object",
                        "properties": {
                          "latitude": {
                            "type": "number"
                          },
                          "longitude": {
                            "type": "number"
                          }
                        }
                      },
                      "high": {
                        "type": "object",
                        "properties": {
                          "latitude": {
                            "type": "number"
                          },
                          "longitude": {
                            "type": "number"
                          }
                        }
                      }
                    }
                  }
                }
              },
              "includedType": {
                "type": "string",
                "description": "Optional place type filter (e.g., 'restaurant', 'museum', 'pharmacy'). See Google Places API place types documentation for full list."
              },
              "minRating": {
                "type": "number",
                "description": "Minimum rating filter (0.0 to 5.0, increments of 0.5). Only places with rating >= minRating will be returned.",
                "minimum": 0.0,
                "maximum": 5.0
              },
              "openNow": {
                "type": "boolean",
                "description": "If true, return only places that are currently open. Defaults to false.",
                "default": false
              },
              "includeReviews": {
                "type": "boolean",
                "description": "If true, include user reviews in the response. Defaults to false to keep response size manageable. Reviews significantly increase response size.",
                "default": false
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "math",
    "skill_id": "calculate",
    "app_namespace_ts": "math",
    "skill_method_ts": "calculate",
    "app_namespace_py": "math",
    "skill_method_py": "calculate",
    "description_key": "math.calculate.description",
    "description": "MANDATORY: Use this skill for ALL mathematical calculations without exception. This includes simple arithmetic such as addition, subtraction, multiplication (written as *, x, or \u00d7), division, and parenthesised expressions like (4x22x7)/2 or (100+50)*3/2. Also use for algebra, trigonometry, calculus, unit conversions, symbolic simplification, equation solving, derivatives, and integrals. NEVER attempt to compute a numeric result yourself \u2014 always call this skill so results are guaranteed to be ex",
    "schema": {
      "type": "object",
      "properties": {
        "title": {
          "type": "string",
          "description": "A short human-readable title that explains why this calculation is being made. This is shown in the embed preview, so prefer concise context like \"Bike time to the Moon\" or \"Monthly mortgage estimate\".\n"
        },
        "expression": {
          "type": "string",
          "description": "The mathematical expression, equation, or operation to evaluate. Examples: - Arithmetic: \"3.14159 * (42.7)^2 / cos(0.3)\" - Symbolic simplify: \"simplify((x^2 - 1) / (x - 1))\" - Solve equation: \"solve(x^2 - 4*x + 3, x)\" - Derivative: \"diff(sin(x) * exp(x), x)\" - Integral: \"integrate(x^2 * log(x), x)\" - Unit conversion: \"convert(100, kg, lbs)\" - With context vars: \"E = m * c^2 where m=1, c=299792458\"\n"
        },
        "mode": {
          "type": "string",
          "description": "Evaluation mode. 'auto' (default) detects the appropriate mode from the expression. 'numeric' forces numerical evaluation. 'symbolic' forces symbolic computation. 'solve' solves an equation for a variable. 'simplify' simplifies an algebraic expression. 'diff' computes derivative. 'integrate' computes integral. 'convert' converts units.\n",
          "enum": [
            "auto",
            "numeric",
            "symbolic",
            "solve",
            "simplify",
            "diff",
            "integrate",
            "convert"
          ],
          "default": "auto"
        },
        "variable": {
          "type": "string",
          "description": "The variable to differentiate or integrate with respect to, or to solve for. Defaults to 'x'. Only needed when mode is 'diff', 'integrate', or 'solve'.\n",
          "default": "x"
        },
        "precision": {
          "type": "integer",
          "description": "Number of significant digits for numeric results. Defaults to 15. Use higher values (e.g. 50) for high-precision calculations.\n",
          "default": 15,
          "minimum": 1,
          "maximum": 100
        }
      },
      "required": [
        "expression"
      ]
    }
  },
  {
    "app_id": "models3d",
    "skill_id": "search",
    "app_namespace_ts": "models3d",
    "skill_method_ts": "search",
    "app_namespace_py": "models3d",
    "skill_method_py": "search",
    "description_key": "app_skills.models3d.search.description",
    "description": "Search public 3D model catalogs for existing models. Use this when the user wants to find, browse, compare, or link to existing 3D-printable or downloadable 3D models. Do not use it to generate new models.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of 3D model search requests. Each request searches public 3D model catalogs and returns preview-only result cards.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query, e.g. \"benchy\", \"phone stand\", or \"desk cable clip\"."
              },
              "providers": {
                "type": "array",
                "items": {
                  "type": "string",
                  "enum": [
                    "Printables"
                  ]
                },
                "description": "Optional provider filter. Defaults to Printables."
              },
              "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 10,
                "description": "Maximum total results to return after merging providers."
              },
              "sort": {
                "type": "string",
                "enum": [
                  "best_match",
                  "popular",
                  "downloads",
                  "newest"
                ],
                "default": "best_match",
                "description": "Sorting strategy applied after provider results are merged."
              },
              "free_only": {
                "type": "boolean",
                "default": false,
                "description": "Return only results that the provider marks as free."
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "music",
    "skill_id": "generate",
    "app_namespace_ts": "music",
    "skill_method_ts": "generate",
    "app_namespace_py": "music",
    "skill_method_py": "generate",
    "description_key": "app_skills.music.generate.description",
    "description": "Generate music from a text prompt, including full songs, instrumental tracks, background music, loops, jingles, lyric-based songs, and soundtrack cues. Use this when the user asks to create music or background music. Do not use this to imitate the voice, vocals, cadence, or persona of a real public figure, living artist, famous educator, or recognizable person. Use original voices and styles only, and reject scams, spam, or detection evasion.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of music generation request objects. Each object must\ninclude a prompt and can specify duration_seconds, mode, lyrics, style,\nnegative_prompt, seed, and model.\n",
          "items": {
            "type": "object",
            "properties": {
              "prompt": {
                "type": "string",
                "description": "Text description of the music to generate."
              },
              "mode": {
                "type": "string",
                "enum": [
                  "song",
                  "instrumental",
                  "background",
                  "loop",
                  "jingle"
                ],
                "default": "background",
                "description": "Desired music type."
              },
              "lyrics": {
                "type": "string",
                "description": "Optional lyrics to include for vocal/song generation."
              },
              "style": {
                "type": "string",
                "description": "Optional genre, mood, instrumentation, tempo, or production style."
              },
              "duration_seconds": {
                "type": "integer",
                "minimum": 3,
                "maximum": 184,
                "default": 30,
                "description": "Target duration in seconds. Lyria 3 Clip is 30s; Lyria 3 Pro supports longer tracks in preview."
              },
              "negative_prompt": {
                "type": "string",
                "description": "Optional sounds, genres, instruments, or qualities to avoid."
              },
              "seed": {
                "type": "integer",
                "description": "Optional seed for more reproducible output when supported."
              },
              "model": {
                "type": "string",
                "enum": [
                  "lyria-3-pro-preview",
                  "lyria-3-clip-preview",
                  "lyria-002"
                ],
                "default": "lyria-3-pro-preview",
                "description": "Google Lyria model. Prefer lyria-3-pro-preview for latest quality."
              }
            },
            "required": [
              "prompt"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "news",
    "skill_id": "search",
    "app_namespace_ts": "news",
    "skill_method_ts": "search",
    "app_namespace_py": "news",
    "skill_method_py": "search",
    "description_key": "news.search.description",
    "description": "Search for news articles, current events, headlines, announcements.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of search request objects for parallel processing (up to 5 requests). \nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single search.\nExample for single search: {\"requests\": [{\"query\": \"iPhone news\"}]}\nExample for multiple searches: {\"requests\": [{\"query\": \"iPhone news\"}, {\"query\": \"MacBook news\"}]}\nEach object must contain 'query' (search query string), and can include optional parameters (count, country, search_lang, safesearch, freshness).\nNote: The 'id' field is auto-generated if not provided - you don't need to include it.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query string"
              },
              "count": {
                "type": "integer",
                "description": "Number of results for this request (max 20)",
                "minimum": 1,
                "maximum": 20,
                "default": 6
              },
              "country": {
                "type": "string",
                "description": "Country code for localized results. Must be one of: AR, AU, AT, BE, BR, CA, CL, DK, FI, FR, DE, GR, HK, IN, ID, IT, JP, KR, MY, MX, NL, NZ, NO, CN, PL, PT, PH, RU, SA, ZA, ES, SE, CH, TW, TR, GB, US, or ALL (case-insensitive). Defaults to 'us' if invalid.",
                "enum": [
                  "AR",
                  "AU",
                  "AT",
                  "BE",
                  "BR",
                  "CA",
                  "CL",
                  "DK",
                  "FI",
                  "FR",
                  "DE",
                  "GR",
                  "HK",
                  "IN",
                  "ID",
                  "IT",
                  "JP",
                  "KR",
                  "MY",
                  "MX",
                  "NL",
                  "NZ",
                  "NO",
                  "CN",
                  "PL",
                  "PT",
                  "PH",
                  "RU",
                  "SA",
                  "ZA",
                  "ES",
                  "SE",
                  "CH",
                  "TW",
                  "TR",
                  "GB",
                  "US",
                  "ALL",
                  "ar",
                  "au",
                  "at",
                  "be",
                  "br",
                  "ca",
                  "cl",
                  "dk",
                  "fi",
                  "fr",
                  "de",
                  "gr",
                  "hk",
                  "in",
                  "id",
                  "it",
                  "jp",
                  "kr",
                  "my",
                  "mx",
                  "nl",
                  "nz",
                  "no",
                  "cn",
                  "pl",
                  "pt",
                  "ph",
                  "ru",
                  "sa",
                  "za",
                  "es",
                  "se",
                  "ch",
                  "tw",
                  "tr",
                  "gb",
                  "us",
                  "all"
                ],
                "default": "us"
              },
              "search_lang": {
                "type": "string",
                "description": "Language code for search (ISO 639-1, e.g., 'en', 'es', 'fr')",
                "default": "en"
              },
              "safesearch": {
                "type": "string",
                "description": "Safe search level",
                "enum": [
                  "off",
                  "moderate",
                  "strict"
                ],
                "default": "moderate"
              },
              "freshness": {
                "type": "string",
                "description": "Filter by freshness - \"pd\" (past 24 hours), \"pw\" (past week), \"pm\" (past month), \"py\" (past year). Defaults to \"pw\" (past week) to prioritize recent news content.",
                "enum": [
                  "pd",
                  "pw",
                  "pm",
                  "py"
                ],
                "default": "pw"
              },
              "filter_tabloids": {
                "type": "boolean",
                "description": "Filter out tabloid/boulevard media sources (e.g., BILD, Daily Mail, TMZ, The Sun) from results. Enabled by default for quality news. Set to false ONLY if the user explicitly asks for tabloid sources.",
                "default": true
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "nutrition",
    "skill_id": "search_recipes",
    "app_namespace_ts": "nutrition",
    "skill_method_ts": "searchRecipes",
    "app_namespace_py": "nutrition",
    "skill_method_py": "search_recipes",
    "description_key": "app_skills.nutrition.search_recipes.description",
    "description": "Search Edamam for recipes by natural-language query and nutrition filters. Returns recipe details with ingredients, step-by-step instructions, images, source links, and nutrition metadata. Recipes without instructions are filtered out. Best for: recipe recommendations, meal planning, dietary filtering, and cooking guidance.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of recipe search requests. Each request searches for recipes matching a free-text query and optional Edamam filters.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Free-text recipe query, e.g. \"quick vegan pasta\", \"gluten-free pancakes\", or \"miso salmon\".\n"
              },
              "health": {
                "type": "array",
                "description": "Optional Edamam health labels such as vegan, vegetarian, gluten-free, dairy-free, keto-friendly, peanut-free, tree-nut-free.\n",
                "items": {
                  "type": "string"
                }
              },
              "diet": {
                "type": "array",
                "description": "Optional Edamam diet labels such as balanced, high-fiber, high-protein, low-carb, low-fat, low-sodium.\n",
                "items": {
                  "type": "string"
                }
              },
              "time": {
                "type": "string",
                "description": "Optional cooking/prep time range, e.g. \"1-30\"."
              },
              "calories": {
                "type": "string",
                "description": "Optional calories range, e.g. \"100-600\"."
              },
              "cuisine_type": {
                "type": "array",
                "description": "Optional cuisine filters such as Italian, Japanese, Mexican.",
                "items": {
                  "type": "string"
                }
              },
              "meal_type": {
                "type": "array",
                "description": "Optional meal filters such as Breakfast, Dinner, Lunch, Snack.",
                "items": {
                  "type": "string"
                }
              },
              "dish_type": {
                "type": "array",
                "description": "Optional dish filters such as Main course, Soup, Salad, Pancake.",
                "items": {
                  "type": "string"
                }
              },
              "excluded": {
                "type": "array",
                "description": "Optional ingredients or terms to exclude from recipes.",
                "items": {
                  "type": "string"
                }
              },
              "ingredients": {
                "type": "string",
                "description": "Optional ingredient-count range, e.g. \"5-10\"."
              },
              "max_results": {
                "type": "integer",
                "description": "Maximum number of recipes to return with full details (1-10, default 6). Each returned result includes ingredients, step-by-step instructions, image data, source attribution, and nutrition metadata.\n",
                "default": 6
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "openmates",
    "skill_id": "share-usecase",
    "app_namespace_ts": "openmates",
    "skill_method_ts": "shareUsecase",
    "app_namespace_py": "openmates",
    "skill_method_py": "share_usecase",
    "description_key": "openmates_app.share_usecase.description",
    "description": "Use when the user has explicitly agreed to anonymously share a summary of their intended use cases with the OpenMates team to help improve the product. NEVER call this without clear user consent.",
    "schema": {
      "type": "object",
      "properties": {
        "summary": {
          "type": "string",
          "description": "A brief summary (2-5 sentences) of what the user wants to use OpenMates for, as discussed in the conversation. Should capture the key use cases and interests.\n"
        },
        "language": {
          "type": "string",
          "description": "ISO 639-1 language code of the conversation (e.g., 'en', 'de')"
        }
      },
      "required": [
        "summary",
        "language"
      ]
    }
  },
  {
    "app_id": "openmates",
    "skill_id": "get-docs",
    "app_namespace_ts": "openmates",
    "skill_method_ts": "getDocs",
    "app_namespace_py": "openmates",
    "skill_method_py": "get_docs",
    "description_key": "openmates_app.get_docs.description",
    "description": "Use when the user shares an openmates.org/docs URL, or asks to read a specific OpenMates documentation page. Automatically triggered when an openmates docs URL is detected in the conversation.",
    "schema": {
      "type": "object",
      "properties": {
        "url": {
          "type": "string",
          "description": "An openmates.org/docs URL or a docs slug path (e.g., 'architecture/chats' or 'https://openmates.org/docs/architecture/chats')\n"
        }
      },
      "required": [
        "url"
      ]
    }
  },
  {
    "app_id": "openmates",
    "skill_id": "search-docs",
    "app_namespace_ts": "openmates",
    "skill_method_ts": "searchDocs",
    "app_namespace_py": "openmates",
    "skill_method_py": "search_docs",
    "description_key": "openmates_app.search_docs.description",
    "description": "Use when the user asks about OpenMates features, setup, architecture, or documentation. Searches across all OpenMates documentation to find relevant pages.",
    "schema": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Search terms to find in OpenMates documentation"
        }
      },
      "required": [
        "query"
      ]
    }
  },
  {
    "app_id": "pdf",
    "skill_id": "read",
    "app_namespace_ts": "pdf",
    "skill_method_ts": "read",
    "app_namespace_py": "pdf",
    "skill_method_py": "read",
    "description_key": "pdf.read.description",
    "description": "Load and read the raw text content (markdown) of specific pages from an uploaded PDF document. Use when the user asks what a PDF says, wants you to summarise sections, or requests information that is likely textual (paragraphs, tables, headings). The embed TOON content includes a TOC and per-page token estimates \u2014 use them to select the most relevant pages. Limits output to 50 000 tokens; call again for remaining pages if needed. Pass the exact embed_ref (original filename) from the toon block \u2014",
    "schema": {
      "type": "object",
      "properties": {
        "file_path": {
          "type": "string",
          "description": "The original filename of the PDF (e.g. \"report.pdf\"). Use the exact embed_ref value from the toon block. The server resolves all cryptographic and storage details from this filename automatically.\n"
        },
        "pages": {
          "type": "array",
          "description": "1-indexed page numbers to read (e.g. [1, 2, 3]). If omitted, reads from page 1 onwards up to the token budget.",
          "items": {
            "type": "integer"
          }
        }
      },
      "required": [
        "file_path"
      ]
    }
  },
  {
    "app_id": "pdf",
    "skill_id": "search",
    "app_namespace_ts": "pdf",
    "skill_method_ts": "search",
    "app_namespace_py": "pdf",
    "skill_method_py": "search",
    "description_key": "pdf.search.description",
    "description": "Search for specific text, keywords, or phrases across all pages of an uploaded PDF. Returns matching text blocks with surrounding context and page numbers. Use when the user asks to find where something is mentioned in the document, or when a targeted keyword search is faster than reading entire sections. No LLM call required \u2014 pure text search over the OCR data. Pass the exact embed_ref (original filename) from the toon block as file_path.",
    "schema": {
      "type": "object",
      "properties": {
        "file_path": {
          "type": "string",
          "description": "The original filename of the PDF. Use the exact embed_ref from the toon block. The server resolves all cryptographic and storage details automatically.\n"
        },
        "query": {
          "type": "string",
          "description": "The search query string (case-insensitive substring match)."
        },
        "context_chars": {
          "type": "integer",
          "description": "Number of characters of surrounding context to include per match (default: 200)."
        }
      },
      "required": [
        "file_path",
        "query"
      ]
    }
  },
  {
    "app_id": "pdf",
    "skill_id": "view",
    "app_namespace_ts": "pdf",
    "skill_method_ts": "view",
    "app_namespace_py": "pdf",
    "skill_method_py": "view",
    "description_key": "pdf.view.skill_description",
    "description": "View one or more page screenshots from an uploaded PDF and return them as multimodal image blocks so the main inference model can see the pages directly. Use when the user asks about the visual layout, diagrams, charts, figures, or images on specific pages. Also useful when text OCR may have been imperfect (e.g. complex tables, mathematical notation, handwriting). Up to 5 pages can be viewed per call. Pass the exact embed_ref (original filename) from the toon block as file_path \u2014 the server reso",
    "schema": {
      "type": "object",
      "properties": {
        "file_path": {
          "type": "string",
          "description": "The original filename of the PDF. Use the exact embed_ref from the toon block. The server resolves all cryptographic and storage details automatically.\n"
        },
        "pages": {
          "type": "array",
          "description": "1-indexed page numbers to view (max 5). Example: [1, 2].",
          "items": {
            "type": "integer"
          }
        },
        "query": {
          "type": "string",
          "description": "The user's question or instruction about the page(s)."
        }
      },
      "required": [
        "file_path",
        "pages",
        "query"
      ]
    }
  },
  {
    "app_id": "reminder",
    "skill_id": "set-reminder",
    "app_namespace_ts": "reminder",
    "skill_method_ts": "setReminder",
    "app_namespace_py": "reminder",
    "skill_method_py": "set_reminder",
    "description_key": "reminder.set_reminder.description",
    "description": "Schedule, create, or set up reminders for the user. Handles one-time and recurring reminders (e.g., \"every morning\", \"daily at 9am\", \"weekly\", \"monthly\"). Use when user wants to be reminded, notified, or alerted about something at a specific time or on a recurring schedule. Also use for automating tasks like \"get news every day\" or \"summarize updates weekly\".",
    "schema": {
      "type": "object",
      "properties": {
        "prompt": {
          "type": "string",
          "description": "The reminder message/prompt that will be shown when the reminder fires"
        },
        "trigger_type": {
          "type": "string",
          "enum": [
            "specific",
            "random"
          ],
          "description": "'specific' for exact datetime, 'random' for random time within a window"
        },
        "trigger_datetime": {
          "type": "string",
          "description": "ISO 8601 datetime for specific trigger (e.g., '2026-02-05T14:30:00'). Required if trigger_type is 'specific'."
        },
        "random_start_date": {
          "type": "string",
          "description": "Start date for random window (YYYY-MM-DD). Required if trigger_type is 'random'."
        },
        "random_end_date": {
          "type": "string",
          "description": "End date for random window (YYYY-MM-DD). Required if trigger_type is 'random'."
        },
        "random_time_start": {
          "type": "string",
          "description": "Earliest time of day for random trigger (HH:MM, 24h format, e.g., '10:00'). Optional for random triggers."
        },
        "random_time_end": {
          "type": "string",
          "description": "Latest time of day for random trigger (HH:MM, 24h format, e.g., '14:00'). Optional for random triggers."
        },
        "timezone": {
          "type": "string",
          "description": "User's timezone (e.g., 'Europe/Berlin', 'America/New_York'). Required."
        },
        "target_type": {
          "type": "string",
          "enum": [
            "new_chat",
            "existing_chat",
            "embed"
          ],
          "default": "existing_chat",
          "description": "'existing_chat' sends a follow-up in the current chat and is the default for reminders requested from chat, 'new_chat' creates a new chat when the user explicitly asks for a new chat or standalone reminder thread, 'embed' opens a saved embed fullscreen"
        },
        "new_chat_title": {
          "type": "string",
          "description": "Title for the new chat. Required if target_type is 'new_chat'."
        },
        "target_embed_id": {
          "type": "string",
          "description": "Embed ID to open when target_type is 'embed'."
        },
        "target_embed_app_id": {
          "type": "string",
          "description": "App ID for the embed target. Optional; used by client display."
        },
        "target_embed_title": {
          "type": "string",
          "description": "Display title for the embed target. Optional; used by client display."
        },
        "response_type": {
          "type": "string",
          "enum": [
            "simple",
            "full"
          ],
          "default": "simple",
          "description": "'simple' = notification-only: no AI response is generated, just a notification, email, and a visual marker in the chat history. Use for passive nudges ('remind me about this', 'ping me tomorrow'). 'full' = action trigger: the AI executes a task when the reminder fires. Use ONLY when the user wants the AI to actively do something ('summarize the news every morning', 'give me an update on X'). Default is 'simple'."
        },
        "repeat": {
          "type": "object",
          "description": "Configuration for repeating reminders. Omit for one-time reminders.",
          "properties": {
            "type": {
              "type": "string",
              "enum": [
                "daily",
                "weekly",
                "monthly",
                "custom"
              ],
              "description": "Type of repeat schedule"
            },
            "interval": {
              "type": "integer",
              "minimum": 1,
              "description": "For custom type: repeat every N units"
            },
            "interval_unit": {
              "type": "string",
              "enum": [
                "days",
                "weeks",
                "months"
              ],
              "description": "For custom type: unit of the interval"
            },
            "day_of_week": {
              "type": "integer",
              "minimum": 0,
              "maximum": 6,
              "description": "For weekly type: 0=Monday, 6=Sunday"
            },
            "day_of_month": {
              "type": "integer",
              "minimum": 1,
              "maximum": 31,
              "description": "For monthly type: day of the month (1-31)"
            },
            "end_date": {
              "type": "string",
              "description": "Optional: stop repeating after this date (YYYY-MM-DD)"
            },
            "max_occurrences": {
              "type": "integer",
              "minimum": 1,
              "description": "Optional: maximum number of times to fire"
            }
          },
          "required": [
            "type"
          ]
        }
      },
      "required": [
        "prompt",
        "trigger_type",
        "timezone"
      ]
    }
  },
  {
    "app_id": "reminder",
    "skill_id": "list-reminders",
    "app_namespace_ts": "reminder",
    "skill_method_ts": "listReminders",
    "app_namespace_py": "reminder",
    "skill_method_py": "list_reminders",
    "description_key": "reminder.list_reminders.description",
    "description": "Show the user's existing scheduled reminders.",
    "schema": {
      "type": "object",
      "properties": {
        "status": {
          "type": "string",
          "enum": [
            "pending",
            "all"
          ],
          "default": "pending",
          "description": "Filter reminders by status. 'pending' shows only upcoming reminders."
        }
      }
    }
  },
  {
    "app_id": "reminder",
    "skill_id": "cancel-reminder",
    "app_namespace_ts": "reminder",
    "skill_method_ts": "cancelReminder",
    "app_namespace_py": "reminder",
    "skill_method_py": "cancel_reminder",
    "description_key": "reminder.cancel_reminder.description",
    "description": "Cancel or delete an existing reminder.",
    "schema": {
      "type": "object",
      "properties": {
        "reminder_id": {
          "type": "string",
          "description": "ID of the reminder to cancel"
        }
      },
      "required": [
        "reminder_id"
      ]
    }
  },
  {
    "app_id": "shopping",
    "skill_id": "search_products",
    "app_namespace_ts": "shopping",
    "skill_method_ts": "searchProducts",
    "app_namespace_py": "shopping",
    "skill_method_py": "search_products",
    "description_key": "app_skills.shopping.search_products.description",
    "description": "Search products on REWE, Amazon, or Stoffe.de with real-time prices. Use category to route groceries, marketplace products, fabrics, sewing supplies, and patterns to compatible providers. Invalid provider/category combinations are rejected.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of product search requests. Each request searches for products matching a query on a compatible shopping provider.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query, e.g. \"bio joghurt\", \"coffee grinder\", \"wireless mouse\".\n"
              },
              "provider": {
                "type": "string",
                "description": "Product provider. If omitted, inferred from category: grocery routes to REWE, fabrics/sewing_supplies/patterns route to Stoffe.de, and marketplace categories route to Amazon. Invalid explicit provider/category combinations are rejected.\n",
                "enum": [
                  "REWE",
                  "Amazon",
                  "Stoffe.de"
                ]
              },
              "category": {
                "type": "string",
                "description": "Product category used for routing and provider compatibility. Fabrics can be searched on Stoffe.de or Amazon. Groceries can be searched on REWE or Amazon. Marketplace categories are Amazon-only.\n",
                "enum": [
                  "grocery",
                  "fabrics",
                  "sewing_supplies",
                  "patterns",
                  "general_marketplace",
                  "electronics",
                  "home",
                  "fashion",
                  "beauty",
                  "books",
                  "sports",
                  "toys",
                  "automotive",
                  "health",
                  "music",
                  "movies",
                  "tools",
                  "office",
                  "pet_supplies",
                  "video_games",
                  "baby"
                ]
              },
              "max_results": {
                "type": "integer",
                "description": "Maximum number of products to return (1-20, default 10).",
                "default": 10
              },
              "sort": {
                "type": "string",
                "description": "Sort order for results. REWE supports: relevance, price_asc, price_desc, new. Amazon supports: relevance, price_asc, price_desc, review_rank, newest, best_sellers. Stoffe.de supports: relevance, price_asc, price_desc, new.\n",
                "enum": [
                  "relevance",
                  "price_asc",
                  "price_desc",
                  "new",
                  "review_rank",
                  "newest",
                  "best_sellers"
                ],
                "default": "relevance"
              },
              "service_type": {
                "type": "string",
                "description": "REWE-only fulfilment type. \"DELIVERY\" for home delivery (default). \"CLICK_AND_COLLECT\" for store pickup. Ignored for Amazon and Stoffe.de.\n",
                "enum": [
                  "DELIVERY",
                  "CLICK_AND_COLLECT"
                ],
                "default": "DELIVERY"
              },
              "country": {
                "type": "string",
                "description": "Amazon-only marketplace country code. Example: us, uk, de, fr, it, es, ca, au, jp, in, br, mx, nl, sg, se, pl. If omitted, inferred from user language/locale with fallback to us.\n"
              },
              "department": {
                "type": "string",
                "description": "Amazon-only category filter. Example: electronics, computers, fashion, home, books, sports, toys, beauty, grocery, automotive, health, music, movies, tools, office, pet_supplies, video_games, baby.\n",
                "enum": [
                  "electronics",
                  "computers",
                  "fashion",
                  "home",
                  "books",
                  "sports",
                  "toys",
                  "beauty",
                  "grocery",
                  "automotive",
                  "health",
                  "music",
                  "movies",
                  "tools",
                  "office",
                  "pet_supplies",
                  "video_games",
                  "baby"
                ]
              },
              "min_price": {
                "type": "number",
                "description": "Amazon-only minimum price filter (client-side after fetch)."
              },
              "max_price": {
                "type": "number",
                "description": "Amazon-only maximum price filter (client-side after fetch)."
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "social_media",
    "skill_id": "get-posts",
    "app_namespace_ts": "socialMedia",
    "skill_method_ts": "getPosts",
    "app_namespace_py": "social_media",
    "skill_method_py": "get_posts",
    "description_key": "app_skills.social_media.get_posts.description",
    "description": "Fetch recent social media posts from one or more specific platform pages or profiles. Supports Reddit subreddits, Bluesky profile feeds, and Mastodon public profiles. Use for profile monitoring, community research, and finding conversations to review manually. Costs 10 credits per request.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of social post fetch requests. For Reddit, page is the subreddit name without r/ (for example: privacy, selfhosted, buildinpublic). For Bluesky profile posts, page is the actor handle. For Mastodon, page is user@instance or a public profile URL.\n",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "description": "Optional caller-supplied ID for correlating responses."
              },
              "platform": {
                "type": "string",
                "description": "Social platform to fetch from.",
                "enum": [
                  "bluesky",
                  "mastodon",
                  "reddit"
                ],
                "default": "reddit"
              },
              "page": {
                "type": "string",
                "description": "Platform page/profile identifier. For Reddit, this is the subreddit name. For Bluesky, this is an actor handle for profile feeds. For Mastodon, use user@instance or a profile URL."
              },
              "sort": {
                "type": "string",
                "description": "Post listing sort. Reddit supports new/hot/rising/top/comments. Comments means most discussed in the selected time range. Bluesky and Mastodon profile feeds ignore this value.",
                "enum": [
                  "new",
                  "hot",
                  "rising",
                  "top",
                  "comments"
                ],
                "default": "new"
              },
              "time_range": {
                "type": "string",
                "description": "Reddit time filter for top/comments sorts.",
                "enum": [
                  "hour",
                  "day",
                  "week",
                  "month",
                  "year",
                  "all"
                ]
              },
              "limit": {
                "type": "integer",
                "description": "Number of posts to fetch per page.",
                "minimum": 1,
                "maximum": 25,
                "default": 10
              },
              "include_comments": {
                "type": "boolean",
                "description": "Whether to fetch comments/replies for returned posts when supported.",
                "default": true
              },
              "comments_limit": {
                "type": "integer",
                "description": "Number of comments/replies to fetch per post.",
                "minimum": 0,
                "maximum": 5,
                "default": 5
              },
              "comments_sort": {
                "type": "string",
                "description": "Reddit comment sort. Bluesky and Mastodon ignore this value.",
                "enum": [
                  "confidence",
                  "top",
                  "new",
                  "controversial",
                  "old"
                ],
                "default": "top"
              },
              "min_score": {
                "type": "integer",
                "description": "Minimum Reddit score/upvotes to include.",
                "minimum": 0
              },
              "min_comments": {
                "type": "integer",
                "description": "Minimum Reddit comment count to include.",
                "minimum": 0
              },
              "exclude_stickied": {
                "type": "boolean",
                "description": "Exclude stickied Reddit posts.",
                "default": true
              },
              "exclude_nsfw": {
                "type": "boolean",
                "description": "Exclude NSFW Reddit posts.",
                "default": true
              },
              "include_self_posts": {
                "type": "boolean",
                "description": "Include Reddit text/self posts.",
                "default": true
              },
              "include_link_posts": {
                "type": "boolean",
                "description": "Include Reddit link/media posts.",
                "default": true
              }
            }
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "social_media",
    "skill_id": "search",
    "app_namespace_ts": "socialMedia",
    "skill_method_ts": "search",
    "app_namespace_py": "social_media",
    "skill_method_py": "search",
    "description_key": "app_skills.social_media.search.description",
    "description": "Search supported social platforms for recent public posts around a topic. Use this for topic monitoring and broad discovery across pages/profiles, not for monitoring a known profile; use Get posts for profile/page posts. Omit platform to search every supported social platform. Costs 10 credits per request.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of social post search requests. For Bluesky, query is the topic to search and author optionally restricts results to a specific handle. For Mastodon, mastodon.social is searched by default and mastodon_instances can add more public instances.\n",
          "items": {
            "type": "object",
            "properties": {
              "id": {
                "description": "Optional caller-supplied ID for correlating responses."
              },
              "platform": {
                "type": "string",
                "description": "Social platform to search. Omit or use all to search every supported provider.",
                "enum": [
                  "all",
                  "bluesky",
                  "mastodon",
                  "reddit"
                ],
                "default": "all"
              },
              "query": {
                "type": "string",
                "description": "Topic or search query to find posts around."
              },
              "page": {
                "type": "string",
                "description": "Optional subreddit/page to restrict Reddit search to, without r/. For Mastodon, optionally provide one extra instance such as fosstodon.org."
              },
              "mastodon_instances": {
                "type": "array",
                "description": "Optional additional Mastodon instances to search after mastodon.social, for example fosstodon.org or hachyderm.io.",
                "items": {
                  "type": "string"
                }
              },
              "sort": {
                "type": "string",
                "description": "Search sort. Bluesky supports latest/top. Reddit supports relevance/hot/top/new/comments/latest. Mastodon public search returns instance-ranked recent results and ignores sort.",
                "enum": [
                  "latest",
                  "top",
                  "new",
                  "hot",
                  "relevance",
                  "comments"
                ],
                "default": "latest"
              },
              "time_range": {
                "type": "string",
                "description": "Reddit time filter for top/comments search.",
                "enum": [
                  "hour",
                  "day",
                  "week",
                  "month",
                  "year",
                  "all"
                ]
              },
              "limit": {
                "type": "integer",
                "description": "Number of posts to fetch per search.",
                "minimum": 1,
                "maximum": 25,
                "default": 10
              },
              "author": {
                "type": "string",
                "description": "Optional platform profile/handle filter. For Bluesky, this maps to the author filter."
              },
              "include_comments": {
                "type": "boolean",
                "description": "Whether to fetch comments/replies for returned posts when supported.",
                "default": false
              },
              "comments_limit": {
                "type": "integer",
                "description": "Number of comments/replies to fetch per returned post when supported.",
                "minimum": 0,
                "maximum": 5,
                "default": 0
              },
              "comments_sort": {
                "type": "string",
                "description": "Reddit comment sort.",
                "enum": [
                  "confidence",
                  "top",
                  "new",
                  "controversial",
                  "old"
                ],
                "default": "top"
              },
              "min_score": {
                "type": "integer",
                "description": "Minimum Reddit score/upvotes to include.",
                "minimum": 0
              },
              "min_comments": {
                "type": "integer",
                "description": "Minimum Reddit comment count to include.",
                "minimum": 0
              },
              "exclude_stickied": {
                "type": "boolean",
                "description": "Exclude stickied Reddit posts.",
                "default": true
              },
              "exclude_nsfw": {
                "type": "boolean",
                "description": "Exclude NSFW Reddit posts.",
                "default": true
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "tasks",
    "skill_id": "create",
    "app_namespace_ts": "tasks",
    "skill_method_ts": "create",
    "app_namespace_py": "tasks",
    "skill_method_py": "create",
    "description_key": "tasks.skills.create.description",
    "description": "Create one or more user-visible tasks. Use this for planning, task capture, or breaking a request into trackable work. Default unclear assignees to the user.",
    "schema": {
      "type": "object",
      "properties": {
        "tasks": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "title": {
                "type": "string"
              },
              "description": {
                "type": "string"
              },
              "assignee": {
                "type": "string",
                "enum": [
                  "user",
                  "openmates"
                ]
              },
              "status": {
                "type": "string",
                "enum": [
                  "backlog",
                  "todo",
                  "in_progress",
                  "blocked"
                ]
              }
            }
          }
        },
        "title": {
          "type": "string",
          "description": "Single-task title when not using tasks[]."
        },
        "description": {
          "type": "string"
        },
        "assignee": {
          "type": "string",
          "enum": [
            "user",
            "openmates"
          ]
        }
      },
      "required": []
    }
  },
  {
    "app_id": "tasks",
    "skill_id": "search",
    "app_namespace_ts": "tasks",
    "skill_method_ts": "search",
    "app_namespace_py": "tasks",
    "skill_method_py": "search",
    "description_key": "tasks.skills.search.description",
    "description": "Search the user's encrypted tasks through a connected capable client. Do not use server-visible metadata as a private task-content search fallback.",
    "schema": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Private task text to search for on a connected client."
        }
      },
      "required": [
        "query"
      ]
    }
  },
  {
    "app_id": "travel",
    "skill_id": "search_connections",
    "app_namespace_ts": "travel",
    "skill_method_ts": "searchConnections",
    "app_namespace_py": "travel",
    "skill_method_py": "search_connections",
    "description_key": "app_skills.travel.search_connections.description",
    "description": "Search for flight or train connections for a particular date with details (airlines/operators, times, stops, durations, prices). Use when user asks about flights, train connections, or travel between cities on a specific date. Set transport_methods to [\"airplane\"] for flights or [\"train\"] for trains. If the user names a provider, set providers to one or more of: google_flights, deutsche_bahn, flix. If no provider is specified, all providers for the selected transport method are searched. Add cou",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of connection search requests. Each request searches for transport connections for a complete trip (one-way, round trip, or multi-stop).\n",
          "items": {
            "type": "object",
            "properties": {
              "legs": {
                "type": "array",
                "description": "Ordered list of trip legs. One-way trip = 1 leg. Round trip = 2 legs (outbound + return). Multi-stop = N legs. Each leg specifies an origin, destination, and departure date.\n",
                "items": {
                  "type": "object",
                  "properties": {
                    "origin": {
                      "type": "string",
                      "description": "Origin city or location name (e.g. \"Munich\", \"London Heathrow\", \"Berlin\"). The system resolves this to airport codes or coordinates internally.\n"
                    },
                    "destination": {
                      "type": "string",
                      "description": "Destination city or location name."
                    },
                    "date": {
                      "type": "string",
                      "description": "Departure date in YYYY-MM-DD format."
                    }
                  },
                  "required": [
                    "origin",
                    "destination",
                    "date"
                  ]
                }
              },
              "transport_methods": {
                "type": "array",
                "description": "Transport types to search. Supported: \"airplane\" (worldwide via Google Flights), \"train\" (Germany + select European routes via Deutsche Bahn and FlixTrain). IMPORTANT: Set to [\"train\"] when user asks about trains, rail, or Deutsche Bahn.\n",
                "items": {
                  "type": "string",
                  "enum": [
                    "airplane",
                    "train",
                    "bus",
                    "boat"
                  ]
                },
                "default": [
                  "airplane"
                ]
              },
              "providers": {
                "type": "array",
                "description": "Optional provider IDs to search. Use \"google_flights\" for flights, \"deutsche_bahn\" for Deutsche Bahn / ICE / Bahn.de / Sparpreis train searches, and \"flix\" for FlixBus / FlixTrain. If omitted, all providers for the selected transport method are used, then filtered by countries if provided.\n",
                "items": {
                  "type": "string",
                  "enum": [
                    "google_flights",
                    "deutsche_bahn",
                    "flix"
                  ]
                }
              },
              "countries": {
                "type": "array",
                "description": "ISO 3166-1 alpha-2 country codes involved in the route, inferred from origin, destination, and known stops. Country matching is OR: a provider is relevant when it supports at least one listed country. Google Flights is global and remains eligible for airplane searches in all countries.\n",
                "items": {
                  "type": "string"
                }
              },
              "passengers": {
                "type": "integer",
                "description": "Number of adult passengers.",
                "default": 1
              },
              "travel_class": {
                "type": "string",
                "description": "Cabin class for flights.",
                "enum": [
                  "economy",
                  "premium_economy",
                  "business",
                  "first"
                ],
                "default": "economy"
              },
              "max_results": {
                "type": "integer",
                "description": "Maximum number of connection options to return per transport method.",
                "default": 6
              },
              "non_stop_only": {
                "type": "boolean",
                "description": "If true, only return direct/non-stop connections.",
                "default": false
              },
              "max_stops": {
                "type": "integer",
                "description": "Maximum number of stops allowed. Use 0 for direct/non-stop only, 1 for up to one stop, or 2 for up to two stops."
              },
              "max_price": {
                "type": "number",
                "description": "Maximum total price for the connection in the requested currency. Results above this price are filtered from strict matches."
              },
              "include_airlines": {
                "type": "array",
                "description": "Only show flights from these airlines. Use IATA carrier codes when known, such as LH, BA, VY, or FR.",
                "items": {
                  "type": "string"
                }
              },
              "exclude_airlines": {
                "type": "array",
                "description": "Exclude flights from these airlines. Use IATA carrier codes when known. Do not combine with include_airlines.",
                "items": {
                  "type": "string"
                }
              },
              "min_departure_time": {
                "type": "string",
                "description": "Earliest acceptable local departure time in HH:MM format."
              },
              "max_departure_time": {
                "type": "string",
                "description": "Latest acceptable local departure time in HH:MM format."
              },
              "min_arrival_time": {
                "type": "string",
                "description": "Earliest acceptable local arrival time in HH:MM format."
              },
              "max_arrival_time": {
                "type": "string",
                "description": "Latest acceptable local arrival time in HH:MM format."
              },
              "max_duration_minutes": {
                "type": "integer",
                "description": "Maximum total duration for the first leg, in minutes."
              },
              "max_layover_minutes": {
                "type": "integer",
                "description": "Maximum allowed layover or transfer duration, in minutes."
              },
              "avoid_overnight_layovers": {
                "type": "boolean",
                "description": "If true, remove connections with overnight layovers or transfers.",
                "default": false
              },
              "currency": {
                "type": "string",
                "description": "Preferred currency for prices (ISO 4217 code).",
                "default": "EUR"
              },
              "sort_by": {
                "type": "string",
                "description": "How to sort the results. Options: \"price_asc\" (cheapest first, default), \"price_desc\" (most expensive first), \"duration_asc\" (shortest first), \"duration_desc\" (longest first), \"departure_asc\" (earliest departure first), \"departure_desc\" (latest departure first), \"stops_asc\" (fewest stops first), \"stops_desc\" (most stops first).\n",
                "enum": [
                  "price_asc",
                  "price_desc",
                  "duration_asc",
                  "duration_desc",
                  "departure_asc",
                  "departure_desc",
                  "stops_asc",
                  "stops_desc"
                ],
                "default": "price_asc"
              }
            },
            "required": [
              "legs"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "travel",
    "skill_id": "search_stays",
    "app_namespace_ts": "travel",
    "skill_method_ts": "searchStays",
    "app_namespace_py": "travel",
    "skill_method_py": "search_stays",
    "description_key": "app_skills.travel.search_stays.description",
    "description": "Run this OpenMates app skill.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "Array of stay search requests. Each request searches for accommodation at a specific destination for given dates.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query describing the destination or property (e.g. \"Hotels in Paris\", \"Hostels near Eiffel Tower\", \"Barcelona beachfront hotel\").\n"
              },
              "check_in_date": {
                "type": "string",
                "description": "Check-in date in YYYY-MM-DD format (e.g. \"2026-03-15\").\n"
              },
              "check_out_date": {
                "type": "string",
                "description": "Check-out date in YYYY-MM-DD format (e.g. \"2026-03-18\").\n"
              },
              "adults": {
                "type": "integer",
                "description": "Number of adult guests.",
                "default": 2
              },
              "children": {
                "type": "integer",
                "description": "Number of children.",
                "default": 0
              },
              "currency": {
                "type": "string",
                "description": "Price currency (ISO 4217 code, e.g. \"EUR\", \"USD\").\n",
                "default": "EUR"
              },
              "sort_by": {
                "type": "string",
                "description": "Sort order for results. Options: \"relevance\" (default), \"price_asc\" (lowest price first), \"rating_desc\" (highest rated first), \"reviews_desc\" (most reviewed).\n",
                "default": "relevance"
              },
              "min_price": {
                "type": "number",
                "description": "Minimum nightly price filter."
              },
              "max_price": {
                "type": "number",
                "description": "Maximum nightly price filter."
              },
              "hotel_class": {
                "type": "string",
                "description": "Comma-separated star rating filter (e.g. \"3,4,5\" for 3-star and above).\n"
              },
              "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return.",
                "default": 10
              }
            },
            "required": [
              "query",
              "check_in_date",
              "check_out_date"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "travel",
    "skill_id": "get_flight",
    "app_namespace_ts": "travel",
    "skill_method_ts": "getFlight",
    "app_namespace_py": "travel",
    "skill_method_py": "get_flight",
    "description_key": "app_skills.travel.get_flight.description",
    "description": "Fetch the real GPS flight track and actual departure/landing times for a specific completed/past flight. Use when the user asks to see how a flight actually went, the real flight path on a map, or actual timing and runway info. Requires the IATA flight number (e.g. 'LH2472') and the departure date. Costs 7 credits per lookup.",
    "schema": {
      "type": "object",
      "properties": {
        "flight_number": {
          "type": "string",
          "description": "IATA flight number including the carrier code prefix (e.g. 'LH2472', 'BA234', 'AF447'). Do NOT include spaces.\n"
        },
        "departure_date": {
          "type": "string",
          "description": "Departure date in YYYY-MM-DD format (e.g. '2026-03-05'). Must be a past/completed date \u2014 live tracking is not supported.\n"
        },
        "origin_iata": {
          "type": "string",
          "description": "Optional IATA code of the departure airport (e.g. 'MUC'). Used for disambiguation when a flight number has multiple legs.\n"
        },
        "destination_iata": {
          "type": "string",
          "description": "Optional IATA code of the destination airport (e.g. 'LHR'). Used for diversion detection.\n"
        }
      },
      "required": [
        "flight_number",
        "departure_date"
      ]
    }
  },
  {
    "app_id": "videos",
    "skill_id": "generate",
    "app_namespace_ts": "videos",
    "skill_method_ts": "generate",
    "app_namespace_py": "videos",
    "skill_method_py": "generate",
    "description_key": "app_skills.videos.generate.description",
    "description": "Generate short photorealistic or generative footage from text prompts using Google Veo. Use this when the user asks for cinematic footage, realistic scenes, camera movement, stylized animation, or non-deterministic video generation. Do not use this for exact text slides, product announcements, diagrams, charts, UI-like motion graphics, or branded videos where exact text and layout matter; those requests should use videos.create with an explicit ```remotion:Name.tsx fence instead. Do not use this",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED array of video generation request objects.",
          "items": {
            "type": "object",
            "properties": {
              "prompt": {
                "type": "string",
                "description": "Detailed text description of the video to generate."
              },
              "aspect_ratio": {
                "type": "string",
                "enum": [
                  "16:9",
                  "9:16"
                ],
                "default": "16:9"
              },
              "duration_seconds": {
                "type": "integer",
                "enum": [
                  4,
                  6,
                  8
                ],
                "default": 8
              },
              "resolution": {
                "type": "string",
                "enum": [
                  "720p",
                  "1080p",
                  "4k"
                ],
                "default": "720p"
              },
              "seed": {
                "type": "integer",
                "description": "Optional seed for more reproducible output when supported."
              },
              "model": {
                "type": "string",
                "enum": [
                  "veo-3.1-generate-preview",
                  "veo-3.1-fast-generate-preview",
                  "veo-3.0-generate-001"
                ],
                "default": "veo-3.1-generate-preview"
              }
            },
            "required": [
              "prompt"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "videos",
    "skill_id": "create",
    "app_namespace_ts": "videos",
    "skill_method_ts": "create",
    "app_namespace_py": "videos",
    "skill_method_py": "create",
    "description_key": "app_skills.videos.create.description",
    "description": "Create deterministic code-backed videos with Remotion. Use this for text slides, product announcements, diagrams, charts, UI-like motion graphics, or branded videos where exact text and layout matter. The assistant must write an explicit ```remotion:Name.tsx fence; do not use this for photorealistic footage or generic TSX components.",
    "schema": {
      "type": "object",
      "properties": {
        "source": {
          "type": "string",
          "description": "Remotion TSX source code to render."
        },
        "filename": {
          "type": "string",
          "description": "Source filename, for example ProductAnnouncement.tsx."
        }
      },
      "required": [
        "source"
      ]
    }
  },
  {
    "app_id": "videos",
    "skill_id": "get_transcript",
    "app_namespace_ts": "videos",
    "skill_method_ts": "getTranscript",
    "app_namespace_py": "videos",
    "skill_method_py": "get_transcript",
    "description_key": "videos.get_transcript.description",
    "description": "Get the transcript/content of a specific YouTube video URL.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of transcript request objects for parallel processing. \nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single transcript.\nExample for single transcript: {\"requests\": [{\"url\": \"https://youtube.com/watch?v=abc123\"}]}\nExample for multiple transcripts: {\"requests\": [{\"url\": \"https://youtube.com/watch?v=abc123\"}, {\"url\": \"https://youtube.com/watch?v=def456\"}]}\nEach object must contain 'url' (YouTube video URL), and can include optional parameters (languages).\nNote: The 'id' field is auto-generated if not provided - you don't need to include it.\n",
          "items": {
            "type": "object",
            "properties": {
              "url": {
                "type": "string",
                "description": "YouTube video URL (supports youtube.com/watch?v= and youtu.be/ formats)"
              },
              "languages": {
                "type": "array",
                "description": "List of language codes to try for transcript (ISO 639-1, e.g., 'en', 'de', 'es', 'fr'). The API will use the first available language.",
                "items": {
                  "type": "string"
                },
                "default": [
                  "en",
                  "de",
                  "es",
                  "fr"
                ]
              }
            },
            "required": [
              "url"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "videos",
    "skill_id": "search",
    "app_namespace_ts": "videos",
    "skill_method_ts": "search",
    "app_namespace_py": "videos",
    "skill_method_py": "search",
    "description_key": "videos.search.description",
    "description": "Search for videos, documentaries, tutorials, clips on the web.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of search request objects for parallel processing (up to 5 requests). \nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single search.\nExample for single search: {\"requests\": [{\"query\": \"Python tutorial\"}]}\nExample for multiple searches: {\"requests\": [{\"query\": \"Python tutorial\"}, {\"query\": \"FastAPI tutorial\"}]}\nEach object must contain 'query' (search query string), and can include optional parameters (count, country, search_lang, safesearch).\nNote: The 'id' field is auto-generated if not provided - you don't need to include it.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query string"
              },
              "count": {
                "type": "integer",
                "description": "Number of results for this request (max 20)",
                "minimum": 1,
                "maximum": 20,
                "default": 6
              },
              "country": {
                "type": "string",
                "description": "Country code for localized results. Must be one of: AR, AU, AT, BE, BR, CA, CL, DK, FI, FR, DE, GR, HK, IN, ID, IT, JP, KR, MY, MX, NL, NZ, NO, CN, PL, PT, PH, RU, SA, ZA, ES, SE, CH, TW, TR, GB, US, or ALL (case-insensitive). Defaults to 'us' if invalid.",
                "enum": [
                  "AR",
                  "AU",
                  "AT",
                  "BE",
                  "BR",
                  "CA",
                  "CL",
                  "DK",
                  "FI",
                  "FR",
                  "DE",
                  "GR",
                  "HK",
                  "IN",
                  "ID",
                  "IT",
                  "JP",
                  "KR",
                  "MY",
                  "MX",
                  "NL",
                  "NZ",
                  "NO",
                  "CN",
                  "PL",
                  "PT",
                  "PH",
                  "RU",
                  "SA",
                  "ZA",
                  "ES",
                  "SE",
                  "CH",
                  "TW",
                  "TR",
                  "GB",
                  "US",
                  "ALL",
                  "ar",
                  "au",
                  "at",
                  "be",
                  "br",
                  "ca",
                  "cl",
                  "dk",
                  "fi",
                  "fr",
                  "de",
                  "gr",
                  "hk",
                  "in",
                  "id",
                  "it",
                  "jp",
                  "kr",
                  "my",
                  "mx",
                  "nl",
                  "nz",
                  "no",
                  "cn",
                  "pl",
                  "pt",
                  "ph",
                  "ru",
                  "sa",
                  "za",
                  "es",
                  "se",
                  "ch",
                  "tw",
                  "tr",
                  "gb",
                  "us",
                  "all"
                ],
                "default": "us"
              },
              "search_lang": {
                "type": "string",
                "description": "Language code for search (ISO 639-1, e.g., 'en', 'es', 'fr')",
                "default": "en"
              },
              "safesearch": {
                "type": "string",
                "description": "Safe search level",
                "enum": [
                  "off",
                  "moderate",
                  "strict"
                ],
                "default": "moderate"
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "weather",
    "skill_id": "forecast",
    "app_namespace_ts": "weather",
    "skill_method_ts": "forecast",
    "app_namespace_py": "weather",
    "skill_method_py": "forecast",
    "description_key": "apps.weather.forecast.description",
    "description": "Get current and upcoming weather forecasts for a place, including daily weather, temperatures, rain likelihood, and hourly details stored in day embeds. Use this for weather questions, forecast requests, and trip/day planning involving weather.",
    "schema": {
      "type": "object",
      "properties": {
        "location": {
          "type": "string",
          "description": "Place name for the forecast, e.g. Berlin, Karlsruhe, Tokyo. Required unless latitude and longitude are provided."
        },
        "days": {
          "type": "integer",
          "description": "Number of forecast days to return. Defaults to 7. Maximum 14.",
          "minimum": 1,
          "maximum": 14,
          "default": 7
        },
        "latitude": {
          "type": "number",
          "description": "Optional latitude in decimal degrees. Use with longitude for exact coordinates."
        },
        "longitude": {
          "type": "number",
          "description": "Optional longitude in decimal degrees. Use with latitude for exact coordinates."
        },
        "timezone": {
          "type": "string",
          "description": "Optional IANA timezone. Defaults to provider/location timezone."
        },
        "units": {
          "type": "string",
          "description": "Unit system. Only metric is currently supported.",
          "enum": [
            "metric"
          ],
          "default": "metric"
        }
      },
      "required": [
        "location"
      ]
    }
  },
  {
    "app_id": "weather",
    "skill_id": "rain_radar",
    "app_namespace_ts": "weather",
    "skill_method_ts": "rainRadar",
    "app_namespace_py": "weather",
    "skill_method_py": "rain_radar",
    "description_key": "apps.weather.rain_radar.description",
    "description": "Get nearby German rain radar with a timeline, including whether rain is visible now, whether rain is expected around the selected location in about 10 minutes, and compact frame-by-frame rain intensity metadata. Use this for rain radar, precipitation radar, and hyperlocal \"will it rain here soon\" questions in Germany.",
    "schema": {
      "type": "object",
      "properties": {
        "location": {
          "type": "string",
          "description": "German place name for the radar, e.g. Berlin, Hamburg, Munich. Required unless latitude and longitude are provided."
        },
        "latitude": {
          "type": "number",
          "description": "Optional latitude in decimal degrees. Use with longitude for exact coordinates. V1 supports Germany only."
        },
        "longitude": {
          "type": "number",
          "description": "Optional longitude in decimal degrees. Use with latitude for exact coordinates. V1 supports Germany only."
        },
        "radius_km": {
          "type": "integer",
          "description": "Radar radius around the location in kilometers. Defaults to 5 for a neighborhood/city-part view. Maximum 100.",
          "minimum": 1,
          "maximum": 100,
          "default": 5
        },
        "timezone": {
          "type": "string",
          "description": "Optional IANA timezone. Defaults to provider/location timezone."
        }
      },
      "required": [
        "location"
      ]
    }
  },
  {
    "app_id": "web",
    "skill_id": "search",
    "app_namespace_ts": "web",
    "skill_method_ts": "search",
    "app_namespace_py": "web",
    "skill_method_py": "search",
    "description_key": "app_skills.web.search.description",
    "description": "General web search for current information, prices, weather, facts, stocks, sports scores, etc. Use as a fallback when no specialized skill applies.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of search request objects for parallel processing (up to 5 requests). \nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single search.\nExample for single search: {\"requests\": [{\"query\": \"Python async\"}]}\nExample for multiple searches: {\"requests\": [{\"query\": \"Python async\"}, {\"query\": \"FastAPI best practices\"}]}\nEach object must contain 'query' (search query string), and can include optional parameters (count, country, search_lang, safesearch).\nNote: The 'id' field is auto-generated if not provided - you don't need to include it.\n",
          "items": {
            "type": "object",
            "properties": {
              "query": {
                "type": "string",
                "description": "Search query string"
              },
              "count": {
                "type": "integer",
                "description": "Number of results for this request (max 20)",
                "minimum": 1,
                "maximum": 20,
                "default": 6
              },
              "country": {
                "type": "string",
                "description": "Country code for localized results. Must be one of: AR, AU, AT, BE, BR, CA, CL, DK, FI, FR, DE, GR, HK, IN, ID, IT, JP, KR, MY, MX, NL, NZ, NO, CN, PL, PT, PH, RU, SA, ZA, ES, SE, CH, TW, TR, GB, US, or ALL (case-insensitive). Defaults to 'us' if invalid.",
                "enum": [
                  "AR",
                  "AU",
                  "AT",
                  "BE",
                  "BR",
                  "CA",
                  "CL",
                  "DK",
                  "FI",
                  "FR",
                  "DE",
                  "GR",
                  "HK",
                  "IN",
                  "ID",
                  "IT",
                  "JP",
                  "KR",
                  "MY",
                  "MX",
                  "NL",
                  "NZ",
                  "NO",
                  "CN",
                  "PL",
                  "PT",
                  "PH",
                  "RU",
                  "SA",
                  "ZA",
                  "ES",
                  "SE",
                  "CH",
                  "TW",
                  "TR",
                  "GB",
                  "US",
                  "ALL",
                  "ar",
                  "au",
                  "at",
                  "be",
                  "br",
                  "ca",
                  "cl",
                  "dk",
                  "fi",
                  "fr",
                  "de",
                  "gr",
                  "hk",
                  "in",
                  "id",
                  "it",
                  "jp",
                  "kr",
                  "my",
                  "mx",
                  "nl",
                  "nz",
                  "no",
                  "cn",
                  "pl",
                  "pt",
                  "ph",
                  "ru",
                  "sa",
                  "za",
                  "es",
                  "se",
                  "ch",
                  "tw",
                  "tr",
                  "gb",
                  "us",
                  "all"
                ],
                "default": "us"
              },
              "search_lang": {
                "type": "string",
                "description": "Language code for search (ISO 639-1, e.g., 'en', 'es', 'fr')",
                "default": "en"
              },
              "safesearch": {
                "type": "string",
                "description": "Safe search level",
                "enum": [
                  "off",
                  "moderate",
                  "strict"
                ],
                "default": "moderate"
              },
              "filter_tabloids": {
                "type": "boolean",
                "description": "Filter out tabloid/boulevard media sources (e.g., BILD, Daily Mail, TMZ, The Sun) from results. Enabled by default for quality results. Set to false ONLY if the user explicitly asks for tabloid sources.",
                "default": true
              }
            },
            "required": [
              "query"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "web",
    "skill_id": "read",
    "app_namespace_ts": "web",
    "skill_method_ts": "read",
    "app_namespace_py": "web",
    "skill_method_py": "read",
    "description_key": "web.read.description",
    "description": "Read and extract content from a specific URL or webpage the user provided.",
    "schema": {
      "type": "object",
      "properties": {
        "requests": {
          "type": "array",
          "description": "REQUIRED: Array of read request objects for parallel processing (up to 5 requests). \nThis parameter is MANDATORY - you MUST always provide a 'requests' array, even for a single URL.\nExample for single URL: {\"requests\": [{\"id\": 1, \"url\": \"https://example.com/article\"}]}\nExample for multiple URLs: {\"requests\": [{\"id\": 1, \"url\": \"https://example.com/article1\"}, {\"id\": 2, \"url\": \"https://example.com/article2\"}]}\nEach object must contain 'id' (unique identifier) and 'url' (webpage URL), and can include optional parameters (formats, only_main_content, max_age, timeout).\n",
          "items": {
            "type": "object",
            "properties": {
              "url": {
                "type": "string",
                "description": "URL of the webpage to read/scrape"
              },
              "formats": {
                "type": "array",
                "description": "List of output formats to include (e.g., 'markdown', 'html', 'summary')",
                "items": {
                  "type": "string"
                },
                "default": [
                  "markdown"
                ]
              },
              "only_main_content": {
                "type": "boolean",
                "description": "Whether to return only main content (excluding headers, navs, footers, etc.)",
                "default": true
              },
              "max_age": {
                "type": "integer",
                "description": "Cache age in milliseconds (default: 172800000 = 2 days). Returns cached version if available."
              },
              "timeout": {
                "type": "integer",
                "description": "Timeout in milliseconds for the request"
              }
            },
            "required": [
              "url"
            ]
          }
        }
      },
      "required": [
        "requests"
      ]
    }
  },
  {
    "app_id": "workflows",
    "skill_id": "create-or-modify",
    "app_namespace_ts": "workflows",
    "skill_method_ts": "createOrModify",
    "app_namespace_py": "workflows",
    "skill_method_py": "create_or_modify",
    "description_key": "workflows.skills.create_or_modify.description",
    "description": "Create or modify exactly one workflow from chat. Do not batch multiple workflows into one skill call.",
    "schema": {
      "type": "object",
      "properties": {
        "workflow_id": {
          "type": "string",
          "description": "Existing workflow ID when modifying a workflow."
        },
        "title": {
          "type": "string",
          "description": "Short user-facing workflow title."
        },
        "graph": {
          "type": "object",
          "description": "Valid WorkflowGraph definition."
        }
      },
      "required": [
        "title"
      ]
    }
  },
  {
    "app_id": "workflows",
    "skill_id": "search",
    "app_namespace_ts": "workflows",
    "skill_method_ts": "search",
    "app_namespace_py": "workflows",
    "skill_method_py": "search",
    "description_key": "workflows.skills.search.description",
    "description": "Search the user's existing persisted workflows before proposing a new automation. Include temporary workflows only when the user explicitly asks about recent chat-created workflows.",
    "schema": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Workflow title or intent text to search for."
        },
        "include_temporary": {
          "type": "boolean",
          "description": "Include temporary chat-created workflows in the search results."
        }
      }
    }
  }
] as const;

export class AiAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Run this OpenMates app skill.
   * Description key: ai.ask.description
   * Skill: ai/ask
   */
  async ask<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("ai", "ask", input);
  }
}

export class BooksAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Run this OpenMates app skill.
   * Description key: books.translate.description
   * Skill: books/translate
   */
  async translate<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("books", "translate", input);
  }
}

export class CodeAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Run this OpenMates app skill.
   * Description key: code.add_issue.description
   * Skill: code/add_issue
   */
  async addIssue<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("code", "add_issue", input);
  }
  /**
   * Run this OpenMates app skill.
   * Description key: code.clean_repo.description
   * Skill: code/clean_repo
   */
  async cleanRepo<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("code", "clean_repo", input);
  }
  /**
   * Get latest documentation for programming libraries, frameworks, APIs, SDKs. Use for ANY programming-related query about a specific library or framework.
   * Description key: code.get_docs.description
   * Skill: code/get_docs
   */
  async getDocs<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("code", "get_docs", input);
  }
  /**
   * Run this OpenMates app skill.
   * Description key: code.get_issues.description
   * Skill: code/get_issues
   */
  async getIssues<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("code", "get_issues", input);
  }
  /**
   * Run this OpenMates app skill.
   * Description key: code.get_project_overview.description
   * Skill: code/get_project_overview
   */
  async getProjectOverview<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("code", "get_project_overview", input);
  }
  /**
   * Run this OpenMates app skill.
   * Description key: code.remove_secrets.description
   * Skill: code/remove_secrets
   */
  async removeSecrets<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("code", "remove_secrets", input);
  }
  /**
   * Search GitHub repositories. Use this instead of web.search whenever the user asks to find GitHub repos, repositories, open-source libraries, starred repos, or repo examples by topic, language, framework, or project need. Returns licensed repository embeds. Costs 10 credits per search.
   * Description key: code.search_repos.description
   * Skill: code/search_repos
   */
  async searchRepos<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("code", "search_repos", input);
  }
}

export class DesignAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search for free SVG icons for UI, product, interface, or graphic design. Use this when the user asks to find icons by name, concept, object, or action. Do not use it for brand-logo search or generated icon creation.
   * Description key: app_skills.design.search_icons.description
   * Skill: design/search_icons
   */
  async searchIcons<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("design", "search_icons", input);
  }
}

export class ElectronicsAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Use this skill when the user asks to find electronic components, especially power converters or voltage regulators matching input voltage, output voltage, output current, efficiency, BOM cost, footprint, or topology requirements. Currently supports category power_converters via Texas Instruments WEBENCH Power Designer.
   * Description key: electronics.search_components.description
   * Skill: electronics/search_components
   */
  async searchComponents<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("electronics", "search_components", input);
  }
}

export class EventsAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search for local or online events, meetups, hackathons, conferences, workshops, networking events, parties, concerts, or any community gathering. Use ONLY this skill for event searches — do NOT additionally call web.search or any other search skill for the same query. Sources: Meetup, Luma, Eventbrite, Google Events, Resident Advisor (electronic music/clubs), Siegessäule (Berlin LGBTQ+ events), Berlin Philharmonic (classical concerts in Berlin), and official event schedules for GPN24, 39C3, 38C3
   * Description key: events.search.description
   * Skill: events/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("events", "search", input);
  }
}

export class FitnessAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search available Urban Sports Club public fitness classes. Use this when the user asks for dated fitness classes, course availability, free spots, on-site classes, online classes, or plan-filtered Urban Sports classes. Omit plan unless the user explicitly asks for Essential, Classic, Premium, or Max.
   * Description key: fitness.search_classes.description
   * Skill: fitness/search_classes
   */
  async searchClasses<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("fitness", "search_classes", input);
  }
  /**
   * Search Urban Sports Club public fitness locations. Use this when the user asks for gyms, studios, pools, or Urban Sports locations near a city, address, or radius. Do not use it for class availability; use fitness.search_classes for dated class searches.
   * Description key: fitness.search_locations.description
   * Skill: fitness/search_locations
   */
  async searchLocations<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("fitness", "search_locations", input);
  }
}

export class HealthAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Run this OpenMates app skill.
   * Description key: health.create_report.description
   * Skill: health/create_report
   */
  async createReport<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("health", "create_report", input);
  }
  /**
   * Search available medical appointments at German doctors/specialists by speciality and city. Covers any medical booking — general practitioners, specialists (e.g. dentist, dermatologist, gynecologist), scans and imaging (e.g. MRT/MRI, CT, Röntgen, Ultraschall), vaccinations, check-ups, blood tests, and other examinations. Note: "Termin" in a medical context means appointment, not event — route here instead of events-search. Sources: Doctolib, Jameda (Germany only).
   * Description key: app_skills.health.search_appointments.description
   * Skill: health/search_appointments
   */
  async searchAppointments<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("health", "search_appointments", input);
  }
}

export class HomeAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search for apartments, houses, and WG rooms in German cities. Searches ImmoScout24, Kleinanzeigen, and WG-Gesucht simultaneously. Returns listings with prices, sizes, rooms, addresses, and direct links. Costs 10 credits per search. Use when user asks about finding housing in Germany.
   * Description key: app_skills.home.search.description
   * Skill: home/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("home", "search", input);
  }
}

export class ImagesAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Generate high-quality images from text prompts and/or reference images (image-to-image editing). Also use for: mockups, design concepts, visual mockup creation, logo mockups, product mockups, illustration requests, visual design, concept art, posters, banners, thumbnails, or any request that implies creating a visual output. Use output_filetype="svg" for logos, icons, illustrations, and any other vector graphics that need to be scalable or editable. When the user provides uploaded images as refe
   * Description key: images.generate.description
   * Skill: images/generate
   */
  async generate<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("images", "generate", input);
  }
  /**
   * Quickly generate a draft/preview image from a text prompt and/or reference images (image-to-image). Also use for: quick mockups, rough design concepts, draft illustrations, sketches, quick visual previews, or any request for a fast/rough image. When the user provides uploaded images as references (embed_refs), pass them via reference_images. Do not use this for scam, spam, fake-document, fake-endorsement, public-figure impersonation, or watermark/detection-evasion requests.
   * Description key: images.generate_draft.description
   * Skill: images/generate_draft
   */
  async generateDraft<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("images", "generate_draft", input);
  }
}

export class MailAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Run this OpenMates app skill.
   * Description key: app_skills.mail.search.description
   * Skill: mail/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("mail", "search", input);
  }
}

export class MapsAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search for places, businesses, restaurants, directions, locations.
   * Description key: maps.search.description
   * Skill: maps/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("maps", "search", input);
  }
}

export class MathAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * MANDATORY: Use this skill for ALL mathematical calculations without exception. This includes simple arithmetic such as addition, subtraction, multiplication (written as *, x, or ×), division, and parenthesised expressions like (4x22x7)/2 or (100+50)*3/2. Also use for algebra, trigonometry, calculus, unit conversions, symbolic simplification, equation solving, derivatives, and integrals. NEVER attempt to compute a numeric result yourself — always call this skill so results are guaranteed to be ex
   * Description key: math.calculate.description
   * Skill: math/calculate
   */
  async calculate<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("math", "calculate", input);
  }
}

export class Models3dAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search public 3D model catalogs for existing models. Use this when the user wants to find, browse, compare, or link to existing 3D-printable or downloadable 3D models. Do not use it to generate new models.
   * Description key: app_skills.models3d.search.description
   * Skill: models3d/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("models3d", "search", input);
  }
}

export class MusicAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Generate music from a text prompt, including full songs, instrumental tracks, background music, loops, jingles, lyric-based songs, and soundtrack cues. Use this when the user asks to create music or background music. Do not use this to imitate the voice, vocals, cadence, or persona of a real public figure, living artist, famous educator, or recognizable person. Use original voices and styles only, and reject scams, spam, or detection evasion.
   * Description key: app_skills.music.generate.description
   * Skill: music/generate
   */
  async generate<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("music", "generate", input);
  }
}

export class NewsAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search for news articles, current events, headlines, announcements.
   * Description key: news.search.description
   * Skill: news/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("news", "search", input);
  }
}

export class NutritionAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search Edamam for recipes by natural-language query and nutrition filters. Returns recipe details with ingredients, step-by-step instructions, images, source links, and nutrition metadata. Recipes without instructions are filtered out. Best for: recipe recommendations, meal planning, dietary filtering, and cooking guidance.
   * Description key: app_skills.nutrition.search_recipes.description
   * Skill: nutrition/search_recipes
   */
  async searchRecipes<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("nutrition", "search_recipes", input);
  }
}

export class OpenmatesAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Use when the user shares an openmates.org/docs URL, or asks to read a specific OpenMates documentation page. Automatically triggered when an openmates docs URL is detected in the conversation.
   * Description key: openmates_app.get_docs.description
   * Skill: openmates/get-docs
   */
  async getDocs<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("openmates", "get-docs", input);
  }
  /**
   * Use when the user asks about OpenMates features, setup, architecture, or documentation. Searches across all OpenMates documentation to find relevant pages.
   * Description key: openmates_app.search_docs.description
   * Skill: openmates/search-docs
   */
  async searchDocs<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("openmates", "search-docs", input);
  }
  /**
   * Use when the user has explicitly agreed to anonymously share a summary of their intended use cases with the OpenMates team to help improve the product. NEVER call this without clear user consent.
   * Description key: openmates_app.share_usecase.description
   * Skill: openmates/share-usecase
   */
  async shareUsecase<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("openmates", "share-usecase", input);
  }
}

export class PdfAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Load and read the raw text content (markdown) of specific pages from an uploaded PDF document. Use when the user asks what a PDF says, wants you to summarise sections, or requests information that is likely textual (paragraphs, tables, headings). The embed TOON content includes a TOC and per-page token estimates — use them to select the most relevant pages. Limits output to 50 000 tokens; call again for remaining pages if needed. Pass the exact embed_ref (original filename) from the toon block —
   * Description key: pdf.read.description
   * Skill: pdf/read
   */
  async read<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("pdf", "read", input);
  }
  /**
   * Search for specific text, keywords, or phrases across all pages of an uploaded PDF. Returns matching text blocks with surrounding context and page numbers. Use when the user asks to find where something is mentioned in the document, or when a targeted keyword search is faster than reading entire sections. No LLM call required — pure text search over the OCR data. Pass the exact embed_ref (original filename) from the toon block as file_path.
   * Description key: pdf.search.description
   * Skill: pdf/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("pdf", "search", input);
  }
  /**
   * View one or more page screenshots from an uploaded PDF and return them as multimodal image blocks so the main inference model can see the pages directly. Use when the user asks about the visual layout, diagrams, charts, figures, or images on specific pages. Also useful when text OCR may have been imperfect (e.g. complex tables, mathematical notation, handwriting). Up to 5 pages can be viewed per call. Pass the exact embed_ref (original filename) from the toon block as file_path — the server reso
   * Description key: pdf.view.skill_description
   * Skill: pdf/view
   */
  async view<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("pdf", "view", input);
  }
}

export class ReminderAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Cancel or delete an existing reminder.
   * Description key: reminder.cancel_reminder.description
   * Skill: reminder/cancel-reminder
   */
  async cancelReminder<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("reminder", "cancel-reminder", input);
  }
  /**
   * Show the user's existing scheduled reminders.
   * Description key: reminder.list_reminders.description
   * Skill: reminder/list-reminders
   */
  async listReminders<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("reminder", "list-reminders", input);
  }
  /**
   * Schedule, create, or set up reminders for the user. Handles one-time and recurring reminders (e.g., "every morning", "daily at 9am", "weekly", "monthly"). Use when user wants to be reminded, notified, or alerted about something at a specific time or on a recurring schedule. Also use for automating tasks like "get news every day" or "summarize updates weekly".
   * Description key: reminder.set_reminder.description
   * Skill: reminder/set-reminder
   */
  async setReminder<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("reminder", "set-reminder", input);
  }
}

export class ShoppingAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Search products on REWE, Amazon, or Stoffe.de with real-time prices. Use category to route groceries, marketplace products, fabrics, sewing supplies, and patterns to compatible providers. Invalid provider/category combinations are rejected.
   * Description key: app_skills.shopping.search_products.description
   * Skill: shopping/search_products
   */
  async searchProducts<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("shopping", "search_products", input);
  }
}

export class SocialMediaAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Fetch recent social media posts from one or more specific platform pages or profiles. Supports Reddit subreddits, Bluesky profile feeds, and Mastodon public profiles. Use for profile monitoring, community research, and finding conversations to review manually. Costs 10 credits per request.
   * Description key: app_skills.social_media.get_posts.description
   * Skill: social_media/get-posts
   */
  async getPosts<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("social_media", "get-posts", input);
  }
  /**
   * Search supported social platforms for recent public posts around a topic. Use this for topic monitoring and broad discovery across pages/profiles, not for monitoring a known profile; use Get posts for profile/page posts. Omit platform to search every supported social platform. Costs 10 credits per request.
   * Description key: app_skills.social_media.search.description
   * Skill: social_media/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("social_media", "search", input);
  }
}

export class TasksAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Create one or more user-visible tasks. Use this for planning, task capture, or breaking a request into trackable work. Default unclear assignees to the user.
   * Description key: tasks.skills.create.description
   * Skill: tasks/create
   */
  async create<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("tasks", "create", input);
  }
  /**
   * Search the user's encrypted tasks through a connected capable client. Do not use server-visible metadata as a private task-content search fallback.
   * Description key: tasks.skills.search.description
   * Skill: tasks/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("tasks", "search", input);
  }
}

export class TravelAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Fetch the real GPS flight track and actual departure/landing times for a specific completed/past flight. Use when the user asks to see how a flight actually went, the real flight path on a map, or actual timing and runway info. Requires the IATA flight number (e.g. 'LH2472') and the departure date. Costs 7 credits per lookup.
   * Description key: app_skills.travel.get_flight.description
   * Skill: travel/get_flight
   */
  async getFlight<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("travel", "get_flight", input);
  }
  /**
   * Search for flight or train connections for a particular date with details (airlines/operators, times, stops, durations, prices). Use when user asks about flights, train connections, or travel between cities on a specific date. Set transport_methods to ["airplane"] for flights or ["train"] for trains. If the user names a provider, set providers to one or more of: google_flights, deutsche_bahn, flix. If no provider is specified, all providers for the selected transport method are searched. Add cou
   * Description key: app_skills.travel.search_connections.description
   * Skill: travel/search_connections
   */
  async searchConnections<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("travel", "search_connections", input);
  }
  /**
   * Run this OpenMates app skill.
   * Description key: app_skills.travel.search_stays.description
   * Skill: travel/search_stays
   */
  async searchStays<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("travel", "search_stays", input);
  }
}

export class VideosAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Create deterministic code-backed videos with Remotion. Use this for text slides, product announcements, diagrams, charts, UI-like motion graphics, or branded videos where exact text and layout matter. The assistant must write an explicit ```remotion:Name.tsx fence; do not use this for photorealistic footage or generic TSX components.
   * Description key: app_skills.videos.create.description
   * Skill: videos/create
   */
  async create<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("videos", "create", input);
  }
  /**
   * Generate short photorealistic or generative footage from text prompts using Google Veo. Use this when the user asks for cinematic footage, realistic scenes, camera movement, stylized animation, or non-deterministic video generation. Do not use this for exact text slides, product announcements, diagrams, charts, UI-like motion graphics, or branded videos where exact text and layout matter; those requests should use videos.create with an explicit ```remotion:Name.tsx fence instead. Do not use this
   * Description key: app_skills.videos.generate.description
   * Skill: videos/generate
   */
  async generate<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("videos", "generate", input);
  }
  /**
   * Get the transcript/content of a specific YouTube video URL.
   * Description key: videos.get_transcript.description
   * Skill: videos/get_transcript
   */
  async getTranscript<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("videos", "get_transcript", input);
  }
  /**
   * Search for videos, documentaries, tutorials, clips on the web.
   * Description key: videos.search.description
   * Skill: videos/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("videos", "search", input);
  }
}

export class WeatherAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Get current and upcoming weather forecasts for a place, including daily weather, temperatures, rain likelihood, and hourly details stored in day embeds. Use this for weather questions, forecast requests, and trip/day planning involving weather.
   * Description key: apps.weather.forecast.description
   * Skill: weather/forecast
   */
  async forecast<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("weather", "forecast", input);
  }
  /**
   * Get nearby German rain radar with a timeline, including whether rain is visible now, whether rain is expected around the selected location in about 10 minutes, and compact frame-by-frame rain intensity metadata. Use this for rain radar, precipitation radar, and hyperlocal "will it rain here soon" questions in Germany.
   * Description key: apps.weather.rain_radar.description
   * Skill: weather/rain_radar
   */
  async rainRadar<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("weather", "rain_radar", input);
  }
}

export class WebAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Read and extract content from a specific URL or webpage the user provided.
   * Description key: web.read.description
   * Skill: web/read
   */
  async read<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("web", "read", input);
  }
  /**
   * General web search for current information, prices, weather, facts, stocks, sports scores, etc. Use as a fallback when no specialized skill applies.
   * Description key: app_skills.web.search.description
   * Skill: web/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("web", "search", input);
  }
}

export class WorkflowsAppSkills {
  private readonly runSkill: AppSkillRunner;
  constructor(runSkill: AppSkillRunner) {
    this.runSkill = runSkill;
  }
  /**
   * Create or modify exactly one workflow from chat. Do not batch multiple workflows into one skill call.
   * Description key: workflows.skills.create_or_modify.description
   * Skill: workflows/create-or-modify
   */
  async createOrModify<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("workflows", "create-or-modify", input);
  }
  /**
   * Search the user's existing persisted workflows before proposing a new automation. Include temporary workflows only when the user explicitly asks about recent chat-created workflows.
   * Description key: workflows.skills.search.description
   * Skill: workflows/search
   */
  async search<T = unknown>(input: SkillInput): Promise<T> {
    return this.runSkill<T>("workflows", "search", input);
  }
}

export class GeneratedAppSkills {
  constructor(runSkill: AppSkillRunner) {
    this.ai = new AiAppSkills(runSkill);
    this.books = new BooksAppSkills(runSkill);
    this.code = new CodeAppSkills(runSkill);
    this.design = new DesignAppSkills(runSkill);
    this.electronics = new ElectronicsAppSkills(runSkill);
    this.events = new EventsAppSkills(runSkill);
    this.fitness = new FitnessAppSkills(runSkill);
    this.health = new HealthAppSkills(runSkill);
    this.home = new HomeAppSkills(runSkill);
    this.images = new ImagesAppSkills(runSkill);
    this.mail = new MailAppSkills(runSkill);
    this.maps = new MapsAppSkills(runSkill);
    this.math = new MathAppSkills(runSkill);
    this.models3d = new Models3dAppSkills(runSkill);
    this.music = new MusicAppSkills(runSkill);
    this.news = new NewsAppSkills(runSkill);
    this.nutrition = new NutritionAppSkills(runSkill);
    this.openmates = new OpenmatesAppSkills(runSkill);
    this.pdf = new PdfAppSkills(runSkill);
    this.reminder = new ReminderAppSkills(runSkill);
    this.shopping = new ShoppingAppSkills(runSkill);
    this.socialMedia = new SocialMediaAppSkills(runSkill);
    this.tasks = new TasksAppSkills(runSkill);
    this.travel = new TravelAppSkills(runSkill);
    this.videos = new VideosAppSkills(runSkill);
    this.weather = new WeatherAppSkills(runSkill);
    this.web = new WebAppSkills(runSkill);
    this.workflows = new WorkflowsAppSkills(runSkill);
  }
  readonly ai: AiAppSkills;
  readonly books: BooksAppSkills;
  readonly code: CodeAppSkills;
  readonly design: DesignAppSkills;
  readonly electronics: ElectronicsAppSkills;
  readonly events: EventsAppSkills;
  readonly fitness: FitnessAppSkills;
  readonly health: HealthAppSkills;
  readonly home: HomeAppSkills;
  readonly images: ImagesAppSkills;
  readonly mail: MailAppSkills;
  readonly maps: MapsAppSkills;
  readonly math: MathAppSkills;
  readonly models3d: Models3dAppSkills;
  readonly music: MusicAppSkills;
  readonly news: NewsAppSkills;
  readonly nutrition: NutritionAppSkills;
  readonly openmates: OpenmatesAppSkills;
  readonly pdf: PdfAppSkills;
  readonly reminder: ReminderAppSkills;
  readonly shopping: ShoppingAppSkills;
  readonly socialMedia: SocialMediaAppSkills;
  readonly tasks: TasksAppSkills;
  readonly travel: TravelAppSkills;
  readonly videos: VideosAppSkills;
  readonly weather: WeatherAppSkills;
  readonly web: WebAppSkills;
  readonly workflows: WorkflowsAppSkills;
}
