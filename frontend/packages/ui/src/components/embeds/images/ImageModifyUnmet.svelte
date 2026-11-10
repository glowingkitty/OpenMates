<!--
  frontend/packages/ui/src/components/embeds/images/ImageModifyUnmet.svelte

  Plain list of the wishes an edited picture could not fully meet, shown in the
  opened view when the review ended with review_status "unmet_delivered".
-->
<script lang="ts">
  import { text } from '@repo/ui';

  interface Props {
    requirements: string[];
  }

  let { requirements }: Props = $props();
</script>

{#if requirements.length > 0}
  <section class="modify-unmet" data-testid="image-modify-unmet">
    <h3 class="unmet-title">{$text('embeds.image_modify.unmet_title')}</h3>
    <ul class="unmet-list">
      {#each requirements as requirement}
        <li>{requirement}</li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  .modify-unmet {
    width: 100%;
    box-sizing: border-box;
    padding: var(--spacing-6);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
  }

  .unmet-title {
    margin: 0 0 var(--spacing-3);
    font-size: var(--font-size-sm);
    font-weight: 600;
  }

  .unmet-list {
    margin: 0;
    padding-left: var(--spacing-8);
    font-size: var(--font-size-sm);
    line-height: 1.4;
    overflow-wrap: anywhere;
  }
</style>
