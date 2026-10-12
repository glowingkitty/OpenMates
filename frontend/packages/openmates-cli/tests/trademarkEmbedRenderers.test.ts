import { it } from 'node:test';
import assert from 'node:assert/strict';
import { formatEmbedPreviewLines, formatEmbedFullscreenLines } from '../src/embedRenderers.ts';
import type { DecryptedEmbed } from '../src/client.ts';

function embed(data: Record<string, unknown>): DecryptedEmbed {
  return { id: 'trademark', embedId: '12345678-1234-4234-9234-123456789abc',
    type: 'app_skill_use', appId: 'business', skillId: 'search_trademarks',
    content: { query: 'Proposed name', results: [data] } } as DecryptedEmbed;
}

// contract-test: supporting surface=cli assertions=trademarks.coverage,trademarks.parity
it('saved zero matches retain checked and unsearched regions in terminal previews', () => {
  const output = formatEmbedPreviewLines(embed({ result_count: 0, matches: [], coverage: [
    { query: 'Proposed name', region: 'US', status: 'searched' },
    { query: 'Proposed name', region: 'DE', status: 'unsupported' },
  ] })).join('\n');
  assert.match(output, /Records: 0/);
  assert.match(output, /US: Checked/);
  assert.match(output, /DE: Not searched/);
  assert.match(output, /Preliminary/);
});

// contract-test: supporting surface=cli assertions=trademarks.coverage,trademarks.evidence,trademarks.parity
it('terminal fullscreen retains records, filters, failures and safe official links', async () => {
  const data = { result_count: 1, match: 'exact', status_filter: 'all', nice_classes: [9],
    matches: [{ mark: 'PUBLIC MARK', status: 'registered', region: 'US', owners: ['Public owner'],
      application_number: '12345678', goods_services: ['Software'], nice_classes: [9],
      source_url: 'https://tsdr.uspto.gov/#caseNumber=12345678' }],
    coverage: [{ query: 'PUBLIC MARK', region: 'US', status: 'partial', checked_at: '2026-10-12', more_results: true },
      { region: 'DE', status: 'unsupported', source_url: 'https://register.dpma.de/DPMAregister/marke/uebersicht' }],
    limitation: 'No matches do not establish legal availability.' };
  const output = (await formatEmbedFullscreenLines(embed(data), {} as never)).join('\n');
  assert.match(output, /PUBLIC MARK · registered · US/);
  assert.match(output, /Public owner/);
  assert.match(output, /Filters: exact · all · classes 9/);
  assert.match(output, /Partial · 2026-10-12/);
  assert.match(output, /More matching records/);
  assert.match(output, /https:\/\/tsdr.uspto.gov\/#caseNumber=12345678/);
  assert.match(output, /legal availability/);
  assert.match(output, /https:\/\/register.dpma.de/);
  data.matches[0].source_url = 'https://tsdr.uspto.gov.evil.example/';
  assert.doesNotMatch((await formatEmbedFullscreenLines(embed(data), {} as never)).join('\n'), /evil\.example/);
  const failed = (await formatEmbedFullscreenLines(embed({ matches: [], error: 'Provider unavailable',
    coverage: [{ region: 'US', status: 'error' }] }), {} as never)).join('\n');
  assert.match(failed, /Search failed/);
  assert.match(failed, /Error: Provider unavailable/);
});
