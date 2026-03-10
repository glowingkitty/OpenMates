/**
 * Preview mock data for EventEmbedPreview.
 * This is the child embed card component for a single event.
 *
 * Access at: /dev/preview/embeds/events/EventEmbedPreview
 */

const sampleEvent = {
  embed_id: "preview-event-embed-1",
  id: "evt-preview-1",
  provider: "meetup",
  title: "AI & Machine Learning Berlin Meetup – Spring Edition",
  description:
    "Join us for an evening of talks on large language models, RAG architectures, " +
    "and deploying AI to production. Speakers from leading Berlin AI companies.\n\n" +
    "Schedule:\n- 18:30 Doors open\n- 19:00 Talk 1: LLMs in Production\n" +
    "- 19:45 Talk 2: RAG Architectures\n- 20:30 Networking",
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
  embed_id: "preview-event-embed-online",
  id: "evt-preview-online",
  provider: "meetup",
  title: "TypeScript Deep Dive: Advanced Patterns for Scalable Apps",
  description:
    "A live online session covering generic constraints, conditional types, and module augmentation.",
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
  embed_id: "preview-event-embed-paid",
  id: "evt-preview-paid",
  provider: "meetup",
  title: "Product Management Summit – London 2026",
  description:
    "Two-day conference covering product strategy, user research, and growth tactics.",
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

/** Default props — physical event, finished */
const defaultProps = {
  id: sampleEvent.embed_id,
  event: sampleEvent,
  isMobile: false,
  onFullscreen: () =>
    () => {},
};

export default defaultProps;

/** Named variants */
export const variants = {
  /** Online event */
  online: {
    id: sampleOnlineEvent.embed_id,
    event: sampleOnlineEvent,
    isMobile: false,
    onFullscreen: () =>
      () => {},
  },
  /** Paid event with fee */
  paid: {
    id: samplePaidEvent.embed_id,
    event: samplePaidEvent,
    isMobile: false,
    onFullscreen: () =>
      () => {},
  },
  /** Mobile layout */
  mobile: {
    ...defaultProps,
    id: "preview-event-embed-mobile",
    isMobile: true,
  },
};
