export interface DemoMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string; // Translation key (e.g., 'demo_chats.welcome.message')
	timestamp: string;
	metadata?: {
		apps_used?: string[];
		has_video?: boolean;
		video_url?: string;
	};
}

export interface DemoChat {
	chat_id: string; // Unique ID
	slug: string; // URL-friendly slug
	title: string; // Translation key (e.g., 'demo_chats.welcome.title')
	description: string; // Translation key (e.g., 'demo_chats.welcome.description')
	keywords: string[]; // SEO keywords (not translated)
	messages: DemoMessage[];
	follow_up_suggestions?: string[]; // Translation keys (e.g., 'demo_chats.welcome.follow_up_1')
	metadata: {
		category: string; // Must match a mate category from mates.yml
		icon_names: string[]; // 1-3 Lucide icon names (same format LLM generates)
		featured: boolean;
		order: number;
		lastUpdated: string;
		/** api.video HLS URL for an autoplay-muted background video in the chat header. */
		video_hls_url?: string;
		/** api.video MP4 URL — used as fallback for the background video and for the fullscreen player. */
		video_mp4_url?: string;
		/** Thumbnail image URL for the video (shown in the fullscreen embed before play). */
		video_thumbnail_url?: string;
		/** Timestamp in seconds where the background video should start playing. */
		video_start_time?: number;
		/** Optional list of static image URLs used as a crossfading Ken-Burns slideshow in the
		 *  chat header. When provided, replaces the autoplay background video (the real video
		 *  is still available via the play button / fullscreen embed). Saves video delivery cost. */
		background_frames?: string[];
	};
}

// ============================================================================
// Example Chats — Real conversations hardcoded in frontend
// ============================================================================

/**
 * A single embed in an example chat.
 * Content is TOON-encoded (key: value lines), matching the format
 * used by the embed rendering pipeline.
 */
export interface ExampleChatEmbed {
	embed_id: string;
	type: string; // e.g., 'image_result', 'website', 'app_skill_use'
	content: string; // TOON-encoded content (cleartext)
	parent_embed_id: string | null;
	embed_ids: string[] | null; // child embed IDs for parent embeds
}

/**
 * A message in an example chat.
 * Uses actual content strings (not i18n keys), since example chats
 * are reproduced 1:1 from real shared conversations.
 */
export interface ExampleChatMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string; // Actual message content (markdown with embed references)
	created_at: number; // Unix timestamp
	category?: string; // Mate category for assistant messages
	model_name?: string;
}

/**
 * A hardcoded example chat reproduced from a real shared conversation.
 * Includes full message content and embed data for 1:1 reproduction.
 *
 * Unlike DemoChat (which uses i18n keys), ExampleChat stores actual
 * conversation content — messages, embeds, and metadata.
 * Each example chat has a natural language slug for SEO-friendly URLs.
 */
export interface ExampleChat {
	chat_id: string; // e.g., "example-gigantic-airplanes"
	slug: string; // SEO slug, e.g., "gigantic-airplanes-transporting-rocket-parts"
	title: string; // Actual title (not i18n key)
	summary: string; // Actual summary
	icon: string; // Lucide icon name
	category: string; // Mate category
	keywords: string[]; // SEO keywords
	follow_up_suggestions: string[];
	messages: ExampleChatMessage[];
	embeds: ExampleChatEmbed[];
	metadata: {
		featured: boolean; // Show in default 10 on homepage
		order: number; // Display order
	};
}
