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
  mouse?: { row: number; column: number };
};

export type TerminalKeyHandler = (chunk: string, key: TerminalKey) => void;
export type TerminalResizeHandler = () => void;
export type TerminalCursor = { row: number; column: number };
type PendingFrame = { frame: string; cursor: TerminalCursor | null; selectingText: boolean };

export class TuiTerminal {
  private rawWasEnabled = false;
  private keyHandler: TerminalKeyHandler | null = null;
  private resizeHandler: TerminalResizeHandler | null = null;
  private active = false;
  private suspended = false;
  private selectingText = false;
  private paintedSelection = false;
  private paintedRows: string[] | null = null;
  private paintedCursor: TerminalCursor | null = null;
  private paintedWidth = 0;
  private paintedHeight = 0;
  private outputBlocked = false;
  /** Animation ticks must not add work while stdout is awaiting drain. */
  get isOutputBlocked(): boolean { return this.outputBlocked; }
  private pendingFrame: PendingFrame | null = null;
  private readonly outputDrained = () => {
    this.output.off("drain", this.outputDrained);
    this.outputBlocked = false;
    const pending = this.pendingFrame;
    this.pendingFrame = null;
    if (pending && this.active && !this.suspended) this.paint(pending);
  };
  private readonly resized = () => { this.paintedRows = null; };
  private readonly keyInput = new PassThrough();
  private readonly decoder = new StringDecoder("utf8");
  private pendingInput = "";
  private pendingInputBlocked = false;
  private pendingMouse = "";
  private pendingMouseBlocked = false;
  private discardingMouse = false;
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
  /** Explicit terminal preference; GUI OS motion preferences are not available over SSH. */
  get reducedMotion(): boolean { return process.env.OPENMATES_REDUCED_MOTION === "1"; }
  get ascii(): boolean { return process.env.OPENMATES_ASCII === "1" || process.env.TERM === "dumb"; }

  enter(): void {
    if (this.active) return;
    this.resetPaint();
    this.selectingText = false;
    this.paintedSelection = false;
    this.active = true;
    this.rawWasEnabled = Boolean((this.input as ReadStream).isRaw);
    emitKeypressEvents(this.keyInput);
    this.input.on("data", this.rawInput);
    this.output.on("resize", this.resized);
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
    this.resetPaint();
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
    this.selectingText = false;
    this.paintedSelection = false;
  }

  async suspend<T>(run: () => Promise<T>): Promise<T> {
    this.suspended = true;
    this.resetPaint();
    this.input.off("data", this.rawInput);
    this.output.off("resize", this.resized);
    if (this.resizeHandler) this.output.off("resize", this.resizeHandler);
    if (this.inputTimer) clearTimeout(this.inputTimer);
    if (this.mouseTimer) clearTimeout(this.mouseTimer);
    this.mouseTimer = null;
    this.inputTimer = null;
    this.pendingInput = ""; this.pendingInputBlocked = false; this.pendingMouse = ""; this.pendingMouseBlocked = false; this.discardingMouse = false; this.paste = false; this.pasteText = "";
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
      // Discard bytes queued while an external command owned stdin.
      while (this.input.read() !== null) { /* drain suspended input */ }
      this.input.on("data", this.rawInput);
      this.output.on("resize", this.resized);
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
      this.paintedSelection = this.selectingText;
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
    if (selectingText && this.selectingText && this.paintedRows !== null) return;
    this.selectingText = selectingText;
    const next = { frame, cursor, selectingText };
    if (this.outputBlocked) {
      this.pendingFrame = next;
      return;
    }
    this.paint(next);
  }

