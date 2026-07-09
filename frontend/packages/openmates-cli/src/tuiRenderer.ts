/*
 * OpenMates CLI TUI pure renderer.
 *
 * Purpose: turn terminal chat state into deterministic line-based frames.
 * Architecture: no stream writes, no network access, no terminal mutation.
 * This keeps the TUI testable and lets the event loop redraw whole frames.
 * Security: renders file-reference guidance without reading local files.
 * Tests: frontend/packages/openmates-cli/tests/tui.test.ts
 */

import type { ExampleChatConversation, ExampleChatListItem } from "./exampleChats.js";
import { openMatesAsciiLogo } from "./branding.js";

export type TuiScreen = "start" | "help" | "interests" | "examples" | "example" | "chat" | "embed" | "status";

export type TuiMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  title?: string | null;
};

export type TuiState = {
  screen: TuiScreen;
  input: string;
  scrollOffset: number;
  selectedIndex: number;
  selectedInterests: string[];
  examples: ExampleChatListItem[];
  activeExample: ExampleChatConversation | null;
  messages: TuiMessage[];
  status: string | null;
  isBusy: boolean;
};

const MIN_WIDTH = 48;
const CONTENT_PREVIEW_LINES = 12;

export const TUI_INTERESTS = [
  "software development",
  "use the CLI",
  "writing",
  "research",
  "learning",
  "travel",
  "privacy & security",
  "image generation",
  "everyday tasks",
  "news",
  "events",
  "apartments",
];

export function createInitialTuiState(): TuiState {
  return {
    screen: "start",
    input: "",
    scrollOffset: 0,
    selectedIndex: 0,
    selectedInterests: [],
    examples: [],
    activeExample: null,
    messages: [],
    status: null,
    isBusy: false,
  };
}

export function programmaticQuickstart(): string {
  return `OpenMates CLI

Interactive:
  openmates                         Open the terminal chat UI
  openmates --help                  Show all commands

Ask from scripts:
  openmates chats new "Explain SQLite strict tables"
  openmates chats new "Explain SQLite strict tables" --json
  openmates chats send --chat <chat-id> "Continue" --json

Account:
  openmates login                   Pair-auth login
  openmates signup                  Create an account
  openmates whoami --json           Show current account

Chats and examples:
  openmates chats list
  openmates chats show example-gigantic-airplanes
  openmates chats search "flight"

Files:
  openmates chats new "Review @./src/app.ts"
  openmates chats new "Summarize @~/Downloads/report.pdf"

More:
  openmates apps list
  openmates mentions list
  openmates embeds show <embed-id>
  openmates help
`;
}

export function rankExamples(
  examples: ExampleChatListItem[],
  interests: string[],
): ExampleChatListItem[] {
  const needles = interests.map((interest) => interest.toLowerCase());
  return [...examples]
    .map((example, index) => {
      const haystack = [example.title, example.summary, example.slug, example.category]
        .join(" ")
        .toLowerCase();
      const score = needles.reduce((total, interest) => total + interestScore(haystack, interest), 0);
      return { example, index, score };
    })
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.example);
}

export function renderTuiFrame(state: TuiState, width: number, height: number): string {
  const safeWidth = Math.max(MIN_WIDTH, width);
  const safeHeight = Math.max(12, height);
  const innerWidth = safeWidth - 4;
  const header = topBorder(safeWidth);
  const footer = bottomBorder(safeWidth);
  const contentHeight = safeHeight - 4;
  const body = renderBody(state, innerWidth);
  const visible = sliceForScroll(body, contentHeight, state.scrollOffset, state.screen === "chat");
  const inputLine = state.screen === "interests" || state.screen === "examples"
    ? renderHintLine(state, innerWidth)
    : `> ${state.input || inputPlaceholder(state)}`;
  const lines = [
    header,
    ...padLines(visible, contentHeight, innerWidth).map((line) => boxed(line, innerWidth)),
    separator(safeWidth),
    boxed(truncateVisible(inputLine, innerWidth), innerWidth),
    footer,
  ];
  return lines.join("\n");
}

