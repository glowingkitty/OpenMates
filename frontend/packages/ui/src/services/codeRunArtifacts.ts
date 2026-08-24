// frontend/packages/ui/src/services/codeRunArtifacts.ts
//
// Pure helpers for Code Run generated artifact metadata.
// Keep signed download URLs available only in encrypted client payloads, while
// inference payloads receive path/size/status metadata without tokens or storage keys.
// Tests: frontend/packages/ui/src/services/__tests__/codeRunService.test.ts.

import type {
  CodeRunArtifact,
  CodeRunArtifactVersion,
  CodeRunOutput,
  CodeRunOutputPayload,
  CodeRunSkippedArtifact,
} from '../types/chat';
import { v5 as uuidv5 } from 'uuid';

export interface CodeRunArtifactSanitizeOptions {
  includeDownloadUrl?: boolean;
  includeNativeRenderPayload?: boolean;
  capturedAt?: number;
}

export interface CodeRunArtifactChildRoute {
  appId: string;
  frontendType: string;
  renderer: 'registered_native' | 'generic_file';
}

const CODE_RUN_ARTIFACT_CHILD_NAMESPACE = '7d9d682a-f21d-4be4-9fd2-273bd5bf26a2';
const NATIVE_IMAGE_MIME_TYPES = new Set(['image/png', 'image/webp']);

const ARTIFACT_SENSITIVE_FIELDS = [
  'aes_key',
  'aes_nonce',
  'bytes',
  'content_base64',
  's3_key',
  'sandbox_id',
  'token',
  'vault_wrapped_aes_key',
] as const;

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function cloneJsonRecord(value: Record<string, unknown>): Record<string, unknown> | undefined {
  try {
    const clone = JSON.parse(JSON.stringify(value)) as unknown;
    return clone && typeof clone === 'object' && !Array.isArray(clone)
      ? clone as Record<string, unknown>
      : undefined;
  } catch {
    return undefined;
  }
}

function normalizeArtifactVersion(
  raw: unknown,
  options: CodeRunArtifactSanitizeOptions,
): CodeRunArtifactVersion | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, unknown>;
  for (const field of ARTIFACT_SENSITIVE_FIELDS) {
    if (field in item) return null;
  }
  const path = stringValue(item.path) || stringValue(item.normalized_path);
  if (!path) return null;
  const normalizedPath = stringValue(item.normalized_path) || path;
  const version: CodeRunArtifactVersion = {
    path,
    normalized_path: normalizedPath,
  };
  const mimeType = stringValue(item.mime_type);
  const kind = stringValue(item.kind);
  const status = stringValue(item.status);
  const assetId = stringValue(item.asset_id);
  const variant = stringValue(item.variant);
  const sizeBytes = numberValue(item.size_bytes);
  const downloadExpiresAt = numberValue(item.download_expires_at);
  const capturedAt = numberValue(item.captured_at) ?? options.capturedAt;
  if (mimeType) version.mime_type = mimeType;
  if (kind) version.kind = kind;
  if (sizeBytes !== undefined) version.size_bytes = sizeBytes;
  if (status) version.status = status;
  if (assetId) version.asset_id = assetId;
  if (variant) version.variant = variant;
  if (downloadExpiresAt !== undefined) version.download_expires_at = downloadExpiresAt;
  if (capturedAt !== undefined) version.captured_at = capturedAt;
  const downloadUrl = stringValue(item.download_url);
  if (options.includeDownloadUrl !== false && downloadUrl) version.download_url = downloadUrl;
  const nativeRenderPayload = normalizeNativeRenderPayload(item.native_render_payload);
  if (options.includeNativeRenderPayload && nativeRenderPayload) {
    version.native_render_payload = nativeRenderPayload;
  }
  return version;
}

function normalizeNativeRenderPayload(value: unknown) {
  if (!value || typeof value !== 'object') return undefined;
  const payload = value as Record<string, unknown>;
  if (
    typeof payload.app_id !== 'string'
    || typeof payload.frontend_type !== 'string'
    || !payload.content
    || typeof payload.content !== 'object'
  ) return undefined;
  const content = cloneJsonRecord(payload.content as Record<string, unknown>);
  if (!content) return undefined;
  return {
    app_id: payload.app_id,
    frontend_type: payload.frontend_type,
    content,
  };
}

export function codeRunArtifactChildId(parentEmbedId: string, normalizedPath: string): string {
  return uuidv5(`${parentEmbedId}:${normalizedPath.trim().toLowerCase()}`, CODE_RUN_ARTIFACT_CHILD_NAMESPACE);
}

export function routeCodeRunArtifactChild(artifact: CodeRunArtifact): CodeRunArtifactChildRoute {
  const native = artifact.native_render_payload;
  if (
    native?.app_id === 'images'
    && native.frontend_type === 'image'
    && NATIVE_IMAGE_MIME_TYPES.has(artifact.mime_type || '')
    && isCompatibleNativeImagePayload(native.content)
  ) {
    return { appId: 'images', frontendType: 'image', renderer: 'registered_native' };
  }
  return { appId: 'file', frontendType: 'file-file', renderer: 'generic_file' };
}

