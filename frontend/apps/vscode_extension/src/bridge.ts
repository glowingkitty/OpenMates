/*
 * OpenMates VS Code webview bridge contract.
 *
 * Purpose: expose the tiny native VS Code surface needed by the bundled app.
 * Architecture: the webview sends typed messages; the extension host handles
 * mapped file opening and readonly diff display only.
 * Security: V1 deliberately excludes file writes, patch application, terminal
 * commands, package installs, tests, and git mutations.
 */

export const ALLOWED_WEBVIEW_MESSAGE_TYPES = [
  "openFile",
  "showDiff",
  "copyText",
  "reportReady",
] as const;

export const FORBIDDEN_V1_MESSAGE_TYPES = [
  "applyPatch",
  "writeFile",
  "runCommand",
  "installPackage",
  "runTests",
  "gitCommit",
  "gitPush",
] as const;

export type AllowedWebviewMessageType = (typeof ALLOWED_WEBVIEW_MESSAGE_TYPES)[number];

export interface OpenFileMessage {
  type: "openFile";
  sourceId?: string;
  path: string;
}

export interface ShowDiffMessage {
  type: "showDiff";
  sourceId?: string;
  path: string;
  original: string;
  modified: string;
  language?: string;
}

export interface CopyTextMessage {
  type: "copyText";
  text: string;
}

export interface ReportReadyMessage {
  type: "reportReady";
}

export type AllowedWebviewMessage =
  | OpenFileMessage
  | ShowDiffMessage
  | CopyTextMessage
  | ReportReadyMessage;

export interface BridgeHandlers {
  openFile(message: OpenFileMessage): Promise<unknown> | unknown;
  showDiff(message: ShowDiffMessage): Promise<unknown> | unknown;
  copyText(message: CopyTextMessage): Promise<unknown> | unknown;
  reportReady(message: ReportReadyMessage): Promise<unknown> | unknown;
}

const MAX_BRIDGE_TEXT_LENGTH = 2_000_000;

export function isAllowedWebviewMessageType(type: string): type is AllowedWebviewMessageType {
  return (ALLOWED_WEBVIEW_MESSAGE_TYPES as readonly string[]).includes(type);
}

export function assertNoMutationMessageTypes(messageTypes: readonly string[] = ALLOWED_WEBVIEW_MESSAGE_TYPES): void {
  const forbidden = messageTypes.filter((type) =>
    (FORBIDDEN_V1_MESSAGE_TYPES as readonly string[]).includes(type),
  );
  if (forbidden.length > 0) {
    throw new Error(`VS Code V1 bridge exposes forbidden mutation messages: ${forbidden.join(", ")}`);
  }
}

export async function handleWebviewMessage(
  rawMessage: unknown,
  handlers: BridgeHandlers,
): Promise<unknown> {
  const message = parseAllowedWebviewMessage(rawMessage);
  assertNoMutationMessageTypes();
  return handlers[message.type](message as never);
}

export function parseAllowedWebviewMessage(rawMessage: unknown): AllowedWebviewMessage {
  if (!isObjectWithType(rawMessage)) {
    throw new Error("Invalid OpenMates VS Code bridge message.");
  }
  if (!isAllowedWebviewMessageType(rawMessage.type)) {
    throw new Error(`Unsupported OpenMates VS Code bridge message: ${rawMessage.type}`);
  }
  if (rawMessage.type === "reportReady") return { type: "reportReady" };
  if (rawMessage.type === "copyText") {
    return { type: "copyText", text: requireBoundedString(rawMessage, "text") };
  }
  if (rawMessage.type === "openFile") {
    return {
      type: "openFile",
      path: requireSafeRelativePath(rawMessage),
      sourceId: optionalBoundedString(rawMessage, "sourceId"),
    };
  }
  return {
    type: "showDiff",
    path: requireSafeRelativePath(rawMessage),
    sourceId: optionalBoundedString(rawMessage, "sourceId"),
    original: requireBoundedString(rawMessage, "original"),
    modified: requireBoundedString(rawMessage, "modified"),
    language: optionalBoundedString(rawMessage, "language"),
  };
}

function isObjectWithType(value: unknown): value is { type: string } {
  return typeof value === "object" && value !== null && typeof (value as { type?: unknown }).type === "string";
}

function requireBoundedString(value: object, key: string): string {
  const field = (value as Record<string, unknown>)[key];
  if (typeof field !== "string" || field.length > MAX_BRIDGE_TEXT_LENGTH) {
    throw new Error(`Invalid OpenMates VS Code bridge field: ${key}`);
  }
  return field;
}

function optionalBoundedString(value: object, key: string): string | undefined {
  const field = (value as Record<string, unknown>)[key];
  if (field === undefined) return undefined;
  if (typeof field !== "string" || field.length > MAX_BRIDGE_TEXT_LENGTH) {
    throw new Error(`Invalid OpenMates VS Code bridge field: ${key}`);
  }
  return field;
}

function requireSafeRelativePath(value: object): string {
  const filePath = requireBoundedString(value, "path");
  if (
    filePath.startsWith("/") ||
    filePath.startsWith("~/") ||
    /^[A-Za-z]:[\\/]/.test(filePath) ||
    filePath.includes("\0") ||
    filePath.split(/[\\/]/).some((part) => part === "..")
  ) {
    throw new Error("Invalid OpenMates VS Code bridge path.");
  }
  return filePath;
}
