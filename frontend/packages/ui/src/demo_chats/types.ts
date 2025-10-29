export interface DemoMessage {
	id: string;
	role: 'user' | 'assistant';
	content: string; // Markdown content
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
	title: string; // SEO title
	description: string; // SEO description
	keywords: string[]; // SEO keywords
	messages: DemoMessage[];
	follow_up_suggestions?: string[]; // Follow-up question suggestions (like real chats)
	metadata: {
		category: string; // Must match a mate category from mates.yml
		icon_names: string[]; // 1-3 Lucide icon names (same format LLM generates)
		featured: boolean;
		order: number;
		lastUpdated: string;
	};
}
