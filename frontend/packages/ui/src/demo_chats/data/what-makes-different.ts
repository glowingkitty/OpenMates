import type { DemoChat } from '../types';

export const whatMakesDifferentChat: DemoChat = {
	chat_id: 'demo-different',
	slug: 'what-makes-different',
	title: 'What makes OpenMates different?',
	description: 'Discover specialized Mates, zero-knowledge encryption, multiple drafts, and performance-optimized UX',
	keywords: ['features', 'privacy', 'mates', 'drafts', 'comparison', 'encryption'],
	messages: [
		{
			id: 'diff-1',
			role: 'user',
			content: 'What makes OpenMates different from other AI assistants?',
			timestamp: new Date().toISOString()
		},
		{
			id: 'diff-2',
			role: 'assistant',
			content: `Great question! OpenMates stands out in several key ways:

## 🤝 Optimized Mates for Every Task

Instead of one generic assistant, OpenMates automatically routes your request to specialized "Mates" optimized for different domains:

- **Sophia** - Software development expert (coding, architecture, debugging)
- **Burton** - Business development (strategy, market analysis, growth)
- **Melvin** - Medical & health information (with proper disclaimers)
- **Leon** - Legal topics (educational, not legal advice)
- **Makani** - Maker & rapid prototyping (DIY, 3D printing, electronics)
- **Mark** - Marketing & sales strategies
- **Finn** - Finance & investment information
- **Denise** - Design (UI/UX, graphic design, aesthetics)
- **Plus more** - History, Science, Life Coaching, Cooking, and more!

Each Mate has a specialized system prompt and expertise area, ensuring you get the most relevant and capable assistant for your specific task.

## 📝 Multiple Drafts Support

OpenMates supports **multiple conversation drafts** - allowing you to:
- Explore different approaches to the same problem
- Compare various solutions side-by-side
- Keep alternative conversation paths without losing context
- Work on multiple versions of creative content

This encourages experimentation and iterative thinking.

## 🔒 Zero-Knowledge Encryption

Your privacy is architecturally guaranteed:
- **Zero-knowledge storage** - The server cannot decrypt your stored chats by itself
- **Device-controlled processing** - Your device must decrypt and send chats to the server for AI processing
- **Encrypted at rest** - Stored messages are encrypted and require your device's participation to decrypt
- **Transparent security** - Open source code you can audit

**Important to understand:** While your chats are encrypted when stored, they must be decrypted during AI processing. This means the server can read messages while processing them, but cannot access stored messages without your device's active participation.

This is more secure than services that can access all your data anytime, but less private than fully local AI processing.

## ⚡ Performance-Optimized UX

Built for real-world usability:
- **Fast, responsive interface** - Optimized for performance at every level
- **Intuitive design** - Clean, simple UI that gets out of your way
- **Accessible by default** - Screen reader support, keyboard navigation
- **Progressive enhancement** - Works on all devices and connection speeds

The design philosophy: Make AI assistance feel natural and effortless.

## 🌱 Coming Soon: Apps & Skills

We're actively developing:
- **Web Search** - Real-time information from the internet
- **Code Execution** - Run and test code safely
- **File Analysis** - Work with documents and data
- **And more tools** to make your AI teammate even more capable!

---

**In short:** OpenMates gives you specialized expertise, true privacy, flexible thinking, and a UX designed for humans - not just impressive demos.

Want to dive deeper into any of these features?`,
			timestamp: new Date().toISOString()
		}
	],
	follow_up_suggestions: [
		"How does zero-knowledge encryption work?",
		"Tell me more about the Mates system",
		"What's the multiple drafts feature?"
	],
	metadata: {
		category: 'general_knowledge', // Real category from mates.yml
		icon_names: ['shield-check', 'users', 'zap'], // Lucide icons for security/team/performance
		featured: true,
		order: 2,
		lastUpdated: new Date().toISOString()
	}
};
