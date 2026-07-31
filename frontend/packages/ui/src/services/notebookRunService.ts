// frontend/packages/ui/src/services/notebookRunService.ts
//
// Client helpers for first-party notebook execution. The backend validates the
// notebook and delegates execution to the existing Code Run/E2B lifecycle, while
// outputs are persisted separately through notebook-run sidecars.

import { getApiUrl } from '../config/api';
import { getWebSocketToken } from '../utils/cookies';
import { getSessionId } from '../utils/sessionId';
import type { CodeRunEvent, CodeRunStatus, CodeRunStreamMessage, CodeRunDependencyInstall } from './codeRunService';

export class NotebookRunStartError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string
  ) {
    super(message);
    this.name = 'NotebookRunStartError';
  }
}

export interface NotebookRunStartResponse {
  execution_id: string;
  status: string;
  notebook_embed_id: string;
  selected_cell_indices: number[];
  source_version?: string | null;
  credits_per_minute: number;
  stream_path: string;
  status_path: string;
}

export interface NotebookRunExtractedOutput {
  type: 'notebook_run_output';
  status?: string;
  selected_cell_indices?: number[];
  cell_outputs: Array<{
    cell_index: number;
    execution_count?: number | null;
    outputs: unknown[];
  }>;
  error?: string;
}

const NOTEBOOK_OUTPUT_START = 'OPENMATES_NOTEBOOK_OUTPUT_JSON_START';
const NOTEBOOK_OUTPUT_END = 'OPENMATES_NOTEBOOK_OUTPUT_JSON_END';

export async function startNotebookRun(
  chatId: string,
  notebookEmbedId: string,
  clientNotebook: Record<string, unknown>,
  options: {
    runScope?: 'all' | 'cells';
    cellIndices?: number[];
    sourceVersion?: string | null;
    dependencyInstalls?: CodeRunDependencyInstall[];
    enableInternet?: boolean;
  } = {},
): Promise<NotebookRunStartResponse> {
  const response = await fetch(`${getApiUrl()}/v1/code/notebooks/run`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: chatId,
      notebook_embed_id: notebookEmbedId,
      run_scope: options.runScope ?? 'all',
      ...(options.cellIndices?.length ? { cell_indices: options.cellIndices } : {}),
      enable_internet: options.enableInternet ?? true,
      dependency_installs: options.dependencyInstalls ?? [],
      client_notebook: clientNotebook,
      source_version: options.sourceVersion ?? undefined,
    }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    if (detail && typeof detail === 'object') {
      throw new NotebookRunStartError(
        detail.message || `Notebook run failed to start (${response.status})`,
        response.status,
        detail.code
      );
    }
    throw new NotebookRunStartError(detail || `Notebook run failed to start (${response.status})`, response.status);
  }

  return response.json();
}

export async function getNotebookRunStatus(executionId: string): Promise<CodeRunStatus> {
  const response = await fetch(`${getApiUrl()}/v1/code/notebooks/run/${encodeURIComponent(executionId)}/status`, {
    credentials: 'include',
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || `Notebook run status unavailable (${response.status})`);
  }

  return response.json();
}

export function getNotebookRunStreamUrl(executionId: string): string {
  const wsUrl = `${getApiUrl().replace(/^http/, 'ws')}/v1/code/notebooks/run/${encodeURIComponent(executionId)}/stream`;
  const params = new URLSearchParams();
  params.set('sessionId', getSessionId());

  const token = getWebSocketToken();
  if (token) {
    params.set('token', token);
  }

  return `${wsUrl}?${params.toString()}`;
}

export function extractNotebookRunOutput(events: CodeRunEvent[]): NotebookRunExtractedOutput | null {
  const stdout = events
    .filter((event) => event.kind === 'stdout')
    .map((event) => event.text)
    .join('');
  const startIndex = stdout.lastIndexOf(NOTEBOOK_OUTPUT_START);
  const endIndex = stdout.lastIndexOf(NOTEBOOK_OUTPUT_END);
  if (startIndex < 0 || endIndex < 0 || endIndex <= startIndex) return null;

  const jsonText = stdout.slice(startIndex + NOTEBOOK_OUTPUT_START.length, endIndex).trim();
  try {
    const parsed = JSON.parse(jsonText) as NotebookRunExtractedOutput;
    if (parsed?.type !== 'notebook_run_output' || !Array.isArray(parsed.cell_outputs)) return null;
    return parsed;
  } catch (error) {
    console.warn('[notebookRunService] Failed to parse notebook run output JSON', error);
    return null;
  }
}

export type NotebookRunStreamMessage = CodeRunStreamMessage;
