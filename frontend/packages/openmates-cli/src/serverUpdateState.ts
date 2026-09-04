/**
 * Durable host state and process locking for CLI-managed server updates.
 * Status writes are atomic so an interrupted write cannot discard a pending
 * email idempotency identity. One install-scoped lock prevents concurrent update
 * processes from applying containers or sending completion mail simultaneously.
 */

import { randomBytes } from "node:crypto";
import { chmodSync, closeSync, existsSync, mkdirSync, openSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { ServerRole } from "./serverPlanning.js";

export function serverUpdateStatusFile(installPath: string, role: ServerRole): string {
  return join(installPath, ".openmates", `${role}-update-status.json`);
}

export function readServerUpdateStatus(installPath: string, role: ServerRole): Record<string, unknown> {
  const filePath = serverUpdateStatusFile(installPath, role);
  if (!existsSync(filePath)) return {};
  try {
    const parsed = JSON.parse(readFileSync(filePath, "utf-8")) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { statusReadError: "invalid_update_status" };
    }
    return parsed as Record<string, unknown>;
  } catch {
    return { statusReadError: "invalid_update_status" };
  }
}

export function writeServerUpdateStatus(installPath: string, role: ServerRole, status: Record<string, unknown>): void {
  const filePath = serverUpdateStatusFile(installPath, role);
  mkdirSync(dirname(filePath), { recursive: true, mode: 0o700 });
  const temporaryPath = `${filePath}.${process.pid}.${randomBytes(4).toString("hex")}.tmp`;
  writeFileSync(temporaryPath, `${JSON.stringify({ role, updated_at: new Date().toISOString(), ...status }, null, 2)}\n`, { mode: 0o600 });
  renameSync(temporaryPath, filePath);
  chmodSync(filePath, 0o600);
}

export function acquireServerUpdateLock(installPath: string): () => void {
  const stateDir = join(installPath, ".openmates");
  const lockPath = join(stateDir, "server-update.lock");
  mkdirSync(stateDir, { recursive: true, mode: 0o700 });
  let descriptor: number;
  try {
    descriptor = openSync(lockPath, "wx", 0o600);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    const lockOwner = readFileSync(lockPath, "utf8").trim();
    const lockPid = Number.parseInt(lockOwner.split(":", 1)[0] ?? "", 10);
    let stale = false;
    try {
      if (Number.isFinite(lockPid)) process.kill(lockPid, 0);
    } catch (ownerError) {
      if ((ownerError as NodeJS.ErrnoException).code === "ESRCH") stale = true;
      else throw ownerError;
    }
    throw new Error(stale
      ? "A stale OpenMates server update lock exists for this installation; verify no update is running, then remove .openmates/server-update.lock explicitly."
      : "Another OpenMates server update is already running for this installation.");
  }
  const ownershipToken = `${process.pid}:${randomBytes(16).toString("hex")}`;
  writeFileSync(descriptor, ownershipToken);
  return () => {
    closeSync(descriptor);
    if (existsSync(lockPath) && readFileSync(lockPath, "utf8").trim() === ownershipToken) {
      rmSync(lockPath);
    }
  };
}
