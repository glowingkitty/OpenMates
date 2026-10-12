# Business

## Search trademarks

Search candidate brand or product names in your intended markets. Supply up to
three names and select regions. Optional Nice classes narrow the goods and
services searched; leave them empty for a broader first check. Choose exact
names or spelling-similar matches, and active records or all records.

The initial automated source is the free US federal USPTO register. It includes
applications and registrations. EU, German and worldwide selections currently
show a coverage gap with official manual-search links. A mixed selection keeps
the completed US evidence and identifies the regions that were not searched.

Each completed search reports its time, filters, total match count and whether
more records exist. Results include the mark, owner, status, classes, goods and
services, dates and official record links where available. Zero matches,
incomplete searches and unavailable sources remain distinct. Searches are
preliminary: zero matches do not establish legal availability, and spelling
similarity does not cover every legal, phonetic or visual conflict.

### CLI

Use your authenticated OpenMates CLI:

```sh
openmates apps business search_trademarks --input '{"queries":["ADIDAS"],"regions":["US"],"match":"exact","max_results":3}' --json
```

### SDKs

The npm SDK exposes `client.apps.business.searchTrademarks(input)`. The Python
SDK exposes `client.apps.business.search_trademarks(input)`. Both use the same
input and preserve `matches`, `coverage`, `result_count`, `nice_classes`,
`status_filter`, `match`, `partial` and `limitation`.

OpenMates authentication is required; no USPTO account or provider key is needed.
The external source is free. OpenMates applies its normal skill-credit pricing.

## Find a brand name

Start with “Help me find a name for my new product.” The mode asks for a compact
brief, offers a varied shortlist, then checks two or three chosen finalists with
domain, web and trademark searches. It compares the checked evidence and any
coverage gaps, while keeping creative suggestions clearly distinguishable from
availability checks. You can skip questions or ask it to select finalists.
