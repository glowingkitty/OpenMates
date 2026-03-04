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
    footer: footerProp,
    status: statusProp,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let localReceiver = $state('');
  let localSubject = $state('');
  let localContent = $state('');
  let localFooter = $state('');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');

  $effect(() => {
    localReceiver = receiverProp || '';
    localSubject = subjectProp || '';
    localContent = contentProp || '';
    localFooter = footerProp || '';
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
  let footer = $derived(applyPIIMode(localFooter));
  let status = $derived(localStatus);

  let skillName = $derived(subject || $text('embeds.mail.email'));
  let statusText = $derived(receiver ? `${$text('embeds.mail.to')} ${receiver}` : '');
  let previewLine = $derived(content.split('\n').map((line) => line.trim()).find((line) => line.length > 0) || '');

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
    if (typeof c.footer === 'string') localFooter = c.footer;

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
  showSkillIcon={false}
  showStatus={true}
  customStatusText={statusText}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details(snippetProps)}
    <div class="mail-details" class:mobile={snippetProps.isMobile}>
      <div class="mail-subject">{subject || $text('embeds.mail.email')}</div>
      <div class="mail-receiver">{$text('embeds.mail.to')}: {receiver || '—'}</div>
      <div class="mail-body-preview">{previewLine || $text('embeds.mail.empty_content')}</div>
      {#if footer}
        <div class="mail-footer">{footer}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .mail-details {
    display: flex;
    flex-direction: column;
    gap: 6px;
    justify-content: center;
    height: 100%;
    color: var(--color-grey-100);
  }

  .mail-subject {
    font-size: 14px;
    font-weight: 700;
    line-height: 1.25;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mail-receiver {
    font-size: 11px;
    color: var(--color-font-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mail-body-preview,
  .mail-footer {
    font-size: 12px;
    line-height: 1.35;
    color: var(--color-font-secondary);
    display: -webkit-box;
    -webkit-box-orient: vertical;
    overflow: hidden;
    white-space: pre-wrap;
  }

  .mail-body-preview {
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }

  .mail-footer {
    -webkit-line-clamp: 2;
    line-clamp: 2;
    opacity: 0.8;
  }

  .mail-details.mobile .mail-subject {
    font-size: 12px;
  }

  .mail-details.mobile .mail-receiver,
  .mail-details.mobile .mail-body-preview,
  .mail-details.mobile .mail-footer {
    font-size: 10px;
  }
</style>
