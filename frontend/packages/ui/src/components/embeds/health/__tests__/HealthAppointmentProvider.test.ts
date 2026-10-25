import { readFileSync } from 'node:fs';
import { parse } from 'yaml';
import { mount, tick, unmount, type Component } from 'svelte';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../../services/chatSyncService', () => ({ chatSyncService: {} }));

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
  it('renders unknown insurance with the stored provider rather than a fixed provider label', async () => {
    const child = { embed_id: 'local-saved-appointment', type: 'health-appointment' };
    const decodedContent = {
      app_id: 'health', skill_id: 'appointment', name: 'Dr. Fixture',
      insurance: 'unknown', provider_platform: 'Stored clinic',
      slot_datetime: '2026-11-04T10:00:00Z', booking_url: 'https://example.com/appointment',
    };
    const resolved = await embedPreviewRegistry.resolve({
      embedId: child.embed_id,
      embedData: { type: child.type, status: 'finished' },
      decodedContent,
      onFullscreen: () => {},
    });
    expect(resolved).not.toBeNull();
    expect(resolved!.props.providerPlatform).toBe('Stored clinic');
    const target = document.createElement('div');
    document.body.append(target);
    const component = mount(resolved!.component as Component, { target, props: resolved!.props });
    try {
      await tick();
      const badge = target.querySelector('.insurance-unknown-badge');
      expect(badge?.textContent?.trim()).toBe('Insurance: verify on Stored clinic');
      expect(badge?.getAttribute('title')).toContain('verify on Stored clinic');
      expect(target.textContent).not.toContain('ExampleClinicB');
    } finally {
      await unmount(component);
      target.remove();
    }
  });
});

// contract-test: direct surface=gui.web assertions=app-skills.history.renderable
it('search history displays its supplied provider and leaves missing attribution empty', async () => {
  const { default: SearchPreview } = await import('../HealthSearchEmbedPreview.svelte');
  for (const provider of ['Stored clinic', undefined]) {
    const target = document.createElement('div');
    document.body.append(target);
    const component = mount(SearchPreview, { target, props: {
      id: 'saved-search', query: 'Saved appointments', provider,
      status: 'finished', results: [], onFullscreen: () => {},
    } });
    try {
      await tick();
      const attribution = target.querySelector('.ds-search-provider');
      if (provider) expect(attribution?.textContent).toContain(provider);
      else expect(attribution).toBeNull();
    } finally {
      await unmount(component);
      target.remove();
    }
  }
});
