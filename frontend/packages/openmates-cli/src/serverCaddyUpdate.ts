/** Release-matched path updates for host Caddy, preserving host configuration. */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { accessSync, constants, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, isAbsolute, resolve } from "node:path";

type Paths = Record<string, string[]>;
type Matcher = { line: number; paths: string[]; prefix: string; suffix: string };
export type CaddyProfile = "self-host" | "official-upload";
export type OfficialUploadOrigins = { prod: string; dev: string };
export type CaddyUpdateState = { version: 1; configPath: string; site: string | null; revision: string; paths: Paths; template: string; profile?: CaddyProfile };
export type CaddyUpdateResult = { status: "updated" | "unchanged" | "not_installed"; revision?: string; backupPath?: string };
const hash = (text: string) => createHash("sha256").update(text).digest("hex");

export function caddyConfigFromArgs(args: string[], cwd?: string): string | undefined {
  const index = args.indexOf("--config");
  const value = index >= 0 ? args[index + 1] : args.find(arg => arg.startsWith("--config="))?.slice(9);
  if (!value || value.startsWith("--")) return undefined;
  if (!isAbsolute(value) && !cwd) throw new Error("caddy_relative_config_requires_explicit_path");
  return resolve(cwd ?? "/", value);
}

/** Prefer the running service's actual file over an unused default Caddyfile. */
export function detectCaddyConfigPath(explicit?: string): string | undefined {
  if (explicit) return resolve(explicit);
  let pid: string | undefined;
  try {
    pid = execFileSync("systemctl", ["show", "caddy", "--property=MainPID", "--value"], {
      encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 5_000,
    }).trim();
  } catch { /* Non-systemd hosts can still use the default file. */ }
  if (pid && /^[1-9]\d*$/.test(pid)) {
    try {
      const args = readFileSync(`/proc/${pid}/cmdline`, "utf8").split("\0").filter(Boolean);
      const config = caddyConfigFromArgs(args);
      if (config) return config;
    } catch { throw new Error("caddy_running_config_requires_explicit_path"); }
    throw new Error("caddy_running_config_requires_explicit_path");
  }
  return existsSync("/etc/caddy/Caddyfile") ? "/etc/caddy/Caddyfile" : undefined;
}

/** Authenticate sudo without changing the user's installation/config context. */
export function caddyUpdateRetryCommand(input: { installPath: string; role: string; configPath: string; profile?: CaddyProfile }): string {
  const quote = (value: string) => `'${value.replaceAll("'", "'\\''")}'`;
  return `sudo -v && openmates server caddy update --path ${quote(input.installPath)} --role ${quote(input.role)} --caddy-config ${quote(input.configPath)}`
    + (input.profile === "official-upload" ? " --caddy-profile official-upload" : "");
}

export function resolveCaddyProfile(role: string, explicit: string | boolean | undefined, previous?: CaddyProfile): CaddyProfile {
  if (explicit === undefined) return previous ?? "self-host";
  if (role !== "upload" || explicit !== "official-upload") throw new Error("caddy_profile_unsupported");
  if (previous && previous !== explicit) throw new Error("caddy_profile_conflicts_with_baseline");
  return explicit;
}

