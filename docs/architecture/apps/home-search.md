# Home search

Home searches the existing ImmoScout24 mobile endpoint, Kleinanzeigen search and
detail HTML, and WG-Gesucht search, detail API and public gallery pages. Search
results retain provider identity and source links. Bounded detail enrichment
adds descriptions, advertised amenities, rent components, availability, address
components, location provenance and complete supplied galleries.

`image_url` remains the primary photo. `image_urls` contains the ordered,
deduplicated gallery; visual-assessment limits do not shorten it. A recognized
gallery yields `gallery_status: complete`; failed or unrecognized details retain
the cover and disclose partial/unavailable coverage. This describes the retrieved
provider response, not a guarantee that a blocked or changed platform exposed
every photo.
Provider size variants share one photo slot, upgraded to the best supplied
rendition. Gallery extraction excludes advertiser avatars and recommended ads.

## Criteria and selection

The public request schema is declared in `backend/apps/home/app.yml` and validated
by `SearchRequestItem`. Generic clients pass the same fields without a separate
client-specific implementation. For example:

```json
{"requests":[{"query":"Berlin","listing_type":"rent","max_warm_rent_eur":1500,"required_amenities":["balcony"],"neighborhood_categories":["water"],"relevance_criteria":"A balcony is required; prefer a nearby public waterfront.","max_results":10}]}
```

Numeric price/size/room/availability constraints run before optional inference.
Advertised, warm and cold rent are distinct. Required/excluded amenities need
supported evidence; unknown values do not satisfy them. `include_unconfirmed`
allows explicitly labelled uncertain listings while preserving exclusions for
known conflicts. Preferred amenities only affect relevance.

Natural-language criteria are interpreted into bounded amenity decisions with a
conservative language fallback. Jev then evaluates descriptions and, when
appropriate, up to three spaced gallery photos per candidate. Photo visibility
alone is possible evidence: a building balcony does not prove that it belongs to
the apartment. Text, provider flags, source conflicts, visual findings and photo
coverage remain separate. `visual_analysis: false` skips image downloading and
image inference while preserving text and advertised evidence.

Requested geographic evidence is gathered before final ranking. The requested
result limit still controls emitted results and embeds; provider-page coverage
and enrichment shortfalls are disclosed.
Hard amenity conflicts are removed before geocoding. Supported matches receive
priority, and coordinates are resolved before optional neighborhood lookups
consume the shared request and time budget.

## Location and neighborhood evidence

Provider coordinates retain declared approximation. Missing coordinates use the
existing Geoapify connection for address lookup, with match type, confidence,
precision, source and retrieval timestamp. The final city fallback is clearly
approximate. Intentional provider approximation is never upgraded to a precise
apartment location.
Root and nested location metadata use the same fallback provenance so persisted
embeds cannot turn a city-center marker into a street-level match.

Water, parks, transit, groceries and schools are requested on demand through the
existing cached and quota-guarded Geoapify wrapper. A bounded empty result is not
proof of absence. Water polygons can support shoreline distance; a representative
place point remains a weaker measurement. Street/district/city locations do not
support precise apartment distances. Walking time is only exposed for an actual
provider route to explicitly supported public pedestrian waterfront geometry;
otherwise access remains unknown. Hard distance/time constraints never use a
straight-line walking estimate. No spatial index or bulk map dataset is created.

The web overview uses the same visible predicate for listing cards and map
markers. Home-specific filters cover price basis, rooms, area and supported
amenities. Approximate markers are visually distinct, and nearby evidence places
are not accidentally rendered as apartment pins. Listings without coordinates
remain accessible.

## Image and cache lifecycle

Shopping and Home share `backend/shared/python_utils/public_images.py`. Analysis
downloads stream into bounded memory, reject private networks/credentials/unsafe
redirects, pin validated DNS and prepare metadata-free JPEGs in memory. No
temporary image file, raw-photo disk cache or new upload is created. Cancellation
joins child work and drops prepared-image references.

Housing detail responses have a finite five-minute process-local source cache;
it stores HTML/JSON and URLs rather than downloaded photos. Geoapify uses the
existing TTL response caches and shared quota guard. The separate public UI
display proxy retains its existing seven-day disk-cache policy and removes
expired entries during access/writes/statistics checks. Existing owner-encrypted
original uploads retain their original lifecycle; this analysis path does not
delete them or promise zero retention by external inference providers.
