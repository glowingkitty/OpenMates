// contract-test-file: infrastructure
import assert from "node:assert/strict";
import { PassThrough } from "node:stream";
import { test } from "node:test";
import { TuiTerminal, type TerminalKey } from "../src/tuiTerminal.js";

function fakeTerminal() {
  const input = new PassThrough() as PassThrough & NodeJS.ReadStream & {isRaw: boolean; setRawMode: (value: boolean) => void};
  input.isRaw = false;
  input.setRawMode = (value) => { input.isRaw = value; };
  const output = new PassThrough() as PassThrough & NodeJS.WriteStream & {columns: number; rows: number; getColorDepth: () => number};
  output.columns = 100; output.rows = 24; output.getColorDepth = () => 24;
  let written = "";
  output.on("data", (chunk: Buffer) => { written += chunk.toString(); });
  return {input, output, terminal: new TuiTerminal(input, output), written: () => written};
}

test("bracketed multiline paste is one paste event and never an implicit send", async () => {
  const {input, terminal} = fakeTerminal();
  const keys: Array<{text: string; key: TerminalKey}> = [];
  terminal.enter();
  terminal.onKey((text, key) => keys.push({text, key}));
  input.write("\x1b[200~hello\n");
  input.write("world\x1b[201~");
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(keys.map(({text, key}) => ({text, name: key.name})), [{text: "hello\nworld", name: "paste"}]);
  terminal.leave();
});

