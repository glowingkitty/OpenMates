// frontend/packages/ui/src/services/projectState/projectFilePolicy.ts
// spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
// Pure hosted Project file job decisions used by hostedProjectFileExecutor.ts:
// metadata path normalization and the list / search request shaping that runs
// after the path policy has marked each file hidden (private or Git-ignored).
// File content, the Git-ignore matcher (`ignore` package), YAML parsing and the
// project-key HMAC identity stay in TypeScript. Each op has a Rust twin in
// packages/openmates-rust/src/web_projects/hosted_files.rs, answered by the Worker
// `chatState` op `projectDecide` when a web adapter supplies `decidePolicy`
// (VITE_OPENMATES_RUST_CORE=1). Refusals are data ({fileError}/{searchError});
// settleProjectFileDecision rethrows them as the original error types.
// This module is shared with the npm CLI (node --experimental-strip-types), so it
// never reads import.meta.env.
import {
  isProtectedProjectReadPath,
  matchesProjectSearchGlob,
  normalizeProjectSearchRequest,
  ProjectSearchProtocolError,
  type ProjectSearchRequest,
} from "../../utils/projectSearchProtocol";

/** A refusal answered as data: a coded executor failure or a search protocol error. */
export type ProjectFileRefusal = { fileError: string } | { searchError: string };

/** One listed file as the list/search decisions see it (no content, no keys). */
export interface ProjectFilePolicyFile {
  path: string;
  /** Private (built-in, authoritative or file-local) or Git-ignored under the loaded policy. */
  hidden: boolean;
}

export type HostedPathResult = { path: string } | { code: string };

export interface HostedSearchPlan {
  search: ProjectSearchRequest;
  /** Indices into `files` of the search candidates, in listing order. */
  candidates: number[];
  excluded: number;
}

function failure(code: string): never { throw Object.assign(new Error(code), { code }); }
function hasControlCharacters(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0;
    if (codePoint <= 0x1f || codePoint === 0x7f) return true;
  }
  return false;
}

/** Validates a hosted Project file path (`invalid_path` / `protected_path`). */
export function normalizeHostedProjectPath(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > 4096 || value.includes("\\") || hasControlCharacters(value)
      || value.startsWith("/") || /^[a-z]:/i.test(value)) failure("invalid_path");
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) failure("invalid_path");
  if (parts.includes(".git") || isProtectedProjectReadPath(value)) failure("protected_path");
  return value;
}

function refusal(error: unknown): ProjectFileRefusal {
  if (error instanceof ProjectSearchProtocolError) return { searchError: error.code };
  const code = (error as { code?: unknown } | null)?.code;
  if (typeof code === "string") return { fileError: code };
  throw error;
}

function hostedPaths(input: { paths: unknown[] }): { results: HostedPathResult[] } {
  return {
    results: input.paths.map((value) => {
      try { return { path: normalizeHostedProjectPath(value) }; }
      catch (error) { return { code: (error as { code: string }).code }; }
    }),
  };
}

function hostedList(input: { path?: unknown; files: ProjectFilePolicyFile[] }):
  { entries: { path: string; kind: "file" }[]; truncated: boolean } | ProjectFileRefusal {
  let prefix: string;
  try {
    prefix = input.path === undefined || input.path === "." || input.path === "" ? "" : `${normalizeHostedProjectPath(input.path)}/`;
  } catch (error) {
    return refusal(error);
  }
  const matched = input.files.filter((file) => file.path.startsWith(prefix) && !file.hidden);
  return { entries: matched.slice(0, 500).map((file) => ({ path: file.path, kind: "file" as const })), truncated: matched.length > 500 };
}

function hostedSearchPlan(input: { args: Record<string, unknown>; files: ProjectFilePolicyFile[]; excluded: number }):
  HostedSearchPlan | ProjectFileRefusal {
  let search: ProjectSearchRequest;
  let prefix: string;
  try {
    // Hosted search is bounded before decryption; large Projects require narrower paths.
    search = normalizeProjectSearchRequest(input.args);
    if (search.mode === "regex") failure("regex_search_unavailable");
    prefix = search.path === "." ? "" : normalizeHostedProjectPath(search.path);
  } catch (error) {
    return refusal(error);
  }
  let excluded = input.excluded;
  const candidates: number[] = [];
  input.files.forEach((file, index) => {
    const path = file.path;
    if (file.hidden) { excluded++; return; }
    if ((!prefix || path === prefix || path.startsWith(`${prefix}/`)) && matchesProjectSearchGlob(path, search.glob)) {
      candidates.push(index);
    }
  });
  return { search, candidates, excluded };
}

/** Every hosted file decision as its TypeScript rule; keys are the Rust op names. */
export const PROJECT_FILE_POLICY = {
  projectHostedPaths: hostedPaths,
  projectHostedList: hostedList,
  projectHostedSearchPlan: hostedSearchPlan,
};

export type ProjectFileOpName = keyof typeof PROJECT_FILE_POLICY;
type FileRule<K extends ProjectFileOpName> = (typeof PROJECT_FILE_POLICY)[K];
export type ProjectFileInput<K extends ProjectFileOpName> = Parameters<FileRule<K>>[0];
export type ProjectFileOutput<K extends ProjectFileOpName> = ReturnType<FileRule<K>>;

/** Answers a hosted file decision off the page (the flag-on Worker hop). */
export type ProjectFileDecider = <K extends ProjectFileOpName>(op: K, input: ProjectFileInput<K>) => Promise<ProjectFileOutput<K>>;

/** The TypeScript rule run synchronously (flag-off path). */
export function projectFileRule<K extends ProjectFileOpName>(op: K, input: ProjectFileInput<K>): ProjectFileOutput<K> {
  return (PROJECT_FILE_POLICY[op] as (value: ProjectFileInput<K>) => ProjectFileOutput<K>)(input);
}

/** Rethrows a data refusal as the error the executor always threw; passes a decision through. */
export function settleProjectFileDecision<T extends object>(answer: T | ProjectFileRefusal): T {
  if ("searchError" in answer) throw new ProjectSearchProtocolError((answer as { searchError: string }).searchError);
  if ("fileError" in answer) failure((answer as { fileError: string }).fileError);
  return answer as T;
}

/** Path of one `projectHostedPaths` result, or the coded failure it carries. */
export function settleHostedPath(result: HostedPathResult | undefined): string {
  if (result === undefined) failure("protected_path");
  if ("code" in result) failure(result.code);
  return result.path;
}

/** Runs a TS rule on a JSON-shaped input and answers the JSON document the Rust op answers. */
export function runProjectFilePolicy(op: ProjectFileOpName, input: unknown): unknown {
  const rule = PROJECT_FILE_POLICY[op] as (value: unknown) => unknown;
  return JSON.parse(JSON.stringify(rule(input)) ?? "null");
}
