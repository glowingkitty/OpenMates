/*
 * Account Import V1 CLI parsing helpers.
 *
 * Purpose: normalize user-provided Claude/OpenMates export archives before the
 * CLI calls the backend preview and transient scan endpoints.
 * Architecture: docs/specs/account-import-v1/spec.yml.
 * Security: source fingerprints are one-way hashes; raw provider exports stay
 * local and are never logged by these helpers.
 */

import { createHash } from "node:crypto";
import JSZip from "jszip";

export type AccountImportSource = "claude" | "openmates";

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
  const entry = zip.file(requiredName);
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
