# OpenMates

AI team mates for everyday tasks & learning. Plan trips, find apartments, discuss videos & news, build projects - and much more. With user interests & privacy above anything else by design.

OpenMates is currently in a fairly stable alpha state. The best way to help right now is to test it, report issues, suggest improvements, improve documentation, and contribute to public GitHub issues.

[Try OpenMates](https://openmates.org) · [Self-host](./docs/self-hosting/setup.md) · [Report an issue](https://github.com/glowingkitty/OpenMates/issues) · [Suggest an improvement](https://github.com/glowingkitty/OpenMates/issues) · [Contribute](./CONTRIBUTING.md)

> Image TODO: Generate the README hero image with Remotion.
>
> It should show a polished OpenMates web app scene: a short product headline, the chat UI, and at least one useful app result or rich embed.

## What You Can Do With OpenMates

OpenMates is meant to help with real tasks, not only open-ended chatting.

### Get Everyday Tasks Done

Summarize the news, find events across platforms, find train connections and flights including prices and booking links, look for doctor appointments, search apartments, compare options, plan trips, and handle many other everyday tasks from one conversational interface.

Instead of switching between many websites, forms, and search result pages, OpenMates can use apps and skills to collect relevant information, structure it, and keep the result inside the conversation.

> Image TODO: Generate an everyday-tasks image with Remotion.
>
> It should show examples such as news summaries, events, travel connections with prices, or apartment/appointment search results.

### Build Projects

Plan projects, write and execute code snippets in a sandboxed environment from the comfort of a web browser, research technical decisions, find electronics components for a project, compare tools, and turn scattered ideas into concrete next steps.

OpenMates is built for both technical and non-technical project work: drafting plans, collecting references, testing snippets safely, and using specialized apps when a normal chat response is not enough.

> Image TODO: Generate a project-building image with Remotion.
>
> It should show a browser-based project workflow: planning, code snippets, sandboxed execution, or component/tool research.

### Learn Faster

Learn about new topics, explore related Wikipedia articles, compare explanations, ask follow-up questions, and use learning-focused optimizations instead of treating every topic like a generic chat.

OpenMates should make exploration feel natural: start with a question, branch into related concepts, inspect sources, and keep useful context available as the learning session develops.

> Image TODO: Generate a learning image with Remotion.
>
> It should show a learning conversation with related articles, follow-up suggestions, or a guided topic map.

### Use Familiar AI Models Better

OpenMates is designed to work with AI models people are already familiar with, but with better privacy, safety, and usability than typical AI agents.

The goal is not to hide the model behind another black box. The goal is to make model use more practical: better task flows, safer provider use, richer results, clearer controls, and a product that puts the user's interests first.

## User Interests First

OpenMates is designed around privacy, safety, and usability from the start.

- **Privacy by design:** chats, titles, app settings, memories, and other sensitive fields are encrypted in the browser before being stored on the server. Sensitive details can also be detected and replaced with placeholders before prompts are sent to third-party AI providers.
- **Safety by design:** external providers, app skills, tool use, and sandboxed execution should be understandable and controlled instead of hidden behind opaque automation.
- **Usability by design:** apps, skills, rich embeds, focus modes, memories, and example flows make AI useful for everyday people, not only prompt experts.
- **No ecosystem lock-in:** OpenMates can be used with various AI provider APIs and is designed to support offline/local AI models later.
- **Open source and self-hostable:** run it yourself, inspect how it works, adapt it to your needs, or help improve the public project.

Self-hosting is powerful, but it does not make every connected service free. Many OpenMates app skills require API keys from external providers, and many of those providers require paid subscriptions or usage-based billing.

> Image TODO: Generate a user-interests-first image with Remotion.
>
> It should communicate privacy, safety, usability, no lock-in, and open-source/self-hosting without feeling like a dense architecture diagram.

## Feature Highlights

### Privacy-First AI Assistance

OpenMates treats privacy as product infrastructure, not as a marketing add-on. Client-side encryption, account recovery, privacy-preserving observability, and careful prompt preprocessing are part of the core system.

Server-side processing only decrypts transiently when needed for user-requested AI responses or actions, and plaintext must not be written to disk, logs, or traces.

Relevant docs: [Security](./docs/architecture/core/security.md), [Client-side encryption](./docs/architecture/core/client-side-encryption.md), [Account recovery](./docs/architecture/core/account-recovery.md), [PII protection](./docs/architecture/privacy/pii-protection.md).

### Apps, Skills, And Rich Embeds

OpenMates uses apps and skills to move beyond generic chat. Skills can search the web, read pages, find events, search maps, generate or analyze media, manage reminders, and return structured results.

Rich embeds keep results inside the conversation so users can inspect, compare, and continue from useful outputs instead of jumping through disconnected links.

Relevant docs: [Apps user guide](./docs/user-guide/apps/README.md), [App skills architecture](./docs/architecture/apps/app-skills.md), [Embeds architecture](./docs/architecture/messaging/embeds.md).

### Focus Modes And Memories

Focus modes help OpenMates behave differently for different situations: learning, career exploration, task workflows, and other guided experiences.

Memories are designed to make OpenMates more useful over time while still giving users control over sensitive data. The goal is helpful personalization without uncontrolled data collection.

Relevant docs: [Focus modes](./docs/architecture/apps/focus-modes.md), [Focus modes implementation](./docs/architecture/apps/focus-modes-implementation.md), [Privacy promises](./docs/architecture/privacy/privacy-promises.md).

### Model And Provider Independence

OpenMates is not meant to depend on a single AI provider. The app can route tasks across different models and providers, expose which model was used, and give users more control when they need it.

For developers, this means provider abstractions, routing, cost/quality tradeoffs, model capability detection, and graceful failure handling are important parts of the system.

Relevant docs: [AI model selection](./docs/architecture/ai/ai-model-selection.md), [Thinking models](./docs/architecture/ai/thinking-models.md).

### Developer API And CLI

OpenMates includes developer-facing access through an OpenAI-compatible REST API and a CLI package. This makes it possible to connect OpenMates to scripts, local workflows, and other developer tools.

Relevant docs: [CLI](./docs/cli/README.md), [REST API architecture](./docs/architecture/apps/rest-api.md), [CLI package architecture](./docs/architecture/apps/cli-package.md).

## Explore Real Examples

Feature images should link to real examples wherever possible. These examples use deterministic demo chats or public preview pages, not private user data or unstable test accounts.

- Example chats should be used for apps, skills, embeds, focus modes, follow-up suggestions, and learning flows.
- Short videos should be used for privacy flows, memories, model routing, and anything that is hard to make deterministic in a public chat.
- Documentation should be used for architecture-heavy topics such as encryption, provider routing, self-hosting, API, and CLI.

> Image TODO: Generate an examples-grid image with Remotion once the first public demo chats and videos are selected.

## Self-Host OpenMates

OpenMates is open source and self-hostable. The self-hosting docs are the starting point if you want to run your own instance, evaluate the architecture, or contribute infrastructure improvements.

[Start the self-hosting guide](./docs/self-hosting/setup.md)

Self-hosting docs:

- [Setup](./docs/self-hosting/setup.md)
- [Server hardening](./docs/self-hosting/server-hardening.md)
- [Deployment docs](./deployment/README.md)

Remember that self-hosting OpenMates does not automatically include access to every external service. Many app skills require separate provider API keys, and some providers require paid subscriptions.

> Image TODO: Generate a self-hosting image with Remotion.
>
> It should show a simple deployment or architecture overview next to a running OpenMates web app.

## Contributing

The most valuable contributions right now are high-quality issue reports, improvement suggestions, documentation fixes, example improvements, and focused pull requests connected to public GitHub issues.

[Read the contributing guide](./CONTRIBUTING.md)

Good starting points:

- Test the app and report rough edges.
- Improve self-hosting and setup docs.
- Add or improve app and skill documentation.
- Pick a `good first issue` or `help wanted` issue once the public issue tracker is populated.
- Review architecture docs and suggest clearer explanations.
- Improve examples, screenshots, Remotion images, and demo chats.

Useful links:

- [Open a GitHub issue](https://github.com/glowingkitty/OpenMates/issues)
- [Frontend standards](./docs/contributing/standards/frontend.md)
- [Backend standards](./docs/contributing/standards/backend.md)
- [Testing guide](./docs/contributing/guides/testing.md)
- [Documentation structure](./docs/contributing/docs-structure.md)

Community:

- [Discord Community](https://discord.gg/PYXfVrSEaj)
- [Signal Developer Group](https://signal.group/#CjQKIGQMnJFxYVRMH7TExMhec3PYXjOKexwjbo3rRB-tk8YdEhB87IRJWy7m5p0qXOoGHr0h)
- [Meetup Events](https://www.meetup.com/openmates/)

## Architecture

OpenMates is a SvelteKit web app with a Python/FastAPI backend, PostgreSQL/Directus CMS, encrypted client-side state, app and skill modules, provider wrappers, model routing, and rich embed renderers.

Start here:

- [Architecture overview](./docs/architecture/README.md)
- [Frontend app](./frontend/apps/web_app/README.md)
- [Backend apps](./backend/apps/README.md)
- [Apps and skills](./docs/architecture/apps/app-skills.md)
- [Message processing](./docs/architecture/messaging/message-processing.md)
- [Encryption architecture](./docs/architecture/core/encryption-architecture.md)
- [Privacy promises](./docs/architecture/privacy/privacy-promises.md)

## License

OpenMates is licensed under the GNU Affero General Public License.

You may run OpenMates on your own machine or server, share access with a team, and create open-source software based on it. If you provide OpenMates as a network service to others, you must make your complete corresponding source code, including modifications, available under the AGPL.

[Learn more about the AGPL](https://www.gnu.org/licenses/why-affero-gpl.html)
