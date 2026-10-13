/** Static parent + registered child fixture for generated-media drilldown. */
import { embedStore } from '../../services/embedStore';

const firstId = '9c02483d-faba-4467-85ef-26167a7ad64e';
const secondId = '462d4ad2-2712-4f6f-b779-b10348d7f94d';
const imageUrl = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="160" height="120"%3E%3Crect width="160" height="120" fill="%23325f9e"/%3E%3C/svg%3E';

for (const [embedId, prompt] of [
  [firstId, 'A stone lighthouse at dawn with sea mist and three gulls'],
  [secondId, 'A copper observatory in a mountain valley at blue hour'],
]) {
  embedStore.registerStaticEmbed({
    embedId,
    type: 'generated_image',
    appId: 'images', skillId: 'generate',
    content: JSON.stringify({
      type: 'generated_image', app_id: 'images', skill_id: 'generate',
      status: 'finished', prompt, model: 'google/gemini-3-pro-image-preview',
      previewImageUrl: imageUrl, embed_ref: `generated-images-${embedId.slice(0, 12)}`,
    }),
  });
}

export default {
  embedId: '0e29d61f-c88d-489c-b4a0-d471d37ea365',
  data: {
    decodedContent: {
      app_id: 'images', skill_id: 'generate', status: 'finished',
      result_count: 2, embed_ids: [firstId, secondId],
      embed_ref: 'generated-media-images-0e29d61fc88d',
    },
    embedData: { status: 'finished', type: 'app_skill_use', embed_ids: [firstId, secondId] },
  },
  onClose: () => {},
};
