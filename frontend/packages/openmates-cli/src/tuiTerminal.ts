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

  enter(): void {
    if (this.active) return;
    this.active = true;
    this.rawWasEnabled = Boolean((this.input as ReadStream).isRaw);
    emitKeypressEvents(this.input);
    if (typeof (this.input as ReadStream).setRawMode === "function") {
      (this.input as ReadStream).setRawMode(true);
    }
    this.input.resume();
    this.output.write("\x1b[?1049h");
    this.output.write("\x1b[?25l");
    this.output.write("\x1b[2J\x1b[H");
  }

  leave(): void {
    if (!this.active) return;
    this.removeListeners();
    this.output.write("\x1b[?25h");
    this.output.write("\x1b[?1000l\x1b[?1006l");
    this.output.write("\x1b[?1049l");
    if (typeof (this.input as ReadStream).setRawMode === "function") {
      (this.input as ReadStream).setRawMode(this.rawWasEnabled);
    }
    this.active = false;
  }

  async suspend<T>(run: () => Promise<T>): Promise<T> {
    this.output.write("\x1b[?25h");
    this.output.write("\x1b[?1000l\x1b[?1006l");
    this.output.write("\x1b[?1049l");
    if (typeof (this.input as ReadStream).setRawMode === "function") {
      (this.input as ReadStream).setRawMode(this.rawWasEnabled);
    }
    try {
      return await run();
    } finally {
      if (typeof (this.input as ReadStream).setRawMode === "function") {
        (this.input as ReadStream).setRawMode(true);
      }
      this.input.resume();
      this.output.write("\x1b[?1049h");
      this.output.write("\x1b[?25l");
      this.output.write("\x1b[2J\x1b[H");
    }
  }

  onKey(handler: TerminalKeyHandler): void {
    if (this.keyHandler) this.input.off("keypress", this.keyHandler as never);
    this.keyHandler = handler;
    this.input.on("keypress", handler as never);
  }

  onResize(handler: TerminalResizeHandler): void {
    if (this.resizeHandler) this.output.off("resize", this.resizeHandler);
    this.resizeHandler = handler;
    this.output.on("resize", handler);
  }

  render(frame: string): void {
    this.output.write("\x1b[H");
    this.output.write(frame);
  }

  private removeListeners(): void {
    if (this.keyHandler) {
      this.input.off("keypress", this.keyHandler as never);
      this.keyHandler = null;
    }
    if (this.resizeHandler) {
      this.output.off("resize", this.resizeHandler);
      this.resizeHandler = null;
    }
  }
}
