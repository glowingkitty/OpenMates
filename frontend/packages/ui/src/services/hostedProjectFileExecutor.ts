/** Encrypted hosted-file adapter shared by browser and CLI job executors. */
import { applyProjectFilePatch } from "../utils/projectFilePatch";
import { projectFileMutationDigest, type ProjectFileMutation } from "../utils/projectFileMutationProtocol";
import type { ProjectFileJob } from "./projectFileJobExecutor";
import { isProtectedProjectReadPath, normalizeProjectSearchRequest, matchesProjectSearchGlob, matchesProjectSearchQuery } from "../utils/projectSearchProtocol";

export interface HostedProjectFile {
  embedId: string;
  path: string;
}
export interface HostedProjectFileHead {
  embedKey: Uint8Array;
  content: Record<string, unknown>;
  revision: number;
  hasInitialHistory: boolean;
}
export interface HostedProjectFileAdapter {
  projectId: string;
  projectKey: Uint8Array;
  chatKey: Uint8Array;
  teamId?: string | null;
  listFiles: () => Promise<HostedProjectFile[]>;
  readHead: (embedId: string) => Promise<HostedProjectFileHead>;
  encrypt: (value: string, key: Uint8Array) => Promise<string>;
  wrap: (value: Uint8Array, key: Uint8Array) => Promise<string>;
  encodeContent: (content: Record<string, unknown>) => Promise<string>;
  commit: (payload: Record<string, unknown>) => Promise<Record<string, unknown>>;
  receipt: (embedId: string, job: ProjectFileJob, digest: string) => Promise<Record<string, unknown> | null>;
}