function scopedHandleBlock(content: string, name: string): string | undefined {
  const lines = content.split("\n");
  const start = lines.findIndex(line => new RegExp(`^\\s*handle\\s+${name}\\s*\\{$`).test(line));
  if (start < 0) return undefined;
  let depth = 0;
  for (let i = start; i < lines.length; i++) {
    const code = lines[i].replace(/#.*$/, "");
    depth += (code.match(/\{/g)?.length ?? 0) - (code.match(/\}/g)?.length ?? 0);
    if (depth === 0) return lines.slice(start, i + 1).join("\n");
  }
  return undefined;
}

function reverseProxyBlocks(content: string): string[] {
  const lines = content.split("\n");
  const blocks: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const first = lines[i].replace(/#.*$/, "");
    if (!/^\s*reverse_proxy\b/.test(first)) continue;
    if (!/\{\s*$/.test(first)) throw new Error("caddy_official_upload_structure_missing");
    const start = i;
    let depth = 0;
    let closed = false;
    for (; i < lines.length; i++) {
      const code = lines[i].replace(/#.*$/, "");
      depth += (code.match(/\{/g)?.length ?? 0) - (code.match(/\}/g)?.length ?? 0);
      if (depth === 0) {
        blocks.push(lines.slice(start, i + 1).join("\n"));
        closed = true;
        break;
      }
    }
    if (!closed) throw new Error("caddy_official_upload_structure_missing");
  }
  return blocks;
}

function headerUpAffectsTargetEnv(line: string): boolean {
  const field = /^header_up\s+(\S+)/i.exec(line)?.[1]?.replace(/^['"]|['"]$/g, "").replace(/^[+-]/, "").toLowerCase();
  if (!field) return false;
  const escaped = field.split("*").map(part => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join(".*");
  return new RegExp(`^${escaped}$`).test("x-target-env");
}

export function officialUploadOrigins(content: string): OfficialUploadOrigins {
  const origins: Partial<OfficialUploadOrigins> = {};
  for (const environment of ["prod", "dev"]) {
    const matches = [...content.matchAll(new RegExp(`^\\s*@${environment}_origin\\s+expression\\s+\\{header\\.Origin\\}\\s*==\\s*"([^"\\n]+)"\\s*$`, "gm"))];
    if (matches.length !== 1) {
      throw new Error("caddy_official_upload_structure_missing");
    }
    const origin = matches[0][1];
    let parsed: URL;
    try { parsed = new URL(origin); } catch { throw new Error("caddy_official_upload_origin_invalid"); }
    if (parsed.protocol !== "https:" || parsed.origin !== origin || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) {
      throw new Error("caddy_official_upload_origin_invalid");
    }
    origins[environment as keyof OfficialUploadOrigins] = origin;
  }
  if (origins.prod === origins.dev) throw new Error("caddy_official_upload_origin_conflict");
  return origins as OfficialUploadOrigins;
}

export function validateOfficialUploadCaddy(content: string, expectedOrigins?: OfficialUploadOrigins): void {
  const origins = officialUploadOrigins(content);
  if (expectedOrigins && (origins.prod !== expectedOrigins.prod || origins.dev !== expectedOrigins.dev)) {
    throw new Error("caddy_official_upload_origin_mismatch");
  }
  const scoped = matchers(content, null, true);
  if (!scoped.has("@prod_origin/@upload_api") || !scoped.has("@dev_origin/@upload_api") ||
      !scoped.has("@upload_health") || !scoped.has("@admin_paths")) {
    throw new Error("caddy_official_upload_structure_missing");
  }
  for (const environment of ["prod", "dev"]) {
    const block = scopedHandleBlock(content, `@${environment}_origin`);
    const active = block?.split("\n").filter(line => !line.trim().startsWith("#")).join("\n") ?? "";
    if (!block || !active.includes("@upload_options method OPTIONS") || !/handle\s*\{\s*abort\s*\}/.test(active)) {
      throw new Error("caddy_official_upload_structure_missing");
    }
    const proxies = reverseProxyBlocks(active);
    if (proxies.length < 2) throw new Error("caddy_official_upload_structure_missing");
    for (const proxy of proxies) {
      const targetHeaders = proxy.split("\n")
        .map(line => line.replace(/#.*$/, "").trim())
        .filter(headerUpAffectsTargetEnv);
      if (targetHeaders.length !== 1 || !new RegExp(`^header_up\\s+X-Target-Env\\s+(?:"${environment}"|${environment})$`, "i").test(targetHeaders[0])) {
        throw new Error("caddy_official_upload_structure_missing");
      }
    }
  }
}

export function renderOfficialUploadCaddyTemplate(template: string, domain: string, email: string): string {
  if (!/^[a-z0-9.-]+$/i.test(domain) || !domain.includes(".") || !/^[^\s{}$@]+@[^\s{}$@]+\.[^\s{}$@]+$/.test(email)) {
    throw new Error("caddy_official_upload_render_values_invalid");
  }
  const rendered = template.replaceAll("${DEPLOY_UPLOAD_DOMAIN}", domain).replaceAll("${DEPLOY_ACME_EMAIL}", email);
  if (/\$\{[A-Z_][A-Z0-9_]*\}/.test(rendered)) throw new Error("caddy_official_upload_template_unresolved");
  validateOfficialUploadCaddy(rendered);
  return rendered;
}

function siteRange(lines: string[], site: string | null): [number, number] {
  if (!site) return [0, lines.length];
  const start = lines.findIndex(line => line.trim() === `${site} {`);
  if (start < 0) throw new Error("caddy_managed_site_missing");
  let depth = 0;
  for (let i = start; i < lines.length; i++) {
    // Environment placeholders contain balanced braces on the same line.
    const code = lines[i].replace(/#.*$/, "");
    depth += (code.match(/\{/g)?.length ?? 0) - (code.match(/\}/g)?.length ?? 0);
    if (depth === 0) return [start, i + 1];
  }
  throw new Error("caddy_managed_site_unclosed");
}

function matchers(content: string, site: string | null, scopeAware = false): Map<string, Matcher> {
  const lines = content.split("\n");
  const [start, end] = siteRange(lines, site);
  const result = new Map<string, Matcher>();
  let depth = 0;
  const handles: Array<{ name: string; depth: number }> = [];
  for (let i = start; i < end; i++) {
    const named = /^\s*(@[\w-]+)\s+(.*)$/.exec(lines[i]);
    if (named) {
      let pathLine = i;
      if (named[2].trim() === "{") {
        pathLine = -1;
        for (let j = i + 1; j < end && lines[j].trim() !== "}"; j++) {
          if (/^\s*path\s/.test(lines[j])) {
            if (pathLine !== -1) throw new Error("caddy_ambiguous_path_matcher");
            pathLine = j;
          }
        }
      }
      const path = pathLine >= 0 ? /^(.*?\bpath\s+)([^#]*?)(\s*(?:#.*)?)$/.exec(lines[pathLine]) : null;
      if (path) {
        const paths = path[2].trim().split(/\s+/);
        if (paths.some(value => !value.startsWith("/") || /[{}"'\\]/.test(value))) throw new Error("caddy_unsupported_path_matcher");
        const scope = scopeAware ? handles.at(-1)?.name : undefined;
        const key = scope ? `${scope}/${named[1]}` : named[1];
        if (result.has(key)) throw new Error("caddy_ambiguous_path_matcher");
        result.set(key, { line: pathLine, paths, prefix: path[1], suffix: path[3] });
      }
    }
    if (scopeAware) {
      const handle = /^\s*handle\s+(@[\w-]+)\s*\{/.exec(lines[i]);
      if (handle) handles.push({ name: handle[1], depth: depth + 1 });
      const code = lines[i].replace(/#.*$/, "");
      depth += (code.match(/\{/g)?.length ?? 0) - (code.match(/\}/g)?.length ?? 0);
      while (handles.length && depth < handles[handles.length - 1].depth) handles.pop();
    }
  }
  return result;
}

export function mergeCaddyPaths(input: {
  current: string; target: string; site: string | null; previous?: Paths; scopeAware?: boolean;
}): { content: string; paths: Paths } {
  const current = matchers(input.current, input.site, input.scopeAware);
  const target = matchers(input.target, input.site, input.scopeAware);
  if (!target.size) throw new Error("caddy_release_matchers_missing");
  const lines = input.current.split("\n");
  const paths: Paths = {};
  for (const [name, wanted] of target) {
    const existing = current.get(name);
    // New handler/matcher structures require a reviewed host migration.
    if (!existing) throw new Error(`caddy_matcher_missing:${name}`);
    const owned = input.previous?.[name] ?? [];
    if (owned.some(path => wanted.paths.includes(path) && !existing.paths.includes(path))) {
      throw new Error(`caddy_local_route_conflict:${name}`);
    }
    const custom = existing.paths.filter(path => !owned.includes(path));
    const merged = [...new Set([...wanted.paths, ...custom])];
    paths[name] = wanted.paths;
    // Retain exact formatting when no change is required.
    if (merged.length === existing.paths.length && merged.every(path => existing.paths.includes(path))) continue;
    lines[existing.line] = `${existing.prefix}${merged.join(" ")}${existing.suffix}`;
  }
  for (const name of Object.keys(input.previous ?? {})) {
    if (!target.has(name)) throw new Error(`caddy_removed_matcher_requires_migration:${name}`);
  }
  return { content: lines.join("\n"), paths };
}

export function readCaddyUpdateState(path: string, configPath: string, site: string | null): CaddyUpdateState | undefined {
  if (!existsSync(path)) return undefined;
  try {
    const state = JSON.parse(readFileSync(path, "utf8")) as CaddyUpdateState;
    if (state.version !== 1 || state.configPath !== configPath || state.site !== site ||
      !/^[a-f0-9]{40}$/i.test(state.revision) || typeof state.template !== "string" || !state.template || !state.paths || Array.isArray(state.paths) ||
      (state.profile !== undefined && state.profile !== "self-host" && state.profile !== "official-upload") ||
      Object.entries(state.paths).some(([name, paths]) => !/^(?:@[\w-]+\/)?@[\w-]+$/.test(name) ||
        !Array.isArray(paths) || paths.some(path => typeof path !== "string" || !path.startsWith("/")))) {
      throw new Error();
    }
    return state;
  } catch { throw new Error("caddy_update_state_invalid"); }
}

/** Merge release changes with operator edits; overlapping changes fail closed. */
export function mergeCaddyRelease(current: string, previous: string, target: string): string {
  if (previous === target) return current;
  if (current === previous) return target;
  const directory = mkdtempSync(join(tmpdir(), "openmates-caddy-merge-"));
  try {
    const files = ["current", "previous", "target"].map(name => join(directory, name));
    [current, previous, target].forEach((content, i) => writeFileSync(files[i], content, { mode: 0o600 }));
    try {
      return execFileSync("diff3", ["-m", ...files], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 10_000 });
    } catch (error) {
      throw new Error((error as { status?: number }).status === 1 ? "caddy_local_config_conflict" : "caddy_merge_tool_unavailable");
    }
  } finally { rmSync(directory, { recursive: true, force: true }); }
}

// This small host transaction also works when the CLI is run by an operator
// with passwordless sudo. Configuration travels over stdin, never argv/logs.
const HOST_TRANSACTION = String.raw`
const fs = require('node:fs'), cp = require('node:child_process'), crypto = require('node:crypto'), path = require('node:path');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const digest = text => crypto.createHash('sha256').update(text).digest('hex');
function run(command, args) {
  const options = {stdio: ['ignore','pipe','pipe'], timeout: 20000};
  try { cp.execFileSync(command, args, options); }
  catch (error) {
    // A user-owned Caddyfile can still belong to a root-managed service.
    // Honor a cached sudo session for reload without elevating file access.
    if (command !== 'systemctl') throw error;
    try { cp.execFileSync('sudo', ['-n', command, ...args], options); }
    catch { throw error; }
  }
}
function replace(content, metadata) {
  const temp = input.configPath + '.openmates-' + crypto.randomUUID();
  let fd;
  try {
    fd = fs.openSync(temp, 'wx', 0o600);
    fs.writeFileSync(fd, content); fs.fsyncSync(fd); fs.closeSync(fd); fd = undefined;
    fs.chownSync(temp, metadata.uid, metadata.gid); fs.chmodSync(temp, metadata.mode & 0o777);
    fs.renameSync(temp, input.configPath);
    const directory = fs.openSync(path.dirname(input.configPath), 'r');
    try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
  } finally { if (fd !== undefined) fs.closeSync(fd); if (fs.existsSync(temp)) fs.unlinkSync(temp); }
}
let reason = 'caddy_host_operation_failed';
try {
  if (input.action === 'read') {
    process.stdout.write(JSON.stringify({content: fs.readFileSync(input.configPath, 'utf8')}));
  } else {
    const current = fs.readFileSync(input.configPath, 'utf8');
    if (digest(current) !== input.expectedHash) { reason = 'caddy_config_changed'; throw new Error(); }
    const metadata = fs.statSync(input.configPath);
    if (!metadata.isFile() || fs.lstatSync(input.configPath).isSymbolicLink()) { reason = 'caddy_config_not_regular'; throw new Error(); }
    if (input.action === 'restore') {
      replace(fs.readFileSync(input.backupPath, 'utf8'), metadata);
      reason = 'caddy_rollback_reload_failed'; run('systemctl', ['reload', 'caddy']);
      run('systemctl', ['is-active', '--quiet', 'caddy']);
      process.stdout.write('{}');
    } else {
      const candidate = input.configPath + '.openmates-candidate-' + crypto.randomUUID();
      let backupPath;
      try {
        fs.writeFileSync(candidate, input.content, {flag: 'wx', mode: 0o600});
        reason = 'caddy_validation_failed'; run('caddy', ['validate', '--config', candidate, '--adapter', 'caddyfile']);
        // Recheck after validation so operator edits are not overwritten.
        if (digest(fs.readFileSync(input.configPath, 'utf8')) !== input.expectedHash) { reason = 'caddy_config_changed'; throw new Error(); }
        if (current !== input.content) {
          backupPath = input.configPath + '.openmates-backup-' + Date.now() + '-' + crypto.randomUUID();
          fs.copyFileSync(input.configPath, backupPath, fs.constants.COPYFILE_EXCL);
          fs.chmodSync(backupPath, 0o600);
          replace(input.content, metadata);
        }
        reason = 'caddy_reload_failed';
        try { run('systemctl', ['reload', 'caddy']); run('systemctl', ['is-active', '--quiet', 'caddy']); }
        catch (error) {
          if (backupPath) {
            replace(current, metadata);
            try { run('systemctl', ['reload', 'caddy']); run('systemctl', ['is-active', '--quiet', 'caddy']); }
            catch { reason = 'caddy_rollback_reload_failed'; }
          }
          throw error;
        }
        process.stdout.write(JSON.stringify({backupPath}));
      } finally { if (fs.existsSync(candidate)) fs.unlinkSync(candidate); }
    }
  }
} catch { process.stderr.write(reason); process.exit(1); }
`;

export function caddyHostOperation(input: Record<string, unknown> & { configPath: string }): { content?: string; backupPath?: string } {
  let privileged = false;
  try { accessSync(input.action === "read" ? input.configPath : dirname(input.configPath), input.action === "read" ? constants.R_OK : constants.W_OK); } catch { privileged = true; }
  const args = ["-e", HOST_TRANSACTION];
  try {
    return JSON.parse(execFileSync(privileged ? "sudo" : process.execPath,
      privileged ? ["-n", process.execPath, ...args] : args,
      { input: JSON.stringify(input), encoding: "utf8", stdio: ["pipe", "pipe", "pipe"], timeout: 90_000 }));
  } catch (error) {
    const reason = (error as { stderr?: string | Buffer }).stderr?.toString().trim();
    throw new Error(reason && /^caddy_[a-z_]+$/.test(reason) ? reason : "caddy_host_privileges_or_tools_unavailable");
  }
}

export async function applyCaddyPathUpdate(input: {
  installPath: string; role: string; configPath: string; site: string | null;
  target: string; revision: string; verify: () => Promise<void>; profile?: CaddyProfile;
}): Promise<CaddyUpdateResult> {
  if (!/^[a-f0-9]{40}$/i.test(input.revision)) throw new Error("caddy_release_revision_invalid");
  const current = caddyHostOperation({ action: "read", configPath: input.configPath }).content!;
  const statePath = join(input.installPath, ".openmates", "caddy", `${input.role}.json`);
  const previous = readCaddyUpdateState(statePath, input.configPath, input.site);
  // Existing installations have no previous template. Adopt their known route
  // matchers first, preserving every other byte. Later releases use a complete
  // three-way merge, including handler changes and route removals.
  const merged = previous
    ? { content: mergeCaddyRelease(current, previous.template, input.target), paths: Object.fromEntries([...matchers(input.target, input.site, input.profile === "official-upload")].map(([name, matcher]) => [name, matcher.paths])) }
    : mergeCaddyPaths({ current, target: input.target, site: input.site, scopeAware: input.profile === "official-upload" });
  if (input.profile === "official-upload") validateOfficialUploadCaddy(merged.content, officialUploadOrigins(input.target));
  const result = caddyHostOperation({ action: "apply", configPath: input.configPath, expectedHash: hash(current), content: merged.content });
  try { await input.verify(); }
  catch (error) {
    if (result.backupPath) caddyHostOperation({ action: "restore", configPath: input.configPath, expectedHash: hash(merged.content), backupPath: result.backupPath });
    if (error instanceof Error && /^caddy_upload_(?:health_route_failed|prod_preflight_failed|dev_preflight_failed|unknown_origin_allowed)$/.test(error.message)) throw error;
    throw new Error("caddy_public_route_verification_failed");
  }
  const state: CaddyUpdateState = { version: 1, configPath: input.configPath, site: input.site, revision: input.revision, paths: merged.paths, template: input.target, profile: input.profile ?? "self-host" };
  mkdirSync(dirname(statePath), { recursive: true });
  const temp = `${statePath}.${process.pid}.tmp`;
  writeFileSync(temp, JSON.stringify(state) + "\n", { mode: 0o600 });
  renameSync(temp, statePath);
  return { status: current === merged.content ? "unchanged" : "updated", revision: input.revision, ...result };
}

export async function verifyCaddyCoreRoutes(apiUrl: string, origin: string): Promise<void> {
  const request = (path: string, init: RequestInit = {}) => fetch(`${apiUrl.replace(/\/$/, "")}${path}`, {
    ...init, redirect: "error", signal: AbortSignal.timeout(5_000),
  });
  const embedPreflight = await request("/v1/embeds/chats/00000000-0000-4000-8000-000000000000/references/availability", { method: "OPTIONS", headers: {
    Origin: origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type",
  } });
  if (!embedPreflight.ok || embedPreflight.headers.get("access-control-allow-origin") !== origin ||
    embedPreflight.headers.get("access-control-allow-credentials") !== "true") throw new Error("caddy_embed_reference_cors_failed");
  const availability = await request("/v1/features/availability");
  if (!availability.ok) throw new Error("caddy_availability_route_failed");
  const features = await availability.json() as { disabled?: string[] };
  if (!Array.isArray(features.disabled)) throw new Error("caddy_availability_response_invalid");
  if (features.disabled.includes("platform:workflows")) return;
  const preflight = await request("/v1/workflows", { method: "OPTIONS", headers: {
    Origin: origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "content-type",
  } });
  if (!preflight.ok || preflight.headers.get("access-control-allow-origin") !== origin ||
    preflight.headers.get("access-control-allow-credentials") !== "true") throw new Error("caddy_workflow_cors_failed");
  for (const path of ["/v1/workflows", "/v1/workflows/00000000-0000-4000-8000-000000000000/runs"]) {
    const response = await request(path, { headers: { Origin: origin } });
    if (response.status !== 401 || response.headers.get("access-control-allow-origin") !== origin) throw new Error("caddy_workflow_route_failed");
  }
}

export async function verifyCaddyUploadRoutes(
  baseUrl: string,
  origins: OfficialUploadOrigins,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const endpoint = baseUrl.replace(/\/$/, "");
  const request = (path: string, init: RequestInit = {}) => fetcher(`${endpoint}${path}`, {
    ...init, redirect: "error", signal: AbortSignal.timeout(5_000),
  });
  let health: Response;
  try { health = await request("/health"); } catch { throw new Error("caddy_upload_health_route_failed"); }
  if (!health.ok) throw new Error("caddy_upload_health_route_failed");
  for (const environment of ["prod", "dev"] as const) {
    const origin = origins[environment];
    let preflight: Response;
    try {
      preflight = await request("/v1/upload/file", { method: "OPTIONS", headers: {
        Origin: origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type",
      } });
    } catch { throw new Error(`caddy_upload_${environment}_preflight_failed`); }
    const methods = preflight.headers.get("access-control-allow-methods")?.split(",").map(value => value.trim().toUpperCase()) ?? [];
    if (!preflight.ok || preflight.headers.get("access-control-allow-origin") !== origin ||
        preflight.headers.get("access-control-allow-credentials") !== "true" || !methods.includes("POST")) {
      throw new Error(`caddy_upload_${environment}_preflight_failed`);
    }
  }
  const unknownOrigin = "https://openmates-route-probe.invalid";
  if (Object.values(origins).includes(unknownOrigin)) throw new Error("caddy_upload_unknown_origin_allowed");
  try {
    const denied = await request("/v1/upload/file", { method: "OPTIONS", headers: {
      Origin: unknownOrigin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type",
    } });
    if (![403, 404].includes(denied.status) || denied.headers.get("access-control-allow-origin") === unknownOrigin) {
      throw new Error("caddy_upload_unknown_origin_allowed");
    }
  } catch (error) {
    // Caddy's `abort` closes the connection, which fetch reports as a rejection.
    if (error instanceof Error && error.message === "caddy_upload_unknown_origin_allowed") throw error;
  }
}
