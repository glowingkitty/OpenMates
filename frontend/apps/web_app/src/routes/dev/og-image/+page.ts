/**
 * OG image preview page configuration.
 *
 * Renders a 1200×600px design card showing the app slogan on the left
 * and the real web app (demo-for-everyone chat) in a phone frame on the right.
 *
 * Purpose: Playwright screenshots this page to generate up-to-date OG images
 * and GitHub/README assets that always reflect the current design.
 *
 * Architecture: /dev/ layout gate ensures this is only accessible on dev
 * environments (localhost / app.dev.openmates.org), not production.
 */
export const ssr = false;
export const prerender = false;
