/*
 * Account Import V1 CLI parsing helpers.
 *
 * Purpose: normalize user-provided Claude/ChatGPT/OpenMates export archives before the
 * CLI calls the backend preview and transient scan endpoints.
 * Architecture: docs/specs/account-import-v1/spec.yml.
 * Security: source fingerprints are one-way hashes; raw provider exports stay
 * local and are never logged by these helpers.
 */

import { createHash } from "node:crypto";
import JSZip from "jszip";

export type AccountImportSource = "claude" | "chatgpt" | "openmates";

export interface ParsedImportMessage {
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string | null;
  source_message_id?: string | null;
  provider_metadata: Record<string, unknown>;
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
  chats: ParsedImportChat[];
  skippedDomains: string[];
}

function fingerprint(provider: AccountImportSource, sourceChatId: string, messages: ParsedImportMessage[]): string {
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

export async function parseClaudeImportBuffer(payload: Buffer, sourceName = "claude-export"): Promise<ParsedAccountImport> {
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
        } satisfies ParsedImportMessage;
      });
    return {
      provider: "claude",
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
  return { source: "claude", chats, skippedDomains: [] };
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

export async function parseChatGPTImportBuffer(payload: Buffer, sourceName = "chatgpt-export"): Promise<ParsedAccountImport> {
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
      });
    }
    return {
      provider: "chatgpt",
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
  return { source: "chatgpt", chats, skippedDomains: [] };
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

export async function parseOpenMatesImportBuffer(payload: Buffer, sourceName = "openmates-export.zip"): Promise<ParsedAccountImport> {
  const zip = await JSZip.loadAsync(payload);
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
  return { source: "openmates", chats, skippedDomains };
}
