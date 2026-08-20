/**
 * Authenticated quick functional checks for CLI-managed OpenMates servers.
 *
 * The module keeps instance binding, credit consent decisions, synthetic chat
 * cleanup, and sanitized result shaping independent from terminal/update code.
 * It reuses the first-party CLI client's existing chat and app-skill surfaces.
 */

import { randomUUID } from "node:crypto";

export type QuickServerRole = "core" | "upload" | "preview";
export type QuickServerTestAction = "prompt" | "run" | "skip";
export type QuickServerTestCheckStatus = "passed" | "failed";

export interface QuickServerTestClient {
  readonly apiUrl: string;
  hasSession(): boolean;
  getSession(): { apiUrl: string };
  sendMessage(params: {
    message: string;
    chatId?: string;
    personal?: boolean;
    taskUpdateJobs?: boolean;
    autoApproveSubChats?: boolean;
    autoApproveMemories?: boolean;
    responseTimeoutMs?: number;
  }): Promise<{
    status: "completed" | "waiting_for_user";
    chatId: string;
    messageId: string | null;
    assistant: string;
  }>;
  getChatMessages(chatId: string, options?: { personal?: boolean }): Promise<{ messages: Array<{ role?: string; content?: string }> }>;
  deleteChat(chatId: string, options?: { personal?: boolean }): Promise<void>;
  runSkill(params: {
    app: string;
    skill: string;
    inputData: Record<string, unknown>;
  }): Promise<unknown>;
}

export interface QuickServerTestCheck {
  id: string;
  status: QuickServerTestCheckStatus;
  duration_ms: number;
  sanitized_reason?: string;
}

export interface QuickServerTestResult {
  status: "passed" | "failed";
  completed_at: string;
  checks: QuickServerTestCheck[];
}

export type QuickServerTestEligibility =
  | { status: "ready"; expectedOrigin: string }
  | {
      status: "not_applicable";
      reason: "non_core_role";
    }
  | {
      status: "login_required";
      reason: "session_missing" | "session_instance_mismatch";
      expectedOrigin: string;
      loginCommand: string;
      rerunCommand: string;
    };

const QUICK_TEST_RESPONSE_TIMEOUT_MS = 120_000;
const QUICK_TEST_WEB_QUERY = "site:openmates.org OpenMates";
const QUICK_TEST_EXPECTED_RESPONSE = "server quick test passed";

export function normalizedApiOrigin(apiUrl: string): string {
  return new URL(apiUrl).origin;
}

export function assessQuickServerTestEligibility(input: {
  role: QuickServerRole;
  expectedApiUrl: string;
  client: Pick<QuickServerTestClient, "apiUrl" | "hasSession" | "getSession">;
}): QuickServerTestEligibility {
  if (input.role !== "core") {
    return { status: "not_applicable", reason: "non_core_role" };
  }

  const expectedOrigin = normalizedApiOrigin(input.expectedApiUrl);
  const guidance = {
    expectedOrigin,
    loginCommand: `openmates --api-url ${expectedOrigin} login`,
    rerunCommand: "openmates server test --quick",
  };
  if (!input.client.hasSession()) {
    return { status: "login_required", reason: "session_missing", ...guidance };
  }

  let sessionOrigin: string;
  try {
    sessionOrigin = normalizedApiOrigin(input.client.getSession().apiUrl);
  } catch {
    return { status: "login_required", reason: "session_missing", ...guidance };
  }
  let requestOrigin: string;
  try {
    requestOrigin = normalizedApiOrigin(input.client.apiUrl);
  } catch {
    return { status: "login_required", reason: "session_instance_mismatch", ...guidance };
  }
  if (sessionOrigin !== expectedOrigin || requestOrigin !== expectedOrigin) {
    return { status: "login_required", reason: "session_instance_mismatch", ...guidance };
  }
  return { status: "ready", expectedOrigin };
}

export function decideQuickServerTestAction(input: {
  interactive: boolean;
  json?: boolean;
  continuous?: boolean;
  skipQuickTest?: boolean;
  quickTest?: boolean;
  confirmSpendCredits?: boolean;
  yes?: boolean;
}): QuickServerTestAction {
  if (input.skipQuickTest) return "skip";
  if (input.json || input.continuous) {
    return input.quickTest && input.confirmSpendCredits ? "run" : "skip";
  }
  if (input.confirmSpendCredits) return "run";
  if (!input.interactive) {
    return input.quickTest && input.confirmSpendCredits ? "run" : "skip";
  }
  return "prompt";
}

