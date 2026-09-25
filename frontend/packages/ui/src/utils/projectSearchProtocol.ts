/** Shared typed Project search contract for hosted and remote executors. */

export type ProjectSearchTarget = "files" | "content";
export type ProjectSearchMode = "literal" | "regex";

export interface ProjectSearchRequest {
  target: ProjectSearchTarget;
  mode: ProjectSearchMode;
  query: string;
  path: string;
  glob?: string;
  maxResults: number;
}

export class ProjectSearchProtocolError extends Error {
  readonly code: string;

  constructor(code: string) {
    super(code);
    this.name = "ProjectSearchProtocolError";
    this.code = code;
  }
}

export const PROJECT_SEARCH_DEFAULT_MAX_RESULTS = 20;
export const PROJECT_SEARCH_MAX_RESULTS = 100;
export const PROJECT_SEARCH_MAX_QUERY_CHARS = 2_000;
export const PROJECT_SEARCH_MAX_GLOB_CHARS = 512;

/** Negative rg globs that prevent the search process from opening credentials. */
export const PROJECT_CREDENTIAL_GLOBS = [
  ".env",
  ".env.*",
  "**/.env",
  "**/.env.*",
  ".ssh/**",
  "**/.ssh/**",
  ".aws/**",
  "**/.aws/**",
  ".gnupg/**",
  "**/.gnupg/**",
  ".config/gcloud/**",
  "**/.config/gcloud/**",
  ".npmrc",
  "**/.npmrc",
  ".pypirc",
  "**/.pypirc",
  ".netrc",
  "**/.netrc",
  ".pgpass",
  "**/.pgpass",
  ".my.cnf",
  "**/.my.cnf",
  ".git-credentials",
  "**/.git-credentials",
  "credentials",
  "**/credentials",
  "credentials.json",
  "**/credentials.json",
  "application_default_credentials.json",
  "**/application_default_credentials.json",
  "id_rsa",
  "**/id_rsa",
  "id_ed25519",
  "**/id_ed25519",
  "id_dsa",
  "**/id_dsa",
  "id_ecdsa",
  "**/id_ecdsa",
  "*.pem",
  "**/*.pem",
  "*.key",
  "**/*.key",
  "*.p12",
  "**/*.p12",
  "*.pfx",
  "**/*.pfx",
  "*.keystore",
  "**/*.keystore",
  "*.kdbx",
  "**/*.kdbx",
  "*.credentials",
  "**/*.credentials",
] as const;

export function normalizeProjectSearchRequest(args: Record<string, unknown>): ProjectSearchRequest {
  const target = args.target ?? "content";
  const mode = args.mode ?? "literal";
  const query = args.query;
  const path = args.path ?? ".";
  const glob = args.glob;
  const maxResults = args.max_results ?? PROJECT_SEARCH_DEFAULT_MAX_RESULTS;

  if (target !== "files" && target !== "content") fail("invalid_search_target");
  if (mode !== "literal" && mode !== "regex") fail("invalid_search_mode");
  if (
    typeof query !== "string"
    || !query.trim()
    || query.length > PROJECT_SEARCH_MAX_QUERY_CHARS
    || hasControlCharacters(query)
  ) fail("invalid_search_query");
  if (typeof path !== "string") fail("invalid_search_path");
  const normalizedPath = normalizeSearchPath(path);
  if (
    glob !== undefined
    && (
      typeof glob !== "string"
      || !glob
      || glob.length > PROJECT_SEARCH_MAX_GLOB_CHARS
      || glob.startsWith("!")
      || hasControlCharacters(glob)
      || glob.includes("\\")
      || glob.includes("[")
      || glob.includes("]")
      || glob.includes("{")
      || glob.includes("}")
      || glob.startsWith("/")
      || glob.split("/").some((part) => part === "..")
    )
  ) fail("invalid_search_glob");
  if (typeOfInteger(maxResults) === false || maxResults < 1 || maxResults > PROJECT_SEARCH_MAX_RESULTS) {
    fail("invalid_search_limit");
  }

  return {
    target,
    mode,
    query,
    path: normalizedPath,
    ...(typeof glob === "string" ? { glob } : {}),
    maxResults,
  };
}