const bytes = (value: string) => new TextEncoder().encode(value);
function failure(code: string): never { throw Object.assign(new Error(code), { code }); }
function hasControlCharacters(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0;
    if (codePoint <= 0x1f || codePoint === 0x7f) return true;
  }
  return false;
}
export function normalizeHostedProjectPath(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > 4096 || value.includes("\\") || hasControlCharacters(value)
      || value.startsWith("/") || /^[a-z]:/i.test(value)) failure("invalid_path");
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) failure("invalid_path");
  if (parts.includes(".git") || isProtectedProjectReadPath(value)) failure("protected_path");
  return value;
}
export async function projectFileContentHash(content: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes(content))), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
export async function hostedProjectFileIdentity(projectKey: Uint8Array, path: string, kind: "embed" | "item"): Promise<string> {
  const normalized = normalizeHostedProjectPath(path);
  const key = await crypto.subtle.importKey("raw", new Uint8Array(projectKey).buffer, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const digest = new Uint8Array(await crypto.subtle.sign("HMAC", key, bytes(JSON.stringify(["openmates-hosted-file-v1", kind, normalized])))).slice(0, 16);
  // Reserved opaque UUIDv5-shaped identifiers; the HMAC also hides path guesses.
  digest[6] = (digest[6]! & 15) | 0x50;
  digest[8] = (digest[8]! & 63) | 0x80;
  const hex = Array.from(digest, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function textContent(head: HostedProjectFileHead): string {
  const content = head.content.code ?? head.content.content;
  if (typeof content !== "string" || bytes(content).length > 200 * 1024 || content.includes("\0")) failure("unsupported_file_content");
  return content;
}

export async function executeHostedProjectFileJob(adapter: HostedProjectFileAdapter, job: ProjectFileJob, mutation?: ProjectFileMutation): Promise<Record<string, unknown>> {
  const files = await adapter.listFiles();
  if (job.operation === "list") {
    const prefix = job.arguments.path === undefined || job.arguments.path === "." || job.arguments.path === "" ? "" : `${normalizeHostedProjectPath(job.arguments.path)}/`;
    const matched = files.filter((file) => file.path.startsWith(prefix));
    return { entries: matched.slice(0, 500).map((file) => ({ path: file.path, kind: "file" })), truncated: matched.length > 500 };
  }
  if (job.operation === "search") {
    // Hosted search is bounded before decryption; large Projects require narrower paths.
    const search = normalizeProjectSearchRequest(job.arguments);
    if (search.mode === "regex") failure("regex_search_unavailable");
    const prefix = search.path === "." ? "" : normalizeHostedProjectPath(search.path);
    let excluded = 0;
    const candidates: HostedProjectFile[] = [];
    for (const file of files) {
      let path: string;
      try { path = normalizeHostedProjectPath(file.path); }
      catch { excluded++; continue; }
      if ((!prefix || path === prefix || path.startsWith(`${prefix}/`)) && matchesProjectSearchGlob(path, search.glob)) {
        candidates.push({ ...file, path });
      }
    }
    const matches: Record<string, unknown>[] = [];
    const limit = search.maxResults;
    const byName = search.target === "files";
    let examined = 0;
    let omitted = 0;
    let incomplete = false;
    for (const file of candidates.slice(0, 100)) {
      examined++;
      if (byName) {
        if (matchesProjectSearchQuery(file.path, search)) {
          if (matches.length < limit) matches.push({ path: file.path });
          else omitted++;
        }
      }
      else {
        let content: string;
        try { content = textContent(await adapter.readHead(file.embedId)); }
        catch { excluded++; continue; }
        const lines = content.split("\n");
        if (lines.length > 4_000) incomplete = true;
        for (let index = 0; index < Math.min(lines.length, 4_000); index++) {
          if (!matchesProjectSearchQuery(lines[index]!, search)) continue;
          if (matches.length < limit) {
            matches.push({ path: file.path, line: index + 1, snippet: lines[index]!.slice(0, 500) });
          } else {
            omitted++;
          }
        }
      }
    }
    return {
      matches,
      excluded,
      omitted,
      truncated: omitted > 0 || incomplete || candidates.length > examined,
    };
  }
  const path = normalizeHostedProjectPath(job.arguments.path);
  const found = files.filter((file) => file.path === path);
  if (found.length > 1) failure("ambiguous_file_path");
  if (job.operation === "read_text") {
    if (!found[0]) failure("file_not_found");
    const head = await adapter.readHead(found[0].embedId);
    const content = textContent(head);
    return { path, content, expected_base: await projectFileContentHash(content), revision: head.revision, size_bytes: bytes(content).length, truncated: false };
  }
  if (!mutation) failure("invalid_file_mutation");
  if (path === ".openmates/permissions.yml") failure("protected_path");
  const creating = mutation.operation === "create_file";
  const embedId = found[0]?.embedId ?? await hostedProjectFileIdentity(adapter.projectKey, path, "embed");
  const digest = await projectFileMutationDigest(adapter.projectKey, adapter.projectId, job.chat_id, mutation);
  const receipt = await adapter.receipt(embedId, job, digest);
  if (receipt?.status === "committed") return { path, operation_id: job.operation_id, revision: receipt.current_revision, idempotent: true };
  if (creating && found[0]) failure("file_exists");
  if (!creating && !found[0]) failure("file_not_found");
  const current = creating ? null : await adapter.readHead(embedId);
  const original = current ? textContent(current) : "";
  if (current && await projectFileContentHash(original) !== mutation.expected_base) failure("stale_base");
  let content = mutation.content ?? "";
  if (!creating) {
    try { content = applyProjectFilePatch(original, mutation.patch!, path).content; }
    catch { failure("invalid_patch"); }
  }
  if (bytes(content).length > 200 * 1024 || content.includes("\0")) failure("file_too_large");
  const now = Math.floor(Date.now() / 1000);
  const embedKey = current?.embedKey ?? crypto.getRandomValues(new Uint8Array(32));
  const revision = (current?.revision ?? 0) + 1;
  const contentField = current && current.content.code === undefined && typeof current.content.content === "string" ? "content" : "code";
  const contentObject = { ...(current?.content ?? { type: "code", language: "text", filename: path }), [contentField]: content, version_number: revision, status: "finished", line_count: content.split("\n").length };
  const historyRows: Record<string, unknown>[] = [];
  if (creating || current?.revision === 1 && !current.hasInitialHistory) {
    historyRows.push({ version_number: 1, encrypted_snapshot: await adapter.encrypt(creating ? content : original, embedKey), created_at: now });
  }
  if (!creating) historyRows.push({ version_number: revision, encrypted_patch: await adapter.encrypt(mutation.patch!, embedKey), created_at: now });
  const payload: Record<string, unknown> = {
    operation_id: job.operation_id, embed_id: embedId, project_id: adapter.projectId, chat_id: job.chat_id,
    proposal_digest: digest, expected_revision: current?.revision ?? 0,
    ...(adapter.teamId ? { team_id: adapter.teamId } : {}),
    head: { encrypted_content: await adapter.encrypt(await adapter.encodeContent(contentObject), embedKey), encrypted_text_preview: await adapter.encrypt(`${path} (${content.split("\n").length} lines)`, embedKey), status: "finished", updated_at: now },
    history_rows: historyRows,
  };
  if (creating) payload.create = {
    project_item_id: await hostedProjectFileIdentity(adapter.projectKey, path, "item"),
    encrypted_type: await adapter.encrypt("code-code", embedKey),
    target_id_encrypted: await adapter.encrypt(embedId, adapter.projectKey),
    encrypted_display_name: await adapter.encrypt(path, adapter.projectKey),
    encrypted_metadata: await adapter.encrypt(JSON.stringify({ path, source: "hosted_project_file" }), adapter.projectKey),
    key_wrappers: [
      { key_type: "project", encrypted_embed_key: await adapter.wrap(embedKey, adapter.projectKey), created_at: now },
      { key_type: "chat", encrypted_embed_key: await adapter.wrap(embedKey, adapter.chatKey), created_at: now },
    ],
  };
  const result = await adapter.commit(payload);
  if (result.status === "conflict") failure("revision_conflict");
  if (result.status !== "committed") failure(typeof result.code === "string" ? result.code : "commit_rejected");
  return { path, operation_id: job.operation_id, embed_id: embedId, revision: result.current_revision, expected_base: await projectFileContentHash(content), applied_diff: mutation.patch ?? null, created: creating };
}