test("suspend detaches key input and frame rendering during external auth, then restores and cleans up", async () => {
  const {input, output, terminal, written} = fakeTerminal();
  const keys: string[] = [];
  terminal.enter();
  terminal.onKey((text) => keys.push(text));
  let resizeCount = 0;
  terminal.onResize(() => { resizeCount += 1; });
  const value = await terminal.suspend(async () => {
    assert.equal(input.isRaw, false);
    const before = written();
    input.write("x");
    output.emit("resize");
    terminal.render("should stay off alternate screen");
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(written(), before);
    assert.deepEqual(keys, []);
    assert.equal(resizeCount, 0);
    return "authorized";
  });
  assert.equal(value, "authorized");
  assert.equal(input.isRaw, true);
  input.write("y");
  output.emit("resize");
  terminal.render("restored frame");
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(keys, ["y"]);
  assert.equal(resizeCount, 1);
  assert.match(written(), /restored frame/);
  terminal.leave();
  assert.equal(input.isRaw, false);
  assert.equal(input.readableFlowing, false, "leaving releases the resumed input stream so the CLI can exit");
  assert.equal(input.listenerCount("data"), 0);
  assert.equal(output.listenerCount("resize"), 0);
  assert.ok(written().includes("\x1b[?1049l"));
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe, terminal-pointer.visible-action-parity
test("fragmented SGR left press emits one zero-based click while wheels and paste retain their meaning", async () => {
  const {input,terminal,written}=fakeTerminal(),keys:Array<{text:string;name?:string;mouse?:TerminalKey["mouse"]}>=[];
  terminal.enter();terminal.onKey((text,key)=>keys.push({text,name:key.name,mouse:key.mouse}));
  assert.ok(written().includes("\x1b[?1000h\x1b[?1006h"));
  input.write("\x1b");await new Promise((resolve)=>setTimeout(resolve,45));input.write("[<64;12;5M");
  input.write("\x1b[");await new Promise((resolve)=>setTimeout(resolve,45));input.write("<65;12;5M");
  input.write("\x1b[<0;12;");input.write("5M\x1b[<0;12;5ma");
  input.write("\x1b[200~literal \x1b[<64;12;5M\x1b[201~");
  await new Promise((resolve)=>setImmediate(resolve));
  assert.deepEqual(keys,[
    {text:"",name:"scrollup",mouse:{row:4,column:11}},
    {text:"",name:"scrolldown",mouse:{row:4,column:11}},
    {text:"",name:"mouseclick",mouse:{row:4,column:11}},
    {text:"a",name:"a",mouse:undefined},
    {text:"literal \x1b[<64;12;5M",name:"paste",mouse:undefined},
  ]);
  terminal.leave();assert.ok(written().includes("\x1b[?1000l\x1b[?1006l"));
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe
test("mouse releases, other buttons, motion, modifiers, and invalid coordinates cannot activate a click", async () => {
  const {input, terminal} = fakeTerminal();
  const names: string[] = [];
  terminal.enter();
  terminal.onKey((_text, key) => names.push(key.name ?? ""));
  for (const report of [
    "0;1;1m", "1;1;1M", "2;1;1M", "3;1;1M", "32;1;1M",
    "4;1;1M", "8;1;1M", "16;1;1M", "0;0;1M", "0;1;0M",
    "0;9007199254740992;1M", "0;1;9007199254740992M", "bogus;1;1M",
  ]) input.write(`\x1b[<${report}`);
  input.write("\x1b[<0;1;1M");
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(names, ["mouseclick"]);
  terminal.leave();
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe
test("incomplete and oversized reports stay out of composer input across suspension and selection", async () => {
  const {input, terminal, written} = fakeTerminal();
  const keys: Array<{text: string; name?: string}> = [];
  terminal.enter();
  terminal.onKey((text, key) => keys.push({text, name: key.name}));
  input.write("\x1b[<0;" + "9".repeat(140));
  input.write("9Mok");
  input.write("\x1b[<0;2;");
  await terminal.suspend(async () => { input.write("3M"); });
  input.write("z");
  terminal.render("select", null, true);
  input.write("\x1b[<0;1;1M");
  await new Promise((resolve) => setImmediate(resolve));
  terminal.render("resume", null, false);
  input.write("\x1b[<0;1;1M");
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(keys, [{text: "o", name: "o"}, {text: "k", name: "k"}, {text: "z", name: "z"}, {text: "", name: "mouseclick"}]);
  terminal.leave();
  assert.ok(written().endsWith("\x1b[?1049l"));
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe
test("timed-out mouse fragments cannot leak trailing bytes or consume a later paste", async () => {
  const {input, terminal} = fakeTerminal();
  const keys: Array<{text: string; name?: string}> = [];
  terminal.enter();
  terminal.onKey((text, key) => keys.push({text, name: key.name}));
  input.write("\x1b[<0;20;");
  await new Promise((resolve) => setTimeout(resolve, 550));
  input.write("3M");
  input.write("\x1b[<0;20;");
  input.write("\x1b[200~literal \x1b[<0;2;3M\x1b[201~");
  input.write("\x1b[<0;1;1M");
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(keys, [
    {text: "literal \x1b[<0;2;3M", name: "paste"},
    {text: "", name: "mouseclick"},
  ]);
  terminal.leave();
});

test("full-width redraws address rows without newline autowrap or erasing the last cell",()=>{
  const {terminal,written}=fakeTerminal();terminal.enter();const before=written().length;
  terminal.render(Array.from({length:24},(_,i)=>String(i).padEnd(100,"x")).join("\n"));
  const frame=written().slice(before);
  assert.equal(frame.includes("\n"),false);assert.equal(frame.includes("\x1b[J"),false);
  for(let i=0;i<24;i++)assert.ok(frame.includes(`\x1b[${i+1};1H\x1b[2K${String(i).padEnd(100,"x")}`));
  assert.ok(frame.endsWith("\x1b[?2026l"));terminal.leave();
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe
test("incremental painting writes changed rows, including style-only changes, and clears removed rows", () => {
  const {terminal, written} = fakeTerminal();
  terminal.enter();
  terminal.render("header\n\x1b[31mvalue\x1b[0m\nfooter");
  const first = written();
  terminal.render("header\n\x1b[31mvalue\x1b[0m\nfooter");
  assert.equal(written(), first, "unchanged frame emits no bytes");
  terminal.render("header\n\x1b[32mvalue\x1b[0m\nfooter");
  const changed = written().slice(first.length);
  assert.ok(changed.includes("\x1b[2;1H\x1b[2K\x1b[32mvalue"));
  assert.ok(!changed.includes("\x1b[1;1H"));
  assert.ok(!changed.includes("\x1b[3;1H"));
  const beforeRemoval = written().length;
  terminal.render("header");
  const removed = written().slice(beforeRemoval);
  assert.ok(removed.includes("\x1b[2;1H\x1b[J"), "old lower rows are erased");
  assert.ok(!removed.includes("\x1b[1;1H"));
  terminal.leave();
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe
test("resize and resumed alternate screen repaint the complete frame", async () => {
  const {terminal, output, written} = fakeTerminal();
  terminal.enter();
  terminal.render("one\ntwo");
  const beforeResize = written().length;
  output.columns = 80;
  output.rows = 12;
  output.emit("resize");
  terminal.render("one\ntwo");
  const resized = written().slice(beforeResize);
  assert.ok(resized.includes("\x1b[1;1H\x1b[2Kone"));
  assert.ok(resized.includes("\x1b[2;1H\x1b[2Ktwo"));
  terminal.render("one\ntwo", null, true);
  const beforeSuspend = written().length;
  await terminal.suspend(async () => {});
  terminal.render("one\ntwo", null, true);
  assert.ok(written().slice(beforeSuspend).includes("\x1b[1;1H\x1b[2Kone"));
  terminal.leave();
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe
test("shrinking to a full-height frame clears old rows without erasing the new final row", () => {
  const {terminal, output, written} = fakeTerminal();
  output.rows = 3;
  terminal.enter();
  terminal.render("old first\nold second\nold third");
  const beforeResize = written().length;
  output.rows = 2;
  output.emit("resize");
  terminal.render("new first\nnew final");
  const resized = written().slice(beforeResize);
  assert.ok(resized.includes("\x1b[?2026h\x1b[?25l\x1b[2J"));
  assert.ok(resized.includes("\x1b[2;1H\x1b[2Knew final"));
  assert.ok(!resized.includes("\x1b[3;1H\x1b[J"));
  terminal.leave();
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe
test("slow output coalesces pending frames and releases its drain listener on suspension and leave", async () => {
  const {terminal, output, written} = fakeTerminal();
  terminal.enter();
  const write = output.write.bind(output);
  let block = true;
  output.write = ((chunk: string) => {
    write(chunk);
    return !block;
  }) as typeof output.write;
  terminal.render("first");
  const accepted = written();
  terminal.render("obsolete");
  terminal.render("newest");
  assert.equal(written(), accepted, "backpressure holds all subsequent frames");
  assert.equal(output.listenerCount("drain"), 1);
  block = false;
  output.emit("drain");
  const flushed = written().slice(accepted.length);
  assert.ok(flushed.includes("newest"));
  assert.ok(!flushed.includes("obsolete"));
  assert.equal(output.listenerCount("drain"), 0);
  block = true;
  terminal.render("blocked again");
  terminal.render("discard on suspend");
  assert.equal(output.listenerCount("drain"), 1);
  await terminal.suspend(async () => {
    assert.equal(output.listenerCount("drain"), 0);
  });
  const afterSuspend = written();
  output.emit("drain");
  assert.equal(written(), afterSuspend, "suspended frame never reaches the new screen");
  block = false;
  terminal.render("restored");
  assert.ok(written().slice(afterSuspend.length).includes("\x1b[1;1H\x1b[2Krestored"));
  block = true;
  terminal.render("blocked once more");
  terminal.render("discard on leave");
  assert.equal(output.listenerCount("drain"), 1);
  terminal.leave();
  assert.equal(output.listenerCount("drain"), 0);
  const afterLeave = written();
  output.emit("drain");
  assert.equal(written(), afterLeave);
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe, terminal-pointer.viewport-coherent
test("mouse packets begun during backpressure cannot activate the newer pending frame", async () => {
  const {input, output, terminal, written} = fakeTerminal();
  const names: string[] = [];
  terminal.enter();
  terminal.onKey((_text, key) => names.push(key.name ?? ""));
  const write = output.write.bind(output);
  let blocked = true;
  output.write = ((chunk: string) => {
    write(chunk);
    return !blocked;
  }) as typeof output.write;
  terminal.render("old frame");
  terminal.render("new frame");
  input.write("\x1b[<0;1;1M");
  input.write("\x1b[<64;1;1M");
  input.write("x");
  input.write("\x1b");
  blocked = false;
  output.emit("drain");
  input.write("[<0;2;2M");
  input.write("\x1b[<0;3;3M");
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(written().includes("new frame"));
  assert.deepEqual(names, ["x", "mouseclick"], "only the fresh click reaches the new hit map");
  terminal.onKey((_text, key) => {
    names.push(key.name ?? "");
    if (key.name === "y") terminal.render("keyboard redraw");
  });
  blocked = true;
  input.write("y\x1b[<0;4;4M");
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(output.listenerCount("drain"), 1);
  assert.deepEqual(names, ["x", "mouseclick", "y"], "a mouse report after a blocking key handler in the same chunk is suppressed");
  blocked = false;
  output.emit("drain");
  terminal.leave();
});

// contract: feature.terminal-ui@1 terminal-pointer.lifecycle-selection-safe
test("cursor-only updates and selection transitions preserve the frozen frame", () => {
  const {terminal, written} = fakeTerminal();
  terminal.enter();
  terminal.render("stable", {row: 2, column: 3});
  const first = written();
  terminal.render("stable", {row: 2, column: 3});
  assert.equal(written(), first);
  terminal.render("stable", {row: 2, column: 4});
  const moved = written().slice(first.length);
  assert.ok(moved.includes("\x1b[3;5H\x1b[?25h"));
  assert.ok(!moved.includes("\x1b[1;1H"));
  const beforeSelection = written().length;
  terminal.render("stable", null, true);
  const selected = written().slice(beforeSelection);
  assert.ok(selected.includes("\x1b[?1000l\x1b[?1006l"));
  assert.ok(!selected.includes("\x1b[1;1H"));
  const frozen = written();
  terminal.render("background changed", null, true);
  assert.equal(written(), frozen);
  terminal.render("background changed", {row: 2, column: 4}, false);
  const resumed = written().slice(frozen.length);
  assert.ok(resumed.includes("\x1b[?1000h\x1b[?1006h"));
  assert.ok(resumed.includes("\x1b[1;1H\x1b[2Kbackground changed"));
  terminal.leave();
});

test("buffered Escape still dismisses controls and split arrow keys retain their meaning",async()=>{
  const {input,terminal}=fakeTerminal(),names:Array<string|undefined>=[];
  terminal.enter();terminal.onKey((_text,key)=>names.push(key.name));
  input.write("\x1b");await new Promise((resolve)=>setTimeout(resolve,580));assert.deepEqual(names,["escape"]);
  input.write("\x1b[");await new Promise((resolve)=>setTimeout(resolve,45));input.write("A");
  await new Promise((resolve)=>setImmediate(resolve));assert.deepEqual(names,["escape","up"]);terminal.leave();
});

test('composer caret is positioned and native text selection releases mouse capture and freezes redraws',()=>{
  const {terminal,written}=fakeTerminal();terminal.enter();
  terminal.render('Frame',{row:20,column:34});assert.ok(written().includes('\x1b[21;35H\x1b[?25h'));
  terminal.render('Select text',null,true);assert.ok(written().includes('\x1b[?1000l\x1b[?1006l'));
  const selected=written();terminal.render('Background update',null,true);assert.equal(written(),selected);
  terminal.render('Resumed',{row:20,column:34},false);assert.ok(written().includes('Resumed'));assert.ok(written().slice(selected.length).includes('\x1b[?1000h\x1b[?1006h'));
  terminal.leave();assert.ok(written().endsWith('\x1b[?1049l'));
});
