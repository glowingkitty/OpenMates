<!-- figma-visual-proof: not-required. Reuses the shared result shell and Design artboard. -->
<script lang="ts">
  import { text } from '../../../i18n/translations';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import DesignPageThumbnail from './editor/DesignPageThumbnail.svelte';
  import type { DesignDocument } from './editor/designDocument';

  interface Props {
    id: string;
    design: DesignDocument | null;
    status: 'finished' | 'processing' | 'error';
    onFullscreen: () => void;
  }
  let { id, design, status, onFullscreen }: Props = $props();
  const title = $derived(design?.title ?? $text('apps.design'));
</script>

<UnifiedEmbedPreview {id} appId="design" skillId="document" skillIconName="design" skillName={title}
  {status} {onFullscreen} onStop={() => {}} showSkillIcon={false} resultPreview>
  {#snippet details()}
    {#if design}
      <ResultEmbedCard {title}>
        {#snippet media()}
          <div class="thumbnail" data-testid="design-embed-thumbnail">
            <DesignPageThumbnail page={design.pages[0]} card />
          </div>
        {/snippet}
      </ResultEmbedCard>
    {:else}
      <ResultEmbedCard {title} description={$text('common.detail_load_error', { values: { item: title } })} />
    {/if}
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .thumbnail { box-sizing: border-box; height: 100%; padding: var(--spacing-2) 48px; }
</style>
