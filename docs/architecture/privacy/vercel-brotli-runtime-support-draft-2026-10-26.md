# Unsent Vercel security support draft

To: security@vercel.com

Subject: Managed Node 24.x functions still run 24.21.0 after CVE-2026-111497 updates

Our development web project is configured for Node 24.x and uses
`@sveltejs/adapter-vercel` with `runtime: 'nodejs24.x'`. The build passes a check
requiring Node 24.22.1 or later and
`zlib.constants.BROTLI_DECODER_ERROR_FORMAT_BLOCK_SWITCH === -17`.

However, actual function startup on 2026-10-26 reports Node 24.21.0 with that
constant missing. Our new security guard stops server initialization, so affected
server-rendered requests currently fail with HTTP 500. The static app still loads.

Reproducible deployments of dev commit
`929203c4454c663eec131f084da011dcb3761dce`:

- `dpl_FBPweV9NJF1ZfVeBoUKba2h8qRhg`, serving `app.dev.openmates.org`.
- `dpl_2okfGmyt2vcQEznzBMGx3mSYHXWd`, a fresh preview deployment of the same
  commit. Its build log confirms: “Skipping build cache, deployment was triggered
  without cache.” The function still reports Node 24.21.0.
- Observed function log region: `arn1`; configured runtime: `nodejs24.x`.

The requests were ordinary GETs for nonexistent public asset paths, causing our
SvelteKit server to initialize. No malformed compressed input or exploit was used.
The generic error contains only runtime versions and the patch marker; no user
content or credentials are involved.

Please update the managed Node 24.x runtime to 24.22.1 or later with the Brotli
fix, and confirm availability in the affected region. Is any supported project
action needed beyond a fresh deployment while your rollout is in progress?

References:

- <https://vercel.com/kb/bulletin/node-js-security-advisory>
- <https://nodejs.org/en/blog/vulnerability/october-2026-security-releases>
