/*
 * OpenMates financial support copy for CLI surfaces.
 *
 * Purpose: keep voluntary support wording consistent across CLI commands.
 * Architecture: pure formatting helpers with no network or auth dependency.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Safety: avoids donation wording because OpenMates is a business project.
 * Tests: frontend/packages/openmates-cli/tests/cli.test.ts and server.test.ts
 */

export const SUPPORT_URL = "https://openmates.org/#settings/support";
export const SUPPORT_TITLE = "Support OpenMates development";
export const SUPPORT_MESSAGE = "Financial support is voluntary and helps keep OpenMates maintained.";

export function renderSupportInfo(): string {
  return `${SUPPORT_TITLE}:\n  ${SUPPORT_URL}\n\n${SUPPORT_MESSAGE}`;
}

export function renderSupportStartReminder(): string {
  return `Friendly reminder: you can financially support OpenMates development at ${SUPPORT_URL}`;
}