function isCompatibleNativeImagePayload(content: Record<string, unknown>): boolean {
  const files = content.files;
  if (!files || typeof files !== 'object') return false;
  const variants = files as Record<string, unknown>;
  const renderVariant = variants.full || variants.preview;
  return Boolean(
    typeof content.s3_base_url === 'string'
    && typeof content.aes_key === 'string'
    && renderVariant
    && typeof renderVariant === 'object'
    && typeof (renderVariant as Record<string, unknown>).s3_key === 'string'
  );
}

export function sanitizeCodeRunArtifacts(
  value: unknown,
  options: CodeRunArtifactSanitizeOptions = {},
): CodeRunArtifact[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw): CodeRunArtifact[] => {
    const version = normalizeArtifactVersion(raw, options);
    if (!version) return [];
    const rawVersions = raw && typeof raw === 'object' ? (raw as Record<string, unknown>).versions : undefined;
    const versions = Array.isArray(rawVersions)
      ? dedupeArtifactVersions(rawVersions.flatMap((candidate) => {
        const normalized = normalizeArtifactVersion(candidate, options);
        return normalized ? [normalized] : [];
      }))
      : [];
    return [{ ...version, ...(versions.length ? { versions } : {}) }];
  });
}

export function sanitizeCodeRunSkippedArtifacts(value: unknown): CodeRunSkippedArtifact[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw): CodeRunSkippedArtifact[] => {
    if (!raw || typeof raw !== 'object') return [];
    const item = raw as Record<string, unknown>;
    const path = stringValue(item.path);
    const reason = stringValue(item.reason);
    return path && reason ? [{ path, reason }] : [];
  });
}

export function mergeCodeRunArtifactHistory(
  previousArtifacts: CodeRunArtifact[] | undefined,
  latestArtifacts: CodeRunArtifact[] | undefined,
  capturedAt: number,
): CodeRunArtifact[] {
  const previousByPath = new Map<string, CodeRunArtifact>();
  for (const artifact of sanitizeCodeRunArtifacts(previousArtifacts, {
    includeDownloadUrl: true,
    includeNativeRenderPayload: true,
  })) {
    previousByPath.set(codeRunArtifactPathKey(artifact), artifact);
  }
  return sanitizeCodeRunArtifacts(latestArtifacts, {
    includeDownloadUrl: true,
    includeNativeRenderPayload: true,
    capturedAt,
  }).map((artifact) => {
    const previous = previousByPath.get(codeRunArtifactPathKey(artifact));
    if (!previous) return artifact;
    const versions = dedupeArtifactVersions([
      artifactVersionFromArtifact(previous),
      ...(previous.versions ?? []),
    ].filter((version): version is CodeRunArtifactVersion => Boolean(version)));
    return { ...artifact, ...(versions.length ? { versions } : {}) };
  });
}

export function buildCodeRunOutputPayload(
  output: CodeRunOutput,
  options: CodeRunArtifactSanitizeOptions = {},
): CodeRunOutputPayload {
  return {
    output: output.output,
    status: output.status,
    files: output.files?.map((file) => String(file)),
    events: output.events?.map(({ kind, text, timestamp }) => ({
      kind: String(kind),
      text: String(text),
      timestamp: Number(timestamp),
    })),
    artifacts: sanitizeCodeRunArtifacts(output.artifacts, options),
    skipped_artifacts: sanitizeCodeRunSkippedArtifacts(output.skipped_artifacts),
    saved_at: output.saved_at,
    created_at: output.created_at,
    updated_at: output.updated_at,
  };
}

export function isCodeRunArtifactDownloadAvailable(artifact: CodeRunArtifact | CodeRunArtifactVersion, nowSeconds = Date.now() / 1000): boolean {
  return Boolean(artifact.download_url && (!artifact.download_expires_at || artifact.download_expires_at > nowSeconds));
}

export function formatCodeRunArtifactSize(sizeBytes: number | undefined): string {
  if (sizeBytes === undefined) return '';
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

function codeRunArtifactPathKey(artifact: CodeRunArtifact | CodeRunArtifactVersion): string {
  return artifact.normalized_path || artifact.path;
}

function artifactVersionFromArtifact(artifact: CodeRunArtifact): CodeRunArtifactVersion | null {
  return normalizeArtifactVersion(artifact, { includeDownloadUrl: true });
}

function artifactVersionIdentity(version: CodeRunArtifactVersion): string {
  return [
    version.asset_id || '',
    version.variant || '',
    version.normalized_path || version.path,
    String(version.captured_at ?? ''),
    String(version.download_expires_at ?? ''),
    String(version.size_bytes ?? ''),
    version.status || '',
  ].join('|');
}

function dedupeArtifactVersions(versions: CodeRunArtifactVersion[]): CodeRunArtifactVersion[] {
  const seen = new Set<string>();
  const deduped: CodeRunArtifactVersion[] = [];
  for (const version of versions) {
    const key = artifactVersionIdentity(version);
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(version);
  }
  return deduped.sort((a, b) => (b.captured_at ?? 0) - (a.captured_at ?? 0));
}
