/**
 * Preview mock data for EventsSearchEmbedFullscreen.
 *
 * This file provides sample props and named variants for the component preview system.
 * Access at: /dev/preview/embeds/events/EventsSearchEmbedFullscreen
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

/** Default props — shows a fullscreen events search results view */
const defaultProps = {
  query: "AI meetups in Berlin",
  provider: "Meetup",
  results: sampleResults,
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: false,
};

export default defaultProps;

/** Named variants for different component states */
export const variants = {
  /** With navigation arrows */
  withNavigation: {
    ...defaultProps,
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },

  /** Empty results */
  noResults: {
    query: "extremely rare events",
    provider: "Meetup",
    results: [],
    onClose: () => {},
  },
};
