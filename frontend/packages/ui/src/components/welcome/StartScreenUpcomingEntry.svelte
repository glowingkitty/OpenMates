<!--
  StartScreenUpcomingEntry.svelte — compact text entry for an upcoming event or
  appointment below the start-screen row (TASK-1321).

  Events are not chats, so they no longer appear as cards in the Chats row. When a
  saved event or appointment starts soon, this single line (coloured circle with the
  item's icon, title and time) sits below the row; tapping it opens the saved item.

  Spec: specifications/features/continue-carousel (continue-carousel.upcoming-entry)
-->
<script lang="ts">
  import { getAppGradientBackground } from '../activeChatUtils';
  import { getLucideIcon, getValidIconName } from '../../utils/categoryUtils';

  type Props = {
    title: string;
    timeLabel: string;
    appId: string;
    icon?: string | null;
    category?: string | null;
    variant?: 'text' | 'pill';
    onActivate: () => void;
  };

  let { title, timeLabel, appId, icon = null, category = null, variant = 'text', onActivate }: Props = $props();

  let IconComponent = $derived(getLucideIcon(getValidIconName(icon || 'calendar', category || 'general_knowledge')));
  const ChevronRight = getLucideIcon('chevron-right');
</script>

<button
  type="button"
  class="start-upcoming-entry"
  class:pill={variant === 'pill'}
  data-testid="start-screen-upcoming-entry"
  data-app-id={appId}
  onclick={onActivate}
>
  <span class="start-upcoming-circle" style:background={getAppGradientBackground(appId)} aria-hidden="true">
    <IconComponent size={15} color="white" />
  </span>
  <span class="start-upcoming-text">
    <span class="start-upcoming-title" data-testid="start-screen-upcoming-title">{title}</span>
    <span class="start-upcoming-time" data-testid="start-screen-upcoming-time">{timeLabel}</span>
  </span>
  {#if variant === 'pill'}
    <span class="start-upcoming-chevron" aria-hidden="true"><ChevronRight size={16} color="currentColor" /></span>
  {/if}
</button>

<style>
  .start-upcoming-entry {
    display: inline-flex;
    align-items: center;
    gap: var(--spacing-5);
    max-width: min(100%, 520px);
    min-height: 40px;
    margin: 0;
    padding: var(--spacing-2) var(--spacing-4);
    border: none;
    border-radius: var(--radius-full);
    background: transparent;
    color: var(--color-font-primary);
    font: inherit;
    font-size: var(--font-size-p);
    cursor: pointer;
    pointer-events: auto;
    filter: none;
    scale: 1;
  }

  .start-upcoming-entry:hover,
  .start-upcoming-entry:active {
    background: var(--color-grey-25);
    filter: none;
    scale: 1;
  }

  .start-upcoming-entry.pill {
    padding: var(--spacing-3) var(--spacing-8) var(--spacing-3) var(--spacing-3);
    background: var(--color-grey-0);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  }

  .start-upcoming-entry.pill:hover {
    background: var(--color-grey-10);
  }

  .start-upcoming-entry:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }

  .start-upcoming-circle {
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: 50%;
  }

  .start-upcoming-text {
    display: inline-flex;
    align-items: baseline;
    gap: var(--spacing-5);
    min-width: 0;
  }

  /* Phones: the time moves under the title so the title keeps its width. */
  @media (max-width: 480px) {
    .start-upcoming-text {
      flex-direction: column;
      align-items: flex-start;
      gap: 0;
    }

    .start-upcoming-time {
      font-size: var(--font-size-small);
    }
  }

  .start-upcoming-title {
    max-width: 100%;
    min-width: 0;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-weight: 500;
  }

  .start-upcoming-time {
    flex-shrink: 0;
    white-space: nowrap;
    color: var(--color-font-tertiary);
  }

  .start-upcoming-chevron {
    display: inline-flex;
    color: var(--color-font-secondary);
  }
</style>
