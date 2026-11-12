# Companies House (UK company register)

`business.company_ownership` reads UK company data through the official [Companies House Public Data API](https://developer.company-information.service.gov.uk). The free API key is sent as the HTTP basic-auth user name and comes from Vault `kv/data/providers/companies_house` (key `api_key`) or `SECRET__COMPANIES__HOUSE__API_KEY`. The published limit is 600 requests per 5 minutes; the wrapper retries 429 and 5xx responses briefly.

Company lookups use `GET /company/{number}` for an 8-character company number or `GET /search/companies`, then `GET /company/{number}/persons-with-significant-control` for owners and `GET /company/{number}/officers` for officers. Person lookups use `GET /search/officers` and the officer's `GET /officers/{id}/appointments`. The register reports significant control in bands (25-50, 50-75, 75-100 %), shown as `share_band`; it does not publish exact shareholdings or which companies a company holds, which the result states as warnings.

Ceased controllers and resigned officers are left out. Dates of birth, addresses, nationality, country of residence and occupation are dropped. Each record links to the public company or officer page on find-and-update.company-information.service.gov.uk.

Source: [Companies House API reference](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference).
