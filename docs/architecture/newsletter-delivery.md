# Newsletter image publication and delivery

Newsletter headers, event cards, hero images, campaign icons, and video thumbnails
use compressed images on the first-party public website. The shared generic
footer logo may remain embedded. Final newsletter HTML must be at most 80 KiB
in UTF-8 before provider tracking is added; oversized messages stop before send.

## Author and publish images

Keep reviewed image references repo-relative in campaign metadata. Run:

```sh
python scripts/publish_newsletter_assets.py --manifest /path/to/reviewed-campaign.yml
```

The command also covers committed issue manifests and the public event registry.
Temporary campaign manifests may be YAML or JSON. Source images must exist at
their referenced repository paths while publishing. The command creates:

- Content-addressed, deduplicated JPEGs under `frontend/apps/website/static/newsletter-assets/`.
- `backend/newsletters/asset-map.json`, bundled with API and worker images.

Review both outputs and deploy the website assets and backend index before any
preview delivery. Runtime rendering reads the bundled index and works after
temporary source files disappear; it never fetches image URLs. Development
messages use `landing.dev.openmates.org`; production messages use `openmates.org`.
Confirm the exact image URLs load on the deployed target before broadcasting.

A historical Luma image reference requires an explicit, reviewed local source:

```sh
python scripts/publish_newsletter_assets.py --remote-source 'https://images.lumacdn.com/path/image.png=/path/to/reviewed-image.png'
```

The publisher accepts that authored source host only and never downloads it.
Configured references without a published index entry block rendering. Preserve
localized alt text, visible event details, and destination links in the campaign.

## Preview admission

`--test-to` and newsletter admin previews are test traffic, including ordinary
personal addresses. Every live preview recipient must be an exact entry in
`OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST`; plus aliases require their own entries.
Captured isolated CI mail uses Mailpit and never falls back to Brevo. Real
subscribers retain user delivery metadata and require their persistent one-click
unsubscribe token, including subscribers with registered accounts.

## Existing stored campaigns

Directus `body_markdown` is materialized unchanged for delivery. New image
publication does not rewrite an existing body containing base64 image data.
Oversized stored content will therefore remain blocked by the HTML size guard.

Inspect only the authorized campaign payload and its status. For a pending
campaign with embedded images, decode its reviewed public image bytes in the
authoring workspace, publish compressed assets, and replace the embedded image
references with their first-party HTTPS URLs while preserving copy, localized
alt text, links, event dates, and campaign identity. Review the resulting diff
and rendered EN/DE messages. A material campaign edit must invalidate its old
review/schedule and receive fresh previews and approval through the existing
campaign service before delivery. Never regenerate old campaign content from
today's registry or silently change an approved pending campaign at send time.
