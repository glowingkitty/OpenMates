import preview, { eventContent, overlapContent, variants as previewVariants } from './CalendarEventEmbedPreview.preview';

export default { content: eventContent };
export const variants = {
  overlap: { content: overlapContent },
  large: { content: eventContent, large: true },
  largeOverlap: { content: overlapContent, large: true },
  mobile: { content: eventContent },
  minimal: { content: previewVariants.minimal.content },
  invalid: { content: previewVariants.invalid.content },
  processing: { content: previewVariants.processing.content },
  cancelled: { content: { ...preview.content, status: 'cancelled' } },
  longTitle: { content: previewVariants.longTitle.content },
};
