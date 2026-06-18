<!--
  frontend/packages/ui/src/components/embeds/calendar/CalendarActionEmbedPreview.svelte

  Generic preview card for Calendar connected-account skill embeds.
  Uses UnifiedEmbedPreview while the full Calendar permission UI is being built.
  Keeps registry entries renderable for get/create/update/delete Calendar actions.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  type EmbedStatus = 'processing' | 'finished' | 'error' | 'cancelled';

  interface Props {
    id: string;
    skillId?: string;
    status?: EmbedStatus;
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
    title?: string;
    summary?: string;
    message?: string;
    error?: string;
    events?: unknown[];
    results?: unknown[];
  }

  let {
    id,
    skillId: skillIdProp = 'get-events',
    status: statusProp = 'processing',
    taskId,
    isMobile = false,
    onFullscreen,
    title: titleProp,
    summary: summaryProp,
    message: messageProp,
    error: errorProp,
    events: eventsProp,
    results: resultsProp
  }: Props = $props();

  let localSkillId = $state('get-events');
  let localStatus = $state<EmbedStatus>('processing');
  let localTitle = $state('Calendar');
  let localSummary = $state('');
  let localError = $state('');
  let localCount = $state(0);

  $effect(() => {
    localSkillId = skillIdProp;
    localStatus = statusProp;
    localTitle = titleProp || skillTitle(skillIdProp);
    localSummary = summaryProp || messageProp || '';
    localError = errorProp || '';
    localCount = (eventsProp || resultsProp || []).length;
  });

  let skillName = $derived(skillTitle(localSkillId));
  let displayTitle = $derived(localTitle || skillName);
  let displaySummary = $derived.by(() => {
    if (localStatus === 'error') return localError || $text('chat.an_error_occured');
    if (localSummary) return localSummary;
    if (localCount > 0) return `${localCount} calendar item${localCount === 1 ? '' : 's'}`;
    return localStatus === 'processing' ? $text('common.loading') : '';
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const content = data.decodedContent || {};
    if (typeof content.skill_id === 'string') localSkillId = content.skill_id;
    if (typeof content.title === 'string') localTitle = content.title;
    if (typeof content.summary === 'string') localSummary = content.summary;
    if (typeof content.message === 'string') localSummary = content.message;
    if (typeof content.error === 'string') localError = content.error;
    if (Array.isArray(content.events)) localCount = content.events.length;
    if (Array.isArray(content.results)) localCount = content.results.length;
  }

  function skillTitle(skillId: string): string {
    const titles: Record<string, string> = {
      'get-events': 'Search',
      'create-event': 'Create calendar event',
      'update-event': 'Update calendar event',
      'delete-event': 'Delete calendar event'
    };
    return titles[skillId] || 'Calendar';
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="calendar"
  skillId={localSkillId}
  skillIconName="search"
  status={localStatus}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="calendar-preview" class:mobile={isMobileLayout}>
      <div class="calendar-title">{displayTitle}</div>
      {#if displaySummary}
        <div class="calendar-summary">{displaySummary}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .calendar-preview {
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-3);
    height: 100%;
    color: var(--color-font-primary);
  }

  .calendar-title {
    font: var(--font-p-bold);
  }

  .calendar-summary {
    display: -webkit-box;
    overflow: hidden;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    font: var(--font-small);
    color: var(--color-font-secondary);
  }

  .calendar-preview.mobile .calendar-summary {
    -webkit-line-clamp: 5;
  }
</style>