function renderBody(state: TuiState, width: number): string[] {
  switch (state.screen) {
    case "help":
      return renderHelp(width);
    case "interests":
      return renderInterests(state, width);
    case "examples":
      return renderExamples(state, width);
    case "example":
      return renderExampleChat(state, width);
    case "chat":
      return renderChat(state, width);
    case "status":
      return renderStatus(state, width);
    case "embed":
      return renderStatus(state, width);
    case "start":
    default:
      return renderStart(width);
  }
}

function renderStart(width: number): string[] {
  return [
    "",
    ...openMatesAsciiLogo(width),
    "",
    "AI team mates.",
    "For everyday tasks & learning.",
    "With privacy & safety by design.",
    "",
    "Type a message to start chatting.",
    "Check example chats via /examples",
    "",
    "File references:",
    "Type @./notes.md, @~/Downloads/report.pdf, or @src/app.ts in your message.",
    "Images, PDFs, audio, and code files are attached as encrypted embeds when you are signed in.",
    "",
    "Shortcuts: /help  /login  /signup  /examples  /exit",
  ].flatMap((line) => wrap(line, width));
}

function renderHelp(width: number): string[] {
  return [
    "Help",
    "",
    "Chat",
    "  Enter              Send message",
    "  @./file.md         Attach a file from current directory",
    "  @~/file.pdf        Attach a file from home directory",
    "  @/abs/path.png     Attach a file by absolute path",
    "",
    "Navigation",
    "  Up/Down            Scroll or move selection",
    "  PageUp/PageDown    Scroll faster",
    "  Home/End           Jump to start/end",
    "",
    "Commands",
    "  /examples          Choose example chats",
    "  /login             Pair-auth login",
    "  /signup            Leave TUI and run guided signup",
    "  /embed <id>        Open an embed detail view",
    "  /exit              Leave OpenMates and restore terminal",
    "",
    "Outside TUI: openmates --help, openmates chats --help, openmates apps --help",
  ].flatMap((line) => wrap(line, width));
}

function renderInterests(state: TuiState, width: number): string[] {
  const lines = [
    "Private local personalization",
    "What are you interested in?",
    "",
    "Use Space to select, Enter to continue.",
    "",
  ];
  for (let i = 0; i < TUI_INTERESTS.length; i += 1) {
    const interest = TUI_INTERESTS[i];
    const marker = state.selectedInterests.includes(interest) ? "◉" : "○";
    const cursor = i === state.selectedIndex ? ">" : " ";
    lines.push(`${cursor} ${marker} ${interest}`);
  }
  lines.push("", "Your choices stay local in this terminal session for v1.");
  return lines.flatMap((line) => wrap(line, width));
}

function renderExamples(state: TuiState, width: number): string[] {
  const interests = state.selectedInterests.length > 0 ? state.selectedInterests.join(", ") : "recent examples";
  const lines = ["Example chats", `Recommended from your interests: ${interests}`, ""];
  const visibleCount = Math.max(1, CONTENT_PREVIEW_LINES);
  const start = Math.max(0, Math.min(state.selectedIndex, state.examples.length - visibleCount));
  const examples = state.examples.slice(start, start + visibleCount);
  for (let i = 0; i < examples.length; i += 1) {
    const absoluteIndex = start + i;
    const example = examples[i];
    const cursor = absoluteIndex === state.selectedIndex ? ">" : " ";
    lines.push(`${cursor} ${absoluteIndex + 1}. ${example.title ?? example.slug}`);
    if (example.summary) lines.push(`     ${example.summary}`);
    lines.push("");
  }
  return lines.flatMap((line) => wrap(line, width));
}

function renderExampleChat(state: TuiState, width: number): string[] {
  const convo = state.activeExample;
  if (!convo) return renderExamples(state, width);
  const lines = [
    `Example chat: ${convo.chat.title ?? convo.chat.slug}`,
    "",
  ];
  for (const message of convo.messages) {
    lines.push(labelForRole(message.role));
    lines.push(...renderMessageContent(message.content, width));
    lines.push("");
  }
  if (convo.followUpSuggestions.length > 0) {
    lines.push("Follow-up ideas:");
    for (const [index, suggestion] of convo.followUpSuggestions.slice(0, 3).entries()) {
      lines.push(`  ${index + 1}. ${suggestion}`);
    }
  }
  return lines.flatMap((line) => wrap(line, width));
}

