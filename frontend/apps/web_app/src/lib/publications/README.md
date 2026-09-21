# Public publication manifest

`publicationManifest.v1.json` is the reviewed public handoff from the private
`openmates-marketing` authoring workflow. It contains only fields that may be
published. The web application validates the complete manifest during module
load and refuses unknown fields, unsupported URL hosts, duplicate IDs/slugs,
non-HTTPS links, or social media used as the media host.

The private publisher should create a complete replacement file and move it
into place atomically after its review succeeds. Buffer access, channel IDs,
drafts, internal notes, raw API responses, credentials, and unpublished
campaign data must remain in the marketing repository. Successfully sent posts
are represented here by their public copy, publication time, owned media URL,
and exact per-platform permalink. Updating this manifest does not send an email
or create a social post.

English is the required source locale. German copy is optional per record;
when it is absent, the public route preserves the original English post rather
than inventing a translation. Full videos and original downloadable images use
content-addressed objects below the permanent `publications/social/` prefix in
Hetzner Object Storage. Small posters use the app's `/publications/social/`
asset path so cards can render quickly through Vercel. Individual S3 objects
must remain anonymously readable, while bucket listing and all browser write
access stay disabled. The temporary `buffer-media/` lifecycle rules do not
apply to the permanent publication prefix.
