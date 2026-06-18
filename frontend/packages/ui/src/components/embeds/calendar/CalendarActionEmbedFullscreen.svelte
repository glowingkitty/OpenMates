<!--
  frontend/packages/ui/src/components/embeds/calendar/CalendarActionEmbedFullscreen.svelte

  Generic fullscreen view for Calendar connected-account skill embeds.
  Uses UnifiedEmbedFullscreen and renders decoded Calendar action content safely.
  The richer approve/undo Calendar UI is tracked in the executable spec.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  let content = $derived(data.decodedContent || {});
  let skillId = $derived(typeof content.skill_id === 'string' ? content.skill_id : 'get-events');
  let title = $derived(
    typeof content.title === 'string' ? content.title : skillTitle(skillId)
  );
  let subtitle = $derived(
    typeof content.summary === 'string' ? content.summary : typeof content.message === 'string' ? content.message : ''
  );
  let error = $derived(typeof content.error === 'string' ? content.error : '');
  let events = $derived(Array.isArray(content.events) ? content.events : []);
  let results = $derived(Array.isArray(content.results) ? content.results : []);
  let items = $derived(events.length > 0 ? events : results);

  function skillTitle(value: string): string {
    const titles: Record<string, string> = {
      'get-events': 'Search',
      'create-event': 'Create calendar event',
      'update-event': 'Update calendar event',
      'delete-event': 'Delete calendar event'
    };
    return titles[value] || 'Calendar';
  }

  function itemTitle(item: unknown): string {
    if (!item || typeof item !== 'object') return String(item ?? 'Calendar item');
    const record = item as Record<string, unknown>;
    return String(record.summary || record.title || record.event_id || 'Calendar item');
  }

  function itemDetail(item: unknown): string {
    if (!item || typeof item !== 'object') return '';
    const record = item as Record<string, unknown>;
    return String(record.start || record.start_time || record.status || record.html_link || '');
  }
</script>

<UnifiedEmbedFullscreen
  appId="calendar"
  {skillId}
  skillIconName="search"
  embedHeaderTitle={title}
  embedHeaderSubtitle={subtitle}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="calendar-fullscreen">
      {#if error}
        <div class="calendar-error">{error}</div>
      {:else if items.length > 0}
        <div class="calendar-list">
          {#each items as item}
            <section class="calendar-card">
              <h3>{itemTitle(item)}</h3>
              {#if itemDetail(item)}
                <p>{itemDetail(item)}</p>
              {/if}
            </section>
          {/each}
        </div>
      {:else if subtitle}
        <p class="calendar-empty">{subtitle}</p>
      {:else}
        <p class="calendar-empty">{$text('common.loading')}</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .calendar-fullscreen {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    padding: var(--spacing-4);
    color: var(--color-font-primary);
  }

  .calendar-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .calendar-card {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-4);
    padding: var(--spacing-4);
    background: var(--color-grey-0);
  }

  .calendar-card h3 {
    margin: 0 0 var(--spacing-2);
    font: var(--font-p-bold);
  }

  .calendar-card p,
  .calendar-empty,
  .calendar-error {
    margin: 0;
    font: var(--font-p);
    color: var(--color-font-secondary);
  }

  .calendar-error {
    color: var(--color-error);
  }
</style>