function renderChat(state: TuiState, width: number): string[] {
  const lines = ["OpenMates", ""];
  for (const message of state.messages) {
    lines.push(message.title ?? labelForRole(message.role));
    lines.push(...renderMessageContent(message.content, width));
    lines.push("");
  }
  if (state.isBusy) lines.push("Sophia is typing...");
  if (state.status) lines.push("", state.status);
  return lines.flatMap((line) => wrap(line, width));
}

function renderStatus(state: TuiState, width: number): string[] {
  return ["OpenMates", "", state.status ?? "Working..."]
    .flatMap((line) => wrap(line, width));
}

export function renderMessageContent(content: string, width: number): string[] {
  const lines: string[] = [];
  const rawLines = content.replace(/\n{3,}/g, "\n\n").split("\n");
  let inFence = false;
  let fenceLines = 0;
  for (const rawLine of rawLines) {
    if (rawLine.startsWith("```") || rawLine.startsWith("~~~")) {
      inFence = !inFence;
      fenceLines = 0;
      lines.push(rawLine);
      continue;
    }
    if (inFence) {
      if (fenceLines < CONTENT_PREVIEW_LINES) {
        lines.push(rawLine);
      } else if (fenceLines === CONTENT_PREVIEW_LINES) {
        lines.push("...");
      }
      fenceLines += 1;
      continue;
    }
    lines.push(...wrap(rawLine, width));
  }
  return lines;
}

function renderHintLine(state: TuiState, width: number): string {
  if (state.screen === "interests") return truncateVisible("↑/↓ move   Space select   Enter continue   Esc back", width);
  return truncateVisible("↑/↓ choose   Enter open   /search filter   Esc back", width);
}

function inputPlaceholder(state: TuiState): string {
  if (state.screen === "example") return "Continue from this example, or ask your own question...";
  if (state.screen === "chat") return "Ask a follow-up, use @file, or type /help";
  return "Ask anything...";
}

function interestScore(haystack: string, interest: string): number {
  let score = haystack.includes(interest) ? 10 : 0;
  for (const token of interest.split(/\s+|&/).filter((part) => part.length > 2)) {
    if (haystack.includes(token)) score += 2;
  }
  return score;
}

function labelForRole(role: string): string {
  if (role === "user") return "You";
  if (role === "system") return "System";
  return "Sophia";
}

function sliceForScroll(lines: string[], height: number, scrollOffset: number, bottomAnchored: boolean): string[] {
  const maxStart = Math.max(0, lines.length - height);
  const start = bottomAnchored
    ? Math.max(0, Math.min(maxStart, maxStart - scrollOffset))
    : Math.max(0, Math.min(maxStart, scrollOffset));
  return lines.slice(start, start + height);
}

function wrap(line: string, width: number): string[] {
  if (line.length <= width) return [line];
  const out: string[] = [];
  let remaining = line;
  while (remaining.length > width) {
    const boundary = Math.max(1, remaining.slice(0, width + 1).lastIndexOf(" "));
    out.push(remaining.slice(0, boundary).trimEnd());
    remaining = remaining.slice(boundary).trimStart();
  }
  out.push(remaining);
  return out;
}

function padLines(lines: string[], height: number, width: number): string[] {
  const padded = [...lines];
  while (padded.length < height) padded.push("");
  return padded.slice(0, height).map((line) => truncateVisible(line, width));
}

function truncateVisible(line: string, width: number): string {
  return line.length > width ? `${line.slice(0, Math.max(0, width - 1))}…` : line;
}

function topBorder(width: number): string {
  return `┌${"─".repeat(width - 2)}┐`;
}

function separator(width: number): string {
  return `├${"─".repeat(width - 2)}┤`;
}

function bottomBorder(width: number): string {
  return `└${"─".repeat(width - 2)}┘`;
}

function boxed(line: string, width: number): string {
  return `│ ${line.padEnd(width)} │`;
}