export function matchesProjectSearchQuery(value: string, request: Pick<ProjectSearchRequest, "mode" | "query">): boolean {
  if (request.mode === "regex") fail("regex_search_unavailable");
  return value.includes(request.query);
}

/** Match the supported *, ** and ? path-glob grammar without dynamic regular expressions. */
export function matchesProjectSearchGlob(path: string, glob?: string): boolean {
  if (!glob) return true;
  const memo = new Map<string, boolean>();

  const visit = (pathIndex: number, globIndex: number): boolean => {
    const key = `${pathIndex}:${globIndex}`;
    const cached = memo.get(key);
    if (cached !== undefined) return cached;
    let matched = false;
    if (globIndex === glob.length) {
      matched = pathIndex === path.length;
    } else if (glob.startsWith("**/", globIndex)) {
      matched = visit(pathIndex, globIndex + 3);
      for (let index = pathIndex; !matched && index < path.length; index += 1) {
        if (path[index] === "/") matched = visit(index + 1, globIndex + 3);
      }
    } else if (glob.startsWith("**", globIndex)) {
      matched = visit(pathIndex, globIndex + 2)
        || (pathIndex < path.length && visit(pathIndex + 1, globIndex));
    } else if (glob[globIndex] === "*") {
      matched = visit(pathIndex, globIndex + 1)
        || (pathIndex < path.length && path[pathIndex] !== "/" && visit(pathIndex + 1, globIndex));
    } else if (glob[globIndex] === "?") {
      matched = pathIndex < path.length && path[pathIndex] !== "/" && visit(pathIndex + 1, globIndex + 1);
    } else {
      matched = pathIndex < path.length && path[pathIndex] === glob[globIndex]
        && visit(pathIndex + 1, globIndex + 1);
    }
    memo.set(key, matched);
    return matched;
  };

  return visit(0, 0);
}

export function isProtectedProjectReadPath(value: string): boolean {
  const normalized = value.replace(/\\/g, "/").replace(/^\.\//, "").toLowerCase();
  const parts = normalized.split("/").filter(Boolean);
  const name = parts.at(-1) ?? "";
  if (name === ".env" || name.startsWith(".env.")) return true;
  if (parts.some((part) => [".ssh", ".aws", ".gnupg"].includes(part))) return true;
  if (normalized === ".config/gcloud" || normalized.endsWith("/.config/gcloud") || normalized.includes(".config/gcloud/")) return true;
  if ([
    ".npmrc", ".pypirc", ".netrc", ".pgpass", ".my.cnf", ".git-credentials",
    "credentials", "credentials.json", "application_default_credentials.json",
    "id_rsa", "id_ed25519", "id_dsa", "id_ecdsa",
  ].includes(name)) return true;
  return [".pem", ".key", ".p12", ".pfx", ".keystore", ".kdbx", ".credentials"]
    .some((extension) => name.endsWith(extension));
}

function normalizeSearchPath(value: string): string {
  if (!value || value.length > 2_048 || hasControlCharacters(value) || value.includes("\\") || value.startsWith("/")) {
    fail("invalid_search_path");
  }
  const parts = value.split("/");
  if (parts.some((part) => part === "..")) fail("invalid_search_path");
  const normalized = parts.filter((part) => part && part !== ".").join("/");
  return normalized || ".";
}

function hasControlCharacters(value: string): boolean {
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0;
    if (codePoint <= 0x1f || codePoint === 0x7f) return true;
  }
  return false;
}

function typeOfInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function fail(code: string): never {
  throw new ProjectSearchProtocolError(code);
}
