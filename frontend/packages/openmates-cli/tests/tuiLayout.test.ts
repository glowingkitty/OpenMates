// contract-test-file: infrastructure
import assert from "node:assert/strict";
import { test } from "node:test";
import { CATEGORY_GRADIENTS } from "../../chatCategoryTheme.js";
import { chatBackground, DEFAULT_CHAT_BACKGROUND, renderWorkspaceFrame } from "../src/tuiLayout.js";
import { createInitialTuiState } from "../src/tuiRenderer.js";
import { cells, stripAnsi } from "../src/tuiText.js";

test("sidebar starts closed at wide and narrow widths", () => {
  const state = createInitialTuiState();
  state.recentChats = [{id: "secret", title: "Sidebar-only chat"} as typeof state.recentChats[number]];
  assert.equal(state.sidebarOpen, false);
  for (const width of [72, 120]) {
    const frame = renderWorkspaceFrame(state, width, 18, ["Visible body"], {colorMode: "none"});
    assert.match(frame, /Visible body/);
    assert.doesNotMatch(frame, /Sidebar-only chat/);
  }
});

test("frame holds exact display-cell width and row count with CJK, emoji and untrusted ANSI", () => {
  const state = createInitialTuiState();
  const width = 112, height = 20;
  const frame = renderWorkspaceFrame(state, width, height, ["漢字 🧪 \x1b[31mred\x1b[0m", "Long 確認 🧪 ".repeat(20)], {colorMode: "none"});
  const rows = frame.split("\n");
  assert.equal(rows.length, height);
  assert.ok(rows.every((row) => cells(row) === width), rows.map((row) => cells(row)).join(","));
  assert.match(frame, /漢字 🧪 red/);
  assert.equal(frame.includes("\x1b"), false);
});

test("long sidebars keep the keyboard selection visible at wide and narrow widths", () => {
  const state = createInitialTuiState();
  state.recentChats = Array.from({length: 40}, (_, i) => ({id: `chat-${i}`, title: `Recent chat ${i + 1}`} as typeof state.recentChats[number]));
  state.sidebarOpen = true;
  state.focus = "sidebar";
  state.sidebarIndex = 36;
  for (const [width, height] of [[48, 16], [112, 20]]) {
    const frame = renderWorkspaceFrame(state, width, height, ["Visible body"], {colorMode: "none"});
    assert.match(frame, /> Recent chat 36/);
    assert.equal(frame.split("\n").length, height);
    assert.ok(frame.split("\n").every((row) => cells(row) === width));
  }
});

test("chat hero uses one shared category color across all rows with a plain fallback", () => {
  const state = createInitialTuiState();
  state.screen = "chat";
  state.activeChat = {id: "chat", title: "Test", category: "software_development"} as typeof state.activeChat;
  const shared = CATEGORY_GRADIENTS.software_development;
  assert.equal(chatBackground("software_development"), shared.start);
  assert.equal(chatBackground("unknown"), DEFAULT_CHAT_BACKGROUND);
  const colored = renderWorkspaceFrame(state, 100, 14, ["Hero", "Second row", "Third row"], {colorMode: "truecolor", headerRows: 3});
  const rgb = [1, 3, 5].map((offset) => parseInt(shared.start.slice(offset, offset + 2), 16));
  assert.ok(colored.includes(`\x1b[48;2;${rgb.join(";")}m`));
  // eslint-disable-next-line no-control-regex -- Inspect trusted terminal background sequences.
  assert.deepEqual([...new Set(colored.match(/\x1b\[48;2;[\d;]+m/g))], [`\x1b[48;2;${rgb.join(";")}m`]);
  const plain = renderWorkspaceFrame(state, 100, 14, ["Hero"], {colorMode: "none", headerRows: 1});
  assert.match(plain, /Hero/);
  assert.equal(stripAnsi(plain), plain);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("manual paging is not overridden by selection and overshoot reverses immediately", () => {
  const state=createInitialTuiState();state.screen="projects";state.focus="content";
  const body=Array.from({length:60},(_,i)=>i===2?"> Selected project":`Row ${i}`);
  state.scrollOffset=10000;
  const bottom=renderWorkspaceFrame(state,90,18,body);
  assert.match(bottom,/Row 59/);assert.doesNotMatch(bottom,/Selected project/);
  const end=state.scrollOffset;assert.ok(end<60);
  state.scrollOffset--;renderWorkspaceFrame(state,90,18,body);assert.equal(state.scrollOffset,end-1);
  state.followSelection=true;
  assert.match(renderWorkspaceFrame(state,90,18,body),/> Selected project/);
  state.scrollOffset=20;
  assert.doesNotMatch(renderWorkspaceFrame(state,90,18,body),/Selected project/);
  state.screen="chat";state.scrollOffset=10000;renderWorkspaceFrame(state,90,18,body);
  const top=state.scrollOffset;state.scrollOffset--;renderWorkspaceFrame(state,90,18,body);assert.equal(state.scrollOffset,top-1);
});
