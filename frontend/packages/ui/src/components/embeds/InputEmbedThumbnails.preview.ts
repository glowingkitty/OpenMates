/** Shared input strip, using a registered image so no account or provider is needed. */
import { embedStore } from '../../services/embedStore';
export const sourceId = 'call-source-preview-image';
embedStore.registerStaticEmbed({ embedId: sourceId, type: 'images-image', appId: 'images', skillId: 'upload',
  content: JSON.stringify({ type: 'image', filename: 'source-frame.jpg',
    previewImageUrl: '/images/examples/group1.jpg' }) });
export default { inputEmbedIds: [sourceId] };
export const variants = { empty: { inputEmbedIds: [] }, loading: { inputEmbedIds: ['missing-source-preview'] } };
