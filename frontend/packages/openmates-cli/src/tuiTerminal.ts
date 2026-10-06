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
export type TerminalCursor = { row: number; column: number };

export class TuiTerminal {
  private rawWasEnabled = false;
  private keyHandler: TerminalKeyHandler | null = null;
  private resizeHandler: TerminalResizeHandler | null = null;
  private active = false;
  private suspended = false;
  private selectingText = false;
  private readonly keyInput = new PassThrough();
  private readonly decoder = new StringDecoder("utf8");
  private pendingInput = "";
  private pendingMouse = "";
  private paste = false;
  private pasteText = "";
  private inputTimer: NodeJS.Timeout | null = null;
  private mouseTimer: NodeJS.Timeout | null = null;
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
    this.output.write("\x1b[?1000h\x1b[?1006h");
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
    if (this.mouseTimer) clearTimeout(this.mouseTimer);
    this.mouseTimer = null;
    this.inputTimer = null;
    this.pendingInput = ""; this.pendingMouse = ""; this.paste = false; this.pasteText = "";
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
      this.output.write(this.selectingText ? "\x1b[?1000l\x1b[?1006l" : "\x1b[?1000h\x1b[?1006h");
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

  render(frame: string, cursor: TerminalCursor | null = null, selectingText = false): void {
    if (!this.active || this.suspended) return;
    // Native terminal selection is erased by repainting. Freeze the displayed
    // frame and release mouse capture while background sync keeps running.
    if (selectingText && this.selectingText) return;
    const mouse = selectingText ? "\x1b[?1000l\x1b[?1006l" : this.selectingText ? "\x1b[?1000h\x1b[?1006h" : "";
    this.selectingText = selectingText;
    // Address each row explicitly: SSH/PTY newline modes and delayed autowrap
    // must not shift a full-width frame or erase its final border cell.
    const rows=frame.split("\n").slice(0,this.height);
    const body=rows.map((row,index)=>`\x1b[${index+1};1H\x1b[2K${row}`).join("");
    const tail=rows.length<this.height?`\x1b[${rows.length+1};1H\x1b[J`:"";
    const caret = cursor && !selectingText && cursor.row >= 0 && cursor.row < this.height && cursor.column >= 0 && cursor.column < this.width
      ? `\x1b[${cursor.row + 1};${cursor.column + 1}H\x1b[?25h` : "";
    this.output.write(`\x1b[?2026h\x1b[?25l${mouse}${body}${tail}${caret}\x1b[?2026l`);
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
      } else this.dispatchInput(before);
      this.paste = !this.paste;
      this.pendingInput = this.pendingInput.slice(found + marker.length);
      this.receiveInput(""); return;
    }
    let trailing = 0;
    for (let i = 1; i < marker.length; i++) if (this.pendingInput.endsWith(marker.slice(0, i))) trailing = i;
    const ready = this.pendingInput.slice(0, this.pendingInput.length - trailing);
    this.pendingInput = trailing ? this.pendingInput.slice(-trailing) : "";
    if (this.paste) this.pasteText = (this.pasteText + ready).slice(0, 131072);
    else if (ready) this.dispatchInput(ready);
    if (trailing && !this.paste) this.inputTimer = setTimeout(() => {this.dispatchInput(this.pendingInput);this.pendingInput="";this.inputTimer=null;}, 30);
  }

  /** Consume SGR mouse reports without letting clicks become composer text. */
  private dispatchInput(text:string):void {
    if(this.mouseTimer)clearTimeout(this.mouseTimer);this.mouseTimer=null;
    const input=this.pendingMouse+text;this.pendingMouse="";
    let offset=0;
    while(offset<input.length){
      const start=input.indexOf("\x1b[<",offset);
      if(start<0){
        const rest=input.slice(offset),prefix=rest.endsWith("\x1b[")?"\x1b[":rest.endsWith("\x1b")?"\x1b":"";
        this.keyInput.write(prefix?rest.slice(0,-prefix.length):rest);
        if(prefix){
          this.pendingMouse=prefix;
          this.mouseTimer=setTimeout(()=>{
            const pending=this.pendingMouse;this.pendingMouse="";this.mouseTimer=null;
            if(pending==="\x1b")this.keyHandler?.("\x1b",{name:"escape",sequence:pending});
            else this.keyInput.write(pending);
          },500);
        }
        break;
      }
      this.keyInput.write(input.slice(offset,start));
      // eslint-disable-next-line no-control-regex -- Parse terminal SGR mouse protocol bytes.
      const rest=input.slice(start),report=/^\x1b\[<(\d+);(\d+);(\d+)([mM])/.exec(rest);
      if(!report){
        // eslint-disable-next-line no-control-regex -- Retain a fragmented SGR mouse report.
        if(rest.length<128&&/^\x1b\[<[\d;]*$/.test(rest)){this.pendingMouse=rest;break;}
        this.keyInput.write(rest.slice(0,3));offset=start+3;continue;
      }
      const button=Number(report[1]);
      if(report[4]==="M"&&(button&64)&&((button&3)===0||(button&3)===1))this.keyHandler?.("",{name:(button&3)===0?"scrollup":"scrolldown",sequence:report[0]});
      offset=start+report[0].length;
    }
  }

  private removeListeners(): void {
    if (this.keyHandler) {
      this.keyInput.off("keypress", this.keyHandler as never);
      this.keyHandler = null;
    }
    this.input.off("data", this.rawInput);
    if (this.inputTimer) clearTimeout(this.inputTimer);
    if (this.mouseTimer) clearTimeout(this.mouseTimer);
    this.mouseTimer = null;
    this.inputTimer = null; this.pendingInput = ""; this.pendingMouse = ""; this.paste = false; this.pasteText = "";
    if (this.resizeHandler) {
      this.output.off("resize", this.resizeHandler);
      this.resizeHandler = null;
    }
  }
}
