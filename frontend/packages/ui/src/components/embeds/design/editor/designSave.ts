// figma-visual-proof: not-required. This module connects the editor to the shared revision client.
import { adoptSavedHead } from '../../../../services/rustCore/embeds/embedContentEdit';
import { commitContentRevision } from '../../../../services/rustCore/embeds/embedEditSession';
import type { EmbedEditScope } from '../../../../services/rustCore/embeds/embedEditProtocol';
import { getWorkspaceCacheEpoch } from '../../../../services/workspaceCacheLifecycle';
import type { DesignDocument } from './designDocument';
import { serializeDesign, validateDesignScene } from './designView';

/** Persist the design's canonical JSON through the existing client-side encrypted revision operation. */
export async function saveDesignRevision(embedId: string, scope: EmbedEditScope, baseVersion: number,
  design: DesignDocument): Promise<number> {
  const epoch = getWorkspaceCacheEpoch();
  const content = serializeDesign(design);
  if (!await validateDesignScene(content) || getWorkspaceCacheEpoch() !== epoch) {
    throw Object.assign(new Error('Design validation failed.'), { code: 'design_scene_invalid' });
  }
  const saved = await commitContentRevision(embedId, scope, baseVersion, content);
  if (getWorkspaceCacheEpoch() === epoch) await adoptSavedHead(embedId, scope, content, saved);
  return saved.version;
}
