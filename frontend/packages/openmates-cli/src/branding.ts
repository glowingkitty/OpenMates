/*
 * OpenMates CLI terminal branding.
 *
 * Purpose: keep the text logo consistent across the TUI and command output.
 * Architecture: pure string helpers only; no terminal writes or color concerns.
 * Security: contains no user data and performs no IO.
 * Tests: frontend/packages/openmates-cli/tests/tui.test.ts, cli.test.ts
 */

export const OPENMATES_WORDMARK = "OPENMATES";

const OPENMATES_ASCII_LARGE = [
  " ██████  ██████  ███████ ███    ██ ███    ███  █████  ████████ ███████ ███████",
  "██    ██ ██   ██ ██      ████   ██ ████  ████ ██   ██    ██    ██      ██     ",
  "██    ██ ██████  █████   ██ ██  ██ ██ ████ ██ ███████    ██    █████   ███████",
  "██    ██ ██      ██      ██  ██ ██ ██  ██  ██ ██   ██    ██    ██           ██",
  " ██████  ██      ███████ ██   ████ ██      ██ ██   ██    ██    ███████ ███████",
];

export function openMatesAsciiLogo(width = 100): string[] {
  return width >= 86 ? [...OPENMATES_ASCII_LARGE, OPENMATES_WORDMARK] : [OPENMATES_WORDMARK];
}

export function renderOpenMatesAsciiLogo(width = 100): string {
  return openMatesAsciiLogo(width).join("\n");
}