  private paint({ frame, cursor, selectingText }: PendingFrame): void {
    const width = this.width;
    const height = this.height;
    // Address each row explicitly: SSH/PTY newline modes and delayed autowrap
    // must not shift a full-width frame or erase its final border cell.
    const rows = frame.split("\n").slice(0, height);
    const repaint = this.paintedRows === null || width !== this.paintedWidth || height !== this.paintedHeight;
    const body = rows.map((row, index) => repaint || row !== this.paintedRows?.[index]
      ? `\x1b[${index + 1};1H\x1b[2K${row}` : "").join("");
    const tail = !repaint && this.paintedRows !== null && rows.length < this.paintedRows.length
      ? `\x1b[${rows.length + 1};1H\x1b[J` : "";
    const nextCursor = cursor && !selectingText && cursor.row >= 0 && cursor.row < height && cursor.column >= 0 && cursor.column < width
      ? cursor : null;
    const cursorChanged = nextCursor?.row !== this.paintedCursor?.row || nextCursor?.column !== this.paintedCursor?.column;
    const mouse = selectingText !== this.paintedSelection
      ? selectingText ? "\x1b[?1000l\x1b[?1006l" : "\x1b[?1000h\x1b[?1006h" : "";
    if (!body && !tail && !cursorChanged && !mouse) return;
    const caret = nextCursor ? `\x1b[${nextCursor.row + 1};${nextCursor.column + 1}H\x1b[?25h` : "";
    // A stream write is accepted even when it returns false. Diff subsequent
    // frames against it, and hold only the newest frame until drain.
    const accepted = this.output.write(`\x1b[?2026h\x1b[?25l${mouse}${repaint ? "\x1b[2J" : ""}${body}${tail}${caret}\x1b[?2026l`);
    this.paintedRows = rows;
    this.paintedWidth = width;
    this.paintedHeight = height;
    this.paintedCursor = nextCursor;
    this.paintedSelection = selectingText;
    if (!accepted) {
      this.outputBlocked = true;
      this.output.on("drain", this.outputDrained);
    }
  }

  private resetPaint(): void {
    this.output.off("drain", this.outputDrained);
    this.outputBlocked = false;
    this.pendingFrame = null;
    this.paintedRows = null;
    this.paintedCursor = null;
    this.paintedWidth = 0;
    this.paintedHeight = 0;
  }

  private receiveInput(text: string): void {
    if (this.inputTimer) clearTimeout(this.inputTimer);
    this.inputTimer = null;
    const blockedAtStart = this.pendingInputBlocked || this.outputBlocked;
    this.pendingInput += text;
    const marker = this.paste ? "\x1b[201~" : "\x1b[200~";
    const found = this.pendingInput.indexOf(marker);
    if (found >= 0) {
      const before = this.pendingInput.slice(0, found);
      if (this.paste) {
        this.pasteText = (this.pasteText + before).slice(0, 131072);
        this.keyHandler?.(this.pasteText, { name: "paste" }); this.pasteText = "";
      } else {
        this.dispatchInput(before, blockedAtStart);
        // Bracketed paste starts a new input mode; stale mouse fragments cannot consume it.
        if (this.mouseTimer) clearTimeout(this.mouseTimer);
        this.mouseTimer = null;
        this.pendingMouse = "";
        this.pendingMouseBlocked = false;
        this.discardingMouse = false;
      }
      this.paste = !this.paste;
      this.pendingInput = this.pendingInput.slice(found + marker.length);
      this.pendingInputBlocked = false;
      this.receiveInput(""); return;
    }
    let trailing = 0;
    for (let i = 1; i < marker.length; i++) if (this.pendingInput.endsWith(marker.slice(0, i))) trailing = i;
    const ready = this.pendingInput.slice(0, this.pendingInput.length - trailing);
    this.pendingInput = trailing ? this.pendingInput.slice(-trailing) : "";
    this.pendingInputBlocked = Boolean(trailing) && blockedAtStart;
    if (this.paste) this.pasteText = (this.pasteText + ready).slice(0, 131072);
    else if (ready) this.dispatchInput(ready, blockedAtStart);
    if (trailing && !this.paste) this.inputTimer = setTimeout(() => {
      this.dispatchInput(this.pendingInput, this.pendingInputBlocked);
      this.pendingInput = ""; this.pendingInputBlocked = false; this.inputTimer = null;
    }, 30);
  }

