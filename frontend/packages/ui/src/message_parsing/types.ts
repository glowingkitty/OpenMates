// Unified embed node types and attributes for the new message parsing architecture

export type EmbedType = 'code-code' | 'sheets-sheet' | 'docs-doc' | 'web-website' | 'videos-video' | 'audio' | 'image' | 'file' | 'text' | 'pdf' | 'book' | 'maps' | 'recording' | 
                       // Group types (follow pattern: {type}-group)
                       'web-website-group' | 'code-code-group' | 'docs-doc-group' | 'sheets-sheet-group' | 'videos-video-group' | 'audio-group' | 'image-group' | 'file-group' |
                       // Allow for future extensions
                       string;

export interface EmbedNodeAttributes {
  // UUID per Q&A; avoid order-based IDs
  id: string;
  
  // Type of embed content
  type: EmbedType;
  
  // Processing status
  status: 'processing' | 'finished';
  
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
  
  // Group-specific attributes
  groupedItems?: EmbedNodeAttributes[];
  groupCount?: number;
}

export interface ParseMessageOptions {
  // Mode for parsing (write for editing, read for display)
  mode?: 'write' | 'read';
  
  // Feature flag for unified parsing
  unifiedParsingEnabled?: boolean;
  
  // Additional options can be added here
  [key: string]: any;
}

export interface ContentStoreEntry {
  contentRef: string;
  data: any;
  type: EmbedType;
  createdAt: number;
  updatedAt: number;
  metadata?: Record<string, any>;
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
