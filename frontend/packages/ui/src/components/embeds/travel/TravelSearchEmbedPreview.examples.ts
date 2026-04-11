/**
 * App-store examples for the travel skill.
 *
 * Captured from real Google Flights (SerpAPI) responses, trimmed to 5 connections per query.
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
        "price": "97",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/BA.png",
        "co2_kg": 80
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "131",
        "price": "131",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 84
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "131",
        "price": "131",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 84
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "131",
        "price": "131",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 84
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "131",
        "price": "131",
        "currency": "EUR",
        "origin": "Munich (MUC)",
        "destination": "London (LHR)",
        "departure": "2026-06-15 21:35",
        "arrival": "2026-06-15 22:40",
        "duration": "2h 5m",
        "stops": 0,
        "carriers": [
          "Lufthansa"
        ],
        "carrier_codes": [
          "LH"
        ],
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 84
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
        "price": "81",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/FR.png",
        "co2_kg": 128
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "83",
        "price": "83",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/VY.png",
        "co2_kg": 138
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "85",
        "price": "85",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/U2.png",
        "co2_kg": 140
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "90",
        "price": "90",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/JU.png",
        "co2_kg": 241
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "97",
        "price": "97",
        "currency": "EUR",
        "origin": "Berlin (BER)",
        "destination": "Barcelona (BCN)",
        "departure": "2026-05-20 10:35",
        "arrival": "2026-05-20 13:20",
        "duration": "2h 45m",
        "stops": 0,
        "carriers": [
          "Vueling"
        ],
        "carrier_codes": [
          "VY"
        ],
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/VY.png",
        "co2_kg": 126
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
        "price": "87",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/DE.png",
        "co2_kg": 60
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "90",
        "price": "90",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/AF.png",
        "co2_kg": 72
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "95",
        "price": "95",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/DE.png",
        "co2_kg": 60
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "96",
        "price": "96",
        "currency": "EUR",
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
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/LH.png",
        "co2_kg": 59
      },
      {
        "type": "connection",
        "transport_method": "airplane",
        "trip_type": "one_way",
        "total_price": "96",
        "price": "96",
        "currency": "EUR",
        "origin": "Frankfurt (FRA)",
        "destination": "Paris (CDG)",
        "departure": "2026-07-10 09:45",
        "arrival": "2026-07-10 11:15",
        "duration": "1h 30m",
        "stops": 0,
        "carriers": [
          "Air France"
        ],
        "carrier_codes": [
          "AF"
        ],
        "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/AF.png",
        "co2_kg": 72
      }
    ]
  }
]

export default examples;
