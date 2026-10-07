# Separating the website and web app

The `/landing` route is the temporary entry point for the scrollable marketing
page. It shares the app's UI tokens and screenshot assets while rendering without
initializing account synchronization. Native phone screenshots can replace the
responsive web assets under `frontend/apps/web_app/static/landing/screenshots/`
later without changing the layout.

## Recommended destinations

| Environment | Website | Web app |
| --- | --- | --- |
| Production | `https://openmates.org` | `https://app.openmates.org` |
| Development | `https://landing.dev.openmates.org` | `https://app.dev.openmates.org` |

Use two SvelteKit apps in this repository, deployed as separate Vercel projects:
the existing `frontend/apps/web_app` and a future `frontend/apps/website`. Keep
shared design tokens, icons, landing components, publication data, and event data
in shared packages. This gives the public website its own server-rendered build
and deployment without loading the app's encryption, IndexedDB, or WebSocket
bootstrap. Vercel supports multiple projects from one repository with separate
root directories ([monorepo documentation](https://vercel.com/docs/monorepos)).

The website should own the landing, blog, news, public events, documentation,
legal pages, public example SEO pages, sitemap, and robots files. The app should
own authenticated workspaces, account flows, OAuth callbacks, pairing, and private
share/deep-link handling. Public example pages can remain on the website and link
to the real interactive chat on the app.

## Migration sequence

1. Extract the website build and configure its app destination. The temporary
   landing route accepts `PUBLIC_LANDING_WEBAPP_URL` and
   `PUBLIC_LANDING_WEBSITE_URL`. Until cutover, they default to the current
   deployment; `landing.dev.openmates.org` defaults to the dev app destination.
2. Deploy the separate website to `landing.dev.openmates.org`, keep the existing
   dev app host, and verify links, SEO output, and the public-content routes.
3. Prepare production app-origin support in the API/Caddy allowlist, WebSocket
   checks, OAuth return URLs, email links, and frontend URL configuration before
   switching the apex domain.
4. Preserve existing passkeys. `auth_passkey.py` currently derives the relying
   party ID from the requesting Origin. Existing credentials registered for
   `openmates.org` need that same RP ID when used from `app.openmates.org`, along
   with validation of the new allowed Origin. A parent-domain RP ID is valid
   from its subdomain; changing the RP ID would prevent existing credentials
   from matching ([WebAuthn RP-ID rules](https://developer.mozilla.org/en-US/docs/Web/API/PublicKeyCredentialCreationOptions#rp)).
5. Review cookie environment separation: current session cookies use
   `.openmates.org` for both development and production. Preserve login recovery
   and encryption keys while preventing environment cookie collisions.
   Browser storage is scoped to the exact origin: IndexedDB, localStorage,
   CacheStorage, and any locally held chat/key material on `openmates.org` will
   not be available to `app.openmates.org`. Before cutover, inventory the app's
   local key and encrypted-chat state, design a consented, short-lived migration
   bridge on the old origin, and test existing accounts with unsynced drafts or
   data. A cookie-only login transfer cannot move those browser-held keys.
6. Verify redirects for old apex URLs. URL fragments never reach the server, so
   old `/#chat-id=...`, `/#settings/...`, and share-key fragments need a small
   browser redirect bridge that preserves the complete fragment. Do not put
   private chat IDs or share keys into query parameters, analytics, or logs.
7. Move the production website to the apex and the production app to its app
   subdomain in a coordinated release. Confirm canonical URLs, sitemap ownership,
   OAuth callbacks, login/passkeys, share links, and the old service-worker cleanup.

Relevant current configuration lives in `frontend/apps/web_app/vercel.json`,
`frontend/packages/ui/src/config/links.ts`, `shared/config/urls.yml`,
`deployment/prod_server/Caddyfile`, and
`backend/core/api/app/routes/auth_routes/auth_passkey.py`. Moving DNS alone would
still serve the app at the apex because the current build's root and catch-all
rewrites belong to the app. The domain cutover is a later separately authorized
production change.
