// frontend/packages/ui/src/services/chatImportTypes.ts
//
// Shared types of the Account Import V1 browser service and its Rust `transfer`
// unit adapter (rustCore/transfer/rustChatImport.ts). Types only, no runtime code.
//
// Spec: docs/specs/account-import-v1/spec.yml
export type AccountImportSource = "openmates" | "chatgpt" | "claude" | "gemini" | "opencode" | "other";
export type AccountImportParserFormat = "claude" | "chatgpt" | "openmates" | "opencode" | "generic";
export type ImportFileType = "claude-json" | "claude-zip" | "chatgpt-json" | "chatgpt-zip" | "opencode-json" | "openmates-zip" | "generic-json";

export interface ImportedAssistantIdentity {
  category: AccountImportSource;
  sender_name: string;
  model_name: string;
}


export interface ParsedImportMessage {
  role: "user" | "assistant" | "system";
  content: string;
  created_at?: string | null;
  source_message_id?: string | null;
  provider_metadata: Record<string, unknown>;
  imported_assistant_identity?: ImportedAssistantIdentity | null;
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
  parser_format?: AccountImportParserFormat;
  selected_source?: AccountImportSource;
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
  parserFormat?: AccountImportParserFormat;
  fileType: ImportFileType;
  chats: ParsedImportChat[];
  skippedDomains: string[];
}

export interface ImportCostEstimate {
  totalInputTokens: number;
  estimatedCredits: number;
  chatCount: number;
  messageCount: number;
}
export type ImportProgressPhase =
  | "parsing"
  | "previewing"
  | "confirming"
  | "scanning"
  | "compressing"
  | "encrypting"
  | "persisting"
  | "completing"
  | "done";

export type ImportProgressCallback = (
  phase: ImportProgressPhase,
  detail: string,
) => void;
