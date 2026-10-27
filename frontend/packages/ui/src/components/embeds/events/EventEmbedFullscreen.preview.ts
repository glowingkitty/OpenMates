/**
 * Preview mock data for EventEmbedFullscreen.
 * This is the drill-down fullscreen for a single event.
 *
 * Uses the data-driven shape (EmbedFullscreenRawData) — the event fields
 * are flattened into decodedContent, matching what the component extracts via
 * `data.decodedContent`. The old `{ event: {...} }` direct-prop format
 * was removed in OPE-413 after the OPE-276 migration to data-driven routing.
 *
 * Access at: /dev/preview/embeds/events/EventEmbedFullscreen
 */

const sampleEvent = {
  embed_id: "preview-event-fullscreen-1",
  id: "evt-preview-1",
  provider: "Gathering",
  title: "AI & Machine Learning Berlin Gathering – Spring Edition",
  description:
    "Join us for an evening of talks on large language models, RAG architectures, " +
    "and deploying AI to production. Speakers from leading Berlin AI companies.\n\n" +
    "**Schedule**\n\n- 18:30 Doors open\n- 19:00 Talk 1: LLMs in Production\n" +
    "- 19:45 Talk 2: RAG Architectures\n- 20:30 Networking\n\n" +
    "This is a beginner-friendly event — no prior ML experience required. " +
    "Light refreshments will be provided. [Read the event guide](https://example.com/event-guide).",
  url: "https://example.com/fixture",
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
  image_url: "/store-examples/home-1.webp",
};

const sampleOnlineEvent = {
  embed_id: "preview-event-fullscreen-online",
  id: "evt-preview-online",
  provider: "Gathering",
  title: "TypeScript Deep Dive: Advanced Patterns for Scalable Apps",
  description:
    "A live online session covering generic constraints, conditional types, " +
    "mapped types, and module augmentation.\n\n" +
    "Suitable for developers with 1+ year of TypeScript experience.",
  url: "https://example.com/fixture",
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
  provider: "Gathering",
  title: "Product Management Summit – London 2026",
  description:
    "Two-day conference covering product strategy, user research, and growth tactics.\n\n" +
    "Day 1: Strategy & Research\nDay 2: Growth & Execution\n\n" +
    "Includes workshop sessions, keynote talks, and networking lunch.",
  url: "https://example.com/fixture",
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
  data: {
    decodedContent: sampleEvent,
    embedData: { status: "finished" },
    attrs: { app_id: "events" },
  },
  onClose: () => {},
  hasPreviousEmbed: false,
  hasNextEmbed: true,
  onNavigatePrevious: () => {},
  onNavigateNext: () => {},
};

export default defaultProps;

/** Named variants */
export const variants = {
  projectedPrivacy: {
    data: { decodedContent: { ...sampleEvent,
      aes_key: 'event-private-crypto-sentinel', aes_nonce: 'event-private-crypto-sentinel',
      s3_base_url: 'event-private-storage-sentinel', files: { original: { s3_key: 'event-private-storage-sentinel' } },
      organizer_name: sampleEvent.organizer.name,
      organizer_private_encryption: 'flat-private-crypto-sentinel', venue_s3_key: 'flat-private-storage-sentinel',
      organizer: { ...sampleEvent.organizer, aes_key: 'organizer-private-crypto-sentinel', storage: { bucket: 'organizer-private-storage-sentinel' } },
      venue: { ...sampleEvent.venue, aes_nonce: 'venue-private-crypto-sentinel', files: { original: 'venue-private-storage-sentinel' } },
      fee: { amount: 0, currency: 'EUR', encryption: 'fee-private-crypto-sentinel', storage_key: 'fee-private-storage-sentinel' },
    } }, onClose: () => {},
  },
  formattedHtml: {
    data: { decodedContent: { ...sampleEvent,
      description: '<p>Join our <strong>Book Lovers Social Gathering!</strong></p><p>Today’s speaker: <em>Matt Damon</em>.</p><ol><li>Read the <a href="https://example.com/reading">reading guide</a>.</li><li>Share your favourite chapter.</li></ol><p>Bring questions.<br>Everyone is welcome.</p><script>window.__eventDescriptionUnsafe = true</script><a href="javascript:alert(1)">Unsafe link</a><img src="/event-description-must-not-load.png" onerror="alert(1)">',
    } }, onClose: () => {},
  },
  overnightTimezone: {
    data: { decodedContent: { ...sampleEvent, date_start: '2026-03-15T23:30:00+09:00', date_end: '2026-03-16T01:00:00+09:00', timezone: 'Asia/Tokyo' } }, onClose: () => {},
  },
  unknownFee: {
    data: { decodedContent: { ...sampleEvent, is_paid: undefined, fee: undefined, image_url: null } },
    onClose: () => {},
  },
  /** Online event — no venue address */
  online: {
    data: {
      decodedContent: sampleOnlineEvent,
      embedData: { status: "finished" },
      attrs: { app_id: "events" },
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: true,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },
  /** Paid event with fee badge */
  paid: {
    data: {
      decodedContent: samplePaidEvent,
      embedData: { status: "finished" },
      attrs: { app_id: "events" },
    },
    onClose: () => {},
    hasPreviousEmbed: true,
    hasNextEmbed: false,
    onNavigatePrevious: () => {},
    onNavigateNext: () => {},
  },
};
