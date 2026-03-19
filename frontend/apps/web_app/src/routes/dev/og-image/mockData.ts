/**
 * Mock data for the OG image / marketing banner page.
 *
 * Contains predefined chat messages, daily inspirations, and mate info
 * so the banner renders deterministic, controllable content regardless
 * of which user is logged in or what's in IndexedDB.
 *
 * Architecture: docs/architecture/web-app.md
 * Tests: none (static fixture data)
 */

// ─── Mock chat messages ────────────────────────────────────────────────────
// Used by ChatMessage components rendered directly in the device mockups.
// Content is plain markdown — ReadOnlyMessage parses it via TipTap internally.

export interface MockMessage {
	role: 'user' | 'assistant';
	content: string;
	category?: string;
	sender_name?: string;
}

export const MOCK_CHAT_MESSAGES: MockMessage[] = [
	{
		role: 'user',
		content: 'How do cuttlefish change color so fast?'
	},
	{
		role: 'assistant',
		category: 'general_knowledge',
		content:
			'Cuttlefish use specialised skin cells called **chromatophores** — tiny sacs of pigment controlled by muscles. When the muscles contract, pigment spreads across the cell surface, changing colour in under a second.\n\nThey also have:\n- **Iridophores** — reflective cells that create iridescent blues and greens\n- **Leucophores** — white-reflecting cells for brightness control\n- **Papillae** — muscles that change skin texture to mimic coral or sand'
	},
	{
		role: 'user',
		content: 'Can they see colour themselves?'
	},
	{
		role: 'assistant',
		category: 'general_knowledge',
		content:
			'Surprisingly, cuttlefish are **colour-blind** — they only have one type of photoreceptor. But they can perceive the *polarisation* of light, which may help them detect contrast and patterns in ways we can\'t.\n\nResearchers think they match colours by adjusting chromatophores until the brightness and pattern of their skin matches the surroundings, rather than directly "seeing" colour.'
	}
];

// ─── Mock daily inspirations ───────────────────────────────────────────────
// Prepared for future use with DailyInspirationBanner. Seeded into
// dailyInspirationStore so the banner renders deterministic content.
// Matches the fixture format from loadDefaultInspirations.ts.
// Type is inline to avoid deep @repo/ui imports that aren't exposed via package exports.

export interface MockDailyInspiration {
	inspiration_id: string;
	phrase: string;
	title?: string;
	category: string;
	content_type: string;
	video: {
		youtube_id: string;
		title: string;
		thumbnail_url: string;
		channel_name: string | null;
		view_count: number | null;
		duration_seconds: number | null;
		published_at: string | null;
	} | null;
	generated_at: number;
	assistant_response?: string;
	follow_up_suggestions?: string[];
}

const MOCK_INSPIRATIONS: MockDailyInspiration[] = [
	{
		inspiration_id: 'og-banner-1',
		phrase: 'How cuttlefish camouflage works',
		title: 'Cuttlefish Camouflage Mechanism',
		category: 'science',
		content_type: 'video',
		video: {
			youtube_id: '3s0LTDhqe5A',
			title: 'How Cuttlefish Instantly Change Color',
			thumbnail_url: 'https://i.ytimg.com/vi/3s0LTDhqe5A/hqdefault.jpg',
			channel_name: 'Nature Explained',
			view_count: 824000,
			duration_seconds: 412,
			published_at: '2024-02-14T00:00:00Z'
		},
		generated_at: 1731000000,
		assistant_response:
			'Cuttlefish use chromatophores, iridophores, and papillae to blend into coral, sand, and rocks in milliseconds.',
		follow_up_suggestions: [
			'Show real-world camouflage examples',
			'Explain chromatophores simply',
			'Compare cuttlefish and octopus camouflage'
		]
	}
];
