import { it } from 'node:test';
import assert from 'node:assert/strict';
import { formatEmbedPreviewLines, formatEmbedFullscreenLines } from '../src/embedRenderers.ts';
import type { DecryptedEmbed } from '../src/client.ts';

function embed(data: Record<string, unknown>): DecryptedEmbed {
  return { id: 'trademark', embedId: '12345678-1234-4234-9234-123456789abc',
    type: 'app_skill_use', appId: 'business', skillId: 'search_trademarks',
    content: { query: 'Proposed name', status: 'finished', results: [data] } } as DecryptedEmbed;
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
      source_url: 'https://www.wipo.int/branddb/en/' }],
    coverage: [{ query: 'PUBLIC MARK', region: 'US', status: 'partial', checked_at: '2026-10-12', more_results: true },
      { region: 'DE', status: 'unsupported', source_url: 'https://register.dpma.de/DPMAregister/marke/uebersicht' }],
    limitation: 'No matches do not establish legal availability.' };
  const output = (await formatEmbedFullscreenLines(embed(data), {} as never)).join('\n');
  assert.match(output, /PUBLIC MARK · registered · US/);
  assert.match(output, /Public owner/);
  assert.match(output, /Filters: exact · all · classes 9/);
  assert.match(output, /Partial · 2026-10-12/);
  assert.match(output, /More matching records/);
  assert.match(output, /https:\/\/www\.wipo\.int\/branddb\/en\//);
  assert.match(output, /legal availability/);
  assert.match(output, /https:\/\/register.dpma.de/);
  data.matches[0].source_url = 'https://evil.example/trademark';
  assert.doesNotMatch((await formatEmbedFullscreenLines(embed(data), {} as never)).join('\n'), /evil\.example/);
  const failed = (await formatEmbedFullscreenLines(embed({ status: 'error', matches: [], error: 'Provider unavailable',
    coverage: [{ region: 'US', status: 'error' }] }), {} as never)).join('\n');
  assert.match(failed, /Search failed/);
  assert.match(failed, /Error: Provider unavailable/);
  assert.doesNotMatch(failed.split('\n')[0], /Completed/);
});

// contract-test: supporting surface=cli assertions=investors.results
it('investor search embeds render names, tickets and skipped sources in the terminal', () => {
  const output = formatEmbedPreviewLines({ id: 'investors', embedId: '12345678-1234-4234-9234-123456789abd',
    type: 'app_skill_use', appId: 'business', skillId: 'search_investors',
    content: { query: 'climate', status: 'finished', result_count: 1, regions: ['DE'],
      investors: [{ name: 'Alex Sample', investor_type: 'angel' }, { city: 'Berlin' }],
      warnings: ['Example Directory was not searched: it does not cover US.'] } } as DecryptedEmbed).join('\n');
  assert.match(output, /Investors: 1 · DE/);
  assert.match(output, /Alex Sample · angel/);
  assert.match(output, /Skipped: Example Directory/);
});

// contract-test: supporting surface=cli assertions=ownership.results
it('company ownership embeds render owners with shares and lookup candidates in the terminal', async () => {
  const content = { query: 'Example Robotics GmbH', status: 'finished', result_count: 1,
    records: [{ subject: { name: 'Example Robotics GmbH', country: 'DE', legal_form: 'GmbH' },
      owners: [{ name: 'Jane Example', share_percent: 42 }, { name: 'Example Holding SAS', share_band: '25-50%' }],
      holdings: [{ name: 'Sample Labs Ltd', until: '2023-09-30' }], officers: [{ name: 'Sam Sample', role: 'Director' }] }],
    errors: [{ query: 'Example Holding', country: 'FR', code: 'ambiguous', candidates: [{ name: 'Example Holding SAS', register_id: '123456789' }] }] };
  const embedFor = (c: Record<string, unknown>) => ({ id: 'ownership', embedId: '12345678-1234-4234-9234-123456789abe',
    type: 'app_skill_use', appId: 'business', skillId: 'company_ownership', content: c } as DecryptedEmbed);
  const preview = formatEmbedPreviewLines(embedFor(content)).join('\n');
  assert.match(preview, /Example Robotics GmbH · DE · GmbH/);
  assert.match(preview, /Jane Example · 42%/);
  assert.match(preview, /Example Holding SAS · 25-50%/);
  const detail = (await formatEmbedFullscreenLines(embedFor(content), {} as never)).join('\n');
  assert.match(detail, /Holding: Sample Labs Ltd · ended 2023-09-30/);
  assert.match(detail, /Candidate: Example Holding SAS · 123456789/);
});
