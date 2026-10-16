# Separating the website and web app

The public website is implemented in `frontend/apps/website`. Its `/` renders the
scrollable landing page, and it owns `/news`, `/blog`,
`/legal/privacy`, `/legal/terms`, `/legal/imprint`, and
`/newsletter/confirm/{token}`. The existing web app retains `/landing` for
compatibility. Both use `frontend/packages/public-site`, a small package with
public components, tokens, icons and content. The website build rejects browser
imports from the web app, the UI package, and app runtime dependencies.

The current phone images are real mobile web captures. Native phone screenshots
can replace the assets in both applications' `static/landing/screenshots/`
directories later without changing the device layout.

## Recommended destinations

| Environment | Website | Web app |
| --- | --- | --- |
| Production | `https://openmates.org` | `https://app.openmates.org` |
| Development | `https://landing.dev.openmates.org` | `https://app.dev.openmates.org` |

Deploy the two SvelteKit apps as separate Vercel projects from this repository.
The website is server-rendered without the app's encryption, IndexedDB or
WebSocket bootstrap. Vercel supports multiple projects from one repository with
separate root directories ([monorepo documentation](https://vercel.com/docs/monorepos)).

The app owns workspaces, account flows, OAuth callbacks, pairing and private
share/deep-link handling. Public event cards open actual app embeds in new tabs.
The app's existing event SEO routes keep their crawler-readable HTML and forward
human browsers to those embeds. Other existing public example and documentation
routes remain with the app until their migration is separately scoped.

## Vercel setup

1. Import the existing GitHub repository as a new project, for example
   `openmates-website`. Keep the current web app project.
2. Set Root Directory to `frontend/apps/website` and enable inclusion of source
   files outside the root. Choose **SvelteKit** and **Node.js 24.x**.
3. Keep the checked-in `vercel.json` commands:
   - Install: `cd ../../.. && corepack enable && pnpm --filter website... install --frozen-lockfile`
   - Build: `cd ../../.. && pnpm --filter website... run build`
   Leave Output Directory at the framework default. Do not copy the app's
   catch-all rewrite to this project.
4. Set Production Branch to `main`. Add `landing.dev.openmates.org` and assign it
   to the `dev` branch preview. Apply the DNS record Vercel displays for that
   domain; its exact value depends on the project. See
   [branch domain assignment](https://vercel.com/docs/domains/working-with-domains/assign-domain-to-a-git-branch).
5. Set these environment variables for the **Preview** environment. For the
   first website deployment, use **Deployments → Create Deployment**, enter
   `dev` as the Git reference, and choose Preview. The website directory is
   currently on `dev`; an initial import that builds `main` cannot build it
   until these changes are merged into `main`. Subsequent pushes to `dev`
   create previews automatically. See
   [creating a deployment from a branch](https://vercel.com/changelog/manually-create-deployments-by-commit-or-branch-in-the-dashboard).

| Variable | Preview / dev | Production, when cutover is approved |
| --- | --- | --- |
| `PUBLIC_WEBSITE_URL` | `https://landing.dev.openmates.org` | `https://openmates.org` |
| `PUBLIC_WEBAPP_URL` | `https://app.dev.openmates.org` | `https://app.openmates.org` |
| `PUBLIC_NEWSLETTER_API_BASE_URL` | `https://api.dev.openmates.org` | `https://api.openmates.org` |

6. In **Settings → Deployment Protection**, ensure the dev website is reachable
   without a Vercel login, including newsletter links opened in a fresh browser.
   Disable Vercel Authentication for this public website project, or add
   `landing.dev.openmates.org` as a protection exception if your plan supports
   exceptions. See [deployment protection](https://vercel.com/docs/deployment-protection)
   and [domain exceptions](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/deployment-protection-exceptions).
7. Once the website is reachable, set the corresponding API and email-worker
   `NEWSLETTER_PUBLIC_WEBSITE_ORIGIN` to its exact origin, with no trailing slash.
   Recreate the API and `core-worker` through the coordinated helper so Compose
   reloads their environment: `python3 scripts/sessions.py docker restart --session <session-id> --service api --service core-worker --build`.
   This setting
   enables credentialless newsletter CORS for subscribe/confirm routes and makes
   confirmation emails link to the website. Until explicitly set, existing
   app newsletter confirmation links remain valid. Confirmation requires a
   button click on the page, activates the selected categories, and then reveals
   the Signal link. Confirm tokens are not stored in browser storage.
8. Set `PUBLIC_LANDING_WEBSITE_URL=https://landing.dev.openmates.org` and
   `PUBLIC_LANDING_WEBAPP_URL=https://app.dev.openmates.org` on the existing web
   app project's dev preview and redeploy. This switches the app's public links
   and legal footer to the new website. The website itself always renders full
   legal documents without the chat UI.
9. Check `/`, `/news`, `/blog`, all three legal documents, app workspace links,
   event detail links, language selection, saved dark mode and a disposable
   newsletter double opt-in. Dev pages intentionally use `noindex`; development
   does not publish a production sitemap.

The website's filtered build compiles selected public app data and EN/DE copy
from tracked canonical sources. It does not need the UI package's generated
metadata, compiled translations, or token build. See the website README for
local commands. The module boundary gate reports compressed client JavaScript
size on every build.

## Migration sequence

1. Configure the website build and its app destination. The temporary
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
