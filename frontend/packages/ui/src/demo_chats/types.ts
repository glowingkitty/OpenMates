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
	};
}
