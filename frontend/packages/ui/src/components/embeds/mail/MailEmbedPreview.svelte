<!--
  Purpose: Preview card for direct-type mail embeds parsed from ```email fences.
  Architecture: Uses the unified embed preview contract (docs/architecture/embeds.md).
  Tests: N/A
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import { embedPIIStore } from '../../../stores/embedPIIStore';

  interface Props {
    id: string;
    receiver?: string;
    subject?: string;
    content?: string;
    footer?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen?: () => void;
  }

  let {
    id,
    receiver: receiverProp,
    subject: subjectProp,
    content: contentProp,
    status: statusProp,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let localReceiver = $state('');
  let localSubject = $state('');
  let localContent = $state('');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');

  $effect(() => {
    localReceiver = receiverProp || '';
    localSubject = subjectProp || '';
    localContent = contentProp || '';
    localStatus = statusProp || 'processing';
  });

  let embedPIIState = $state({ mappings: [] as import('../../../types/chat').PIIMapping[], revealed: false });
  $effect(() => {
    const unsub = embedPIIStore.subscribe((state) => {
      embedPIIState = state;
    });
    return unsub;
  });

  function applyPIIMode(value: string): string {
    if (!value || embedPIIState.mappings.length === 0) return value;
    if (embedPIIState.revealed) return restorePIIInText(value, embedPIIState.mappings);
    return replacePIIOriginalsWithPlaceholders(value, embedPIIState.mappings);
  }

  let receiver = $derived(applyPIIMode(localReceiver));
  let subject = $derived(applyPIIMode(localSubject));
  let content = $derived(applyPIIMode(localContent));
  let status = $derived(localStatus);

  let skillName = $derived(subject || $text('embeds.mail.email'));
  let statusText = $derived(receiver ? `${$text('embeds.mail.to')} ${receiver}` : '');

  /** Build a multi-line body preview from the content, trimming empty lines.
   *  If the full content exceeds the visible lines we append '...' */
  let bodyPreview = $derived.by(() => {
    const lines = content
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0) return '';
    return lines.join('\n');
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (!data.decodedContent) {
      if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
        localStatus = data.status;
      }
      return;
    }

    const c = data.decodedContent;
    if (typeof c.receiver === 'string') localReceiver = c.receiver;
    if (typeof c.subject === 'string') localSubject = c.subject;
    if (typeof c.content === 'string') localContent = c.content;

    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="mail"
  skillId="email"
  skillIconName="mail"
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showSkillIcon={true}
  showStatus={true}
  customStatusText={statusText}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details(snippetProps)}
    <div class="mail-details" class:mobile={snippetProps.isMobile}>
      <div class="mail-body-preview">{bodyPreview || $text('embeds.mail.empty_content')}</div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .mail-details {
    display: flex;
    flex-direction: column;
    gap: 4px;
    justify-content: center;
    height: 100%;
    color: var(--color-grey-100);
  }

  .mail-body-preview {
    font-size: 13px;
    line-height: 1.4;
    color: var(--color-font-secondary);
    display: -webkit-box;
    -webkit-line-clamp: 5;
    line-clamp: 5;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .mail-details.mobile .mail-body-preview {
    font-size: 11px;
    -webkit-line-clamp: 6;
    line-clamp: 6;
  }
</style>
