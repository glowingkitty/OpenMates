/*
 * Account Import V1 CLI parsing helpers.
 *
 * Purpose: normalize user-provided Claude/ChatGPT/OpenCode/OpenMates exports before the
 * CLI calls the backend preview and transient scan endpoints.
 * Architecture: docs/specs/account-import-v1/spec.yml.
 * Security: source fingerprints are one-way hashes; raw provider exports stay
 * local and are never logged by these helpers.
 */

import { createDecipheriv, createHash, scryptSync } from "node:crypto";
import JSZip from "jszip";

const ENCRYPTED_ZIP_MAGIC = "OMZIP1";
const ENCRYPTED_ZIP_KEY_BYTES = 32;
export const ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE = 250;
export const COMPRESSION_SUMMARY_CATEGORY = "compression_summary";

export type AccountImportSource = "openmates" | "chatgpt" | "claude" | "gemini" | "opencode" | "other";
export type AccountImportParserFormat = "claude" | "chatgpt" | "openmates" | "opencode" | "generic";

export interface ImportedAssistantIdentity {
  category: AccountImportSource;
  sender_name: string;
  model_name: string;
  avatar_key: string;
}

export const ACCOUNT_IMPORT_SOURCE_IDENTITIES: Record<AccountImportSource, ImportedAssistantIdentity> = {
  openmates: { category: "openmates", sender_name: "OpenMates", model_name: "OpenMates", avatar_key: "openmates" },
  chatgpt: { category: "chatgpt", sender_name: "ChatGPT", model_name: "ChatGPT", avatar_key: "chatgpt" },
  claude: { category: "claude", sender_name: "Claude", model_name: "Claude", avatar_key: "claude" },
  gemini: { category: "gemini", sender_name: "Gemini", model_name: "Gemini", avatar_key: "gemini" },
  opencode: { category: "opencode", sender_name: "OpenCode", model_name: "OpenCode", avatar_key: "opencode" },
  other: { category: "other", sender_name: "AI assistant", model_name: "Other", avatar_key: "ai-star" },
};

export interface ParsedImportMessage {
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string | null;
  source_message_id?: string | null;
  provider_metadata: Record<string, unknown>;
  imported_assistant_identity: ImportedAssistantIdentity | null;
}

export interface ParsedImportUpload {
  source_upload_id: string;
  file_name: string;
  mime_type?: string | null;
  bytes?: number | null;
  content_ref: string;
}

export interface ParsedImportChat {
  provider: AccountImportSource;
  parser_format: AccountImportParserFormat;
  selected_source: AccountImportSource;
  source_chat_id: string;
  source_fingerprint: string;
  title?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  messages: ParsedImportMessage[];
  embeds: Array<Record<string, unknown>>;
  uploads: ParsedImportUpload[];
  provider_labels: string[];
  source_metadata: Record<string, unknown>;
}

export interface ParsedAccountImport {
  source: AccountImportSource;
  parserFormat: AccountImportParserFormat;
  chats: ParsedImportChat[];
  skippedDomains: string[];
}

export interface AccountImportMessageBatch {
  chatIndex: number;
  chunkIndex: number;
  sourceFingerprint: string;
  batchId: string;
  chat: ParsedImportChat;
}

export function buildAccountImportMessageBatches(
  chats: ParsedImportChat[],
  maxMessages = ACCOUNT_IMPORT_MESSAGE_BATCH_SIZE,
): AccountImportMessageBatch[] {
  if (!Number.isInteger(maxMessages) || maxMessages <= 0) throw new Error("Account import message batch size must be positive");
  return chats.flatMap((chat, chatIndex) => {
    const chunkCount = Math.max(1, Math.ceil(chat.messages.length / maxMessages));
    return Array.from({ length: chunkCount }, (_, chunkIndex) => ({
      chatIndex,
      chunkIndex,
      sourceFingerprint: chat.source_fingerprint,
      batchId: `scan-${chat.source_fingerprint.slice(0, 16)}-${chunkIndex}`,
      chat: {
        ...chat,
        messages: chat.messages.slice(chunkIndex * maxMessages, (chunkIndex + 1) * maxMessages),
      },
    }));
  });
}

