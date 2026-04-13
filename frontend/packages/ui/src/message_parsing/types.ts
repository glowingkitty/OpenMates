// Unified embed node types and attributes for the new message parsing architecture

export type EmbedType =
  | "code-code"
  | "sheets-sheet"
  | "docs-doc"
  | "web-website"
  | "videos-video"
  | "audio"
  | "image"
  | "file"
  | "text"
  | "pdf"
  | "book"
  | "maps"
  | "recording"
  // App skill results (new embeds architecture)
  | "app-skill-use"
  // Focus mode activation indicator (countdown + activated state)
  | "focus-mode-activation"
  // Group types (follow pattern: {type}-group)
  | "app-skill-use-group"
  | "web-website-group"
  | "code-code-group"
  | "docs-doc-group"
  | "sheets-sheet-group"
  | "videos-video-group"
  | "audio-group"
  | "image-group"
  | "file-group"
  // Allow for future extensions
  | string;

export interface EmbedNodeAttributes {
  // UUID per Q&A; avoid order-based IDs
  id: string;

  // Type of embed content
  type: EmbedType;

  // Processing status (including error state for failed decryption/loading)
  // See embedStateMachine.ts for the canonical status type and valid transitions
  status: "processing" | "finished" | "error" | "cancelled";

  // Content reference: stream:<uuid> during generation, cid:sha256:<hash> when finished, null for web embeds
  contentRef: string | null;

  // Optional content hash for finished content
  contentHash?: string;

  // Tiny metadata fields (optional)
  language?: string;
  filename?: string;
  lineCount?: number;
  wordCount?: number;
  cellCount?: number;
  rows?: number;
  cols?: number;
  title?: string;
  url?: string;
  description?: string;
  favicon?: string;
  image?: string;

  // Temporary field for preview code embeds (write mode only)
  // Stores code content inline for visual preview before server creates real embed
  code?: string;

  // Group-specific attributes
  groupedItems?: EmbedNodeAttributes[];
  groupCount?: number;

  // App skill metadata (extracted from JSON embed references during parsing)
  // These are used by AppSkillUseRenderer to determine which Svelte component to render
  // even before the full embed data arrives from the server
  app_id?: string;
  skill_id?: string;
  query?: string; // Search query for search skills
  provider?: string; // Search provider for search skills (e.g., 'Brave Search', 'Google')

  // Focus mode activation metadata
  // Used by FocusModeActivationRenderer to display the focus mode name and manage state
  focus_id?: string; // Full focus mode ID (e.g., 'web-research')
  focus_mode_name?: string; // Translated display name of the focus mode

  // Temporary field set by embedHandlers.ts on PDF embed nodes when the PDF is uploaded
  // to S3 but OCR is still in progress (status: "processing"). Stores the server-assigned
  // embed_id so serializers.ts can emit a placeholder embed reference in the message,
  // allowing the backend to reference the PDF even before OCR completes.
  uploadEmbedId?: string;
}

export interface ParseMessageOptions {
  // Mode for parsing (write for editing, read for display)
  mode?: "write" | "read";

  // Feature flag for unified parsing
  unifiedParsingEnabled?: boolean;

  // Message role — used to determine if single embeds of certain types
  // (docs, code, sheets, mail, math) should be promoted to large preview.
  // Only "assistant" messages get this promotion; user messages render as-is.
  role?: "user" | "assistant" | "system";

  // Validated Wikipedia topics for inline link rendering (accumulated per-chat).
  // When present, text nodes matching topic phrases are wrapped in wikiInline nodes.
  wikipediaTopics?: WikipediaTopic[];

  // Additional options can be added here
  [key: string]: string | boolean | WikipediaTopic[] | undefined;
}

/** A validated Wikipedia topic entry from the post-processor. */
export interface WikipediaTopic {
  topic: string;
  wiki_title: string;
  wikidata_id: string | null;
  thumbnail_url: string | null;
  description: string | null;
}

