<!-- App adapter: the public presentation stays free of stores and networking. -->
<script lang="ts">
  import { getContext, type ComponentProps } from 'svelte';
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultPresentationContext } from '../../types/authoredResult';
  import ResultEmbedCardPresentation from '@repo/public-site/components/results/ResultEmbedCard.svelte';
  import { handleImageError } from '../../utils/offlineImageHandler';
  let { title, titleTestId, description, sourceLabel, faviconUrl, imageUrl, imageAlt, imageTestId, mediaFit, mediaOnly, textFirst, badge, facts, media, children }: Omit<ComponentProps<typeof ResultEmbedCardPresentation>, 'onImageError'> = $props();
  const authoring = getContext<AuthoredResultPresentationContext | undefined>(AUTHORED_RESULT_PRESENTATION_CONTEXT);
  const suppliedTitle = $derived(authoring?.authoring && typeof authoring.content.title === 'string'
    && authoring.content.title.trim() ? authoring.content.title : undefined);
  const displayTitle = $derived(suppliedTitle ?? title);
  const displaySource = $derived(suppliedTitle && title && title !== suppliedTitle
    ? [...new Set([title, sourceLabel].filter(Boolean))].join(' · ') : sourceLabel);
</script>

<ResultEmbedCardPresentation title={displayTitle} {titleTestId} {description} sourceLabel={displaySource} {faviconUrl} {imageUrl} {imageAlt} {imageTestId} {mediaFit} {mediaOnly} {textFirst} {badge} {facts} {media} {children} onImageError={handleImageError} />
