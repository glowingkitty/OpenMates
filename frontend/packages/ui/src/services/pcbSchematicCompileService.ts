/**
 * frontend/packages/ui/src/services/pcbSchematicCompileService.ts
 *
 * Browser API helper for Electronics PCB schematic compile endpoints. The
 * backend owns E2B execution and artifact collection; this service only starts
 * prepare-files requests and fetches status records for fullscreen rendering.
 */

import { getApiEndpoint } from '../config/api';

export interface PcbSchematicArtifactEntry {
  id: string;
  type: string;
  path: string;
  name: string;
}

export interface PcbSchematicArtifactManifest {
  status?: string;
  atopile_version?: string;
  atopile_docs_version?: string;
  bundle?: {
    id: string;
    type: string;
    name: string;
  };
  files?: PcbSchematicArtifactEntry[];
}

export interface PcbSchematicCompileResponse {
  compile_id: string;
  status: string;
  artifact_manifest?: PcbSchematicArtifactManifest | null;
  error?: string | null;
  logs?: string;
}

async function parseResponse(response: Response): Promise<PcbSchematicCompileResponse> {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : 'PCB schematic compile request failed';
    throw new Error(detail);
  }
  return data as PcbSchematicCompileResponse;
}

export async function preparePcbSchematicFiles(embedId: string, force = false): Promise<PcbSchematicCompileResponse> {
  const response = await fetch(getApiEndpoint(`/v1/electronics/pcb-schematic/embeds/${encodeURIComponent(embedId)}/prepare-files`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ force }),
  });
  return parseResponse(response);
}

export async function getPcbSchematicCompileStatus(compileId: string): Promise<PcbSchematicCompileResponse> {
  const response = await fetch(getApiEndpoint(`/v1/electronics/pcb-schematic/compile/${encodeURIComponent(compileId)}`), {
    method: 'GET',
    credentials: 'include',
  });
  return parseResponse(response);
}

export function getPcbSchematicArtifactDownloadUrl(compileId: string, artifactId: string): string {
  return getApiEndpoint(`/v1/electronics/pcb-schematic/compile/${encodeURIComponent(compileId)}/artifacts/${encodeURIComponent(artifactId)}`);
}
