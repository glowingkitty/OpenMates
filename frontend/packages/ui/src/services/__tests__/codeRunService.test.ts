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
  codeRunArtifactChildId,
  mergeCodeRunArtifactHistory,
  routeCodeRunArtifactChild,
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

  // contract-test: supporting surface=gui.web assertions=code-run.artifacts.child-renderer-routing,code-run.artifacts.parent-child-navigation
  it('uses stable path-based child ids and routes only compatible native payloads', () => {
    const firstId = codeRunArtifactChildId('parent-1', 'outputs/chart.png');
    const repeatedId = codeRunArtifactChildId('parent-1', 'outputs/chart.png');
    const secondPathId = codeRunArtifactChildId('parent-1', 'outputs/model.bin');

    expect(firstId).toBe(repeatedId);
    expect(firstId).not.toBe(secondPathId);

    expect(routeCodeRunArtifactChild({
      path: 'outputs/chart.png',
      normalized_path: 'outputs/chart.png',
      mime_type: 'image/png',
      native_render_payload: {
        app_id: 'images',
        frontend_type: 'image',
        content: {
          filename: 'chart.png',
          s3_base_url: 'https://storage.example.test',
          files: { full: { s3_key: 'encrypted-chart', encryption: 'aes-gcm-nonce-prefixed-v1' } },
          aes_key: 'client-visible-inside-encrypted-sidecar',
          aes_nonce: '',
        },
      },
    })).toMatchObject({ appId: 'images', frontendType: 'image', renderer: 'registered_native' });

    expect(routeCodeRunArtifactChild({
      path: 'outputs/model.bin',
      normalized_path: 'outputs/model.bin',
      mime_type: 'application/octet-stream',
    })).toEqual({ appId: 'file', frontendType: 'file-file', renderer: 'generic_file' });

    expect(routeCodeRunArtifactChild({
      path: 'outputs/report.docx',
      normalized_path: 'outputs/report.docx',
      mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      native_render_payload: {
        app_id: 'docs',
        frontend_type: 'docs-doc',
        content: { filename: 'report.docx' },
      },
    })).toEqual({ appId: 'file', frontendType: 'file-file', renderer: 'generic_file' });
  });

  // contract-test: supporting surface=gui.web assertions=code-run.output.chat-bound-encrypted,code-run.artifacts.child-renderer-routing
  it('keeps native render material only in the encrypted sidecar payload', () => {
    const output = {
      id: 'out-native',
      chat_id: 'chat-1',
      embed_id: 'embed-1',
      output: 'ok',
      artifacts: [{
        path: 'outputs/chart.png',
        normalized_path: 'outputs/chart.png',
        mime_type: 'image/png',
        size_bytes: 12,
        native_render_payload: {
          app_id: 'images',
          frontend_type: 'image',
          content: {
            files: { full: { s3_key: 'private-key' } },
            aes_key: 'secret-aes-key',
          },
        },
      }],
      saved_at: 1,
      created_at: 1,
    };

    const encryptedPayload = buildCodeRunOutputPayload(output, { includeDownloadUrl: true, includeNativeRenderPayload: true });
    const inferencePayload = buildCodeRunOutputPayload(output, { includeDownloadUrl: false, includeNativeRenderPayload: false });

    expect(encryptedPayload.artifacts?.[0].native_render_payload).toBeDefined();
    expect(inferencePayload.artifacts?.[0].native_render_payload).toBeUndefined();
    expect(JSON.stringify(inferencePayload)).not.toContain('secret-aes-key');
    expect(JSON.stringify(inferencePayload)).not.toContain('private-key');
  });

  // contract-test: supporting surface=gui.web assertions=code-run.artifacts.child-renderer-routing
  it('normalizes JSON-compatible native payload proxies', () => {
    const content = new Proxy({
      filename: 'chart.png',
      s3_base_url: 'https://storage.example.test',
      files: { full: { s3_key: 'encrypted-chart', encryption: 'aes-gcm-nonce-prefixed-v1' } },
      aes_key: 'client-side-key',
    }, {});

    const artifacts = sanitizeCodeRunArtifacts([{
      path: 'outputs/chart.png',
      mime_type: 'image/png',
      native_render_payload: {
        app_id: 'images',
        frontend_type: 'image',
        content,
      },
    }], { includeNativeRenderPayload: true });

    expect(artifacts[0].native_render_payload?.content).toEqual({
      filename: 'chart.png',
      s3_base_url: 'https://storage.example.test',
      files: { full: { s3_key: 'encrypted-chart', encryption: 'aes-gcm-nonce-prefixed-v1' } },
      aes_key: 'client-side-key',
    });
    expect(routeCodeRunArtifactChild(artifacts[0])).toMatchObject({
      appId: 'images',
      frontendType: 'image',
      renderer: 'registered_native',
    });
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
