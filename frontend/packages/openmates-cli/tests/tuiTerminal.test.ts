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

test("wheel reports survive fragmented input and clicks never enter the composer", async () => {
  const {input,terminal,written}=fakeTerminal(),keys:Array<{text:string;name?:string}>=[];
  terminal.enter();terminal.onKey((text,key)=>keys.push({text,name:key.name}));
  assert.ok(written().includes("\x1b[?1000h\x1b[?1006h"));
  input.write("\x1b");await new Promise((resolve)=>setTimeout(resolve,45));input.write("[<64;12;5M");
  input.write("\x1b[");await new Promise((resolve)=>setTimeout(resolve,45));input.write("<65;12;5M");
  input.write("\x1b[<0;12;5M\x1b[<0;12;5ma");
  input.write("\x1b[200~literal \x1b[<64;12;5M\x1b[201~");
  await new Promise((resolve)=>setImmediate(resolve));
  assert.deepEqual(keys,[{text:"",name:"scrollup"},{text:"",name:"scrolldown"},{text:"a",name:"a"},{text:"literal \x1b[<64;12;5M",name:"paste"}]);
  terminal.leave();assert.ok(written().includes("\x1b[?1000l\x1b[?1006l"));
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
