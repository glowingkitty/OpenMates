import { describe, expect, it } from 'vitest';
import { authoredSharedChildMatches, selectedSharedChildren, selectedSharedKeyWrappers, sharedEmbedType } from './sharedEmbedGraph';

const parent = { embed_id: 'carrier', hashed_user_id: 'owner', hashed_chat_id: 'chat', embed_ids: ['series', 'movie'] };
const child = (embed_id: string) => ({ embed_id, parent_embed_id: 'carrier', hashed_user_id: 'owner', hashed_chat_id: 'chat', status: 'finished' });
const content = { type: 'authored_results', embed_ids: ['series', 'movie'], items: [
  { embed_id: 'series', kind: 'tv.series' }, { embed_id: 'movie', kind: 'tv.movie' },
] };

describe('explicit typed embed share graph', () => {
  // contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable,tv-titles.lifecycle.groups-and-actions
  it('uses real decrypted carrier/TV types and keeps absent type unknown', () => {
    expect(sharedEmbedType('authored_results', null)).toBe('ai-authored-results');
    expect(sharedEmbedType(null, { type: 'tv_movie' })).toBe('tv-movie');
    expect(sharedEmbedType('tv_series', { type: 'tv_series' })).toBe('tv-series');
    expect(sharedEmbedType('app_skill_use', { type: 'app_skill_use' })).toBe('app-skill-use');
    expect(sharedEmbedType(null, null)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.groups.same-response-and-reuse,authored-results.media.safe-and-attributed
  it('keeps typed order and never follows upload/source provenance', () => {
    const rows = [child('movie'), { ...child('series'), source_embed_id: 'private-upload', authoring: { sources: [{ embed_ref: 'private-notes' }] } },
      child('private-upload'), child('private-notes')];
    expect(selectedSharedChildren(parent, content, rows).map(row => row.embed_id)).toEqual(['series', 'movie']);
    expect(selectedSharedChildren(child('movie'), { type: 'tv_movie', authored_media: [{ source_embed_id: 'private-upload' }] }, rows)).toEqual([]);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.groups.same-response-and-reuse
  it('rejects manifest mismatches and cross-owner/chat/backlink children', () => {
    expect(selectedSharedChildren(parent, { ...content, embed_ids: ['movie', 'series'] }, [child('movie'), child('series')])).toEqual([]);
    expect(selectedSharedChildren(parent, { ...content, items: [{ embed_id: 'series', kind: 'ai.app_skill_use' }, content.items[1]] }, [child('movie'), child('series')])).toEqual([]);
    for (const patch of [{ hashed_user_id: 'other' }, { hashed_chat_id: 'other' }, { parent_embed_id: 'other' }, { parent_embed_id: undefined }, { status: 'processing' }])
      expect(selectedSharedChildren(parent, content, [{ ...child('series'), ...patch }, child('movie')]).map(row => row.embed_id)).toEqual(['movie']);
    expect(selectedSharedChildren(parent, content, [child('series'), child('series'), child('movie')]).map(row => row.embed_id)).toEqual(['movie']);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable
  it('accepts valid old same-scope children without a stored backlink', () => {
    const old = { embed_id: 'legacy', hashed_user_id: 'owner', hashed_chat_id: 'chat', embed_ids: ['old-child'] };
    expect(selectedSharedChildren(old, { type: 'app_skill_use' }, [{ embed_id: 'old-child', hashed_user_id: 'owner', hashed_chat_id: 'chat' }])).toHaveLength(1);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.lifecycle.encrypted-and-stable,tv-titles.lifecycle.groups-and-actions
  it('matches each actual decrypted child kind/type instead of manufacturing an app-skill', () => {
    const series = { type: 'tv_series', app_id: 'tv', skill_id: 'series', authoring: { kind: 'tv.series' } };
    expect(authoredSharedChildMatches(content, 'series', series, 'tv_series')).toBe(true);
    expect(authoredSharedChildMatches(content, 'movie', series, 'tv_series')).toBe(false);
    expect(authoredSharedChildMatches(content, 'series', { ...series, type: 'app_skill_use' }, 'app_skill_use')).toBe(false);
    expect(authoredSharedChildMatches(content, 'series', { ...series, app_id: 'other' }, 'tv_series')).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=authored-results.media.safe-and-attributed,authored-results.lifecycle.encrypted-and-stable
  it('admits only wrappers addressed from the selected carrier to selected children', () => {
    const valid = { key_type: 'embed', parent_embed_id: 'carrier-hash', hashed_embed_id: 'movie-hash', encrypted_embed_key: 'existing-wrapped-key' };
    expect(selectedSharedKeyWrappers([valid, { ...valid, key_type: 'master' }, { ...valid, key_type: 'chat' },
      { ...valid, parent_embed_id: 'source-upload-hash' }, { ...valid, hashed_embed_id: 'unselected-hash' }],
    'carrier-hash', new Set(['movie-hash']))).toEqual([valid]);
  });
});
