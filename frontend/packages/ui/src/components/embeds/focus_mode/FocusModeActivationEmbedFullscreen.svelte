<!--
  Fullscreen detail view for a focus-mode activation history embed.
  Uses the shared fullscreen shell and the same translated status contract as
  FocusModeActivationEmbed.svelte. This is read-only history UI; activation and
  cancellation remain owned by the inline preview renderer.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/MiscRenderers.swift
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';

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
    onShowChat,
  }: Props = $props();

  let content = $derived(data.decodedContent ?? {});
  let attrs = $derived(data.attrs ?? {});
  let focusId = $derived(String(content.focus_id ?? attrs.focus_id ?? ''));
  let appId = $derived(String(content.app_id ?? attrs.app_id ?? focusId.split('-')[0] ?? 'ai'));
  let focusModeName = $derived(String(content.focus_mode_name ?? attrs.focus_mode_name ?? focusId));
</script>

<UnifiedEmbedFullscreen
  {appId}
  skillId="focus-mode-activation"
  skillIconName="focus"
  embedHeaderTitle={$text('embeds.focus_mode.activated')}
  embedHeaderSubtitle={focusModeName}
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
    <section class="focus-mode-fullscreen" data-testid="focus-mode-activation-fullscreen">
      <div class="focus-mode-icon" aria-hidden="true">✓</div>
      <p class="focus-mode-status">{$text('embeds.focus_mode.active_banner')}</p>
      <h2>{focusModeName}</h2>
      {#if focusId}
        <p class="focus-mode-id">{$text('embeds.focus_mode.focus_on')} {focusId}</p>
      {/if}
    </section>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .focus-mode-fullscreen {
    width: min(100%, 700px);
    min-height: 320px;
    margin: 0 auto;
    padding: var(--spacing-12);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-5);
    text-align: center;
    color: var(--color-font-primary);
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-8);
  }

  .focus-mode-icon {
    width: 72px;
    height: 72px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    color: var(--color-font-button);
    font-size: var(--font-size-h2);
    background: var(--color-app-ai);
  }

  .focus-mode-status,
  .focus-mode-id,
  h2 {
    margin: 0;
  }

  .focus-mode-status,
  .focus-mode-id {
    color: var(--color-font-secondary);
  }
</style>
