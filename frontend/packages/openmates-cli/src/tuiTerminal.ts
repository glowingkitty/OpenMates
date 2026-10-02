/*
 * OpenMates CLI terminal lifecycle helpers.
 *
 * Purpose: own raw-mode, alternate-screen, resize, and cleanup behavior for
 * the interactive terminal chat UI.
 * Architecture: tiny wrapper over Node streams and ANSI control sequences.
 * Security: cleanup must run even when commands fail so the user's shell is not
 * left in raw mode or with a hidden cursor.
 * Tests: frontend/packages/openmates-cli/tests/tui.test.ts
 */

import { emitKeypressEvents } from "node:readline";
import type { ReadStream, WriteStream } from "node:tty";
import { PassThrough } from "node:stream";
import { StringDecoder } from "node:string_decoder";
import type { TuiColorMode } from "./tuiText.js";

export type TerminalKey = {
  name?: string;
  sequence?: string;
  ctrl?: boolean;
  meta?: boolean;
  shift?: boolean;
};

export type TerminalKeyHandler = (chunk: string, key: TerminalKey) => void;
export type TerminalResizeHandler = () => void;

export class TuiTerminal {
  private rawWasEnabled = false;
  private keyHandler: TerminalKeyHandler | null = null;
  private resizeHandler: TerminalResizeHandler | null = null;
  private active = false;
  private suspended = false;
  private readonly keyInput = new PassThrough();
  private readonly decoder = new StringDecoder("utf8");
  private pendingInput = "";
  private paste = false;
  private pasteText = "";
  private inputTimer: NodeJS.Timeout | null = null;
  private readonly rawInput = (chunk: Buffer | string) => this.receiveInput(typeof chunk === "string" ? chunk : this.decoder.write(chunk));
  private readonly input: NodeJS.ReadStream;
  private readonly output: NodeJS.WriteStream;

  constructor(
    input: NodeJS.ReadStream = process.stdin,
    output: NodeJS.WriteStream = process.stdout,
  ) {
    this.input = input;
    this.output = output;
  }

  get width(): number {
    return (this.output as WriteStream).columns ?? 80;
  }

  get height(): number {
    return (this.output as WriteStream).rows ?? 24;
  }

  get colorMode(): TuiColorMode {
    if (process.env.NO_COLOR !== undefined || process.env.TERM === "dumb") return "none";
    if (process.env.COLORTERM === "truecolor" || process.env.COLORTERM === "24bit" || process.env.FORCE_COLOR === "3") return "truecolor";
    const depth = (this.output as WriteStream).getColorDepth?.() ?? 8;
    return depth >= 24 ? "truecolor" : depth >= 8 ? "ansi256" : depth >= 4 ? "ansi16" : "none";
  }
  get ascii(): boolean { return process.env.OPENMATES_ASCII === "1" || process.env.TERM === "dumb"; }

  enter(): void {
    if (this.active) return;
    this.active = true;
    this.rawWasEnabled = Boolean((this.input as ReadStream).isRaw);
    emitKeypressEvents(this.keyInput);
    this.input.on("data", this.rawInput);
    if (typeof (this.input as ReadStream).setRawMode === "function") {
      (this.input as ReadStream).setRawMode(true);
    }
    this.input.resume();
    this.output.write("\x1b[?1049h");
    this.output.write("\x1b[?25l");
    this.output.write("\x1b[?2004h");
    this.output.write("\x1b[2J\x1b[H");
  }

  leave(): void {
    if (!this.active) return;
    this.removeListeners();
    this.output.write("\x1b[?25h");
    this.output.write("\x1b[?2004l");
    this.output.write("\x1b[?1000l\x1b[?1006l");
    this.output.write("\x1b[?1049l");
    if (typeof (this.input as ReadStream).setRawMode === "function") {
      (this.input as ReadStream).setRawMode(this.rawWasEnabled);
    }
    this.input.pause();
    this.active = false;
  }