export async function runQuickServerTest(
  client: QuickServerTestClient,
  options: { now?: () => number } = {},
): Promise<QuickServerTestResult> {
  const now = options.now ?? Date.now;
  const checks: QuickServerTestCheck[] = [];
  const chatId = randomUUID();
  let chatMayExist = false;

  checks.push({ id: "account.session", status: "passed", duration_ms: 0 });

  const createStarted = now();
  try {
    const marker = randomUUID();
    chatMayExist = true;
    const response = await client.sendMessage({
      message: `OpenMates server quick test ${marker}. Reply with exactly: ${QUICK_TEST_EXPECTED_RESPONSE}`,
      chatId,
      personal: true,
      taskUpdateJobs: false,
      autoApproveSubChats: false,
      autoApproveMemories: false,
      responseTimeoutMs: QUICK_TEST_RESPONSE_TIMEOUT_MS,
    });
    if (
      response.status !== "completed"
      || response.chatId !== chatId
      || !response.messageId
      || response.assistant.trim().toLowerCase() !== QUICK_TEST_EXPECTED_RESPONSE
    ) {
      throw new Error("incomplete_chat_response");
    }
    checks.push(passedCheck("chat.create", createStarted, now));
  } catch {
    checks.push(failedCheck("chat.create", "chat_create_failed", createStarted, now));
  }

  const reloadStarted = now();
  if (chatMayExist) {
    try {
      const reloaded = await client.getChatMessages(chatId, { personal: true });
      const roles = new Set(reloaded.messages.map((message) => message.role));
      if (!roles.has("user") || !roles.has("assistant")) throw new Error("chat_messages_missing");
      checks.push(passedCheck("chat.reload", reloadStarted, now));
    } catch {
      checks.push(failedCheck("chat.reload", "chat_reload_failed", reloadStarted, now));
    }
  } else {
    checks.push(failedCheck("chat.reload", "chat_not_created", reloadStarted, now));
  }

  const mathStarted = now();
  try {
    const result = await client.runSkill({
      app: "math",
      skill: "calculate",
      inputData: { expression: "2 + 2", title: "Server quick test" },
    });
    if (!containsExpectedMathResult(result)) throw new Error("unexpected_math_result");
    checks.push(passedCheck("app.math.calculate", mathStarted, now));
  } catch {
    checks.push(failedCheck("app.math.calculate", "math_calculate_failed", mathStarted, now));
  }

  const webStarted = now();
  try {
    const result = await client.runSkill({
      app: "web",
      skill: "search",
      inputData: { requests: [{ id: "quick", query: QUICK_TEST_WEB_QUERY, count: 1 }] },
    });
    if (!containsBoundedWebResult(result)) throw new Error("unexpected_web_search_result");
    checks.push(passedCheck("app.web.search", webStarted, now));
  } catch {
    checks.push(failedCheck("app.web.search", "web_search_failed", webStarted, now));
  }

  const cleanupStarted = now();
  if (chatMayExist) {
    try {
      await client.deleteChat(chatId, { personal: true });
      checks.push(passedCheck("chat.cleanup", cleanupStarted, now));
    } catch {
      checks.push(failedCheck("chat.cleanup", "chat_cleanup_failed", cleanupStarted, now));
    }
  } else {
    checks.push({ id: "chat.cleanup", status: "passed", duration_ms: 0, sanitized_reason: "not_required" });
  }

  return {
    status: checks.every((check) => check.status === "passed") ? "passed" : "failed",
    completed_at: new Date(now()).toISOString(),
    checks,
  };
}

function passedCheck(id: string, startedAt: number, now: () => number): QuickServerTestCheck {
  return { id, status: "passed", duration_ms: Math.max(0, now() - startedAt) };
}

function failedCheck(id: string, reason: string, startedAt: number, now: () => number): QuickServerTestCheck {
  return { id, status: "failed", duration_ms: Math.max(0, now() - startedAt), sanitized_reason: reason };
}

function containsExpectedMathResult(value: unknown): boolean {
  if (value === 4 || value === "4") return true;
  if (Array.isArray(value)) return value.some(containsExpectedMathResult);
  if (!value || typeof value !== "object") return false;
  return Object.values(value).some(containsExpectedMathResult);
}

function containsBoundedWebResult(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsBoundedWebResult);
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  if (Array.isArray(record.results)) {
    const directResults = record.results.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"));
    if (directResults.some((item) => typeof item.title === "string" && typeof item.url === "string")) return true;
  }
  return Object.values(record).some(containsBoundedWebResult);
}
