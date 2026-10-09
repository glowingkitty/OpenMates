import { webcrypto } from 'node:crypto';
import { describe, expect, it, vi } from 'vitest';
import { connectedReferenceSource, hostedReferenceContentHash, referenceRevisionStatus } from '../projectReferenceRevision';
import { projectFileReferences } from '../projectReferenceData';

describe('Project reference revision', () => {
  // contract-test: supporting surface=gui.web assertions=projects.files.search-result-lifecycle
  it('compares valid source fingerprints and treats truncated or absent fingerprints as unknown', () => {
    expect(referenceRevisionStatus('a'.repeat(64), 'a'.repeat(64))).toBe('same');
    expect(referenceRevisionStatus('a'.repeat(64), 'b'.repeat(64))).toBe('changed');
    expect(referenceRevisionStatus('a'.repeat(64), null)).toBe('unknown');
    expect(referenceRevisionStatus('invalid', 'b'.repeat(64))).toBe('unknown');
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.search-result-lifecycle
  it('hashes the original hosted text using the same SHA-256 bytes as file reads', async () => {
    vi.stubGlobal('crypto', webcrypto);
    expect(await hostedReferenceContentHash({ code: 'hello' })).toBe(
      '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824',
    );
    expect(await hostedReferenceContentHash({ code: '\0secret' })).toBeNull();
    expect(await hostedReferenceContentHash({ code: 'x'.repeat(200 * 1024 + 1) })).toBeNull();
    vi.unstubAllGlobals();
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.search-result-lifecycle
  it('rechecks source availability after a previously opened file', async () => {
    let status = 'connected';
    let checks = 0;
    const load = async () => {
      checks++;
      return [{ source_id: 'source', status }];
    };
    expect(await connectedReferenceSource('source', load)).toEqual({ source_id: 'source', status: 'connected' });
    status = 'offline';
    expect(await connectedReferenceSource('source', load)).toBeNull();
    expect(checks).toBe(2);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.search-consistent,projects.files.search-result-lifecycle
  it('accepts only a valid stored fingerprint without carrying source text', () => {
    const refs = projectFileReferences({ results: [{ project_id: 'project', project_name: 'Project',
      source_id: 'source', path: 'README.md', expected_base: 'f'.repeat(64), content: 'PRIVATE_TEXT' }] });
    expect(refs).toEqual([{ project_id: 'project', project_name: 'Project', source_id: 'source',
      path: 'README.md', expected_base: 'f'.repeat(64) }]);
    expect(JSON.stringify(refs)).not.toContain('PRIVATE_TEXT');
    expect(projectFileReferences({ results: [{ ...refs[0], expected_base: 'not-a-hash' }] })[0]).not.toHaveProperty('expected_base');
  });
});
