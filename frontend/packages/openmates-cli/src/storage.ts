/*
 * OpenMates CLI local session storage.
 *
 * Purpose: persist pair-login session data and local-only incognito chats.
 * Architecture: filesystem state in ~/.openmates with strict permissions.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: chmod 700 dir and 600 files on write.
 * Tests: frontend/packages/openmates-cli/tests/storage.test.ts
 */

import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export interface OpenMatesSession {
  apiUrl: string;
  sessionId: string;
  wsToken: string | null;
  cookies: Record<string, string>;
  masterKeyExportedB64: string;
  hashedEmail: string;
  userEmailSalt: string;
  createdAt: number;
  authorizerDeviceName: string | null;
  autoLogoutMinutes: number | null;
}

export interface IncognitoHistoryItem {
  role: "user" | "assistant";
  content: string;
  createdAt: number;
}

function getStateDir(): string {
  return join(homedir(), ".openmates");
}

function ensureStateDir(): string {
  const dir = getStateDir();
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  }
  chmodSync(dir, 0o700);
  return dir;
}

function readJsonFile<T>(filePath: string): T | null {
  if (!existsSync(filePath)) {
    return null;
  }
  try {
    return JSON.parse(readFileSync(filePath, "utf-8")) as T;
  } catch {
    return null;
  }
}

function writeJsonFile(filePath: string, data: unknown): void {
  writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, {
    mode: 0o600,
  });
  chmodSync(filePath, 0o600);
}

export function saveSession(session: OpenMatesSession): void {
  const filePath = join(ensureStateDir(), "session.json");
  writeJsonFile(filePath, session);
}

export function loadSession(): OpenMatesSession | null {
  const filePath = join(ensureStateDir(), "session.json");
  return readJsonFile<OpenMatesSession>(filePath);
}

export function clearSession(): void {
  const filePath = join(ensureStateDir(), "session.json");
  if (existsSync(filePath)) {
    rmSync(filePath);
  }
}

export function loadIncognitoHistory(): IncognitoHistoryItem[] {
  const filePath = join(ensureStateDir(), "incognito.json");
  return readJsonFile<IncognitoHistoryItem[]>(filePath) ?? [];
}

export function saveIncognitoHistory(items: IncognitoHistoryItem[]): void {
  const filePath = join(ensureStateDir(), "incognito.json");
  writeJsonFile(filePath, items);
}

export function clearIncognitoHistory(): void {
  const filePath = join(ensureStateDir(), "incognito.json");
  writeJsonFile(filePath, []);
}
