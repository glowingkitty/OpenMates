// frontend/packages/ui/src/services/__tests__/pcbSchematicCompileService.test.ts
//
// Regression tests for Electronics PCB schematic compile API helpers. These
// protect the browser fullscreen flow from accidentally calling relative web
// app URLs for backend compile endpoints, which prevents prepare-files requests
// and artifact downloads from reaching the API domain in deployed environments.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../config/api', () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`
}));

import {
  getPcbSchematicArtifactDownloadUrl,
  getPcbSchematicCompileStatus,
  preparePcbSchematicFiles,
} from '../pcbSchematicCompileService';

describe('pcbSchematicCompileService', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('posts prepare-files requests to the API endpoint domain', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ compile_id: 'compile-1', status: 'running' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    );

    await expect(preparePcbSchematicFiles('embed/with spaces', true)).resolves.toMatchObject({
      compile_id: 'compile-1',
      status: 'running'
    });
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.test/v1/electronics/pcb-schematic/embeds/embed%2Fwith%20spaces/prepare-files',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ force: true }),
      }
    );
  });

  it('loads status and artifact URLs from the API endpoint domain', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ compile_id: 'compile-1', status: 'succeeded' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' }
      })
    );

    await expect(getPcbSchematicCompileStatus('compile/1')).resolves.toMatchObject({
      compile_id: 'compile-1',
      status: 'succeeded'
    });
    expect(fetchMock).toHaveBeenCalledWith(
      'https://api.test/v1/electronics/pcb-schematic/compile/compile%2F1',
      {
        method: 'GET',
        credentials: 'include'
      }
    );
    expect(getPcbSchematicArtifactDownloadUrl('compile/1', 'artifact 1')).toBe(
      'https://api.test/v1/electronics/pcb-schematic/compile/compile%2F1/artifacts/artifact%201'
    );
  });
});
