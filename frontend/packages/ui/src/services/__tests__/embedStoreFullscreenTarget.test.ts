// frontend/packages/ui/src/services/__tests__/embedStoreFullscreenTarget.test.ts
//
// Focused coverage for embed fullscreen target resolution in shared chat flows.
// Shared chat hydration stores encrypted Maps Search child embeds as app-skill-use
// rows, with app_id and skill_id metadata extracted separately. Inline embed
// links must use that metadata to open registered child fullscreens directly.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EmbedStore } from '../embedStore';

describe('EmbedStore.resolveFullscreenTarget', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  // contract-test: direct surface=gui.web assertions=public-example-chats.surface.semantic-parity
  it('keeps shared Maps Search place children as direct fullscreen targets', async () => {
    const store = new EmbedStore();

    vi.spyOn(store, 'getRawEntry').mockResolvedValue({
      type: 'app-skill-use',
      embed_id: 'maps-place-child',
      status: 'finished',
      app_id: 'maps',
      skill_id: 'search',
      parent_embed_id: 'maps-search-parent',
    });

    await expect(store.resolveFullscreenTarget('maps-place-child')).resolves.toEqual({
      targetEmbedId: 'maps-place-child',
    });
  });
});
