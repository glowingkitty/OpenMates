<!--
  StartScreenRowActions.svelte — the last item of a start-screen row (TASK-1321).

  Chats, Apps and Workflows end their horizontal card row with the browse actions
  (Chats: Show all, Search; Apps: Show all apps, Search; Workflows: Show templates;
  guests: Select interests, Show all). The user reaches them after scrolling past
  the cards; nothing about browsing sits below the row any more. The tile has the
  card height so the row keeps one baseline.

  Spec: specifications/features/daily-inspiration (daily-inspiration.start-row-actions)
-->
<script lang="ts">
  import { getLucideIcon } from '../../utils/categoryUtils';

  export type StartScreenRowAction = {
    id: string;
    label: string;
    /** Lucide icon name, e.g. "messages-square", "search", "heart". */
    icon: string;
    testId: string;
    /** Optional data-surface attribute kept for selectors that already use it. */
    surface?: string;
    onActivate: () => void;
  };

  type Props = {
    actions: StartScreenRowAction[];
    testId: string;
  };

  let { actions, testId }: Props = $props();
</script>

<div class="start-row-actions" data-testid={testId} role="group">
  {#each actions as action (action.id)}
    {@const ActionIcon = getLucideIcon(action.icon)}
    <button
      type="button"
      class="start-row-action"
      data-testid={action.testId}
      data-surface={action.surface}
      onclick={action.onActivate}
    >
      <span class="start-row-action-icon" aria-hidden="true"><ActionIcon size={18} color="currentColor" /></span>
      <span class="start-row-action-label">{action.label}</span>
    </button>
  {/each}
</div>

<style>
  .start-row-actions {
    display: flex;
    flex: 0 0 auto;
    flex-direction: column;
    align-items: stretch;
    justify-content: center;
    gap: var(--spacing-4);
    /* Fits its longest label (e.g. "Show all examples") instead of cutting it. */
    width: max-content;
    min-width: 190px;
    max-width: 260px;
    height: 200px;
    box-sizing: border-box;
    pointer-events: auto;
  }

  .start-row-action {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    width: 100%;
    min-height: 48px;
    margin: 0;
    padding: var(--spacing-3) var(--spacing-6);
    border: none;
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
    color: var(--color-grey-80);
    font: inherit;
    font-size: var(--font-size-p);
    font-weight: 600;
    text-align: left;
    cursor: pointer;
    filter: none;
    scale: 1;
    transition: background var(--duration-fast) var(--easing-default);
  }

  .start-row-action:hover,
  .start-row-action:focus-visible {
    background: var(--color-grey-25);
    filter: none;
    scale: 1;
  }

  .start-row-action-icon {
    display: inline-flex;
    flex: 0 0 auto;
    color: var(--color-primary-start, var(--color-grey-70));
  }

  .start-row-action-label {
    min-width: 0;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  @media (max-width: 480px) {
    .start-row-actions {
      min-width: min(180px, 46vw);
      max-width: min(230px, 58vw);
    }
  }
</style>
