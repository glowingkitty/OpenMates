import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ replaceState: vi.fn() }));
import { parseDeepLink, processDeepLink } from '../deepLinkHandler';

describe('landing composer deep link', () => {
  // contract-test: supporting surface=gui.web assertions=marketing-landing.composer-focus
  it('requests focus without a draft replacement, chat navigation, or send payload', async () => {
    expect(parseDeepLink('#compose')).toEqual({ type: 'compose', data: {} });
    expect(parseDeepLink('#/compose')).toEqual({ type: 'compose', data: {} });
    const onCompose = vi.fn();
    const onMessage = vi.fn();
    const onChat = vi.fn();
    await expect(processDeepLink('#compose', { onCompose, onMessage, onChat })).resolves.toMatchObject({
      type: 'compose', processed: true
    });
    expect(onCompose).toHaveBeenCalledOnce();
    expect(onMessage).not.toHaveBeenCalled();
    expect(onChat).not.toHaveBeenCalled();
  });
});
