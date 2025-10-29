import type { DemoChat } from '../types';

export const welcomeChat: DemoChat = {
	chat_id: 'demo-welcome',
	slug: 'welcome',
	title: 'Welcome to OpenMates!',
	description: 'Your AI teammates for learning, thinking, and growing together',
	keywords: ['AI assistant', 'getting started', 'introduction', 'OpenMates features'],
	messages: [
		{
			id: 'welcome-1',
			role: 'assistant',
			content: `# Welcome to OpenMates! 👋

I'm your AI teammate - here to help you learn, solve problems, and think through challenges. I'm designed to guide you with questions rather than just give answers, helping you build real understanding. Like all AI, I can make mistakes, but I'm specifically designed to minimize errors, admit uncertainty, and encourage you to verify important information from multiple sources.

## What you can do:

- **Learn topics deeply** - "Teach me about quantum computing" or "Explain neural networks"
- **Get coding help** - "Debug this code" or "Explain how async/await works"
- **Think through decisions** - "Help me evaluate career options" or "What am I missing?"
- **Explore ideas** - "Brainstorm startup ideas in healthcare" or "Design a user survey"
- **Understand complex topics** - "Explain the 2008 financial crisis" or "How does CRISPR work?"
- **Plan and organize** - "Help me structure my research paper" or "Create a learning roadmap"

## Getting Started

**Start a new chat** - Click the "New Chat" button in the top left of this chat

**Sign up for full access** - Open the settings menu (button in the top right) to create an account

**Learn more** - Explore [What makes OpenMates different?](/chat/what-makes-different)

---

*Different specialized AI "Mates" will automatically help based on your topic - from Sophia (software development) to Lisa (life coaching) to Scarlett (science) and more!*
`,
			timestamp: new Date().toISOString()
		}
	],
	follow_up_suggestions: [
		"What makes OpenMates different?",
		"How do the different Mates work?",
		"Tell me about privacy features"
	],
	metadata: {
		category: 'general_knowledge', // Real category from mates.yml
		icon_names: ['hand-wave', 'rocket', 'sparkles'], // Lucide icons for welcome/introduction
		featured: true,
		order: 1,
		lastUpdated: new Date().toISOString()
	}
};