export function appendCompressionSummary(
  chat: ParsedImportChat,
  summary: string | undefined,
): ParsedImportChat {
  if (!summary?.trim()) return chat;
  return {
    ...chat,
    messages: [...chat.messages, {
      role: "system",
      content: summary,
      created_at: null,
      source_message_id: null,
      provider_metadata: { import_type: COMPRESSION_SUMMARY_CATEGORY },
      imported_assistant_identity: null,
    }],
  };
}

function fingerprint(provider: AccountImportParserFormat, sourceChatId: string, messages: ParsedImportMessage[]): string {
  return createHash("sha256").update(JSON.stringify({
    provider,
    source_chat_id: sourceChatId,
    messages: messages.map((message) => ({
      role: message.role,
      source_message_id: message.source_message_id ?? null,
      content: message.content,
    })),
  })).digest("hex");
}

function finalizeImport(
  parserFormat: AccountImportParserFormat,
  selectedSource: AccountImportSource,
  chats: ParsedImportChat[],
  skippedDomains: string[],
): ParsedAccountImport {
  const identity = ACCOUNT_IMPORT_SOURCE_IDENTITIES[selectedSource];
  return {
    source: selectedSource,
    parserFormat,
    chats: chats.map((chat) => ({
      ...chat,
      provider: selectedSource,
      parser_format: parserFormat,
      selected_source: selectedSource,
      messages: chat.messages.map((message) => ({
        ...message,
        imported_assistant_identity: message.role === "assistant" ? { ...identity } : null,
      })),
    })),
    skippedDomains,
  };
}

async function readZipText(payload: Buffer, requiredName: string): Promise<string> {
  const zip = await JSZip.loadAsync(payload);
  const entry = zip.file(requiredName) ?? Object.values(zip.files).find((candidate) => {
    if (candidate.dir) return false;
    if (candidate.name.startsWith("__MACOSX/") || candidate.name.includes("/._") || candidate.name.startsWith("._")) return false;
    return candidate.name.split("/").pop() === requiredName;
  });
  if (!entry) throw new Error(`Import archive is missing ${requiredName}`);
  return entry.async("string");
}

