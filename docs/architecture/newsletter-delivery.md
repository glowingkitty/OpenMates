# Newsletter image publication and delivery

Newsletter headers, event cards, hero images, campaign icons, and video thumbnails
use compressed, immutable images in dedicated Hetzner S3 buckets. Historical
website copies remain available for messages sent before the migration. The shared generic
footer logo may remain embedded. Final newsletter HTML must be at most 80 KiB
in UTF-8 before provider tracking is added; oversized messages stop before send.

## Author images

Keep reviewed image references repo-relative in campaign metadata. Run:

```sh
python scripts/publish_newsletter_assets.py --manifest /path/to/reviewed-campaign.yml
```

The command also covers committed issue manifests and the public event registry.
Temporary campaign manifests may be YAML or JSON. Source images must exist at
their referenced repository paths while publishing. The command creates:

- Content-addressed, deduplicated JPEGs under `frontend/apps/website/static/newsletter-assets/`.
- `backend/newsletters/asset-map.json`, bundled with API and worker images.

Review both outputs before publication. Runtime rendering reads the bundled index
and works after temporary source files disappear; it never fetches image URLs or
requires storage credentials. Reauthoring a logical source retains its previous
immutable image under an archive entry so old email URLs remain valid. Changed
asset sets invalidate existing S3 readiness until each target is published again.

A historical Luma image reference requires an explicit, reviewed local source:

```sh
python scripts/publish_newsletter_assets.py --remote-source 'https://images.lumacdn.com/path/image.png=/path/to/reviewed-image.png'
```

The publisher accepts that authored source host only and never downloads it.
Configured references without a published index entry block rendering. Preserve
localized alt text, visible event details, and destination links in the campaign.

## Publish the dedicated S3 targets

The only accepted destinations are `dev-openmates-newsletter-assets` and
`openmates-newsletter-assets`, both in `nbg1`. Object keys are
`newsletter-images/<sha256>.jpg` or `.svg`. Public URLs use
`https://<bucket>.nbg1.your-objectstorage.com/newsletter-images/<filename>`.
The publisher validates the complete index and every local image's hash, size,
type and dimensions before provider operations. Symlinks, traversal, active SVG
content and unexpected destinations are rejected.

Stage only the reviewed index and its referenced compressed files under a private
root, preserving these paths:

```text
<stage>/backend/newsletters/asset-map.json
<stage>/frontend/apps/website/static/newsletter-assets/<immutable-filename>
```

Use the scoped publisher in an authorized operator environment with access to
the existing Vault Hetzner provider credentials. A dry-run performs selected
bucket reads only; a fresh receipt path is required for every run:

```sh
python backend/scripts/publish_newsletter_s3_assets.py \
  --environment development --repo-root /private/newsletter-stage \
  --receipt /private/newsletter-dev-plan.json
python backend/scripts/publish_newsletter_s3_assets.py \
  --environment development --repo-root /private/newsletter-stage \
  --receipt /private/newsletter-dev-apply.json --apply
```

Repeat for `--environment production` with separate receipts and the same stage
only when that publication is authorized. Publishing image bytes does not deploy
the production app. The CLI suppresses provider/Vault logs; receipts are mode
`0600` and contain bucket, manifest fingerprint, counts, phase and verification
results, without credentials, private object bytes or subscriber data.

A bucket is created only after a missing-bucket response and successful private
creation. The publisher never adopts an existing empty/private bucket. An
existing bucket must have exactly the known policy, owner-only ACLs and only
declared immutable images plus the fixed private access-boundary sentinel.
Unexpected policy, grants or content fail closed without mutation. All SDK calls
name the one selected bucket; there is no general S3 service reconciliation,
bucket enumeration, deletion or unconditional overwrite. Missing objects use
conditional `If-None-Match: *` writes; an existing object must verify identical
metadata and bytes.

The public policy has one anonymous `s3:GetObject` grant on the selected bucket's
`newsletter-images/*` only. It grants no listing, writes or access to any other
prefix/bucket. Before readiness is returned, anonymous reads verify every image's
bytes and type; listing, the existing private sentinel and a new anonymous image
write must each return `403`. The harmless private sentinel stays in the dedicated
bucket for repeatable verification. The publisher never probes unrelated data.

Hetzner key pairs are project-wide by default; this is application-enforced
publication scope, not credential isolation. Credentials remain publisher-only.
See [Hetzner's S3 API guidance](https://docs.hetzner.com/storage/object-storage/getting-started/using-s3-api-tools/)
and [bucket policy guidance](https://docs.hetzner.com/storage/object-storage/faq/buckets-objects/).

Only after all checks does the publisher atomically update the staged index with
the target's canonical asset-set hash, exact filenames/count and public-readiness
record, and select S3 delivery. Copy the verified staged index into the source
workspace for review/deployment. Keep runtime-bundled maps untouched during
publication. Development and production rendering each require their own current
record; a missing or stale target blocks rendering instead of sending broken URLs.
Keep existing website assets deployed for historical email URLs.

## Isolated delivery verification

The newsletter flow requires both disposable Mailpit and object-storage
capabilities. The runner transports the exact candidate index and only its
hash-verified image bytes over stdin; the API checks the index against its own
candidate source before staging a private fixture. It runs the same scoped
publisher against `http://storage.ci.test:9000`, including actual anonymous image
GET and listing/private-prefix/write denial checks. Unsupported bucket policy or
conditional-write behavior fails the proof; there is no public-access fallback.

Any enabled CI/isolation/capture indicator blocks live endpoints unless the full
exact isolated profile and storage endpoint match. A temporary ready-index
override is allowed only inside that profile and beneath `/app/logs`, with no
traversal or symlinks. Real EN/DE captures preserve complete localized titles,
summaries, hosted URLs, text alternatives, size limits, persistent one-click
headers and deduplication. A third actual preview verifies test audience metadata
and the absence of unsubscribe headers when no real subscriber token exists.

## Preview admission

`--test-to` and newsletter admin previews are test traffic, including ordinary
personal addresses. Every live preview recipient must be an exact entry in
`OPENMATES_LIVE_TEST_EMAIL_ALLOWLIST`; plus aliases require their own entries.
The newsletter flow declares both local mail and upload-storage capabilities,
so its isolated job receives Mailpit and the real disposable S3 service.
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
