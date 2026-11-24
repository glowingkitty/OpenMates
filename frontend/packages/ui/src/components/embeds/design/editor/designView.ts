/** Projects a core-validated Design scene to the Phase 0 renderer's local model. */
import { whenSharedRustCore } from '../../../../services/rustCore/host/sharedCoreRegistry';
import { rustEmbedData } from '../../../../services/rustCore/embeds/embedDataClient';
import { getWorkspaceCacheEpoch } from '../../../../services/workspaceCacheLifecycle';
import type { DesignDocument, DesignLayer } from './designDocument';

type SavedDesignLayer = Exclude<DesignLayer, { kind: 'image' }>
  | (Omit<Extract<DesignLayer, { kind: 'image' }>, 'src'> & { assetId: string });

type SavedDesign = Omit<DesignDocument, 'pages'> & {
  pages: (Omit<DesignDocument['pages'][number], 'layers'> & { layers: SavedDesignLayer[] })[];
};

export async function readDesignView(content: Record<string, unknown>, raw?: unknown): Promise<DesignDocument | null> {
  if (import.meta.env.VITE_OPENMATES_RUST_CORE !== '1') return null;
  const epoch = getWorkspaceCacheEpoch();
  await whenSharedRustCore({ timeoutMs: 10_000 });
  const core = rustEmbedData();
  if (!core) return null;
  // Use the original decrypted text if the shell supplies it. Some presentation
  // hosts already decode embed content and supply the scene object directly.
  const input = typeof raw === 'string' ? raw : JSON.stringify(content);
  if (!await core.validateDesignScene(input) || getWorkspaceCacheEpoch() !== epoch) return null;
  const scene: SavedDesign = JSON.parse(input);
  return {
    title: scene.title,
    pages: scene.pages.map((page) => ({
      ...page,
      layers: page.layers.map((layer) => layer.kind === 'image'
        ? { ...layer, src: '', assetId: layer.assetId }
        : layer)
    }))
  };
}
