/**
 * Preview mock data for EventsSearchEmbedPreview.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/events/EventsSearchEmbedPreview
 */

const sampleResults = [
  {
    id: "evt-1",
    provider: "Meetup",
    title: "AI & Machine Learning Berlin Meetup – Spring Edition",
    description:
      "Join us for an evening of talks on LLMs, RAG architectures, and production AI.",
    url: "https://www.meetup.com/example-ai-berlin",
    date_start: "2026-03-15T19:00:00",
    date_end: "2026-03-15T22:00:00",
    timezone: "Europe/Berlin",
    event_type: "PHYSICAL",
    venue: {
      name: "Factory Berlin",
      city: "Berlin",
      country: "Germany",
    },
    organizer: { name: "AI Berlin Community" },
    rsvp_count: 142,
    is_paid: false,
  },
  {
    id: "evt-2",
    provider: "Meetup",
    title: "Web Dev Online: TypeScript Deep Dive",
    description:
      "A live online session covering advanced TypeScript patterns for scalable apps.",
    url: "https://www.meetup.com/example-webdev-online",
    date_start: "2026-03-20T18:00:00",
    date_end: "2026-03-20T20:00:00",
    timezone: "UTC",
    event_type: "ONLINE",
    venue: null,
    organizer: { name: "Web Dev Community" },
    rsvp_count: 87,
    is_paid: false,
  },
  {
    id: "evt-3",
    provider: "Meetup",
    title: "Product Management Summit – London",
    description:
      "Two-day conference covering product strategy, user research, and growth tactics.",
    url: "https://www.meetup.com/example-pm-london",
    date_start: "2026-04-05T09:00:00",
    date_end: "2026-04-06T17:00:00",
    timezone: "Europe/London",
    event_type: "PHYSICAL",
    venue: {
      name: "The Barbican",
      city: "London",
      country: "United Kingdom",
    },
    organizer: { name: "PM London" },
    rsvp_count: 320,
    is_paid: true,
    fee: { amount: 25, currency: "GBP" },
  },
];

/** Default props — shows a finished events search with results */
const defaultProps = {
  id: "preview-events-search-1",
  query: "AI meetups in Berlin",
  provider: "Meetup",
  status: "finished" as const,
  results: sampleResults,
  isMobile: false,
  onFullscreen: () => console.log("[Preview] Fullscreen clicked"),
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** Processing state — shows loading animation */
  processing: {
    id: "preview-events-search-processing",
    query: "searching for events...",
    provider: "Meetup",
    status: "processing" as const,
    results: [],
    isMobile: false,
  },

  /** Error state */
  error: {
    id: "preview-events-search-error",
    query: "failed events search",
    provider: "Meetup",
    status: "error" as const,
    results: [],
    isMobile: false,
  },

  /** Mobile view */
  mobile: {
    ...defaultProps,
    id: "preview-events-search-mobile",
    isMobile: true,
  },
};
