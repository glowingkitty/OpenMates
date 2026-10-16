/** Optional model lifecycle. No account data, automatic downloads or inference. */
import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { chmod, copyFile, lstat, mkdir, open, readFile, rename, rm, statfs, writeFile } from "node:fs/promises";
import { availableParallelism, homedir, totalmem } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import lockfile from "proper-lockfile";
import { resolveStateDir } from "./storage.js";

export const ENHANCED_ANONYMIZATION_LABEL = "Enhanced personal data anonymization (offline AI model)";
export const PRIVACY_MODEL = {
  revision: "935d86882f4b5dc6e0eef05aae48ae5ba0a82a7a",
  bytes: 1637572192,
  sha256: "80efc1803eda7c095a79741d2008c07e2e0a57b01bac8825fbeb448fd097998c",
  url: "https://huggingface.co/LocalAI-io/privacy-filter-GGUF/resolve/935d86882f4b5dc6e0eef05aae48ae5ba0a82a7a/privacy-filter-q8.gguf",
} as const;
export type PrivacyScope = { kind: "message" | "document" | "project"; projectId?: string };
export type PrivacyPreferences = { version: 1; enabled: boolean; documents: boolean; projects: string[]; offerSeen: boolean; idleSeconds: number };
const defaults = (): PrivacyPreferences => ({ version: 1, enabled: false, documents: false, projects: [], offerSeen: false, idleSeconds: 120 });
export function privacyRoot(): string { return resolve(process.env.OPENMATES_PRIVACY_DIR?.trim() || join(homedir(), ".openmates", "privacy-model")); }
export function privacyModelPath(): string { return join(privacyRoot(), PRIVACY_MODEL.revision, "model.gguf"); }
export function privacySocketPath(): string { return join(privacyRoot(), "worker.sock"); }
export function privacyProfile(): string { return createHash("sha256").update(resolveStateDir()).digest("hex"); }
export function privacyRuntimeDirectory(): string { return fileURLToPath(new URL("../fixtures/privacy-runtime/linux-arm64/", import.meta.url)); }
export function privacyError(code: string): Error {
  return Object.assign(new Error(`${ENHANCED_ANONYMIZATION_LABEL}: ${code}. No enhanced-mode text was sent. Retry, or explicitly disable this mode with 'openmates privacy disable'.`), { code });
}
export async function privateDirectory(path: string): Promise<void> {
  await mkdir(path, { recursive: true, mode: 0o700 });
  const s = await lstat(path);
  if (!s.isDirectory() || s.isSymbolicLink() || (process.getuid && s.uid !== process.getuid())) throw privacyError("privacy_unsafe_directory");
  await chmod(path, 0o700);
}
export async function readPrivateJson<T>(path: string): Promise<T | null> {
  try {
    const s = await lstat(path);
    if (!s.isFile() || s.isSymbolicLink() || (s.mode & 0o077) || (process.getuid && s.uid !== process.getuid())) throw privacyError("privacy_unsafe_state");
    return JSON.parse(await readFile(path, "utf8")) as T;
  } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return null; throw error; }
}
export async function writePrivateJson(path: string, value: unknown): Promise<void> {
  await privateDirectory(dirname(path));
  const temporary = path + "." + randomUUID();
  try { await writeFile(temporary, JSON.stringify(value) + "\n", { flag: "wx", mode: 0o600 }); await rename(temporary, path); }
  finally { await rm(temporary, { force: true }); }
}
export async function readPrivacyPreferences(): Promise<PrivacyPreferences> {
  const data = await readPrivateJson<Partial<PrivacyPreferences>>(join(resolveStateDir(), "privacy-preferences.json"));
  if (!data) return defaults();
  if (data.version !== 1 || typeof data.enabled !== "boolean" || typeof data.documents !== "boolean" || !Array.isArray(data.projects)
      || data.projects.length > 512 || data.projects.some((id) => typeof id !== "string" || !/^[0-9a-f-]{36}$/i.test(id))) throw privacyError("privacy_invalid_preferences");
  return { ...defaults(), ...data, projects: [...data.projects], idleSeconds: Math.max(15, Math.min(3600, Number(data.idleSeconds) || 120)) };
}
export async function updatePrivacyPreferences(change: (value: PrivacyPreferences) => PrivacyPreferences): Promise<PrivacyPreferences> {
  const directory = resolveStateDir(); await privateDirectory(directory);
  const release = await lockfile.lock(directory, { lockfilePath: join(directory, "privacy-preferences.lock"), retries: { retries: 10, minTimeout: 50, maxTimeout: 100 }, stale: 30_000 });
  try { const value = change(await readPrivacyPreferences()); await writePrivateJson(join(directory, "privacy-preferences.json"), value); return value; }
  finally { await release(); }
}
export function enhancedScopeEnabled(preferences: PrivacyPreferences, scope: PrivacyScope): boolean {
  return preferences.enabled && (scope.kind === "message" || scope.kind === "document" && preferences.documents || scope.kind === "project" && !!scope.projectId && preferences.projects.includes(scope.projectId));
}
export async function privacyCapability(): Promise<{ supported: boolean; reason?: string }> {
  if (process.platform !== "linux" || process.arch !== "arm64") return { supported: false, reason: "The first packaged runtime supports Linux ARM64." };
  const features = await readFile("/proc/cpuinfo", "utf8").catch(() => "");
  if (!/\basimddp\b/.test(features) || !/\basimdhp\b/.test(features)) return { supported: false, reason: "CPU FP16 and dot-product instructions are required." };
  if (totalmem() < 4 * 2 ** 30 || availableParallelism() < 2) return { supported: false, reason: "At least two CPU cores and 4 GB RAM are required; 8 GB is recommended for development." };
  try { await lstat(join(privacyRuntimeDirectory(), "manifest.json")); }
  catch { return { supported: false, reason: "The packaged native runtime is unavailable in this CLI build." }; }
  return { supported: true };
}
export async function fileDigest(path: string): Promise<string> {
  const hash = createHash("sha256"); for await (const chunk of createReadStream(path)) hash.update(chunk); return hash.digest("hex");
}
export async function verifyInstalledModel(): Promise<void> {
  const path = privacyModelPath(); const s = await lstat(path);
  if (!s.isFile() || s.isSymbolicLink() || (s.mode & 0o077) || s.size !== PRIVACY_MODEL.bytes || (process.getuid && s.uid !== process.getuid())
      || await fileDigest(path) !== PRIVACY_MODEL.sha256) throw privacyError("privacy_model_integrity_failed");
}
export async function verifyPrivacyRuntime(): Promise<string> {
  const directory = privacyRuntimeDirectory();
  const manifest = JSON.parse(await readFile(join(directory, "manifest.json"), "utf8")) as { revision: string; protocol: number; files: Array<{ name: string; bytes: number; sha256: string }> };
  if (manifest.revision !== "735a6c28607ee82afc3a670383f41b55266a3b9a" || manifest.protocol !== 1 || !manifest.files?.length) throw privacyError("privacy_runtime_integrity_failed");
  for (const item of manifest.files) {
    if (!/^[A-Za-z0-9._-]+$/.test(item.name)) throw privacyError("privacy_runtime_integrity_failed");
    const path = join(directory, item.name); const s = await lstat(path);
    if (!s.isFile() || s.isSymbolicLink() || s.size !== item.bytes || await fileDigest(path) !== item.sha256) throw privacyError("privacy_runtime_integrity_failed");
  }
  return join(directory, "openmates-pii-worker");
}
export async function privacyStatus(): Promise<Record<string, unknown>> {
  const [preferences, capability] = await Promise.all([readPrivacyPreferences(), privacyCapability()]);
  let installed = false;
  try { const s = await lstat(privacyModelPath()); installed = s.isFile() && !s.isSymbolicLink() && s.size === PRIVACY_MODEL.bytes; }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
  return { feature: ENHANCED_ANONYMIZATION_LABEL, state: !capability.supported ? "unsupported" : !installed ? "not_installed" : preferences.enabled ? "installed_enabled" : "installed_disabled", reason: capability.reason,
    model_bytes: PRIVACY_MODEL.bytes, memory_gib: 2, local_only: true, messages: preferences.enabled, documents: preferences.enabled && preferences.documents, projects: preferences.projects, installed, idle_seconds: preferences.idleSeconds };
}
export async function claimPrivacyOffer(): Promise<boolean> {
  if (!(await privacyCapability()).supported) return false;
  await privateDirectory(privacyRoot());
  const path = join(privacyRoot(), "tui-offer-seen.json");
  try {
    const file = await open(path, "wx", 0o600);
    try { await file.writeFile(JSON.stringify({ seen: true }) + "\n"); } finally { await file.close(); }
    return !(await privacyStatus()).installed;
  } catch (error) { if ((error as NodeJS.ErrnoException).code === "EEXIST") return false; throw error; }
}
export async function installPrivacyModel(options: { modelFile?: string; downloadOnly?: boolean; progress?: (received: number, total: number) => void } = {}): Promise<void> {
  const capability = await privacyCapability(); if (!capability.supported) throw new Error(capability.reason);
  await verifyPrivacyRuntime(); await privateDirectory(privacyRoot());
  const release = await lockfile.lock(privacyRoot(), { lockfilePath: join(privacyRoot(), "install.lock"), stale: 60_000, update: 10_000 });
  try {
    const directory = dirname(privacyModelPath()); await privateDirectory(directory);
    try {
      await verifyInstalledModel();
      if (!options.downloadOnly) await updatePrivacyPreferences((p) => ({ ...p, enabled: true, offerSeen: true }));
      return;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT" && (error as { code?: string }).code !== "privacy_model_integrity_failed") throw error;
    }
    const space = await statfs(directory);
    if (Number(space.bavail) * Number(space.bsize) < 4 * 2 ** 30) throw new Error("Keep at least 4 GiB free for installation and safe updates.");
    const partial = join(directory, "download.part");
    try {
      const stage = await lstat(partial);
      if (!stage.isFile() || stage.isSymbolicLink() || stage.mode & 0o077 || process.getuid && stage.uid !== process.getuid()) throw privacyError("privacy_unsafe_download");
    } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
    if (options.modelFile) { await copyFile(resolve(options.modelFile), partial); await chmod(partial, 0o600); }
    else {
      let received = 0;
      try { const s = await lstat(partial); if (!s.isFile() || s.isSymbolicLink() || (s.mode & 0o077)) throw privacyError("privacy_unsafe_download"); received = s.size; }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
      if (received > PRIVACY_MODEL.bytes) { await rm(partial); received = 0; }
      if (received < PRIVACY_MODEL.bytes) {
        const response = await fetch(PRIVACY_MODEL.url, { headers: received ? { Range: `bytes=${received}-` } : {}, signal: AbortSignal.timeout(30 * 60_000) });
        if (!(response.status === 200 || response.status === 206) || !response.body) throw new Error("Model download failed. Retry to resume it.");
        if (response.status === 200) received = 0;
        if (response.status === 206 && !response.headers.get("content-range")?.startsWith(`bytes ${received}-`)) throw privacyError("privacy_invalid_download_range");
        const file = await open(partial, received ? "a" : "w", 0o600);
        try {
          for await (const chunk of response.body) {
            received += chunk.length; if (received > PRIVACY_MODEL.bytes) throw privacyError("privacy_invalid_download_size");
            await file.writeFile(chunk); options.progress?.(received, PRIVACY_MODEL.bytes);
          }
          await file.sync();
        } finally { await file.close(); }
      }
    }
    if ((await lstat(partial)).size !== PRIVACY_MODEL.bytes || await fileDigest(partial) !== PRIVACY_MODEL.sha256) {
      await rm(partial, { force: true }); throw privacyError("privacy_model_integrity_failed");
    }
    await rename(partial, privacyModelPath());
    await writePrivateJson(join(directory, "installation.json"), { sha256: PRIVACY_MODEL.sha256, bytes: PRIVACY_MODEL.bytes, revision: PRIVACY_MODEL.revision });
    if (!options.downloadOnly) await updatePrivacyPreferences((p) => ({ ...p, enabled: true, offerSeen: true }));
  } finally { await release(); }
}
