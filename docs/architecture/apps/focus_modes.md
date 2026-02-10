# Focus Modes

Focus modes are temporary changes to the system prompt for a conversation that help the AI assistant focus on a specific goal or task. They allow you to get specialized assistance without needing to be an expert in AI prompt engineering.

## What Are Focus Modes?

When you activate a focus mode, the AI assistant temporarily adjusts how it responds to better match your specific needs. Think of it as switching to a specialized mode optimized for a particular type of task.

**Examples:**

- **Research focus mode** - Helps with in-depth research on complex topics
- **Code writing focus mode** - Optimized for writing and implementing code
- **Fact checking focus mode** - Specialized in verifying claims and information
- **Career advice focus mode** - Focused on professional development guidance

## How Focus Modes Work

Focus modes work by temporarily modifying the system instructions that guide the AI's responses. This happens automatically in the background - you don't need to understand the technical details.

**Key Characteristics:**

- **Temporary:** Focus modes only affect the current chat session
- **App-specific:** Each app can have its own focus modes
- **Easy to switch:** You can activate or deactivate focus modes at any time
- **Context-aware:** The AI understands when to use focus modes based on your requests

## Activating Focus Modes

Focus modes can be activated in several ways:

### 1. Ask the Assistant (Auto-Activation)

Simply ask the assistant to use a focus mode:

- "Help me research this topic using research mode"
- "Let's write code using the code writing focus"
- "Fact check this information for me"

The assistant will automatically select and activate the appropriate focus mode. When this happens, you'll see an **activation countdown card** appear inline in the chat:

- A compact card shows the app icon, focus mode name, and a **4-second countdown** (4, 3, 2, 1) with an animated progress bar
- During the countdown, you can **click the card** or **press ESC** to cancel the activation. This prevents the focus mode from applying to future messages and adds a system message noting which focus mode was rejected
- Once the countdown completes, the card updates to show "Focus activated" and all subsequent AI responses will use the focus mode's specialized prompt

### 2. Planned: Explicit Request Format

In the future, you'll be able to explicitly request a focus mode using the format `@{app_name}/{focus_mode_name}` in your message. For example:

- `@web/research` - Activate research focus mode for the Web app
- `@code/write_code` - Activate code writing focus mode for the Code app

### 3. API Access (For Developers)

Developers can activate focus modes programmatically via the REST API. See [REST API documentation](../rest_api.md) for technical details.

## Deactivating Focus Modes

There are several ways to deactivate a focus mode:

- **Context menu**: Right-click (or long-press on mobile) the focus mode activation card in the chat and select **"Deactivate"**. This immediately clears the focus mode so all subsequent messages are processed without it.
- **Ask the assistant**: Say "Turn off the focus mode" or "Exit focus mode"
- **Reject during countdown**: Click the activation card or press ESC during the 4-second countdown to prevent activation
- **Start a new chat**: Focus modes don't persist across chats

### Focus Mode Context Menu

When you right-click (or long-press) a focus mode activation card, a context menu appears with two options:

- **Deactivate** — Stops the active focus mode. All follow-up messages will be processed without the focus mode prompt.
- **Details** — Opens the focus mode's details in the app store / settings, where you can learn more about what the focus mode does.

## Example: Research Focus Mode (Web App)

When researching complex topics like economics, politics, or geopolitics, the Research focus mode:

- Makes multiple searches from different viewpoints
- Asks critical questions like "Who might be profiting from this?" and "What are the incentives involved?"
- Checks data sources for conflicts of interest
- Provides a more complete and balanced overview

**Example:** Researching why egg prices increased in the US

- Single search might point to bird flu as the reason
- Research mode also searches for company profits during the same period
- Reveals record profits and shareholder payouts
- Concludes that bird flu wasn't the primary reason for price increases

For more examples of focus modes, see the individual app documentation (e.g., [Web App](./web.md), [Videos App](./videos.md), [Code App](./code.md)).

## Focus Modes vs. Skills

It's important to understand the difference:

- **Focus Modes:** Change how the AI responds and thinks (system prompt modifications)
- **Skills:** Execute specific actions like searching the web, generating images, or transcribing videos

Focus modes can trigger skills when needed. For example, the Research focus mode will automatically use the Web Search skill multiple times to gather comprehensive information.

## Getting Started

The easiest way to use focus modes is to simply ask the assistant:

- "Help me research [topic]"
- "Let's write code for [project]"
- "Fact check this [claim or image]"

The assistant will automatically activate the appropriate focus mode and guide you through the process.

## For Developers

If you're building integrations with OpenMates, see the [REST API documentation](../rest_api.md) for technical details on activating focus modes programmatically.

## Related Documentation

- [Apps Architecture](./README.md) - Overview of apps, skills, and focus modes
- [App Store](./app_store.md) - Browse and discover apps and their focus modes
- [Function Calling](./function_calling.md) - How focus modes integrate with the AI system
- [REST API](../rest_api.md) - Developer API for focus mode activation
