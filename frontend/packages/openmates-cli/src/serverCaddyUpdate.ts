/** Release-matched path updates for host Caddy, preserving host configuration. */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { accessSync, constants, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

type Paths = Record<string, string[]>;
type Matcher = { line: number; paths: string[]; prefix: string; suffix: string };
export type CaddyUpdateState = { version: 1; configPath: string; site: string | null; revision: string; paths: Paths; template: string };
export type CaddyUpdateResult = { status: "updated" | "unchanged" | "not_installed"; revision?: string; backupPath?: string };
const hash = (text: string) => createHash("sha256").update(text).digest("hex");

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

function matchers(content: string, site: string | null): Map<string, Matcher> {
  const lines = content.split("\n");
  const [start, end] = siteRange(lines, site);
  const result = new Map<string, Matcher>();
  for (let i = start; i < end; i++) {
    const named = /^\s*(@[\w-]+)\s+(.*)$/.exec(lines[i]);
    if (!named) continue;
    let pathLine = i;
    if (named[2].trim() === "{") {
      pathLine = -1;
      for (let j = i + 1; j < end && lines[j].trim() !== "}"; j++) {
        if (/^\s*path\s/.test(lines[j])) {
          if (pathLine !== -1) throw new Error("caddy_ambiguous_path_matcher");
          pathLine = j;
        }
      }
      if (pathLine === -1) continue;
    }
    const path = /^(.*?\bpath\s+)([^#]*?)(\s*(?:#.*)?)$/.exec(lines[pathLine]);
    if (!path) continue;
    const paths = path[2].trim().split(/\s+/);
    if (paths.some(value => !value.startsWith("/") || /[{}"'\\]/.test(value))) throw new Error("caddy_unsupported_path_matcher");
    if (result.has(named[1])) throw new Error("caddy_ambiguous_path_matcher");
    result.set(named[1], { line: pathLine, paths, prefix: path[1], suffix: path[3] });
  }
  return result;
}

export function mergeCaddyPaths(input: {
  current: string; target: string; site: string | null; previous?: Paths;
}): { content: string; paths: Paths } {
  const current = matchers(input.current, input.site);
  const target = matchers(input.target, input.site);
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
      Object.entries(state.paths).some(([name, paths]) => !/^@[\w-]+$/.test(name) ||
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
function run(command, args) { cp.execFileSync(command, args, {stdio: ['ignore','pipe','pipe'], timeout: 20000}); }
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
  try { accessSync(dirname(input.configPath), constants.W_OK); } catch { privileged = true; }
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
  target: string; revision: string; verify: () => Promise<void>;
}): Promise<CaddyUpdateResult> {
  if (!/^[a-f0-9]{40}$/i.test(input.revision)) throw new Error("caddy_release_revision_invalid");
  const current = caddyHostOperation({ action: "read", configPath: input.configPath }).content!;
  const statePath = join(input.installPath, ".openmates", "caddy", `${input.role}.json`);
  const previous = readCaddyUpdateState(statePath, input.configPath, input.site);
  // Existing installations have no previous template. Adopt their known route
  // matchers first, preserving every other byte. Later releases use a complete
  // three-way merge, including handler changes and route removals.
  const merged = previous
    ? { content: mergeCaddyRelease(current, previous.template, input.target), paths: Object.fromEntries([...matchers(input.target, input.site)].map(([name, matcher]) => [name, matcher.paths])) }
    : mergeCaddyPaths({ current, target: input.target, site: input.site });
  const result = caddyHostOperation({ action: "apply", configPath: input.configPath, expectedHash: hash(current), content: merged.content });
  try { await input.verify(); }
  catch {
    if (result.backupPath) caddyHostOperation({ action: "restore", configPath: input.configPath, expectedHash: hash(merged.content), backupPath: result.backupPath });
    throw new Error("caddy_public_route_verification_failed");
  }
  const state: CaddyUpdateState = { version: 1, configPath: input.configPath, site: input.site, revision: input.revision, paths: merged.paths, template: input.target };
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
