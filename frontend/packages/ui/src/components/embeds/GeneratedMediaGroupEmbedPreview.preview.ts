/** A completed generation invocation remains visible as a parent card. */
// Registers the same static child embeds the fullscreen fixture resolves, so the
// parent card loads real thumbnails and the prompt like it does in a chat.
import './GeneratedMediaGroupEmbedFullscreen.preview';

const defaultProps = {
  id: '0e29d61f-c88d-489c-b4a0-d471d37ea365',
  appId: 'images', skillId: 'generate', status: 'finished' as const,
  resultCount: 2,
  prompt: 'A golden retriever puppy wearing a tiny yellow raincoat, jumping over a puddle in a sunlit Berlin street, soft film grain, shallow depth of field',
  childEmbedIds: ['9c02483d-faba-4467-85ef-26167a7ad64e', '462d4ad2-2712-4f6f-b779-b10348d7f94d'],
  onFullscreen: () => {},
};
export default defaultProps;
export const variants = {
  videoProgress: {
    ...defaultProps, appId: 'videos', status: 'processing' as const, resultCount: 0, childEmbedIds: [],
    prompt: 'A 20 second recap of this week\'s news', progressStage: 'rendering',
  },
};
