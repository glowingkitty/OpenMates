<!--
  Purpose: Fullscreen mail draft view with copy and open-mail-client actions.
  Architecture: Uses unified fullscreen embed shell with optional PII reveal toggle.
  Architecture: docs/architecture/embeds.md
  Tests: N/A
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { restorePIIInText, replacePIIOriginalsWithPlaceholders } from '../../enter_message/services/piiDetectionService';
  import type { PIIMapping } from '../../../types/chat';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  /**
   * Coerce an unknown value to a string, returning empty string for non-strings.
   */
  function coerceString(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  interface Props {
    /** Standardized raw embed data (decodedContent, attrs, embedData) */
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
    piiMappings?: PIIMapping[];
    piiRevealed?: boolean;
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
    onShowChat,
    piiMappings = [],
    piiRevealed = false,
  }: Props = $props();

  // ── Extract fields from data.decodedContent ─────────────────────────────────

  let dc = $derived(data.decodedContent);
  let receiver = $derived(coerceString(dc.receiver));
  let subject = $derived(coerceString(dc.subject));
  let content = $derived(coerceString(dc.content));
  let footer = $derived(coerceString(dc.footer));

  let localPiiRevealed = $state(false);
  $effect(() => {
    localPiiRevealed = piiRevealed;
  });

  let hasPII = $derived(piiMappings.length > 0);

  function applyPIIMode(value: string): string {
    if (!value || !hasPII) return value;
    if (localPiiRevealed) return restorePIIInText(value, piiMappings);
    return replacePIIOriginalsWithPlaceholders(value, piiMappings);
  }

  let safeReceiver = $derived(applyPIIMode(receiver));
  let safeSubject = $derived(applyPIIMode(subject));
  let safeContent = $derived(applyPIIMode(content));
  let safeFooter = $derived(applyPIIMode(footer));

  let mailBody = $derived.by(() => {
    if (safeFooter && safeContent) return `${safeContent}\n\n${safeFooter}`;
    return safeContent || safeFooter || '';
  });

  let mailtoUrl = $derived.by(() => {
    const to = encodeURIComponent(safeReceiver || '');
    const draftSubject = encodeURIComponent(safeSubject || '');
    const body = encodeURIComponent(mailBody || '');
    return `mailto:${to}?subject=${draftSubject}&body=${body}`;
  });

  function togglePII() {
    localPiiRevealed = !localPiiRevealed;
  }

  async function handleCopy() {
    const draft = [
      `${$text('embeds.mail.to')}: ${safeReceiver || ''}`,
      `${$text('embeds.mail.subject')}: ${safeSubject || ''}`,
      '',
      safeContent || '',
      safeFooter ? `\n${safeFooter}` : '',
    ].join('\n').trim();

    const result = await copyToClipboard(draft);
    if (result.success) {
      notificationStore.success($text('embeds.mail.copied'));
      return;
    }
    notificationStore.error($text('embeds.mail.copy_failed'));
  }

  function handleOpenMailClient() {
    window.location.href = mailtoUrl;
  }
</script>

<UnifiedEmbedFullscreen
  appId="mail"
  skillId="email"
  skillIconName="mail"
  embedHeaderTitle={safeSubject || $text('embeds.mail.email')}
  embedHeaderSubtitle={safeReceiver ? `${$text('embeds.mail.to')}: ${safeReceiver}` : undefined}
  onClose={onClose}
  onCopy={handleCopy}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  showPIIToggle={hasPII}
  piiRevealed={localPiiRevealed}
  onTogglePII={togglePII}
>
  {#snippet embedHeaderCta()}
    <EmbedHeaderCtaButton label={$text('embeds.mail.open_mail_client')} onclick={handleOpenMailClient} />
  {/snippet}

  {#snippet content()}
    <div class="mail-fullscreen-content">
      <section class="mail-field">
        <div class="label">{$text('embeds.mail.to')}</div>
        <div class="value">{safeReceiver || '—'}</div>
      </section>

      <section class="mail-field">
        <div class="label">{$text('embeds.mail.subject')}</div>
        <div class="value">{safeSubject || '—'}</div>
      </section>

      <section class="mail-field">
        <div class="label">{$text('embeds.mail.content')}</div>
        <div class="body">{safeContent || $text('embeds.mail.empty_content')}</div>
      </section>

      {#if safeFooter}
        <section class="mail-field">
          <div class="label">{$text('embeds.mail.footer')}</div>
          <div class="body footer">{safeFooter}</div>
        </section>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .mail-fullscreen-content {
    margin: 72px 12px 100px;
    padding: var(--spacing-8);
    border-radius: var(--radius-6);
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .mail-field {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .label {
    font-size: var(--font-size-tiny);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--color-font-secondary);
    font-weight: 700;
  }

  .value,
  .body {
    font-size: var(--font-size-small);
    color: var(--color-font-primary);
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .body {
    padding: var(--spacing-5) var(--spacing-6);
    border-radius: var(--radius-4);
    background: var(--color-grey-5);
    border: 1px solid var(--color-grey-20);
    min-height: 44px;
  }

  .footer {
    font-style: italic;
  }
</style>
