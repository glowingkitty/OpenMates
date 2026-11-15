/**
 * frontend/packages/ui/src/components/embeds/slides/slidesTemplateLayouts.ts
 *
 * Shared by the slide template embed components: the i18n key of a layout name.
 */

const LAYOUT_LABEL_KEYS: Record<string, string> = {
  title: 'embeds.slides_layout_title',
  section: 'embeds.slides_layout_section',
  content: 'embeds.slides_layout_content',
  'title-and-content': 'embeds.slides_layout_content',
  'two-column': 'embeds.slides_layout_two_column',
  image: 'embeds.slides_layout_image',
  quote: 'embeds.slides_layout_quote',
  closing: 'embeds.slides_layout_closing'
};

/** Translation key of a layout's display name, or null for a layout without one. */
export function layoutLabelKey(layout: string | undefined): string | null {
  return LAYOUT_LABEL_KEYS[layout ?? ''] ?? null;
}

/** Stable name used in `data-testid="slides-template-layout-<name>"` (`title-and-content` is `content`). */
export function layoutTestName(layout: string | undefined): string {
  return layout === 'title-and-content' ? 'content' : (layout ?? 'content');
}
