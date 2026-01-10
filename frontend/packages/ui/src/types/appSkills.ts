// frontend/packages/ui/src/types/appSkills.ts
// Type definitions for app skill previews and execution states

/**
 * Status of a skill execution
 */
export type SkillExecutionStatus = 'processing' | 'finished' | 'error' | 'cancelled';

/**
 * Base interface for all app skill preview data
 */
export interface BaseSkillPreviewData {
  app_id: string;
  skill_id: string;
  status: SkillExecutionStatus;
  task_id?: string; // Optional task ID for tracking execution
}

/**
 * Web Search skill preview data
 */
export interface WebSearchSkillPreviewData extends BaseSkillPreviewData {
  app_id: 'web';
  skill_id: 'search';
  query: string;
  provider: string; // e.g., "Brave Search"
  status: SkillExecutionStatus;
  results?: WebSearchResult[]; // Only present when status is 'finished'
  completed_count?: number; // Number of completed requests (for multiple searches)
  total_count?: number; // Total number of requests
}

/**
 * Individual search result from a search skill execution
 */
export interface WebSearchResult {
  type: 'search_result';
  title: string;
  url: string;
  snippet: string;
  hash: string; // Unique hash for the result
  favicon_url?: string; // Optional favicon URL
  preview_image_url?: string; // Optional preview image URL
}

/**
 * Video Transcript skill preview data
 */
export interface VideoTranscriptSkillPreviewData extends BaseSkillPreviewData {
  app_id: 'videos';
  skill_id: 'get_transcript';
  status: SkillExecutionStatus;
  results?: VideoTranscriptResult[]; // Only present when status is 'finished'
  video_count?: number; // Number of videos requested
  success_count?: number; // Number of successful transcript fetches
  failed_count?: number; // Number of failed transcript fetches
}

/**
 * Individual video transcript result
 */
export interface VideoTranscriptResult {
  type: 'video_transcript';
  video_id: string;
  url: string;
  transcript?: string;
  word_count?: number;
  language?: string;
  is_generated?: boolean;
  success: boolean;
  error?: string;
  metadata?: {
    title?: string;
    description?: string;
    channel_title?: string;
    channel_id?: string;
    published_at?: string;
    duration?: string;
    view_count?: number;
    like_count?: number;
    comment_count?: number;
    thumbnail_url?: string;
  };
}

/**
 * Code Get Docs skill preview data
 * Used to display documentation fetched from Context7 API
 */
export interface CodeGetDocsSkillPreviewData extends BaseSkillPreviewData {
  app_id: 'code';
  skill_id: 'get_docs';
  status: SkillExecutionStatus;
  results?: CodeGetDocsResult[];
  library?: string; // Library name that was searched
  question?: string; // Question that was asked
}

/**
 * Individual get_docs result from Context7
 * Note: Backend may send flat (library_id, library_title) or nested (library.id, library.title) structure
 */
export interface CodeGetDocsResult {
  type?: 'get_docs';
  /** Selected library info (nested structure) */
  library?: {
    id?: string; // e.g., "/sveltejs/svelte"
    title?: string; // e.g., "Svelte"
    description?: string;
  };
  /** Flat structure alternatives (from some backend responses) */
  library_id?: string;
  library_title?: string;
  /** Documentation content in markdown format */
  documentation?: string;
  /** Source of documentation (context7, openmates, web_search) */
  source?: string;
  /** Word count of the documentation (pre-calculated by backend) */
  word_count?: number;
  /** Error message if retrieval failed */
  error?: string;
}

/**
 * WebSocket event payload for skill execution status updates
 */
export interface SkillExecutionStatusUpdatePayload {
  chat_id: string;
  message_id: string;
  task_id: string;
  app_id: string;
  skill_id: string;
  status: SkillExecutionStatus;
  preview_data?: BaseSkillPreviewData; // Skill-specific preview data
}

