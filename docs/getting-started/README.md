# Getting Started

![Getting started header image](../images/architecture_header.png)

Welcome to OpenMates - an open-source, privacy-first AI assistant that puts you in control. OpenMates combines the power of multiple AI models with a zero-knowledge encryption architecture, so your conversations stay private.

## What is OpenMates?

OpenMates is an alternative to ChatGPT, Claude, and other AI assistants with key differences:

- **Privacy-first**: Zero-knowledge encryption means the server never sees your data in plaintext
- **Open source**: Fully transparent codebase licensed under AGPL
- **Pay-per-use**: No subscriptions - only pay for what you use with a credits system
- **Multi-model**: Automatically routes your requests to the best AI model for the task
- **App ecosystem**: Built-in apps for web search, code, documents, videos, music, and more

## Quick Links

- **[User Guide](../user-guide/README.md)** - Learn how to use OpenMates features
- **[Apps](../apps/README.md)** - Explore the built-in apps and skills
- **[Self-Hosting](../self-hosting/setup.md)** - Run your own OpenMates instance
- **[Architecture](../architecture/README.md)** - Technical deep dives for developers
- **[Design Guide](../design-guide/README.md)** - UI/UX design principles and patterns
- **[Contributing](../contributing/contributing.md)** - How to contribute to the project
- **[API Reference](/docs/api)** - Interactive REST API documentation

## How It Works

1. **You send a message** in the web app
2. **Pre-processing** detects the complexity, category, and appropriate AI model
3. **Main processing** routes to the best AI model and activates any needed app skills
4. **Post-processing** generates follow-up suggestions and checks for quality
5. **Everything is encrypted** on your device before being stored

All of this happens with zero-knowledge encryption - the server processes your request but never stores readable data.

## Community

- [Signal Developer Group](https://signal.group/#CjQKIGQMnJFxYVRMH7TExMhec3PYXjOKexwjbo3rRB-tk8YdEhB87IRJWy7m5p0qXOoGHr0h)
- [Discord Community](https://discord.gg/PYXfVrSEaj)
