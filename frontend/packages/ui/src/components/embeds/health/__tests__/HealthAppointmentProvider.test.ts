import { readFileSync } from 'node:fs';
import { decode } from '@toon-format/toon';
import { parse } from 'yaml';
import { mount, tick, unmount } from 'svelte';
import { describe, expect, it, vi } from 'vitest';
import { berlinEnglishSpeakingGpAppointmentsChat } from '../../../../demo_chats/data/example_chats/berlin-english-speaking-gp-appointments';

vi.mock('../../UnifiedEmbedPreview.svelte', async () => ({
  default: (await import('./HealthAppointmentShell.svelte')).default,
}));
vi.mock('@repo/ui', async () => {
  const { readable } = await import('svelte/store');
  const translations = parse(readFileSync(new URL('../../../../i18n/sources/embeds.yml', import.meta.url), 'utf8'));
  return { text: readable((key: string) => translations[key.replace(/^embeds\./, '')]?.en ?? key) };
});

import { embedPreviewRegistry } from '../../../../services/embedPreviewRegistry';

describe('saved appointment provider rendering', () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it('renders unknown insurance with the real Berlin doctor provider rather than a fixed Jameda label', async () => {
    const child = berlinEnglishSpeakingGpAppointmentsChat.embeds!.find(
      (embed) => embed.embed_id === '3be646e8-8f97-48f2-afae-df58f6f8ca61',
    )!;
    const decodedContent = decode(child.content) as Record<string, unknown>;
    expect(decodedContent).toMatchObject({ name: 'Hermann Fondis', insurance: 'unknown', provider_platform: 'Doctolib' });
    const resolved = await embedPreviewRegistry.resolve({
      embedId: child.embed_id,
      embedData: { type: child.type, status: 'finished' },
      decodedContent,
      onFullscreen: () => {},
    });
    expect(resolved).not.toBeNull();
    expect(resolved!.props.providerPlatform).toBe('Doctolib');
    const target = document.createElement('div');
    document.body.append(target);
    const component = mount(resolved!.component, { target, props: resolved!.props });
    try {
      await tick();
      const badge = target.querySelector('.insurance-unknown-badge');
      expect(badge?.textContent?.trim()).toBe('Insurance: verify on Doctolib');
      expect(badge?.getAttribute('title')).toContain('verify on Doctolib');
      expect(target.textContent).not.toContain('Jameda');
    } finally {
      await unmount(component);
      target.remove();
    }
  });
});
