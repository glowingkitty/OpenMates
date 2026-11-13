# OpenRegister (German commercial register)

`business.company_ownership` reads German company data through the [OpenRegister API](https://docs.openregister.de), a documented REST API over the official Handelsregister and the documents filed there. Requests use a Bearer API key from Vault `kv/data/providers/openregister` (key `api_key`) or `SECRET__OPENREGISTER__API_KEY`. Without a key, German lookups return `provider_not_configured`; the other registers keep working.

Calls per lookup are kept minimal because the free plan has a small monthly credit allowance: `GET /v1/autocomplete/company` (1 credit) resolves the company, then only the requested facts are fetched: `GET /v1/company/{id}/owners?best_available=true` (10 credits; stock corporations need `best_available`), `GET /v1/company/{id}/holdings` (10) and `GET /v1/company/{id}` for current representatives (10). Person lookups use `POST /v1/search/person` (10), then `GET /v1/person/{id}/holdings` and `GET /v1/person/{id}` for management positions (10 each). Successful records are cached for 7 days; at most five lookups run per call.

The wrapper keeps names, relation type, share percentage, nominal amount, start and end dates and register ids. Birth dates, ages and private addresses are dropped before the record leaves `backend/shared/providers/company_registers/`; `ownership_record` refuses any record that still contains such a field. HTTP 401/403 map to `provider_not_configured`, 402 (credits used up) and 429 to `rate_limited`, 404 on owners to a "no shareholder list" warning.

Source: [OpenRegister API reference](https://docs.openregister.de).