  async suspend<T>(run: () => Promise<T>): Promise<T> {
    this.suspended = true;
    this.input.off("data", this.rawInput);
    if (this.resizeHandler) this.output.off("resize", this.resizeHandler);
    if (this.inputTimer) clearTimeout(this.inputTimer);
    this.inputTimer = null;
    this.pendingInput = ""; this.paste = false; this.pasteText = "";
    this.output.write("\x1b[?25h");
    this.output.write("\x1b[?2004l");
    this.output.write("\x1b[?1000l\x1b[?1006l");
    this.output.write("\x1b[?1049l");
    if (typeof (this.input as ReadStream).setRawMode === "function") {
      (this.input as ReadStream).setRawMode(this.rawWasEnabled);
    }
    try {
      return await run();
    } finally {
      this.suspended = false;
      if (this.active) {
      this.input.on("data", this.rawInput);
      if (this.resizeHandler) this.output.on("resize", this.resizeHandler);
      if (typeof (this.input as ReadStream).setRawMode === "function") {
        (this.input as ReadStream).setRawMode(true);
      }
      this.input.resume();
      this.output.write("\x1b[?1049h");
      this.output.write("\x1b[?25l");
      this.output.write("\x1b[?2004h");
      this.output.write("\x1b[2J\x1b[H");
      }
    }
  }

  onKey(handler: TerminalKeyHandler): void {
    if (this.keyHandler) this.keyInput.off("keypress", this.keyHandler as never);
    this.keyHandler = handler;
    this.keyInput.on("keypress", handler as never);
  }

  onResize(handler: TerminalResizeHandler): void {
    if (this.resizeHandler) this.output.off("resize", this.resizeHandler);
    this.resizeHandler = handler;
    this.output.on("resize", handler);
  }

  render(frame: string): void {
    if (!this.active || this.suspended) return;
    this.output.write("\x1b[H");
    this.output.write(frame);
    this.output.write("\x1b[J");
  }

  private receiveInput(text: string): void {
    if (this.inputTimer) clearTimeout(this.inputTimer);
    this.inputTimer = null;
    this.pendingInput += text;
    const marker = this.paste ? "\x1b[201~" : "\x1b[200~";
    const found = this.pendingInput.indexOf(marker);
    if (found >= 0) {
      const before = this.pendingInput.slice(0, found);
      if (this.paste) {
        this.pasteText = (this.pasteText + before).slice(0, 131072);
        this.keyHandler?.(this.pasteText, { name: "paste" }); this.pasteText = "";
      } else this.keyInput.write(before);
      this.paste = !this.paste;
      this.pendingInput = this.pendingInput.slice(found + marker.length);
      this.receiveInput(""); return;
    }
    let trailing = 0;
    for (let i = 1; i < marker.length; i++) if (this.pendingInput.endsWith(marker.slice(0, i))) trailing = i;
    const ready = this.pendingInput.slice(0, this.pendingInput.length - trailing);
    this.pendingInput = trailing ? this.pendingInput.slice(-trailing) : "";
    if (this.paste) this.pasteText = (this.pasteText + ready).slice(0, 131072);
    else if (ready) this.keyInput.write(ready);
    if (trailing && !this.paste) this.inputTimer = setTimeout(() => {this.keyInput.write(this.pendingInput);this.pendingInput="";this.inputTimer=null;}, 30);
  }

  private removeListeners(): void {
    if (this.keyHandler) {
      this.keyInput.off("keypress", this.keyHandler as never);
      this.keyHandler = null;
    }
    this.input.off("data", this.rawInput);
    if (this.inputTimer) clearTimeout(this.inputTimer);
    this.inputTimer = null; this.pendingInput = ""; this.paste = false; this.pasteText = "";
    if (this.resizeHandler) {
      this.output.off("resize", this.resizeHandler);
      this.resizeHandler = null;
    }
  }
}
