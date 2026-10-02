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
