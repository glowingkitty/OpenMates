import { describe, expect, it } from 'vitest';
import { normalizeEventResult, projectVisibleEventResult } from '../eventResult';

// contract-test: supporting surface=gui.web assertions=events-search.surface-parity
describe('event serialization normalization', () => {
  // contract-test: supporting surface=gui.web assertions=events-search.surface-parity
  it('restores flattened persisted children without losing provider data or unknown states', () => {
    const raw = { organizer_name: 'Berlin Lingua Hub', organizer_id: 'org-1', organizer_slug: 'berlin-lingua',
      venue_name: 'Community space', venue_address: 'Example Street 1', venue_lat: '52.5', venue_lon: '13.4',
      fee_amount: '0', fee_currency: 'EUR', rsvp_count: '80', is_paid: null,
      date_start: '2026-12-15T18:00:00Z', timezone: 'Europe/Berlin', provider: 'Gathering',
      source_evidence: { original: true }, cover_url: '/event.webp' };
    expect(normalizeEventResult(raw, 'child-1')).toMatchObject({
      ...raw, embed_id: 'child-1', organizer: { id: 'org-1', name: 'Berlin Lingua Hub', slug: 'berlin-lingua' },
      venue: { name: 'Community space', address: 'Example Street 1', lat: 52.5, lon: 13.4 },
      fee: { amount: 0, currency: 'EUR' }, rsvp_count: 80, is_paid: undefined,
    });
    expect(raw).not.toHaveProperty('organizer');
  });
  // contract-test: supporting surface=gui.web assertions=events-search.surface-parity
  it('preserves nested shape, additive fields and explicit zero/false while filling partial flat fields', () => {
    const result = normalizeEventResult({ embed_id: 'nested', organizer: { name: 'Nested organizer', photo: '/avatar.webp' },
      organizer_name: 'Ignored flat name', venue: { name: 'Venue', lat: 0 }, venue_lon: '0',
      fee: { amount: 0, currency: 'EUR', basis: 'provider' }, rsvp_count: 0, is_paid: false,
      image_url: null, source: { checked: true } });
    expect(result).toMatchObject({ embed_id: 'nested', organizer: { name: 'Nested organizer', photo: '/avatar.webp' },
      venue: { name: 'Venue', lat: 0, lon: 0 }, fee: { amount: 0, currency: 'EUR', basis: 'provider' },
      rsvp_count: 0, is_paid: false, image_url: null, source: { checked: true } });
  });
  // contract-test: supporting surface=gui.web assertions=events-search.surface-parity
  it('does not invent an organizer, location, fee or RSVP count for missing or malformed data', () => {
    expect(normalizeEventResult({ organizer: null, venue: [], fee: null, rsvp_count: '', is_paid: 'false' })).toMatchObject({
      organizer: undefined, venue: undefined, fee: undefined, rsvp_count: undefined, is_paid: undefined,
    });
  });
});


// contract-test: supporting surface=gui.web assertions=apps.requests.natural-language,apps.results.shared-fullscreen,events-search.surface-parity
it('projects event follow-up context without forwarding raw or nested transport metadata', () => {
  const normalized = normalizeEventResult({
    title: 'Language exchange', description: 'A visible description', date_start: '2026-12-15T18:00:00Z', provider: 'Gathering',
    aes_key: 'raw-private-crypto', files: { original: { s3_key: 'raw-private-storage' } },
    organizer_name: 'Berlin Lingua Hub', organizer_secret: 'flat-private-crypto',
    organizer: { id: 'org', name: 'Berlin Lingua Hub', slug: 'berlin', encryption: 'organizer-private-crypto' },
    venue: { name: 'Venue', lat: 0, lon: 0, storage: { key: 'venue-private-storage' } },
    fee: { amount: 0, currency: 'EUR', aes_key: 'fee-private-crypto' }, rsvp_count: 0, is_paid: false,
  }, 'event-child');
  const result = projectVisibleEventResult(normalized);
  expect(normalized).toHaveProperty('aes_key', 'raw-private-crypto');
  expect(normalized.organizer).toHaveProperty('encryption', 'organizer-private-crypto');
  expect(result).toMatchObject({ embed_id: 'event-child', title: 'Language exchange', description: 'A visible description', provider: 'Gathering',
    organizer: { id: 'org', name: 'Berlin Lingua Hub', slug: 'berlin' }, venue: { name: 'Venue', lat: 0, lon: 0 },
    fee: { amount: 0, currency: 'EUR' }, rsvp_count: 0, is_paid: false });
  expect(Object.keys(result).sort()).toEqual(['embed_id', 'id', 'provider', 'title', 'description', 'url', 'date_start', 'date_end', 'timezone', 'event_type', 'venue', 'organizer', 'fee', 'rsvp_count', 'is_paid', 'image_url', 'cover_url'].sort());
  expect(Object.keys(result.organizer!).sort()).toEqual(['id', 'name', 'slug']);
  expect(Object.keys(result.venue!).sort()).toEqual(['name', 'address', 'city', 'state', 'country', 'lat', 'lon'].sort());
  expect(Object.keys(result.fee!).sort()).toEqual(['amount', 'currency']);
  expect(JSON.stringify(result)).not.toContain('private-');
  expect(result.organizer).not.toBe(normalized.organizer);
  expect(result.venue).not.toBe(normalized.venue);
  expect(result.fee).not.toBe(normalized.fee);
});

// contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.content.typed-and-useful
it('preserves authored source facts without turning missing price, timezone or times into defaults', () => {
  const authoring = { schema_version: 1, kind: 'events.event', origin: 'draft', sources: [{ embed_ref: '会議 notes.pdf (2)' }] };
  const normalized = normalizeEventResult({ title: 'Proposed event', date_start: '2027-01-30',
    source_url: 'https://example.org/event', organizer: 'Supplied organizer', location: 'Supplied venue',
    authoring, online: true, online_url: 'https://example.org/meeting' }, 'actual-child');
  expect(normalized.authoring).toEqual(authoring);
  expect(normalized).toMatchObject({ date_start: '2027-01-30', date_end: undefined, timezone: undefined,
    fee: undefined, is_paid: undefined, rsvp_count: undefined, organizer: { name: 'Supplied organizer' },
    venue: { name: 'Supplied venue' }, url: 'https://example.org/event', online: true });
});

// contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.media.safe-and-attributed
it('projects provenance for follow-ups while removing nested secrets and UI-only media URLs', () => {
  const normalized = normalizeEventResult({ title: 'Supplied event', source_json: 'private raw payload', image_url: 'blob:https://app.example/decrypted',
    authoring: { schema_version: 1, kind: 'events.event', origin: 'user_provided', observed_at: '2026-10-26T10:00:00Z', aes_key: 'authoring-private',
      source_json: 'private-structured', images: [{ url: 'https://example.org/picture.jpg', aes_key: 'image-private' }],
      sources: [{ embed_ref: '会議 notes.pdf (2)', label: 'My notes', aes_key: 'source-private' }] },
    aes_key: 'event-private', authored_media: [{ aes_key: 'media-private' }],
  });
  const projected = projectVisibleEventResult(normalized);
  expect(projected.authoring).toEqual({ schema_version: 1, kind: 'events.event', origin: 'user_provided', observed_at: '2026-10-26T10:00:00Z',
    sources: [{ embed_ref: '会議 notes.pdf (2)', label: 'My notes' }] });
  expect(projected.image_url).toBeUndefined();
  expect(JSON.stringify(projected)).not.toContain('private');
  expect(JSON.stringify(projected)).not.toContain('blob:');
  expect(projected.authoring).not.toBe(normalized.authoring);
});
