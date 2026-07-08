// frontend/packages/ui/src/components/tasks/__tests__/activeChatTaskPreview.test.ts
//
// Deterministic regression guard for the active chat task/plan preview UI. The
// Figma contract requires this bar to appear only when the chat has tasks or an
// active plan, never as a generic loading state during normal chat creation.

import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const componentSource = readFileSync(new URL('../ActiveChatTaskPreview.svelte', import.meta.url), 'utf8');

describe('ActiveChatTaskPreview UI contract', () => {
  it('does not expose a loading placeholder in the chat canvas', () => {
    expect(componentSource).not.toContain('active-chat-task-preview-loading');
    expect(componentSource).not.toContain('Loading tasks');
  });
});
