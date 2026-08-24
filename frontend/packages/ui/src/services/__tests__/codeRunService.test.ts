/**
 * Code Run artifact metadata helper tests.
 *
 * Purpose: verify encrypted sidecar metadata keeps artifact history while
 * inference payloads never receive signed URLs or storage internals.
 * Contract: feature.app-skill.code-run@1.
 * Run: python3 scripts/tests.py run --suite vitest
 */

import { describe, expect, it } from 'vitest';

import {
  buildCodeRunOutputPayload,
  mergeCodeRunArtifactHistory,
  sanitizeCodeRunArtifacts,
  sanitizeCodeRunSkippedArtifacts,
} from '../codeRunArtifacts';

describe('Code Run artifact metadata helpers', () => {
  // contract-test: direct surface=gui.web assertions=code-run.artifacts.chat-bound-versioned,code-run.output.chat-bound-encrypted
  it('keeps signed download URLs only in encrypted storage payloads', () => {
    const output = {
      id: 'out-1',
      chat_id: 'chat-1',
      embed_id: 'embed-1',
      output: 'ok',
      artifacts: [{
        path: 'outputs/summary.csv',
        normalized_path: 'outputs/summary.csv',
        mime_type: 'text/csv',
        size_bytes: 12,
        status: 'captured',
        asset_id: 'embed-1',
        variant: 'summary-csv-abc',
        download_url: 'https://api.dev.openmates.org/v1/generated-assets/embed-1/files/summary-csv-abc/download?token=signed',
      }, {
        path: 'outputs/secret.txt',
        normalized_path: 'outputs/secret.txt',
        mime_type: 'text/plain',
        size_bytes: 4,
        s3_key: 'must-not-survive',
      }],
      skipped_artifacts: [{ path: 'outputs/.env', reason: 'hidden_path' }],
      saved_at: 1,
      created_at: 1,
    };

    const encryptedPayload = buildCodeRunOutputPayload(output, { includeDownloadUrl: true });
    const inferencePayload = buildCodeRunOutputPayload(output, { includeDownloadUrl: false });

    expect(encryptedPayload.artifacts).toHaveLength(1);
    expect(encryptedPayload.artifacts?.[0].download_url).toContain('token=signed');
    expect(encryptedPayload.artifacts?.[0]).not.toHaveProperty('s3_key');
    expect(inferencePayload.artifacts).toHaveLength(1);
    expect(inferencePayload.artifacts?.[0]).not.toHaveProperty('download_url');
    expect(inferencePayload.artifacts?.[0]).not.toHaveProperty('s3_key');
    expect(encryptedPayload.skipped_artifacts).toEqual([{ path: 'outputs/.env', reason: 'hidden_path' }]);
  });

  // contract-test: supporting surface=gui.web assertions=code-run.artifacts.chat-bound-versioned
  it('dedupes current artifacts by output path and preserves prior versions', () => {
    const previous = sanitizeCodeRunArtifacts([{
      path: 'outputs/chart.png',
      normalized_path: 'outputs/chart.png',
      mime_type: 'image/png',
      size_bytes: 100,
      status: 'captured',
      asset_id: 'embed-1',
      variant: 'chart-png-old',
      captured_at: 10,
      download_url: 'https://example.test/old',
    }], { includeDownloadUrl: true });
    const latest = sanitizeCodeRunArtifacts([{
      path: 'outputs/chart.png',
      normalized_path: 'outputs/chart.png',
      mime_type: 'image/png',
      size_bytes: 120,
      status: 'captured',
      asset_id: 'embed-1',
      variant: 'chart-png-new',
      download_url: 'https://example.test/new',
    }], { includeDownloadUrl: true });

    const merged = mergeCodeRunArtifactHistory(previous, latest, 20);

    expect(merged).toHaveLength(1);
    expect(merged[0].variant).toBe('chart-png-new');
    expect(merged[0].captured_at).toBe(20);
    expect(merged[0].versions).toEqual([{
      path: 'outputs/chart.png',
      normalized_path: 'outputs/chart.png',
      mime_type: 'image/png',
      size_bytes: 100,
      status: 'captured',
      asset_id: 'embed-1',
      variant: 'chart-png-old',
      download_url: 'https://example.test/old',
      captured_at: 10,
    }]);
  });

  // contract-test: supporting surface=gui.web assertions=code-run.artifacts.explicit-only
  it('normalizes skipped artifact reasons', () => {
    expect(sanitizeCodeRunSkippedArtifacts([
      { path: 'outputs/.env', reason: 'hidden_path', details: 'secret' },
      { path: '', reason: 'empty' },
      { path: 'outputs/cache.bin' },
    ])).toEqual([{ path: 'outputs/.env', reason: 'hidden_path' }]);
  });
});
