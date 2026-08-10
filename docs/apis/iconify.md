# Iconify API Notes

Last verified: 2026-07-18

Iconify is used by `design.search_icons` to search public SVG icon collections and fetch SVGs server-side.

## Provider

- Base URL: `https://api.iconify.design`
- Authentication: none for the public API endpoints used here
- Privacy policy: `https://iconify.design/privacy/`
- OpenMates provider metadata: `backend/providers/iconify.yml`

## Endpoints Used

- `GET /search?query=<query>&limit=<count>` returns icon IDs and collection metadata.
- `GET /{prefix}.json?icons=<name1,name2>` returns icon dimensions and icon metadata for selected IDs.
- `GET /{prefix}/{name}.svg?height=24` returns the raw SVG for one icon.

## OpenMates Contract

- Clients call `POST /v1/apps/design/skills/search_icons` for search.
- Clients call `GET /v1/apps/design/icons/iconify/{prefix}/{name}.svg` for SVG rendering.
- Browser, SDK, CLI, and Apple clients must not call `api.iconify.design` directly.
- SVG responses are sanitized by the OpenMates API before being returned.
- Search result embeds store metadata only. They must not store SVG markup, PNG bytes, data URLs, raw Iconify responses, provider credentials, or preview-server URLs.

## License Filtering

Default search filters visible results to permissive/no-attribution license identifiers:

- `MIT`
- `ISC`
- `Apache-2.0`
- `BSD-*`
- `CC0` / `CC0-1.0`
- `Unlicense`
- `OFL-1.1`

The `license_policy: all` option can expose all Iconify search results when an approved client flow needs explicit broader filtering.

## Verified Behaviors

- Search for `home` returned HTTP 200 with icon IDs and collection license metadata.
- SVG fetch for `lucide/home.svg?height=24` returned HTTP 200 and `image/svg+xml`.
- No-match search returned HTTP 200 with `icons: []`.
- Missing SVG returned HTTP 404.