function decryptOpenMatesEncryptedZip(payload: Buffer, password: string | undefined): Buffer {
  const magicPrefix = Buffer.from(`${ENCRYPTED_ZIP_MAGIC}\n`, "utf-8");
  if (!payload.subarray(0, magicPrefix.length).equals(magicPrefix)) return payload;
  if (!password) throw new Error("OpenMates encrypted export requires a password.");
  const lengthEnd = payload.indexOf(0x0a, magicPrefix.length);
  if (lengthEnd < 0) throw new Error("OpenMates encrypted export has an invalid header.");
  const headerLength = Number(payload.subarray(magicPrefix.length, lengthEnd).toString("utf-8"));
  if (!Number.isInteger(headerLength) || headerLength <= 0) throw new Error("OpenMates encrypted export has an invalid header length.");
  const headerStart = lengthEnd + 1;
  const headerEnd = headerStart + headerLength;
  const header = JSON.parse(payload.subarray(headerStart, headerEnd).toString("utf-8")) as Record<string, string | number>;
  if (header.magic !== ENCRYPTED_ZIP_MAGIC || header.cipher !== "aes-256-gcm" || header.kdf !== "scrypt") {
    throw new Error("OpenMates encrypted export uses an unsupported encryption format.");
  }
  const key = scryptSync(password, Buffer.from(String(header.salt), "base64"), ENCRYPTED_ZIP_KEY_BYTES);
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(String(header.iv), "base64"));
  decipher.setAuthTag(Buffer.from(String(header.tag), "base64"));
  try {
    return Buffer.concat([decipher.update(payload.subarray(headerEnd)), decipher.final()]);
  } catch (error) {
    throw new Error(`OpenMates encrypted export could not be decrypted: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function claudeMessageContent(message: Record<string, unknown>): { content: string; blockTypes: string[] } {
  const content = Array.isArray(message.content) ? message.content : [];
  const blockTypes: string[] = [];
  const textParts: string[] = [];
  for (const rawBlock of content) {
    if (!rawBlock || typeof rawBlock !== "object") continue;
    const block = rawBlock as Record<string, unknown>;
    const type = String(block.type ?? "unknown");
    blockTypes.push(type);
    if (type === "text" && typeof block.text === "string") textParts.push(block.text);
    if (type === "tool_result" && typeof block.content === "string") textParts.push(block.content);
  }
  return { content: textParts.length > 0 ? textParts.join("\n") : String(message.text ?? ""), blockTypes };
}

function claudeUploads(message: Record<string, unknown>): ParsedImportUpload[] {
  const items = [
    ...(Array.isArray(message.attachments) ? message.attachments : []),
    ...(Array.isArray(message.files) ? message.files : []),
  ];
  return items.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")).map((item, index) => {
    const fileName = String(item.file_name ?? item.name ?? `attachment-${index + 1}`);
    return {
      source_upload_id: String(item.uuid ?? item.id ?? fileName),
      file_name: fileName,
      mime_type: typeof item.mime_type === "string" ? item.mime_type : typeof item.file_type === "string" ? item.file_type : null,
      bytes: typeof item.file_size === "number" ? item.file_size : typeof item.bytes === "number" ? item.bytes : null,
      content_ref: fileName,
    };
  });
}

export async function parseClaudeImportBuffer(payload: Buffer, sourceName = "claude-export", selectedSource: AccountImportSource = "claude"): Promise<ParsedAccountImport> {
  let conversations: unknown;
  try {
    conversations = payload.subarray(0, 2).toString("binary") === "PK"
      ? JSON.parse(await readZipText(payload, "conversations.json"))
      : JSON.parse(payload.toString("utf-8"));
  } catch (error) {
    throw new Error(`Claude export could not be parsed: ${error instanceof Error ? error.message : String(error)}`);
  }
  const rawConversations = Array.isArray(conversations)
    ? conversations
    : conversations && typeof conversations === "object" && Array.isArray((conversations as Record<string, unknown>).conversations)
      ? (conversations as Record<string, unknown>).conversations as unknown[]
      : null;
  if (!rawConversations) throw new Error("Claude export conversations must be an array");

  const chats = rawConversations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")).map((conversation) => {
    const sourceChatId = String(conversation.uuid ?? "");
    if (!sourceChatId) throw new Error("Claude conversation is missing uuid");
    const messages = (Array.isArray(conversation.chat_messages) ? conversation.chat_messages : [])
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
      .map((message) => {
        const { content, blockTypes } = claudeMessageContent(message);
        const sender = String(message.sender ?? "");
        return {
          role: sender === "human" ? "user" : sender === "assistant" ? "assistant" : "system",
          content,
          created_at: typeof message.created_at === "string" ? message.created_at : null,
          source_message_id: typeof message.uuid === "string" ? message.uuid : null,
          provider_metadata: { content_block_types: blockTypes },
          imported_assistant_identity: null,
        } satisfies ParsedImportMessage;
      });
    return {
      provider: "claude",
      parser_format: "claude",
      selected_source: selectedSource,
      source_chat_id: sourceChatId,
      source_fingerprint: fingerprint("claude", sourceChatId, messages),
      title: typeof conversation.name === "string" ? conversation.name : null,
      created_at: typeof conversation.created_at === "string" ? conversation.created_at : null,
      updated_at: typeof conversation.updated_at === "string" ? conversation.updated_at : null,
      messages,
      embeds: [],
      uploads: (Array.isArray(conversation.chat_messages) ? conversation.chat_messages : [])
        .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
        .flatMap(claudeUploads),
      provider_labels: ["claude"],
      source_metadata: { source_name: sourceName, message_count: messages.length },
    } satisfies ParsedImportChat;
  });
  return finalizeImport("claude", selectedSource, chats, []);
}

function chatGPTTimestamp(value: unknown): string | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? new Date(value * 1000).toISOString()
    : null;
}

function chatGPTContentText(content: Record<string, unknown>): { content: string; metadata: Record<string, unknown> } {
  const parts = Array.isArray(content.parts) ? content.parts : [];
  const textParts: string[] = [];
  let assetCount = 0;
  for (const part of parts) {
    if (typeof part === "string" && part.trim()) textParts.push(part);
    else if (part && typeof part === "object" && "asset_pointer" in part) assetCount++;
  }
  if (parts.length === 0 && typeof content.content === "string") textParts.push(content.content);
  return { content: textParts.join("\n"), metadata: { content_type: String(content.content_type ?? "unknown"), asset_count: assetCount } };
}

function chatGPTActiveNodes(conversation: Record<string, unknown>): Record<string, unknown>[] {
  const mapping = conversation.mapping;
  if (!mapping || typeof mapping !== "object" || Array.isArray(mapping)) throw new Error("ChatGPT conversation is missing mapping");
  const nodesById = mapping as Record<string, Record<string, unknown>>;
  const currentNode = String(conversation.current_node ?? "");
  if (currentNode && nodesById[currentNode]) {
    const ordered: Record<string, unknown>[] = [];
    const seen = new Set<string>();
    let nodeId = currentNode;
    while (nodeId && nodesById[nodeId] && !seen.has(nodeId)) {
      seen.add(nodeId);
      const node = nodesById[nodeId];
      ordered.push(node);
      nodeId = String(node.parent ?? "");
    }
    return ordered.reverse();
  }
  return Object.values(nodesById).sort((left, right) => {
    const leftMessage = left.message && typeof left.message === "object" ? left.message as Record<string, unknown> : {};
    const rightMessage = right.message && typeof right.message === "object" ? right.message as Record<string, unknown> : {};
    return Number(leftMessage.create_time ?? 0) - Number(rightMessage.create_time ?? 0);
  });
}

export async function parseChatGPTImportBuffer(payload: Buffer, sourceName = "chatgpt-export", selectedSource: AccountImportSource = "chatgpt"): Promise<ParsedAccountImport> {
  let conversations: unknown;
  try {
    conversations = payload.subarray(0, 2).toString("binary") === "PK"
      ? JSON.parse(await readZipText(payload, "conversations.json"))
      : JSON.parse(payload.toString("utf-8"));
  } catch (error) {
    throw new Error(`ChatGPT export could not be parsed: ${error instanceof Error ? error.message : String(error)}`);
  }
  const rawConversations = Array.isArray(conversations)
    ? conversations
    : conversations && typeof conversations === "object" && Array.isArray((conversations as Record<string, unknown>).conversations)
      ? (conversations as Record<string, unknown>).conversations as unknown[]
      : null;
  if (!rawConversations) throw new Error("ChatGPT export conversations must be an array");

  const chats = rawConversations.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object")).map((conversation) => {
    const sourceChatId = String(conversation.conversation_id ?? conversation.id ?? "");
    if (!sourceChatId) throw new Error("ChatGPT conversation is missing id");
    const messages: ParsedImportMessage[] = [];
    for (const node of chatGPTActiveNodes(conversation)) {
      const rawMessage = node.message && typeof node.message === "object" ? node.message as Record<string, unknown> : null;
      if (!rawMessage) continue;
      const author = rawMessage.author && typeof rawMessage.author === "object" ? rawMessage.author as Record<string, unknown> : {};
      const role = String(author.role ?? "");
      if (role !== "user" && role !== "assistant" && role !== "system") continue;
      const rawContent = rawMessage.content && typeof rawMessage.content === "object" ? rawMessage.content as Record<string, unknown> : null;
      if (!rawContent) continue;
      const { content, metadata } = chatGPTContentText(rawContent);
      if (!content.trim()) continue;
      messages.push({
        role,
        content,
        created_at: chatGPTTimestamp(rawMessage.create_time),
        source_message_id: typeof rawMessage.id === "string" ? rawMessage.id : null,
        provider_metadata: metadata,
        imported_assistant_identity: null,
      });
    }
    return {
      provider: "chatgpt",
      parser_format: "chatgpt",
      selected_source: selectedSource,
      source_chat_id: sourceChatId,
      source_fingerprint: fingerprint("chatgpt", sourceChatId, messages),
      title: typeof conversation.title === "string" ? conversation.title : null,
      created_at: chatGPTTimestamp(conversation.create_time),
      updated_at: chatGPTTimestamp(conversation.update_time),
      messages,
      embeds: [],
      uploads: [],
      provider_labels: ["chatgpt"],
      source_metadata: { source_name: sourceName, message_count: messages.length },
    } satisfies ParsedImportChat;
  });
  return finalizeImport("chatgpt", selectedSource, chats, []);
}

function openCodeTimestamp(value: unknown): string | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? new Date(value).toISOString() : null;
}

export async function parseOpenCodeImportBuffer(payload: Buffer, sourceName = "opencode-session.json", selectedSource: AccountImportSource = "opencode"): Promise<ParsedAccountImport> {
  let transcript: unknown;
  try {
    transcript = JSON.parse(payload.toString("utf-8"));
  } catch (error) {
    throw new Error(`OpenCode transcript export could not be parsed: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!transcript || typeof transcript !== "object" || Array.isArray(transcript)) throw new Error("OpenCode transcript export must be an object");
  const record = transcript as Record<string, unknown>;
  const info = record.info && typeof record.info === "object" ? record.info as Record<string, unknown> : null;
  const rawMessages = Array.isArray(record.messages) ? record.messages : null;
  const sourceChatId = String(info?.id ?? "");
  if (!info || !sourceChatId || !rawMessages) throw new Error("OpenCode transcript export is missing info.id or messages");

  const messages: ParsedImportMessage[] = [];
  for (const item of rawMessages) {
    if (!item || typeof item !== "object") continue;
    const message = item as Record<string, unknown>;
    const messageInfo = message.info && typeof message.info === "object" ? message.info as Record<string, unknown> : {};
    const role = String(messageInfo.role ?? "");
    if (role !== "user" && role !== "assistant") continue;
    const parts = Array.isArray(message.parts)
      ? message.parts.filter((part): part is Record<string, unknown> => Boolean(part && typeof part === "object"))
      : [];
    const textParts = parts.filter((part) => part.type === "text" && part.ignored !== true && typeof part.text === "string");
    const content = textParts.map((part) => String(part.text)).filter((text) => text.trim()).join("\n");
    if (content.trim()) {
      const time = messageInfo.time && typeof messageInfo.time === "object" ? messageInfo.time as Record<string, unknown> : {};
      messages.push({
        role,
        content,
        created_at: openCodeTimestamp(time.created),
        source_message_id: typeof messageInfo.id === "string" ? messageInfo.id : null,
        provider_metadata: { part_types: parts.map((part) => String(part.type ?? "unknown")), text_part_count: textParts.length },
        imported_assistant_identity: null,
      });
    }
  }
  const time = info.time && typeof info.time === "object" ? info.time as Record<string, unknown> : {};
  return finalizeImport("opencode", selectedSource, [{
    provider: "opencode",
    parser_format: "opencode",
    selected_source: selectedSource,
    source_chat_id: sourceChatId,
    source_fingerprint: fingerprint("opencode", sourceChatId, messages),
    title: typeof info.title === "string" ? info.title : null,
    created_at: openCodeTimestamp(time.created),
    updated_at: openCodeTimestamp(time.updated),
    messages,
    embeds: [],
    uploads: [],
    provider_labels: ["opencode"],
    source_metadata: { source_name: sourceName, message_count: messages.length },
  }], []);
}

