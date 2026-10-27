<!-- App adapter: the public presentation stays free of stores and networking. -->
<script lang="ts">
  import type { ComponentProps } from 'svelte';
  import ResultEmbedCardPresentation from '@repo/public-site/components/results/ResultEmbedCard.svelte';
  import { handleImageError } from '../../utils/offlineImageHandler';
  let { title, titleTestId, description, sourceLabel, faviconUrl, imageUrl, imageAlt, imageTestId, mediaFit, mediaOnly, textFirst, badge, facts, media, children }: Omit<ComponentProps<typeof ResultEmbedCardPresentation>, 'onImageError'> = $props();
</script>

<ResultEmbedCardPresentation {title} {titleTestId} {description} {sourceLabel} {faviconUrl} {imageUrl} {imageAlt} {imageTestId} {mediaFit} {mediaOnly} {textFirst} {badge} {facts} {media} {children} onImageError={handleImageError} />
