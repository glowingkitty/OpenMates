import { describe, expect, it } from 'vitest';
import { authoredResultMetadata, authoredResultMediaPresentation, authoredSourceUrl, visibleAuthoredResult } from './authoredResultPresentation';

const draft = () => ({ type: 'event', app_id: 'events', title: 'Community evening',
  authoring: { schema_version: 1, kind: 'events.event', origin: 'draft', sources: [] } });

describe('authored presentation boundary', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('recognizes explicit admitted content and preserves draft/source metadata', () => {
    const content = draft();
    expect(authoredResultMetadata(content)).toBe(content.authoring);
    expect(authoredResultMetadata({ ...content, type: 'website' })).toBeUndefined();
    expect(authoredResultMetadata({ ...content, app_id: 'web' })).toBeUndefined();
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('does not infer admission from prototype properties or future kinds', () => {
    for (const kind of ['__proto__', 'constructor', 'tv.wiki'])
      expect(authoredResultMetadata({ ...draft(), authoring: { ...draft().authoring, kind } })).toBeUndefined();
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('renders only public web link schemes without credential-bearing authority', () => {
    expect(authoredSourceUrl('https://example.org/event#details')).toBe('https://example.org/event#details');
    for (const value of ['javascript:alert(1)', 'data:text/html,test', 'https://user:password@example.org/', 'not a URL'])
      expect(authoredSourceUrl(value)).toBeUndefined();
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('places selected decrypted media in a separate view without changing saved facts', () => {
    const stored = { ...draft(), image_url: 'https://example.org/photo.jpg', authored_media: [{ aes_key: 'private' }] };
    const view = authoredResultMediaPresentation(stored, ['blob:owned-view']);
    expect(view).not.toBe(stored);
    expect(view.image_url).toBe('blob:owned-view');
    expect(stored.image_url).toBe('https://example.org/photo.jpg');
    expect(view.authoring).toBe(stored.authoring);
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed
  it('renders supplied image URLs and preserves the stay gallery contract', () => {
    const content = { type: 'stay', app_id: 'travel', thumbnail: 'https://example.org/old.jpg',
      authoring: { ...draft().authoring, kind: 'travel.stay', images: [{ url: 'https://example.org/selected.jpg' }] } };
    const provided = authoredResultMediaPresentation(content, []);
    expect(provided.thumbnail).toBe('https://example.org/selected.jpg');
    const selected = authoredResultMediaPresentation(content, ['blob:owned-view']);
    expect(selected.thumbnail).toBe('blob:owned-view');
    expect((selected.images as Record<string, unknown>[])[0]).toEqual({ original_image: 'blob:owned-view', thumbnail: 'blob:owned-view' });
    expect(content.thumbnail).toBe('https://example.org/old.jpg');
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed
  it('selects the image fields consumed by model, social and fitness views', () => {
    for (const [kind, type, app, field] of [
      ['models3d.model_result', 'model_result', 'models3d', 'preview_image_url'],
      ['social_media.social_post', 'social_post', 'social_media', 'media_url'],
      ['fitness.class', 'class', 'fitness', 'class_image_url'],
      ['fitness.location', 'location', 'fitness', 'venue_image_url'],
    ]) {
      const content = { type, app_id: app, [field]: 'https://example.org/old.jpg', authoring: { ...draft().authoring, kind } };
      expect(authoredResultMediaPresentation(content, ['blob:owned-view'])[field]).toBe('blob:owned-view');
    }
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed
  it('places selected home images before the supplied gallery without changing stored URLs', () => {
    const content = { type: 'listing', app_id: 'home', image_urls: ['https://example.org/original.jpg'],
      authoring: { ...draft().authoring, kind: 'home.listing', images: [{ url: 'https://example.org/supplied.jpg' }] } };
    const view = authoredResultMediaPresentation(content, ['blob:owned-view']);
    expect(view.image_urls).toEqual(['blob:owned-view', 'https://example.org/supplied.jpg', 'https://example.org/original.jpg']);
    expect(content.image_urls).toEqual(['https://example.org/original.jpg']);
  });
  // contract-test: supporting surface=gui.web assertions=authored-results.facts.provenance-and-drafts,authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('does not send media keys, storage paths or mounted blob URLs as follow-up facts', () => {
    const stored = { ...draft(), count: 0, available: false, source_json: 'private input',
      authored_media: [{ aes_key: 'private', files: {} }], image_url: 'blob:owned-view',
      seasons: [{ season_number: 0, episode_count: 1, aes_nonce: 'private', s3_key: 'private' }] };
    expect(visibleAuthoredResult(stored)).toEqual({ ...draft(), count: 0, available: false,
      seasons: [{ season_number: 0, episode_count: 1 }] });
    expect(stored.authored_media[0].aes_key).toBe('private');
  });
});