function parseOpenMatesManifestDomains(manifestText: string): string[] {
  const lines = manifestText.split(/\r?\n/);
  const domains: string[] = [];
  let inDomains = false;
  for (const line of lines) {
    if (/^domains:\s*$/.test(line)) {
      inDomains = true;
      continue;
    }
    if (inDomains && /^\S/.test(line)) break;
    const match = inDomains ? line.match(/^\s{2}([a-zA-Z0-9_-]+):/) : null;
    if (match) domains.push(match[1]);
  }
  return domains;
}

export async function parseOpenMatesImportBuffer(payload: Buffer, sourceName = "openmates-export.zip", password?: string, selectedSource: AccountImportSource = "openmates"): Promise<ParsedAccountImport> {
  const zip = await JSZip.loadAsync(decryptOpenMatesEncryptedZip(payload, password));
  const manifest = await zip.file("manifest.yml")?.async("string");
  if (!manifest) throw new Error("OpenMates Export V1 archive is missing manifest.yml");
  if (!/format:\s*openmates-account-export/.test(manifest) || !/version:\s*["']?1["']?/.test(manifest)) {
    throw new Error("Unsupported OpenMates Export V1 archive format or version");
  }
  const domains = parseOpenMatesManifestDomains(manifest);
  const skippedDomains = domains.filter((domain) => !["chats", "embeds", "uploads", "referenced_uploads"].includes(domain)).sort();
  const chatFiles = Object.keys(zip.files).filter((name) => name.startsWith("chats/") && /\.ya?ml$/.test(name));
  const chats = chatFiles.map((name) => {
    const sourceChatId = name.split("/").pop()?.replace(/\.ya?ml$/, "") || name;
    const messages: ParsedImportMessage[] = [];
    return {
      provider: "openmates",
      parser_format: "openmates",
      selected_source: selectedSource,
      source_chat_id: sourceChatId,
      source_fingerprint: fingerprint("openmates", sourceChatId, messages),
      title: sourceChatId,
      created_at: null,
      updated_at: null,
      messages,
      embeds: [],
      uploads: [],
      provider_labels: ["openmates"],
      source_metadata: { source_name: sourceName, archive_path: name },
    } satisfies ParsedImportChat;
  });
  if (chats.length === 0) throw new Error("OpenMates Export V1 archive contains no chat YAML files");
  return finalizeImport("openmates", selectedSource, chats, skippedDomains);
}

export async function parseGenericImportBuffer(
  payload: Buffer,
  sourceName = "generic-transcript.json",
  selectedSource: "gemini" | "other",
): Promise<ParsedAccountImport> {
  let decoded: unknown;
  try {
    decoded = JSON.parse(payload.toString("utf-8"));
  } catch (error) {
    throw new Error(`Generic role/content transcript could not be parsed: ${error instanceof Error ? error.message : String(error)}`);
  }
  const rawChats = Array.isArray(decoded) ? decoded : [decoded];
  if (rawChats.length === 0 || rawChats.some((chat) => !chat || typeof chat !== "object" || Array.isArray(chat) || !Array.isArray((chat as Record<string, unknown>).messages))) {
    throw new Error("Generic role/content transcript must be a chat object or array of chat objects with messages arrays");
  }
  const chats = rawChats.map((rawChat, chatIndex) => {
    const chat = rawChat as Record<string, unknown>;
    const allowedChatFields = new Set(["id", "title", "created_at", "updated_at", "messages"]);
    const unknownChatFields = Object.keys(chat).filter((key) => !allowedChatFields.has(key));
    if (unknownChatFields.length > 0) {
      throw new Error(`Generic role/content transcript contains unknown chat fields: ${unknownChatFields.join(", ")}`);
    }
    const rawMessages = chat.messages as unknown[];
    if (rawMessages.length === 0) throw new Error("Generic role/content transcript messages must not be empty");
    const messages = rawMessages.map((rawMessage, messageIndex) => {
      if (!rawMessage || typeof rawMessage !== "object" || Array.isArray(rawMessage)) {
        throw new Error(`Generic role/content message ${messageIndex + 1} must be an object`);
      }
      const message = rawMessage as Record<string, unknown>;
      const allowedMessageFields = new Set(["id", "role", "content", "created_at"]);
      const unknownMessageFields = Object.keys(message).filter((key) => !allowedMessageFields.has(key));
      if (unknownMessageFields.length > 0) {
        throw new Error(`Generic role/content message ${messageIndex + 1} contains unknown fields: ${unknownMessageFields.join(", ")}`);
      }
      if (!Object.prototype.hasOwnProperty.call(message, "role") || !Object.prototype.hasOwnProperty.call(message, "content")) {
        throw new Error(`Generic role/content message ${messageIndex + 1} requires role and content`);
      }
      const role = message.role;
      if (role !== "user" && role !== "assistant" && role !== "system") {
        throw new Error(`Generic role/content message ${messageIndex + 1} has unsupported role`);
      }
      if (typeof message.content !== "string" || !message.content.trim()) {
        throw new Error(`Generic role/content message ${messageIndex + 1} requires non-empty string content`);
      }
      return {
        role,
        content: message.content,
        created_at: typeof message.created_at === "string" ? message.created_at : null,
        source_message_id: typeof message.id === "string" ? message.id : null,
        provider_metadata: {},
        imported_assistant_identity: null,
      } satisfies ParsedImportMessage;
    });
    const sourceChatId = typeof chat.id === "string" && chat.id ? chat.id : `generic-chat-${chatIndex + 1}`;
    return {
      provider: selectedSource,
      parser_format: "generic",
      selected_source: selectedSource,
      source_chat_id: sourceChatId,
      source_fingerprint: fingerprint("generic", sourceChatId, messages),
      title: typeof chat.title === "string" ? chat.title : null,
      created_at: typeof chat.created_at === "string" ? chat.created_at : null,
      updated_at: typeof chat.updated_at === "string" ? chat.updated_at : null,
      messages,
      embeds: [],
      uploads: [],
      provider_labels: [selectedSource, "generic"],
      source_metadata: { source_name: sourceName, message_count: messages.length },
    } satisfies ParsedImportChat;
  });
  return finalizeImport("generic", selectedSource, chats, []);
}