export interface EmbedStoreEntry {
  contentRef: string;

  // DEPRECATED: Legacy field for backward compatibility during migration
  // Old embeds stored entire object as JSON string in this field
  // Migration will convert old data field to separate fields below
  // New embeds should NOT use this field - use separate fields instead
  data?: string;

  type: EmbedType;
  createdAt: number; // Server-provided timestamp (preserved from server, not overwritten)
  updatedAt: number; // Server-provided timestamp (preserved from server, not overwritten)
  metadata?: Record<string, unknown>;

  // App metadata (stored unencrypted in IndexedDB only, not sent to server)
  // This allows efficient filtering and querying by app_id without decrypting all embeds
  app_id?: string; // For app_skill_use embeds: the app that generated this embed
  skill_id?: string; // For app_skill_use embeds: the skill that generated this embed

  // NEW: Separate fields for clean data model (replaces JSON string in data field)
  // For embeds stored via putEncrypted() (synced from server with embed_key encryption):
  embed_id?: string; // Embed ID for synced embeds
  encrypted_content?: string; // Encrypted TOON content (client-encrypted with embed_key)
  encrypted_type?: string; // Encrypted embed type (client-encrypted with embed_key)
  encrypted_text_preview?: string; // Encrypted text preview (client-encrypted with embed_key)
  status?: "processing" | "finished" | "error" | "cancelled"; // Processing status
  hashed_chat_id?: string; // SHA256 hash of chat_id (privacy protection)
  hashed_message_id?: string; // SHA256 hash of message_id (privacy protection)
  hashed_task_id?: string; // SHA256 hash of task_id (optional, for long-running tasks)
  hashed_user_id?: string; // SHA256 hash of user_id
  embed_ids?: string[]; // For composite embeds (app_skill_use)
  parent_embed_id?: string; // For versioned embeds
  version_number?: number; // For versioned embeds
  file_path?: string; // For code/file embeds
  content_hash?: string; // SHA256 hash for deduplication
  text_length_chars?: number; // Character count for text-based embeds
  is_private?: boolean; // Whether embed is private (not shared)
  is_shared?: boolean; // Whether embed has been shared (share link generated)

  // Hybrid Encryption Mode
  encryption_mode?: "client" | "vault"; // NEW: Encryption strategy: 'client' (zero-knowledge) or 'vault' (server-managed)
  vault_key_id?: string; // NEW: Vault key ID for server-managed embeds

  // For embeds stored via put() (encrypted with master key):
  // The encrypted_content field will contain master-key-encrypted JSON string
  // This is different from putEncrypted() which uses embed_key encryption
}

// Clipboard JSON format for embeds
export interface EmbedClipboardData {
  version: 1;
  id: string;
  type: EmbedType;
  language?: string;
  filename?: string;
  contentRef: string;
  contentHash?: string;
  inlineContent?: Record<string, string | number | undefined>;
}


// TipTap document node interfaces used across the message parsing module
// These replace `any` types for TipTap JSON structures

/** A mark applied to a text node (bold, italic, code, link) */
export interface TipTapMark {
  type: string;
  attrs?: Record<string, string | number | boolean | undefined>;
}

/** A single node within a TipTap document tree */
export interface TipTapNode {
  type: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- TipTap attrs can be EmbedNodeAttributes or arbitrary key-value pairs; a union type would require type guards at every access site with no safety benefit since the code already checks node.type before accessing attrs
  attrs?: Record<string, any>;
  content?: TipTapNode[];
  text?: string;
  marks?: TipTapMark[];
}

/** A TipTap document root node */
export interface TipTapDoc {
  type?: string;
  content?: TipTapNode[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- Must be compatible with TipTapDocument from documentEnhancement.ts which uses Record<string, any>
  [key: string]: any;
}

/** Minimal interface for EmbedStore operations used in streamingSemantics */
export interface EmbedStoreLike {
  rekeyStreamToCid(streamKey: string): Promise<string>;
}
