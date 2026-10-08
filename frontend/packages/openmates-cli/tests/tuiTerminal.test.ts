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
