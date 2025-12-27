// Unified embed node types and attributes for the new message parsing architecture

export type EmbedType = 'code-code' | 'sheets-sheet' | 'docs-doc' | 'web-website' | 'videos-video' | 'audio' | 'image' | 'file' | 'text' | 'pdf' | 'book' | 'maps' | 'recording' | 
                       // App skill results (new embeds architecture)
                       'app-skill-use' |
                       // Group types (follow pattern: {type}-group)
                       'app-skill-use-group' | 'web-website-group' | 'code-code-group' | 'docs-doc-group' | 'sheets-sheet-group' | 'videos-video-group' | 'audio-group' | 'image-group' | 'file-group' |
                       // Allow for future extensions
                       string;

export interface EmbedNodeAttributes {
  // UUID per Q&A; avoid order-based IDs
  id: string;
  
  // Type of embed content
  type: EmbedType;
  
  // Processing status (including error state for failed decryption/loading)
  status: 'processing' | 'finished' | 'error';
  
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
  query?: string;  // Search query for search skills
}

export interface ParseMessageOptions {
  // Mode for parsing (write for editing, read for display)
  mode?: 'write' | 'read';
  
  // Feature flag for unified parsing
  unifiedParsingEnabled?: boolean;
  
  // Additional options can be added here
  [key: string]: any;
}

export interface EmbedStoreEntry {
  contentRef: string;
  
  // DEPRECATED: Legacy field for backward compatibility during migration
  // Old embeds stored entire object as JSON string in this field
  // Migration will convert old data field to separate fields below
  // New embeds should NOT use this field - use separate fields instead
  data?: any;
  
  type: EmbedType;
  createdAt: number; // Server-provided timestamp (preserved from server, not overwritten)
  updatedAt: number; // Server-provided timestamp (preserved from server, not overwritten)
  metadata?: Record<string, any>;
  
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
  status?: 'processing' | 'finished' | 'error'; // Processing status
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
  inlineContent?: any;
}
