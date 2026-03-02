/**
 * Preview mock data for EventEmbedFullscreen.
 * This is the drill-down fullscreen for a single event.
 *
 * Access at: /dev/preview/embeds/events/EventEmbedFullscreen
 */

const sampleEvent = {
  embed_id: "preview-event-fullscreen-1",
  id: "evt-preview-1",
  provider: "meetup",
  title: "AI & Machine Learning Berlin Meetup – Spring Edition",
  description:
    "Join us for an evening of talks on large language models, RAG architectures, " +
    "and deploying AI to production. Speakers from leading Berlin AI companies.\n\n" +
    "Schedule:\n- 18:30 Doors open\n- 19:00 Talk 1: LLMs in Production\n" +
    "- 19:45 Talk 2: RAG Architectures\n- 20:30 Networking\n\n" +
    "This is a beginner-friendly event — no prior ML experience required. " +
    "Light refreshments will be provided.",
  url: "https://www.meetup.com/example-ai-berlin/events/preview",
  date_start: "2026-03-15T19:00:00+01:00",
  date_end: "2026-03-15T22:00:00+01:00",
  timezone: "Europe/Berlin",
  event_type: "PHYSICAL",
  venue: {
    name: "Factory Berlin",
    address: "Rheinsberger Str. 76-77",
    city: "Berlin",
    state: null,
    country: "Germany",
    lat: 52.5393,
    lon: 13.4028,
  },
  organizer: {
    id: "org-ai-berlin",
    name: "AI Berlin Community",
    slug: "ai-berlin",
  },
  rsvp_count: 142,
  is_paid: false,
  fee: null,
  image_url: null,
};

const sampleOnlineEvent = {
  embed_id: "preview-event-fullscreen-online",
  id: "evt-preview-online",
  provider: "meetup",
  title: "TypeScript Deep Dive: Advanced Patterns for Scalable Apps",
  description:
    "A live online session covering generic constraints, conditional types, " +
    "mapped types, and module augmentation.\n\n" +
    "Suitable for developers with 1+ year of TypeScript experience.",
  url: "https://www.meetup.com/example-webdev-online/events/preview",
  date_start: "2026-03-20T18:00:00Z",
  date_end: "2026-03-20T20:00:00Z",
  timezone: "UTC",
  event_type: "ONLINE",
  venue: null,
  organizer: { id: "org-webdev", name: "Web Dev Community", slug: "webdev" },
  rsvp_count: 87,
  is_paid: false,
  fee: null,
  image_url: null,
};

const samplePaidEvent = {
  embed_id: "preview-event-fullscreen-paid",
  id: "evt-preview-paid",
  provider: "meetup",
  title: "Product Management Summit – London 2026",
  description:
    "Two-day conference covering product strategy, user research, and growth tactics.\n\n" +
    "Day 1: Strategy & Research\nDay 2: Growth & Execution\n\n" +
    "Includes workshop sessions, keynote talks, and networking lunch.",
  url: "https://www.meetup.com/example-pm-london/events/preview",
  date_start: "2026-04-05T09:00:00+01:00",
  date_end: "2026-04-06T17:00:00+01:00",
  timezone: "Europe/London",
  event_type: "PHYSICAL",
  venue: {
    name: "The Barbican",
    address: "Silk St",
    city: "London",
    state: null,
    country: "United Kingdom",
    lat: 51.521,
    lon: -0.093,
  },
  organizer: { id: "org-pm-london", name: "PM London", slug: "pm-london" },
  rsvp_count: 320,
  is_paid: true,
  fee: { amount: 25, currency: "GBP" },
  image_url: null,
};

/** Default props — physical event with full details */
const defaultProps = {
  event: sampleEvent,
  onClose: () => console.log("[Preview] EventEmbedFullscreen close"),
  hasPreviousEmbed: false,
  hasNextEmbed: true,
  onNavigatePrevious: () => console.log("[Preview] Navigate previous"),
  onNavigateNext: () => console.log("[Preview] Navigate next"),
};

export default defaultProps;

/** Named variants */
export const variants = {
  /** Online event — no venue address */
  online: {
    event: sampleOnlineEvent,
    onClose: () => console.log("[Preview] EventEmbedFullscreen (online) close"),
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => console.log("[Preview] Navigate previous"),
    onNavigateNext: () => console.log("[Preview] Navigate next"),
  },
  /** Paid event with fee badge */
  paid: {
    event: samplePaidEvent,
    onClose: () => console.log("[Preview] EventEmbedFullscreen (paid) close"),
    hasPreviousEmbed: true,
    hasNextEmbed: false,
    onNavigatePrevious: () => console.log("[Preview] Navigate previous"),
    onNavigateNext: () => console.log("[Preview] Navigate next"),
  },
};
