// frontend/packages/ui/src/services/codeRunService.ts
//
// Client helpers for Code Run executions.
// Starts the backend E2B sandbox run for a code embed and streams the Redis-backed
// execution events that power the terminal panel in CodeEmbedFullscreen.

import { getApiUrl } from '../config/api';
import { getWebSocketToken } from '../utils/cookies';
import { getSessionId } from '../utils/sessionId';

export interface CodeRunStartResponse {
  execution_id: string;
  status: string;
  target_filename: string;
  files: string[];
  credits_per_minute: number;
}

export interface CodeRunClientFile {
  embed_id: string;
  code: string;
  language: string;
  filename?: string;
  is_target?: boolean;
}

export interface CodeRunClientAttachment {
  embed_id: string;
  path: string;
  content_base64: string;
  mime_type?: string;
}

export interface CodeRunDependencyInstall {
  ecosystem: 'python' | 'npm';
  packages: string[];
}

export class CodeRunStartError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string
  ) {
    super(message);
    this.name = 'CodeRunStartError';
  }
}

export interface CodeRunEvent {
  kind: 'status' | 'stdout' | 'stderr';
  text: string;
  timestamp: number;
}

export interface CodeRunStatus {
  execution_id: string;
  status: 'queued' | 'preparing_sandbox' | 'uploading_files' | 'installing_dependencies' | 'running' | 'finished' | 'failed' | 'timeout' | 'cancelled';
  target_filename?: string;
  files?: string[];
  events?: CodeRunEvent[];
  exit_code?: number;
  duration_seconds?: number;
  charged_credits?: number;
  charged_minutes?: number;
  error?: string;
}

export type CodeRunStreamMessage =
  | { type: 'code_run_snapshot'; payload: CodeRunStatus }
  | { type: 'code_run_update'; payload: Partial<CodeRunStatus> }
  | { type: 'code_run_event'; payload: CodeRunEvent };

export async function startCodeRun(
  chatId: string,
  targetEmbedId: string,
  clientFiles: CodeRunClientFile[] = [],
  clientAttachments: CodeRunClientAttachment[] = [],
  selectedEmbedIds?: string[],
  dependencyInstalls: CodeRunDependencyInstall[] = []
): Promise<CodeRunStartResponse> {
  const response = await fetch(`${getApiUrl()}/v1/code/run`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      chat_id: chatId,
      target_embed_id: targetEmbedId,
      client_files: clientFiles,
      client_attachments: clientAttachments,
      ...(selectedEmbedIds ? { selected_embed_ids: selectedEmbedIds } : {}),
      ...(dependencyInstalls.length ? { dependency_installs: dependencyInstalls } : {}),
    }),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail = payload?.detail;
    if (detail && typeof detail === 'object') {
      throw new CodeRunStartError(
        detail.message || `Code run failed to start (${response.status})`,
        response.status,
        detail.code
      );
    }
    throw new CodeRunStartError(detail || `Code run failed to start (${response.status})`, response.status);
  }

  return response.json();
}

export async function getCodeRunStatus(executionId: string): Promise<CodeRunStatus> {
  const response = await fetch(`${getApiUrl()}/v1/code/run/${executionId}`, {
    credentials: 'include',
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail || `Code run status unavailable (${response.status})`);
  }

  return response.json();
}

export function getCodeRunStreamUrl(executionId: string): string {
  const wsUrl = `${getApiUrl().replace(/^http/, 'ws')}/v1/code/run/${encodeURIComponent(executionId)}/stream`;
  const params = new URLSearchParams();
  params.set('sessionId', getSessionId());

  const token = getWebSocketToken();
  if (token) {
    params.set('token', token);
  }

  return `${wsUrl}?${params.toString()}`;
}
