/**
 * App-store examples for the travel get_flight skill.
 *
 * Three example flight tracking results with invented flight numbers
 * and synthetic data. The shape matches the real FlightAware/ADS-B
 * provider response so the preview + fullscreen render identically.
 * A "Sample data" banner is shown at the top of the fullscreen via
 * the is_store_example flag set by SkillExamplesSection.
 */

export interface TravelFlightDetailsStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  flightNumber?: string;
  departureDate?: string;
  originIata?: string;
  destinationIata?: string;
  actualTakeoff?: string;
  actualLanding?: string;
  trackPointCount?: number;
  diverted?: boolean;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: TravelFlightDetailsStoreExample[] = [
  {
    "id": "store-example-travel-get-flight-1",
    "query": "LH2472",
    "query_translation_key": "settings.app_store_examples.travel.get_flight.1",
    "flightNumber": "LH2472",
    "departureDate": "2026-04-13",
    "originIata": "MUC",
    "destinationIata": "LHR",
    "actualTakeoff": "2026-04-13T08:15:00Z",
    "actualLanding": "2026-04-13T09:45:00Z",
    "trackPointCount": 142,
    "diverted": false,
    "status": "finished",
    "results": []
  },
  {
    "id": "store-example-travel-get-flight-2",
    "query": "BA918",
    "query_translation_key": "settings.app_store_examples.travel.get_flight.2",
    "flightNumber": "BA918",
    "departureDate": "2026-04-13",
    "originIata": "LHR",
    "destinationIata": "FCO",
    "actualTakeoff": "2026-04-13T11:30:00Z",
    "actualLanding": "2026-04-13T15:10:00Z",
    "trackPointCount": 198,
    "diverted": false,
    "status": "finished",
    "results": []
  },
  {
    "id": "store-example-travel-get-flight-3",
    "query": "EW8614",
    "query_translation_key": "settings.app_store_examples.travel.get_flight.3",
    "flightNumber": "EW8614",
    "departureDate": "2026-04-13",
    "originIata": "BER",
    "destinationIata": "BCN",
    "actualTakeoff": "2026-04-13T14:05:00Z",
    "actualLanding": "2026-04-13T16:50:00Z",
    "trackPointCount": 165,
    "diverted": false,
    "status": "finished",
    "results": []
  }
];

export default examples;
