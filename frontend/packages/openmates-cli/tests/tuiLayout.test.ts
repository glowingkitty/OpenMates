// contract-test-file: infrastructure
import assert from "node:assert/strict";
import { test } from "node:test";
import { CATEGORY_GRADIENTS } from "../../chatCategoryTheme.js";
import { chatBackground, DEFAULT_CHAT_BACKGROUND, renderWorkspaceFrame } from "../src/tuiLayout.js";
import { createInitialTuiState, renderTuiFrame } from "../src/tuiRenderer.js";
import { handleWorkspaceKey, type WorkspaceContext } from "../src/tuiWorkspaceController.js";
import { tuiChatSidebarRows } from "../src/tuiChatSidebar.js";
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
  state.sidebarIndex = tuiChatSidebarRows(state).findIndex(row => row.chatId === "chat-35");
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

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("wide chat body uses the workspace container while the composer stays centered at 100 columns", () => {
  const state = createInitialTuiState();
  state.screen = "chat";
  state.activeChat = {id: "chat", title: "Centered chat", category: "software_development"} as typeof state.activeChat;
  state.messages = [{role: "user", content: "A message in the centered column"}];
  const frame = renderTuiFrame(state, 160, 24, {colorMode: "truecolor"});
  const rows = stripAnsi(frame).split("\n");
  const inputTop = rows.find((row) => /^\s+╭─+╮\s+$/.test(row))!;
  assert.equal(inputTop.indexOf("╭"), 30);
  assert.equal(inputTop.indexOf("╮"), 129);
  const header = frame.split("\n").find((row) => row.includes("Centered chat") && row.includes("\x1b[48;2;"))!;
  // eslint-disable-next-line no-control-regex -- Inspect the painted header bounds.
  const painted = /\x1b\[48;2;[\d;]+m([^\x1b]*)/.exec(header)!;
  assert.equal(cells(painted[1]), 156);
  assert.equal(cells(stripAnsi(header.slice(0, painted.index))), 2);
  assert.equal(rows.find((row) => row.includes("A message in the centered column"))!.indexOf("A message"), 2);
  assert.ok(rows.every((row) => row.startsWith(" ") && row.endsWith(" ") && cells(row) === 160));
  assert.equal(rows.length, 24);
  assert.match(frame, /←\/→ embed/);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("chat and app workspace bodies share the 180-column cap on very wide terminals", () => {
  const state = createInitialTuiState();
  state.screen = "chat";
  state.activeChat = {id: "chat", title: "Wide chat", category: "software_development"} as typeof state.activeChat;
  const frame = renderTuiFrame(state, 220, 24, {colorMode: "truecolor"});
  const rows = stripAnsi(frame).split("\n");
  const heading = frame.split("\n").find((row) => row.includes("Wide chat") && row.includes("\x1b[48;2;"))!;
  // eslint-disable-next-line no-control-regex -- Inspect the painted workspace bounds.
  const painted = /\x1b\[48;2;[\d;]+m([^\x1b]*)/.exec(heading)!;
  assert.equal(cells(painted[1]), 180);
  assert.equal(cells(stripAnsi(heading.slice(0, painted.index))), 20);
  const inputTop = rows.find((row) => /^\s+╭─+╮\s+$/.test(row))!;
  assert.equal(inputTop.indexOf("╭"), 60);
  assert.equal(inputTop.indexOf("╮") - inputTop.indexOf("╭") + 1, 100);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("app content expands while the composer stays centered at its existing maximum width", () => {
  const state = createInitialTuiState();
  state.workspace = "apps"; state.screen = "app";
  state.activeApp = {id: "health", name: "Health", description: "Improve your health", category: "personal", skills: [], focusModes: [], settingsMemories: []};
  state.focus = "composer";
  for (const sidebar of [false, true]) {
    state.sidebarOpen = sidebar;
    const rows = stripAnsi(renderTuiFrame(state, 200, 32, {colorMode: "ansi256"})).split("\n");
    const header = rows.find((row) => row.includes("APP WORKSPACE"))!;
    const tabs = rows.find((row) => row.includes("[Skills]"))!;
    const inputTop = rows.find((row) => /^\s+╭─+╮\s+$/.test(row))!;
    const left = header.indexOf("╭"), right = 200 - header.indexOf("╮") - 1;
    assert.ok(Math.abs(left - (sidebar ? 27 : 0) - right) <= 1);
    const inputLeft=inputTop.indexOf('╭'),inputRight=200-inputTop.indexOf('╮')-1;
    assert.ok(Math.abs(inputLeft-(sidebar?27:0)-inputRight)<=1);
    assert.equal(inputTop.indexOf('╮')-inputLeft+1,100);
    assert.ok(header.indexOf('╮')-left+1>100);
    assert.equal(tabs.indexOf("1 [Skills]"), left + 1);
    assert.ok(rows.every((row) => cells(row) === 200 && row.startsWith(" ") && row.endsWith(" ")));
    assert.equal(rows.length, 32);
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("borderless frame and wrapped composer stay bounded through small terminals and Unicode", () => {
  for (const width of [1, 2, 4, 5, 6, 24, 72, 120, 160]) for (const ascii of [false, true]) {
    const state = createInitialTuiState();
    state.screen = "chat";
    state.input = `${"漢字 🧪 ".repeat(24)}Draft ends here`;
    const frame = renderTuiFrame(state, width, 24, {colorMode: "truecolor", ascii});
    const rows = stripAnsi(frame).split("\n");
    assert.equal(rows.length, 24);
    assert.ok(rows.every((row) => cells(row) === width), `${width}: ${rows.map(cells)}`);
    if (width >= 24) {
      assert.match(stripAnsi(frame).replace(/[\s│|>]/g, ""), /Draftendshere/);
      assert.ok(rows.every((row) => row.startsWith(" ") && row.endsWith(" ")));
    }
  }
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("sidebar sizing keeps the active workspace visible in the navigation header", () => {
  const state = createInitialTuiState();
  state.workspace = "tasks"; state.screen = "tasks"; state.sidebarOpen = true;
  const nav = stripAnsi(renderTuiFrame(state, 112, 24)).split("\n")[0];
  assert.match(nav, /OpenMates\s+Chats\s+Apps\s+Projects\s+Workflows\s+\[Tasks\]/);
  assert.match(nav, /(?:Ctrl\+G navigation|\^G nav)/);
  assert.doesNotMatch(nav, /…/);
});

// contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
test("navigation distinguishes the focused workspace, active workspace, and keyboard hint", () => {
  const state = createInitialTuiState();
  state.workspace = "chats"; state.screen = "chats";
  state.focus = "navigation"; state.navigationIndex = 2;
  const nav = renderTuiFrame(state, 160, 24, {colorMode: "truecolor"}).split("\n")[0];
  assert.ok(nav.includes('\x1b[38;2;255;85;59m[Chats]'));
  assert.ok(nav.includes('\x1b[38;2;50;173;230m› Projects'));
  assert.ok(nav.includes('\x1b[38;2;128;128;128mCtrl+G navigation'));
  assert.match(stripAnsi(nav), /\[Chats\].*› Projects.*Ctrl\+G navigation/);
});

// contract-test: supporting surface=cli assertions=tasks.lifecycle.visible,cli.surface.semantic-parity
test("centered task boards keep every column keyboard reachable at large terminal widths", async () => {
  for (const width of [96, 112, 160, 220]) {
    for (const sidebarOpen of [false, true]) {
      const state = createInitialTuiState();
      state.workspace = "tasks"; state.screen = "tasks"; state.focus = "content";
      state.sidebarOpen = sidebarOpen; state.taskStatusFilter = "todo";
      const context = {state, terminal: {width}, client: {}, render: () => {}, command: async () => {}, send: async () => {}} as unknown as WorkspaceContext;
      await handleWorkspaceKey(context, "", {name: "left"});
      for (const [status, label] of [["backlog", "Backlog"], ["todo", "Todo"], ["in_progress", "In progress"], ["blocked", "Blocked"], ["done", "Done"]]) {
        assert.equal(state.taskStatusFilter, status, `width ${width}, sidebar ${sidebarOpen}`);
        assert.ok(renderTuiFrame(state, width, 40).includes(`${label} (`));
        await handleWorkspaceKey(context, "", {name: "right"});
      }
      assert.equal(state.taskStatusFilter, "backlog");
      await handleWorkspaceKey(context, "", {name: "left"});
      assert.equal(state.taskStatusFilter, "done");
    }
  }
});
