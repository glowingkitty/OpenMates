/**
 * App-store examples for the travel skill.
 *
 * Captured from real Travelpayouts price calendar responses.
 */

export interface TravelPriceCalendarStoreExample {
  id: string;
  query: string;
  query_translation_key?: string;
  provider?: string;
  status: 'finished';
  results: Array<Record<string, unknown>>;
}

const examples: TravelPriceCalendarStoreExample[] = [
  {
    "id": "store-example-travel-price-calendar-1",
    "query": "Munich → London, May 2026",
    "query_translation_key": "settings.app_store_examples.travel.price_calendar.1",
    "provider": "Travelpayouts",
    "status": "finished",
    "results": [
      {
        "type": "price_calendar",
        "origin": "MUC",
        "origin_name": "Munich",
        "destination": "LHR",
        "destination_name": "London",
        "month": "2026-05",
        "currency": "EUR",
        "days_with_data": 0,
        "total_days_in_month": 31,
        "entries": []
      }
    ]
  },
  {
    "id": "store-example-travel-price-calendar-2",
    "query": "Berlin → Barcelona, June 2026",
    "query_translation_key": "settings.app_store_examples.travel.price_calendar.2",
    "provider": "Travelpayouts",
    "status": "finished",
    "results": [
      {
        "type": "price_calendar",
        "origin": "BER",
        "origin_name": "Berlin",
        "destination": "BCN",
        "destination_name": "Barcelona",
        "month": "2026-06",
        "currency": "EUR",
        "days_with_data": 0,
        "total_days_in_month": 30,
        "entries": []
      }
    ]
  },
  {
    "id": "store-example-travel-price-calendar-3",
    "query": "Frankfurt → Paris, July 2026",
    "query_translation_key": "settings.app_store_examples.travel.price_calendar.3",
    "provider": "Travelpayouts",
    "status": "finished",
    "results": [
      {
        "type": "price_calendar",
        "origin": "FRA",
        "origin_name": "Frankfurt",
        "destination": "CDG",
        "destination_name": "Paris",
        "month": "2026-07",
        "currency": "EUR",
        "days_with_data": 0,
        "total_days_in_month": 31,
        "entries": []
      }
    ]
  }
]

export default examples;
