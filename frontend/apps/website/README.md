# Standalone OpenMates website

This SvelteKit app serves the public landing page, newsroom, blog, legal documents, and newsletter confirmation. It imports only `@repo/public-site`; the client bundle gate in `vite.config.ts` rejects app runtime and UI package modules and reports gzip size.

Use Node 24 and pnpm from the repository root. Install with `pnpm --filter website... install --frozen-lockfile`, build with `pnpm --filter website... run build`, and type-check with `pnpm --filter website check`. The public-site build generates selected public app metadata from `backend/apps/*/app.yml` and focus-mode `SKILL.md` files, public translations directly from canonical UI YAML sources, release data, icons, and a byte-identical copy of canonical OpenMates event data. It does not require generated UI locale JSON or app metadata. Landing copy and app capability prompts live in `frontend/packages/public-site/src/i18n/landing.yml`; the small public token stylesheet is checked into that package.

The existing web app's ordinary `prebuild` runs the UI build and then the public-site build before compiling `/landing`, so copied legal data and public assets are current. A direct `vite build` bypasses `prebuild`; run `pnpm --dir frontend/packages/public-site build` first when using that path after canonical public sources change.

Import this same monorepo as a separate Vercel project. Set Root Directory to `frontend/apps/website`, include files outside that directory, Framework Preset to SvelteKit, Node.js to 24.x, and keep the checked-in `vercel.json` install/build commands. The filtered install uses the frozen monorepo lockfile; the filtered build runs public data generation before Vite.

Assign `landing.dev.openmates.org` to the `dev` branch preview for evaluation. When the apex ownership transfer is approved, assign `openmates.org` to this project's production deployment. The web app remains at `app.dev.openmates.org` and later `app.openmates.org`.

The website initially exists on `dev`. Keep `main` as the eventual production branch, and create the first Preview from **Deployments → Create Deployment → `dev`**. An automatic first import of `main` cannot build the new directory until this change is merged there.

Set `PUBLIC_WEBSITE_URL` and `PUBLIC_WEBAPP_URL` per environment to the exact public origins; set `PUBLIC_NEWSLETTER_API_BASE_URL` to the corresponding API origin. Defaults are host-aware for `landing.dev.openmates.org` and `openmates.org`. The API must allow the exact website origin for public newsletter requests via `NEWSLETTER_PUBLIC_WEBSITE_ORIGIN`. Newsletter confirmation URLs contain a token and use `noindex`, `no-store`, and `Referrer-Policy: no-referrer`.

Keep this project's server-rendered public routes, `/robots.txt`, and `/sitemap.xml` without a catch-all app rewrite.
