/**
 * Real Google Flights (SerpAPI) data. Legs + segments preserved so the child fullscreen can render the route map with real airport coordinates.
 */

export interface TravelSearchConnectionsStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: TravelSearchConnectionsStoreExample[] = [
  {
    "id": "store-example-travel-search-connections-1",
    "query": "Flights from Munich to London",
    "query_translation_key": "settings.app_store_examples.travel.search_connections.1",
    "provider": "Google",
    "status": "finished",
    "results": [
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "97",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Munich (MUC)",
            "destination": "London (LHR)",
            "departure": "2026-06-15 20:50",
            "arrival": "2026-06-15 21:45",
            "duration": "1h 55m",
            "stops": 0,
            "segments": [
              {
                "carrier": "British Airways",
                "carrier_code": "BA",
                "number": "BA 939",
                "departure_station": "MUC",
                "departure_time": "2026-06-15 20:50",
                "departure_latitude": 48.353779,
                "departure_longitude": 11.78608,
                "arrival_station": "LHR",
                "arrival_time": "2026-06-15 21:45",
                "arrival_latitude": 51.471626,
                "arrival_longitude": -0.467081,
                "duration": "1h 55m",
                "departure_country_code": "DE",
                "arrival_country_code": "GB",
                "departure_is_daytime": true,
                "arrival_is_daytime": false,
                "airplane": "Airbus A320neo",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/BA.png",
                "legroom": "29 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (29 in)",
                  "Wi-Fi for a fee",
                  "In-seat USB outlet",
                  "Carbon emissions estimate: 79 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Munich (MUC)",
        "destination": "London (LHR)",
        "departure": "2026-06-15 20:50",
        "arrival": "2026-06-15 21:45",
        "duration": "1h 55m",
        "stops": 0,
        "carriers": [
          "British Airways"
        ],
        "carrier_codes": [
          "BA"
        ],
        "booking_token": "WyJDalJJWmpCNVZ6UkRkV1pYTkVsQlN6ZDFVbmRDUnkwdExTMHRMUzB0TFc5NVkya3lPRUZCUVVGQlIyNWhNVVJKVG13emMxTkJFZ1ZDUVRrek9Sb0tDT1JMRUFJYUEwVlZVamdjY085WSIsW1siTVVDIiwiMjAyNi0wNi0xNSIsIkxIUiIsbnVsbCwiQkEiLCI5MzkiXV1d",
        "booking_context": {
          "departure_id": "MUC",
          "arrival_id": "LHR",
          "outbound_date": "2026-06-15",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/BA.png",
        "co2_kg": 80,
        "co2_typical_kg": 88,
        "co2_difference_percent": -9
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "131",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Munich (MUC)",
            "destination": "London (LHR)",
            "departure": "2026-06-15 17:20",
            "arrival": "2026-06-15 18:25",
            "duration": "2h 5m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Lufthansa",
                "carrier_code": "LH",
                "number": "LH 2486",
                "departure_station": "MUC",
                "departure_time": "2026-06-15 17:20",
                "departure_latitude": 48.353779,
                "departure_longitude": 11.78608,
                "arrival_station": "LHR",
                "arrival_time": "2026-06-15 18:25",
                "arrival_latitude": 51.471626,
                "arrival_longitude": -0.467081,
                "duration": "2h 5m",
                "departure_country_code": "DE",
                "arrival_country_code": "GB",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A320neo",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
                "legroom": "29 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (29 in)",
                  "In-seat USB outlet",
                  "Carbon emissions estimate: 84 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Munich (MUC)",
        "destination": "London (LHR)",
        "departure": "2026-06-15 17:20",
        "arrival": "2026-06-15 18:25",
        "duration": "2h 5m",
        "stops": 0,
        "carriers": [
          "Lufthansa"
        ],
        "carrier_codes": [
          "LH"
        ],
        "booking_token": "WyJDalJJWmpCNVZ6UkRkV1pYTkVsQlN6ZDFVbmRDUnkwdExTMHRMUzB0TFc5NVkya3lPRUZCUVVGQlIyNWhNVVJKVG13emMxTkJFZ1pNU0RJME9EWWFDZ2o2WlJBQ0dnTkZWVkk0SEhESGR3PT0iLFtbIk1VQyIsIjIwMjYtMDYtMTUiLCJMSFIiLG51bGwsIkxIIiwiMjQ4NiJdXV0=",
        "booking_context": {
          "departure_id": "MUC",
          "arrival_id": "LHR",
          "outbound_date": "2026-06-15",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 84,
        "co2_typical_kg": 88,
        "co2_difference_percent": -5
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "131",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Munich (MUC)",
            "destination": "London (LHR)",
            "departure": "2026-06-15 18:35",
            "arrival": "2026-06-15 19:40",
            "duration": "2h 5m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Lufthansa",
                "carrier_code": "LH",
                "number": "LH 2480",
                "departure_station": "MUC",
                "departure_time": "2026-06-15 18:35",
                "departure_latitude": 48.353779,
                "departure_longitude": 11.78608,
                "arrival_station": "LHR",
                "arrival_time": "2026-06-15 19:40",
                "arrival_latitude": 51.471626,
                "arrival_longitude": -0.467081,
                "duration": "2h 5m",
                "departure_country_code": "DE",
                "arrival_country_code": "GB",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A320neo",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
                "legroom": "29 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (29 in)",
                  "In-seat USB outlet",
                  "Carbon emissions estimate: 84 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Munich (MUC)",
        "destination": "London (LHR)",
        "departure": "2026-06-15 18:35",
        "arrival": "2026-06-15 19:40",
        "duration": "2h 5m",
        "stops": 0,
        "carriers": [
          "Lufthansa"
        ],
        "carrier_codes": [
          "LH"
        ],
        "booking_token": "WyJDalJJWmpCNVZ6UkRkV1pYTkVsQlN6ZDFVbmRDUnkwdExTMHRMUzB0TFc5NVkya3lPRUZCUVVGQlIyNWhNVVJKVG13emMxTkJFZ1pNU0RJME9EQWFDZ2o2WlJBQ0dnTkZWVkk0SEhESGR3PT0iLFtbIk1VQyIsIjIwMjYtMDYtMTUiLCJMSFIiLG51bGwsIkxIIiwiMjQ4MCJdXV0=",
        "booking_context": {
          "departure_id": "MUC",
          "arrival_id": "LHR",
          "outbound_date": "2026-06-15",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 84,
        "co2_typical_kg": 88,
        "co2_difference_percent": -5
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "131",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Munich (MUC)",
            "destination": "London (LHR)",
            "departure": "2026-06-15 19:40",
            "arrival": "2026-06-15 20:45",
            "duration": "2h 5m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Lufthansa",
                "carrier_code": "LH",
                "number": "LH 2482",
                "departure_station": "MUC",
                "departure_time": "2026-06-15 19:40",
                "departure_latitude": 48.353779,
                "departure_longitude": 11.78608,
                "arrival_station": "LHR",
                "arrival_time": "2026-06-15 20:45",
                "arrival_latitude": 51.471626,
                "arrival_longitude": -0.467081,
                "duration": "2h 5m",
                "departure_country_code": "DE",
                "arrival_country_code": "GB",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A320neo",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
                "legroom": "29 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (29 in)",
                  "In-seat USB outlet",
                  "Carbon emissions estimate: 84 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Munich (MUC)",
        "destination": "London (LHR)",
        "departure": "2026-06-15 19:40",
        "arrival": "2026-06-15 20:45",
        "duration": "2h 5m",
        "stops": 0,
        "carriers": [
          "Lufthansa"
        ],
        "carrier_codes": [
          "LH"
        ],
        "booking_token": "WyJDalJJWmpCNVZ6UkRkV1pYTkVsQlN6ZDFVbmRDUnkwdExTMHRMUzB0TFc5NVkya3lPRUZCUVVGQlIyNWhNVVJKVG13emMxTkJFZ1pNU0RJME9ESWFDZ2o2WlJBQ0dnTkZWVkk0SEhESGR3PT0iLFtbIk1VQyIsIjIwMjYtMDYtMTUiLCJMSFIiLG51bGwsIkxIIiwiMjQ4MiJdXV0=",
        "booking_context": {
          "departure_id": "MUC",
          "arrival_id": "LHR",
          "outbound_date": "2026-06-15",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 84,
        "co2_typical_kg": 88,
        "co2_difference_percent": -5
      }
    ]
  },
  {
    "id": "store-example-travel-search-connections-2",
    "query": "Flights from Berlin to Barcelona",
    "query_translation_key": "settings.app_store_examples.travel.search_connections.2",
    "provider": "Google",
    "status": "finished",
    "results": [
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "81",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Berlin (BER)",
            "destination": "Barcelona (BCN)",
            "departure": "2026-05-20 12:15",
            "arrival": "2026-05-20 14:50",
            "duration": "2h 35m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Ryanair",
                "carrier_code": "FR",
                "number": "FR 132",
                "departure_station": "BER",
                "departure_time": "2026-05-20 12:15",
                "departure_latitude": 52.362877,
                "departure_longitude": 13.503722,
                "arrival_station": "BCN",
                "arrival_time": "2026-05-20 14:50",
                "arrival_latitude": 41.29707,
                "arrival_longitude": 2.078463,
                "duration": "2h 35m",
                "departure_country_code": "DE",
                "arrival_country_code": "ES",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Boeing 737",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/FR.png",
                "legroom": "30 in",
                "travel_class": "Economy",
                "extensions": [
                  "Average legroom (30 in)",
                  "Carbon emissions estimate: 128 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Berlin (BER)",
        "destination": "Barcelona (BCN)",
        "departure": "2026-05-20 12:15",
        "arrival": "2026-05-20 14:50",
        "duration": "2h 35m",
        "stops": 0,
        "carriers": [
          "Ryanair"
        ],
        "carrier_codes": [
          "FR"
        ],
        "booking_token": "WyJDalJJVm5GQ1JXeHNOVUpVYVRCQlExYzJYMmRDUnkwdExTMHRMUzB0TFhaM2MyNHhOMEZCUVVGQlIyNWhNVVJGU0RkU05HRkJFZ1ZHVWpFek1ob0tDS00vRUFJYUEwVlZVamdjY0psSyIsW1siQkVSIiwiMjAyNi0wNS0yMCIsIkJDTiIsbnVsbCwiRlIiLCIxMzIiXV1d",
        "booking_context": {
          "departure_id": "BER",
          "arrival_id": "BCN",
          "outbound_date": "2026-05-20",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/FR.png",
        "co2_kg": 128,
        "co2_typical_kg": 170,
        "co2_difference_percent": -25
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "83",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Berlin (BER)",
            "destination": "Barcelona (BCN)",
            "departure": "2026-05-20 13:50",
            "arrival": "2026-05-20 16:35",
            "duration": "2h 45m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Vueling",
                "carrier_code": "VY",
                "number": "VY 1883",
                "departure_station": "BER",
                "departure_time": "2026-05-20 13:50",
                "departure_latitude": 52.362877,
                "departure_longitude": 13.503722,
                "arrival_station": "BCN",
                "arrival_time": "2026-05-20 16:35",
                "arrival_latitude": 41.29707,
                "arrival_longitude": 2.078463,
                "duration": "2h 45m",
                "departure_country_code": "DE",
                "arrival_country_code": "ES",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A321",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/VY.png",
                "legroom": "29 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (29 in)",
                  "Wi-Fi for a fee",
                  "In-seat USB outlet",
                  "Stream media to your device",
                  "Carbon emissions estimate: 137 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Berlin (BER)",
        "destination": "Barcelona (BCN)",
        "departure": "2026-05-20 13:50",
        "arrival": "2026-05-20 16:35",
        "duration": "2h 45m",
        "stops": 0,
        "carriers": [
          "Vueling"
        ],
        "carrier_codes": [
          "VY"
        ],
        "booking_token": "WyJDalJJVm5GQ1JXeHNOVUpVYVRCQlExYzJYMmRDUnkwdExTMHRMUzB0TFhaM2MyNHhOMEZCUVVGQlIyNWhNVVJGU0RkU05HRkJFZ1pXV1RFNE9ETWFDZ2lqUUJBQ0dnTkZWVkk0SEhDdlN3PT0iLFtbIkJFUiIsIjIwMjYtMDUtMjAiLCJCQ04iLG51bGwsIlZZIiwiMTg4MyJdXV0=",
        "booking_context": {
          "departure_id": "BER",
          "arrival_id": "BCN",
          "outbound_date": "2026-05-20",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/VY.png",
        "co2_kg": 138,
        "co2_typical_kg": 170,
        "co2_difference_percent": -19
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "85",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Berlin (BER)",
            "destination": "Barcelona (BCN)",
            "departure": "2026-05-20 15:00",
            "arrival": "2026-05-20 17:40",
            "duration": "2h 40m",
            "stops": 0,
            "segments": [
              {
                "carrier": "easyJet",
                "carrier_code": "U2",
                "number": "U2 7172",
                "departure_station": "BER",
                "departure_time": "2026-05-20 15:00",
                "departure_latitude": 52.362877,
                "departure_longitude": 13.503722,
                "arrival_station": "BCN",
                "arrival_time": "2026-05-20 17:40",
                "arrival_latitude": 41.29707,
                "arrival_longitude": 2.078463,
                "duration": "2h 40m",
                "departure_country_code": "DE",
                "arrival_country_code": "ES",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A319",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/U2.png",
                "travel_class": "Economy",
                "extensions": [
                  "Carbon emissions estimate: 139 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Berlin (BER)",
        "destination": "Barcelona (BCN)",
        "departure": "2026-05-20 15:00",
        "arrival": "2026-05-20 17:40",
        "duration": "2h 40m",
        "stops": 0,
        "carriers": [
          "easyJet"
        ],
        "carrier_codes": [
          "U2"
        ],
        "booking_token": "WyJDalJJVm5GQ1JXeHNOVUpVYVRCQlExYzJYMmRDUnkwdExTMHRMUzB0TFhaM2MyNHhOMEZCUVVGQlIyNWhNVVJGU0RkU05HRkJFZ1pWTWpjeE56SWFDZ2lFUWhBQ0dnTkZWVkk0SEhDM1RRPT0iLFtbIkJFUiIsIjIwMjYtMDUtMjAiLCJCQ04iLG51bGwsIlUyIiwiNzE3MiJdXV0=",
        "booking_context": {
          "departure_id": "BER",
          "arrival_id": "BCN",
          "outbound_date": "2026-05-20",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/U2.png",
        "co2_kg": 140,
        "co2_typical_kg": 170,
        "co2_difference_percent": -18
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "90",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Berlin (BER)",
            "destination": "Barcelona (BCN)",
            "departure": "2026-05-20 20:15",
            "arrival": "2026-05-21 09:10",
            "duration": "12h 55m",
            "stops": 1,
            "segments": [
              {
                "carrier": "Air Serbia",
                "carrier_code": "JU",
                "number": "JU 357",
                "departure_station": "BER",
                "departure_time": "2026-05-20 20:15",
                "departure_latitude": 52.362877,
                "departure_longitude": 13.503722,
                "arrival_station": "BEG",
                "arrival_time": "2026-05-20 22:05",
                "arrival_latitude": 44.818439,
                "arrival_longitude": 20.30913,
                "duration": "1h 50m",
                "departure_country_code": "DE",
                "arrival_country_code": "RS",
                "departure_is_daytime": true,
                "arrival_is_daytime": false,
                "airplane": "Airbus A319",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/JU.png",
                "legroom": "30 in",
                "travel_class": "Economy",
                "extensions": [
                  "Average legroom (30 in)",
                  "Carbon emissions estimate: 108 kg"
                ]
              },
              {
                "carrier": "Air Serbia",
                "carrier_code": "JU",
                "number": "JU 580",
                "departure_station": "BEG",
                "departure_time": "2026-05-21 06:30",
                "departure_latitude": 44.818439,
                "departure_longitude": 20.30913,
                "arrival_station": "BCN",
                "arrival_time": "2026-05-21 09:10",
                "arrival_latitude": 41.29707,
                "arrival_longitude": 2.078463,
                "duration": "2h 40m",
                "departure_country_code": "RS",
                "arrival_country_code": "ES",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A320",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/JU.png",
                "legroom": "29 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (29 in)",
                  "Carbon emissions estimate: 132 kg"
                ]
              }
            ],
            "layovers": [
              {
                "airport": "Belgrade Nikola Tesla Airport",
                "airport_code": "BEG",
                "duration": "8h 25m",
                "duration_minutes": 505,
                "overnight": true
              }
            ]
          }
        ],
        "origin": "Berlin (BER)",
        "destination": "Barcelona (BCN)",
        "departure": "2026-05-20 20:15",
        "arrival": "2026-05-21 09:10",
        "duration": "12h 55m",
        "stops": 1,
        "carriers": [
          "Air Serbia"
        ],
        "carrier_codes": [
          "JU"
        ],
        "booking_token": "WyJDalJJVm5GQ1JXeHNOVUpVYVRCQlExYzJYMmRDUnkwdExTMHRMUzB0TFhaM2MyNHhOMEZCUVVGQlIyNWhNVVJGU0RkU05HRkJFZ3RLVlRNMU4zeEtWVFU0TUJvS0NQZEZFQUlhQTBWVlVqZ2NjSUJTIixbWyJCRVIiLCIyMDI2LTA1LTIwIiwiQkVHIixudWxsLCJKVSIsIjM1NyJdLFsiQkVHIiwiMjAyNi0wNS0yMSIsIkJDTiIsbnVsbCwiSlUiLCI1ODAiXV1d",
        "booking_context": {
          "departure_id": "BER",
          "arrival_id": "BCN",
          "outbound_date": "2026-05-20",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/JU.png",
        "co2_kg": 241,
        "co2_typical_kg": 170,
        "co2_difference_percent": 42
      }
    ]
  },
  {
    "id": "store-example-travel-search-connections-3",
    "query": "Flights from Frankfurt to Paris",
    "query_translation_key": "settings.app_store_examples.travel.search_connections.3",
    "provider": "Google",
    "status": "finished",
    "results": [
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "87",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Frankfurt (FRA)",
            "destination": "Paris (CDG)",
            "departure": "2026-07-10 19:30",
            "arrival": "2026-07-10 20:50",
            "duration": "1h 20m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Condor",
                "carrier_code": "DE",
                "number": "DE 4293",
                "departure_station": "FRA",
                "departure_time": "2026-07-10 19:30",
                "departure_latitude": 50.037796,
                "departure_longitude": 8.555783,
                "arrival_station": "CDG",
                "arrival_time": "2026-07-10 20:50",
                "arrival_latitude": 49.012516,
                "arrival_longitude": 2.555752,
                "duration": "1h 20m",
                "departure_country_code": "DE",
                "arrival_country_code": "FR",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A320",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/DE.png",
                "legroom": "28 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (28 in)",
                  "Stream media to your device",
                  "Carbon emissions estimate: 60 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Frankfurt (FRA)",
        "destination": "Paris (CDG)",
        "departure": "2026-07-10 19:30",
        "arrival": "2026-07-10 20:50",
        "duration": "1h 20m",
        "stops": 0,
        "carriers": [
          "Condor"
        ],
        "carrier_codes": [
          "DE"
        ],
        "booking_token": "WyJDalJJUlVGU1dISkNhVWhJVmpoQlNrdDNWMEZDUnkwdExTMHRMUzB0TFMxdmEya3hNRUZCUVVGQlIyNWhNVVJKUlRSNWVrbEJFZ1pFUlRReU9UTWFDZ2o3UXhBQ0dnTkZWVkk0SEhEWlR3PT0iLFtbIkZSQSIsIjIwMjYtMDctMTAiLCJDREciLG51bGwsIkRFIiwiNDI5MyJdXV0=",
        "booking_context": {
          "departure_id": "FRA",
          "arrival_id": "CDG",
          "outbound_date": "2026-07-10",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/DE.png",
        "co2_kg": 60,
        "co2_typical_kg": 66,
        "co2_difference_percent": -9
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "90",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Frankfurt (FRA)",
            "destination": "Paris (CDG)",
            "departure": "2026-07-10 15:10",
            "arrival": "2026-07-10 16:35",
            "duration": "1h 25m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Air France",
                "carrier_code": "AF",
                "number": "AF 1219",
                "departure_station": "FRA",
                "departure_time": "2026-07-10 15:10",
                "departure_latitude": 50.037796,
                "departure_longitude": 8.555783,
                "arrival_station": "CDG",
                "arrival_time": "2026-07-10 16:35",
                "arrival_latitude": 49.012516,
                "arrival_longitude": 2.555752,
                "duration": "1h 25m",
                "departure_country_code": "DE",
                "arrival_country_code": "FR",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Embraer 190",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/AF.png",
                "legroom": "29 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (29 in)",
                  "Free Wi-Fi",
                  "In-seat USB outlet",
                  "Carbon emissions estimate: 72 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Frankfurt (FRA)",
        "destination": "Paris (CDG)",
        "departure": "2026-07-10 15:10",
        "arrival": "2026-07-10 16:35",
        "duration": "1h 25m",
        "stops": 0,
        "carriers": [
          "Air France"
        ],
        "carrier_codes": [
          "AF"
        ],
        "booking_token": "WyJDalJJUlVGU1dISkNhVWhJVmpoQlNrdDNWMEZDUnkwdExTMHRMUzB0TFMxdmEya3hNRUZCUVVGQlIyNWhNVVJKUlRSNWVrbEJFZ1pCUmpFeU1Ua2FDZ2pqUlJBQ0dnTkZWVkk0SEhEcFVRPT0iLFtbIkZSQSIsIjIwMjYtMDctMTAiLCJDREciLG51bGwsIkFGIiwiMTIxOSJdXV0=",
        "booking_context": {
          "departure_id": "FRA",
          "arrival_id": "CDG",
          "outbound_date": "2026-07-10",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/AF.png",
        "co2_kg": 72,
        "co2_typical_kg": 66,
        "co2_difference_percent": 9
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "95",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Frankfurt (FRA)",
            "destination": "Paris (CDG)",
            "departure": "2026-07-10 08:30",
            "arrival": "2026-07-10 09:50",
            "duration": "1h 20m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Condor",
                "carrier_code": "DE",
                "number": "DE 4265",
                "departure_station": "FRA",
                "departure_time": "2026-07-10 08:30",
                "departure_latitude": 50.037796,
                "departure_longitude": 8.555783,
                "arrival_station": "CDG",
                "arrival_time": "2026-07-10 09:50",
                "arrival_latitude": 49.012516,
                "arrival_longitude": 2.555752,
                "duration": "1h 20m",
                "departure_country_code": "DE",
                "arrival_country_code": "FR",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A320",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/DE.png",
                "legroom": "28 in",
                "travel_class": "Economy",
                "extensions": [
                  "Below average legroom (28 in)",
                  "Stream media to your device",
                  "Carbon emissions estimate: 60 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Frankfurt (FRA)",
        "destination": "Paris (CDG)",
        "departure": "2026-07-10 08:30",
        "arrival": "2026-07-10 09:50",
        "duration": "1h 20m",
        "stops": 0,
        "carriers": [
          "Condor"
        ],
        "carrier_codes": [
          "DE"
        ],
        "booking_token": "WyJDalJJUlVGU1dISkNhVWhJVmpoQlNrdDNWMEZDUnkwdExTMHRMUzB0TFMxdmEya3hNRUZCUVVGQlIyNWhNVVJKUlRSNWVrbEJFZ1pFUlRReU5qVWFDZ2liU2hBQ0dnTkZWVkk0SEhDRFZ3PT0iLFtbIkZSQSIsIjIwMjYtMDctMTAiLCJDREciLG51bGwsIkRFIiwiNDI2NSJdXV0=",
        "booking_context": {
          "departure_id": "FRA",
          "arrival_id": "CDG",
          "outbound_date": "2026-07-10",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/DE.png",
        "co2_kg": 60,
        "co2_typical_kg": 66,
        "co2_difference_percent": -9
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "96",
        "currency": "EUR",
        "legs": [
          {
            "leg_index": 0,
            "origin": "Frankfurt (FRA)",
            "destination": "Paris (CDG)",
            "departure": "2026-07-10 07:30",
            "arrival": "2026-07-10 08:45",
            "duration": "1h 15m",
            "stops": 0,
            "segments": [
              {
                "carrier": "Lufthansa",
                "carrier_code": "LH",
                "number": "LH 1026",
                "departure_station": "FRA",
                "departure_time": "2026-07-10 07:30",
                "departure_latitude": 50.037796,
                "departure_longitude": 8.555783,
                "arrival_station": "CDG",
                "arrival_time": "2026-07-10 08:45",
                "arrival_latitude": 49.012516,
                "arrival_longitude": 2.555752,
                "duration": "1h 15m",
                "departure_country_code": "DE",
                "arrival_country_code": "FR",
                "departure_is_daytime": true,
                "arrival_is_daytime": true,
                "airplane": "Airbus A320",
                "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
                "legroom": "30 in",
                "travel_class": "Economy",
                "extensions": [
                  "Average legroom (30 in)",
                  "Carbon emissions estimate: 58 kg"
                ]
              }
            ]
          }
        ],
        "origin": "Frankfurt (FRA)",
        "destination": "Paris (CDG)",
        "departure": "2026-07-10 07:30",
        "arrival": "2026-07-10 08:45",
        "duration": "1h 15m",
        "stops": 0,
        "carriers": [
          "Lufthansa"
        ],
        "carrier_codes": [
          "LH"
        ],
        "booking_token": "WyJDalJJUlVGU1dISkNhVWhJVmpoQlNrdDNWMEZDUnkwdExTMHRMUzB0TFMxdmEya3hNRUZCUVVGQlIyNWhNVVJKUlRSNWVrbEJFZ1pNU0RFd01qWWFDZ2k3U2hBQ0dnTkZWVkk0SEhDcFZ3PT0iLFtbIkZSQSIsIjIwMjYtMDctMTAiLCJDREciLG51bGwsIkxIIiwiMTAyNiJdXV0=",
        "booking_context": {
          "departure_id": "FRA",
          "arrival_id": "CDG",
          "outbound_date": "2026-07-10",
          "type": "2",
          "currency": "EUR",
          "gl": "de",
          "adults": "1",
          "travel_class": "1"
        },
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 59,
        "co2_typical_kg": 66,
        "co2_difference_percent": -11
      }
    ]
  }
]

export default examples;
