# FlixBus / FlixTrain Travel Search API Research

## Status

Flix has an official developer portal at `https://developer.api.flixbus.com/`, but the portal is SSO-gated and does not expose public self-serve documentation. Production usage should prefer approved Flix partner/API access when available.

For the travel connection provider, we currently use the public web/mobile JSON endpoints that power Flix search surfaces. This integration is reverse-engineered and should be monitored because endpoint shape, headers, or access controls may change without notice.

## Endpoints

### Autocomplete

`GET https://global.api.flixbus.com/search/autocomplete/cities`

Useful parameters:

| Parameter | Example | Notes |
| --- | --- | --- |
| `q` | `Berlin` | User search text. |
| `lang` | `en` | Two-letter UI language. |
| `country` | `DE` | Country context for ranking. |
| `flixbus_cities_only` | `true` | Limits to Flix-supported cities. |
| `is_train_only` | `false` | Use `true` when resolving train-only requests. |
| `stations` | `true` | Include stations under each city. |
| `popular_stations` | `true` | Include top stations. |

The response contains both UUID `id` values and numeric `legacy_id` values. The mobile trip endpoint requires numeric `legacy_id` values.

### Trip Search

`GET https://global.api.flixbus.com/mobile/v1/trip/search.json`

Required headers:

| Header | Value |
| --- | --- |
| `X-API-Authentication` | Public mobile client token observed in Flix traffic. |
| `User-Agent` | Flix mobile app style user agent. |
| `X-User-Country` | Lowercase country code such as `de` or `us`. |
| `Accept-Language` | Locale such as `en-DE`. |

Useful parameters:

| Parameter | Example | Notes |
| --- | --- | --- |
| `from` | `88` | Numeric origin legacy ID. |
| `to` | `118` | Numeric destination legacy ID. |
| `departure_date` | `20.05.2026` | Format is `DD.MM.YYYY`. |
| `search_by` | `cities` | Also supports `stations`. |
| `currency` | `EUR` | ISO 4217 currency. |
| `adult` | `1` | Adult passengers. |
| `children` | `0` | Child passengers. |
| `bikes` | `0` | Bike slots. |

## Tested Routes

Live probes on 2026-05-11 returned connection results for:

| Route | Result Summary |
| --- | --- |
| Berlin -> Hamburg | 46 journeys, including direct bus and FlixTrain. |
| Hamburg -> Hannover | 7 direct bus journeys. |
| Berlin -> Stuttgart | 21 journeys, including FlixTrain and mixed train/bus transfers. |
| Berlin -> Szczecin | 41 mostly direct bus journeys. |
| Berlin ZOB -> Hamburg ZOB | 46 station-level journeys. |
| New York -> Boston | 48 Greyhound/Flix network bus journeys. |

## Booking Links

Trip groups include `links` entries. The `shop:search` link opens Flix booking with origin, destination, station, date, currency, and passenger counts prefilled. The travel provider maps this link to `ConnectionResult.booking_url`.

## Implementation Notes

- Use autocomplete first and pass the numeric `legacy_id` to trip search.
- Use `is_train_only=true` for train-only searches because station IDs can differ from bus-oriented station IDs.
- Treat HTTP 200 payloads with an `errors` object as provider failures.
- `transfer_type_key` values containing `train` represent FlixTrain or mixed train results.
- `interconnection_transfers` contains transfer station arrival/departure times for layovers.

## Risks

- This is not an official public API contract.
- The mobile auth header may be rotated or blocked.
- Rate limits are undocumented.
- Privacy/legal review is needed before long-term production enablement because user route/date queries are sent to Flix.
