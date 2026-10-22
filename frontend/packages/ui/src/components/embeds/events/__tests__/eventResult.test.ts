import { describe, expect, it } from 'vitest';
import { normalizeEventResult, projectVisibleEventResult } from '../eventResult';

// contract-test: supporting surface=gui.web assertions=events-search.surface-parity
describe('event serialization normalization', () => {
  // contract-test: supporting surface=gui.web assertions=events-search.surface-parity
  it('restores flattened persisted children without losing provider data or unknown states', () => {
    const raw = { organizer_name: 'Berlin Lingua Hub', organizer_id: 'org-1', organizer_slug: 'berlin-lingua',
      venue_name: 'Community space', venue_address: 'Example Street 1', venue_lat: '52.5', venue_lon: '13.4',
      fee_amount: '0', fee_currency: 'EUR', rsvp_count: '80', is_paid: null,
      date_start: '2026-12-15T18:00:00Z', timezone: 'Europe/Berlin', provider: 'meetup',
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
    title: 'Language exchange', description: 'A visible description', date_start: '2026-12-15T18:00:00Z', provider: 'meetup',
    aes_key: 'raw-private-crypto', files: { original: { s3_key: 'raw-private-storage' } },
    organizer_name: 'Berlin Lingua Hub', organizer_secret: 'flat-private-crypto',
    organizer: { id: 'org', name: 'Berlin Lingua Hub', slug: 'berlin', encryption: 'organizer-private-crypto' },
    venue: { name: 'Venue', lat: 0, lon: 0, storage: { key: 'venue-private-storage' } },
    fee: { amount: 0, currency: 'EUR', aes_key: 'fee-private-crypto' }, rsvp_count: 0, is_paid: false,
  }, 'event-child');
  const result = projectVisibleEventResult(normalized);
  expect(normalized).toHaveProperty('aes_key', 'raw-private-crypto');
  expect(normalized.organizer).toHaveProperty('encryption', 'organizer-private-crypto');
  expect(result).toMatchObject({ embed_id: 'event-child', title: 'Language exchange', description: 'A visible description', provider: 'meetup',
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
