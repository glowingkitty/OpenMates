/**
 * Newsletter registry — metadata for the /newsletter/<slug> landing pages.
 *
 * Each entry here backs a public landing page linked from newsletter emails.
 * When sending a new issue with send_newsletter.py, add a matching entry here
 * (keyed by the same `slug` used in the issue's meta.yml) BEFORE deploying.
 *
 * The actual newsletter body lives in openmates-marketing/campaigns/<slug>/;
 * this registry only holds the "landing-page-worthy" subset (title, video
 * URL/poster) that renders when recipients click the clickable-thumbnail
 * image in the email.
 */

export interface NewsletterVideo {
    /** Self-hosted mp4 URL, or direct-link video asset. We do NOT embed YouTube. */
    src: string;
    /** Optional poster image shown before playback (absolute or static path). */
    poster?: string;
    /** Optional mime type override (defaults to video/mp4). */
    mimeType?: string;
}

export interface NewsletterEntry {
    slug: string;
    /** Short display title used in <h1> and <title>. */
    title: string;
    /** Optional subtitle / hook shown below the title. */
    subtitle?: string;
    /** ISO date the newsletter went out — used for ordering and "published" line. */
    publishedAt?: string;
    video?: NewsletterVideo;
    /** Optional primary CTA shown below the video. */
    cta?: {
        url: string;
        label: string;
    };
}

export const NEWSLETTERS: NewsletterEntry[] = [
    // Add new newsletters at the top; keep historical entries so old email
    // links keep working indefinitely.
];

export function findNewsletter(slug: string): NewsletterEntry | null {
    return NEWSLETTERS.find((n) => n.slug === slug) ?? null;
}
