/** Synthetic renderer benchmark. No client construction, account reads, or network. */
import { performance } from 'node:perf_hooks';
import { PassThrough } from 'node:stream';
import { register } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
register(pathToFileURL(path.join(packageRoot, 'tests/loader.mjs')), import.meta.url);
const args = process.argv.slice(2);
const option = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const source = path.resolve(option('--source', path.join(packageRoot, 'src')));
const output = option('--output', null);
const fixtureDir = option('--fixtures', null);
const {createInitialTuiState, renderTuiFrame} = await import(pathToFileURL(path.join(source, 'tuiRenderer.ts')));
const {TuiTerminal} = await import(pathToFileURL(path.join(source, 'tuiTerminal.ts')));
const {parseTuiMarkdown} = await import(pathToFileURL(path.join(source, 'tuiMarkdown.ts')));
const samples = Math.max(3, Math.min(30, Number(option('--samples', '10'))));
const paragraph = 'The **important result** is available in [Berlin](wiki:Berlin). This synthetic message describes a project with tasks, notes, and useful context for the next step. ';
const rich = '### A useful heading\n\n' + paragraph.repeat(5) + '\n\n- **First task:** review the result\n- Second task: compare the evidence\n\n```typescript\nconst example = 42;\n```';
const summarize = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  return {medianMs: +sorted[Math.floor(sorted.length / 2)].toFixed(3), p95Ms: +sorted[Math.ceil(sorted.length * .95) - 1].toFixed(3)};
};
function stateFor(count) {
  const state = createInitialTuiState();
  Object.assign(state, {screen: 'chat', focus: 'composer', signedIn: true, currentUserHash: 'synthetic-owner', activeChatId: 'synthetic-chat',
    activeChat: {id: 'synthetic-chat', shortId: 'synth', title: 'Synthetic render benchmark', summary: 'No real account data.',
      category: 'software_development', createdAt: 1791580800, updatedAt: 1791580800, mateName: 'Sophia'}});
  state.messages = Array.from({length: count}, (_, i) => ({id: `message-${i}`, role: i % 2 ? 'assistant' : 'user',
    content: i % 2 ? `${rich}\n\nMessage ${i}.` : `Please review synthetic result ${i}.`}));
  return state;
}
function terminalFor(width, height) {
  const input = new PassThrough(); input.isRaw = false; input.setRawMode = value => {input.isRaw = value;};
  const output = new PassThrough(); output.columns = width; output.rows = height; output.getColorDepth = () => 24;
  let bytes = 0; output.on('data', chunk => {bytes += chunk.length;});
  const terminal = new TuiTerminal(input, output); terminal.enter();
  return {terminal, bytes: () => bytes};
}
const workloads = [];
for (const count of [20, 100, 500]) {
  for (const [width, height] of [[80, 24], [160, 50], [240, 70]]) {
    const state = stateFor(count); const io = terminalFor(width, height);
    let start = performance.now(); let frame = renderTuiFrame(state, width, height, {colorMode: 'truecolor'});
    const coldMs = performance.now() - start;
    let before = io.bytes(); io.terminal.render(frame); const coldAnsiBytes = io.bytes() - before;
    const draft = [], scroll = [], draftBytes = [], scrollBytes = [];
    // Warm up layouts before measuring typing. All operations retain the same history.
    for (let i = 0; i < 3; i++) renderTuiFrame(state, width, height, {colorMode: 'truecolor'});
    for (let i = 0; i < samples; i++) {
      state.input = `synthetic draft ${i}`;
      start = performance.now(); frame = renderTuiFrame(state, width, height, {colorMode: 'truecolor'}); draft.push(performance.now() - start);
      before = io.bytes(); io.terminal.render(frame); draftBytes.push(io.bytes() - before);
    }
    for (let i = 0; i < samples; i++) {
      state.scrollOffset = i + 1;
      start = performance.now(); frame = renderTuiFrame(state, width, height, {colorMode: 'truecolor'}); scroll.push(performance.now() - start);
      before = io.bytes(); io.terminal.render(frame); scrollBytes.push(io.bytes() - before);
    }
    before = io.bytes(); io.terminal.render(frame); const unchangedAnsiBytes = io.bytes() - before;
    io.terminal.leave();
    const row = {messages: count, viewport: `${width}x${height}`, textBytes: state.messages.reduce((n, m) => n + Buffer.byteLength(m.content), 0),
      coldMs: +coldMs.toFixed(3), draft: summarize(draft), scroll: summarize(scroll), coldAnsiBytes,
      draftAnsiBytes: Math.round(draftBytes.reduce((a, b) => a + b) / samples), scrollAnsiBytes: Math.round(scrollBytes.reduce((a, b) => a + b) / samples), unchangedAnsiBytes};
    workloads.push(row); process.stderr.write(JSON.stringify(row) + '\n');
    if (fixtureDir) {
      fs.mkdirSync(fixtureDir, {recursive: true});
      const projectionStart = performance.now();
      const messages = state.messages.map(m => ({id: m.id, role: m.role, lines: parseTuiMarkdown(m.content, width - 4)
        .filter(block => block.type === 'line').map(block => {const line = block.line;
          return {spans: typeof line === 'string' ? [{text: line}] : line.spans?.map(({text, bold, color}) => ({text, bold, color})) ?? [{text: line.text, bold: line.bold, color: line.color}]};})}));
      fs.writeFileSync(path.join(fixtureDir, `chat-${count}-${width}.json`), JSON.stringify({v: 1, type: 'snapshot', epoch: 1, scope: 'synthetic-owner:personal:synthetic-chat',
        state: {view: 'chats', sidebarOpen: false, title: state.activeChat.title, category: state.activeChat.category,
          categories: [{id: 'software_development', label: 'Software development', color: '#008ba8'}],
          chats: [{id: 'synthetic-chat', title: state.activeChat.title, categoryId: state.activeChat.category}], selectedChatId: 'synthetic-chat',
          messages, draft: '', workspaceRows: []}}));
      row.sharedProjectionMs = +(performance.now() - projectionStart).toFixed(3);
    }
  }
}
const report = {schemaVersion: 1, source, node: process.version, arch: process.arch, cpu: os.cpus()[0]?.model, samples,
  measurement: 'Synchronous frame construction and emitted ANSI bytes; excludes network, decryption, real terminal/SSH latency and input scheduling.',
  memory: process.memoryUsage(), workloads};
if (output) {fs.mkdirSync(path.dirname(output), {recursive: true}); fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');}
else console.log(JSON.stringify(report, null, 2));