  /** Keep SGR mouse bytes out of readline, including malformed and split reports. */
  private dispatchInput(text: string, blockedAtStart = false): void {
    if (this.mouseTimer) clearTimeout(this.mouseTimer);
    this.mouseTimer = null;
    const input = this.pendingMouse + text;
    this.pendingMouse = "";
    const blockedMouse = blockedAtStart || this.pendingMouseBlocked || this.outputBlocked;
    this.pendingMouseBlocked = false;
    let offset = 0;
    if (this.discardingMouse) {
      // eslint-disable-next-line no-control-regex -- Consume the escape that starts a new trusted terminal report.
      const end = input.search(/[mM\x1b]/);
      if (end < 0) return;
      this.discardingMouse = false;
      offset = input[end] === "\x1b" ? end : end + 1;
    }
    while (offset < input.length) {
      const start = input.indexOf("\x1b[<", offset);
      if (start < 0) {
        const rest = input.slice(offset);
        const prefix = rest.endsWith("\x1b[") ? "\x1b[" : rest.endsWith("\x1b") ? "\x1b" : "";
        this.keyInput.write(prefix ? rest.slice(0, -prefix.length) : rest);
        if (prefix) this.holdMousePrefix(prefix, blockedMouse);
        break;
      }
      this.keyInput.write(input.slice(offset, start));
      const nextEscape = input.indexOf("\x1b", start + 3);
      const endM = input.indexOf("M", start + 3);
      const endm = input.indexOf("m", start + 3);
      const end = endM < 0 ? endm : endm < 0 ? endM : Math.min(endM, endm);
      if (end < 0 || (nextEscape >= 0 && nextEscape < end)) {
        if (nextEscape >= 0) { offset = nextEscape; continue; }
        if (input.length - start < 128) this.holdMousePrefix(input.slice(start), blockedMouse);
        else this.discardingMouse = true;
        break;
      }
      const sequence = input.slice(start, end + 1);
      // eslint-disable-next-line no-control-regex -- Parse terminal SGR mouse protocol bytes.
      const report = /^\x1b\[<(\d+);(\d+);(\d+)([mM])$/.exec(sequence);
      if (report && !blockedMouse && !this.outputBlocked) {
        const button = Number(report[1]);
        const column = Number(report[2]);
        const row = Number(report[3]);
        if ([button, column, row].every(Number.isSafeInteger) && column > 0 && row > 0) {
          const mouse = {row: row - 1, column: column - 1};
          if (report[4] === "M" && button === 0 && !this.selectingText) {
            this.keyHandler?.("", {name: "mouseclick", sequence, mouse});
          } else if (report[4] === "M" && (button & 64) && ((button & 3) === 0 || (button & 3) === 1)) {
            this.keyHandler?.("", {name: (button & 3) === 0 ? "scrollup" : "scrolldown", sequence, mouse});
          }
        }
      }
      offset = end + 1;
    }
  }

  private holdMousePrefix(prefix: string, blocked: boolean): void {
    this.pendingMouse = prefix;
    this.pendingMouseBlocked = blocked;
    this.mouseTimer = setTimeout(() => {
      const pending = this.pendingMouse;
      this.pendingMouse = "";
      this.pendingMouseBlocked = false;
      this.mouseTimer = null;
      if (pending === "\x1b") this.keyHandler?.("\x1b", {name: "escape", sequence: pending});
      else if (pending === "\x1b[") this.keyInput.write(pending);
      else this.discardingMouse = true;
    }, 500);
  }

  private removeListeners(): void {
    if (this.keyHandler) {
      this.keyInput.off("keypress", this.keyHandler as never);
      this.keyHandler = null;
    }
    this.input.off("data", this.rawInput);
    this.output.off("resize", this.resized);
    if (this.inputTimer) clearTimeout(this.inputTimer);
    if (this.mouseTimer) clearTimeout(this.mouseTimer);
    this.mouseTimer = null;
    this.inputTimer = null; this.pendingInput = ""; this.pendingInputBlocked = false; this.pendingMouse = ""; this.pendingMouseBlocked = false; this.discardingMouse = false; this.paste = false; this.pasteText = "";
    if (this.resizeHandler) {
      this.output.off("resize", this.resizeHandler);
      this.resizeHandler = null;
    }
  }
}
