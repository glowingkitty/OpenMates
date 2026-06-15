<!--
  frontend/packages/ui/src/components/embeds/images/ImageAuthenticityBadge.svelte

  Shared authenticity indicator for uploaded image embeds.

  Shows a collapsed status icon by default, then expands on hover, focus, or
  click to reveal the Sightengine AI-generated probability and provider link.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import {
    buildAuthenticityBadgeViewModel,
    type AIDetectionMetadata,
  } from './imageAuthenticity';

  interface Props {
    aiDetection: AIDetectionMetadata | null;
    variant?: 'preview' | 'fullscreen';
  }

  let { aiDetection, variant = 'preview' }: Props = $props();
  let isExpanded = $state(false);

  let viewModel = $derived(buildAuthenticityBadgeViewModel(aiDetection, $text));
  let badgeClass = $derived(
    viewModel
      ? `authenticity-badge ${variant} ${viewModel.status === 'authentic' ? 'authentic' : viewModel.status === 'failed' ? 'failed' : 'ai-generated'}${isExpanded ? ' expanded' : ''}`
      : `authenticity-badge ${variant}`,
  );

  function toggleExpanded(event?: MouseEvent | KeyboardEvent) {
    event?.stopPropagation();
    isExpanded = !isExpanded;
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    toggleExpanded(event);
  }
</script>

{#if viewModel}
  <div
    class={badgeClass}
    data-testid="image-authenticity-badge"
    data-authenticity-status={viewModel.status}
    aria-label={viewModel.ariaLabel}
    title={viewModel.ariaLabel}
    role="button"
    aria-expanded={isExpanded}
    tabindex="0"
    onclick={toggleExpanded}
    onkeydown={handleKeydown}
    onmouseenter={() => (isExpanded = true)}
    onmouseleave={() => (isExpanded = false)}
  >
    <span class="authenticity-badge-icon" aria-hidden="true"></span>
    <span class="authenticity-badge-details">
      <span class="authenticity-badge-summary">
        <span class="authenticity-badge-probability">{viewModel.probabilityLabel}</span>
        <span class="authenticity-badge-source">
          {$text('app_skills.images.view.via_provider_prefix')}
          {#if viewModel.providerUrl}
            <a
              href={viewModel.providerUrl}
              target="_blank"
              rel="noopener noreferrer"
              onclick={(event) => event.stopPropagation()}
              onkeydown={(event) => event.stopPropagation()}
            >{viewModel.providerLabel}</a>
          {:else}
            <span>{viewModel.providerLabel}</span>
          {/if}
        </span>
      </span>
      <span class="authenticity-badge-explanation">{viewModel.explanationLabel}</span>
    </span>
  </div>
{/if}

<style>
  .authenticity-badge {
    position: absolute;
    top: 8px;
    right: 8px;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    width: 28px;
    max-width: 28px;
    min-height: 28px;
    padding: 0;
    border-radius: var(--radius-full);
    border: 1px solid rgba(255, 255, 255, 0.58);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.24);
    box-sizing: border-box;
    overflow: hidden;
    cursor: pointer;
    pointer-events: auto;
    transition:
      max-width var(--duration-fast) var(--easing-default),
      width var(--duration-fast) var(--easing-default),
      padding var(--duration-fast) var(--easing-default),
      background var(--duration-fast) var(--easing-default);
  }

  .authenticity-badge.fullscreen {
    top: 12px;
    right: 12px;
    width: 32px;
    max-width: 32px;
    min-height: 32px;
  }

  .authenticity-badge.authentic {
    background: var(--color-success-60, #20a35b);
  }

  .authenticity-badge.ai-generated {
    background: var(--color-grey-70);
  }

  .authenticity-badge.failed {
    background: var(--color-warning-70, #a56b00);
  }

  .authenticity-badge:hover,
  .authenticity-badge:focus-visible,
  .authenticity-badge:focus-within,
  .authenticity-badge.expanded {
    width: auto;
    max-width: min(340px, calc(100% - 16px));
    padding: var(--spacing-2) var(--spacing-4) var(--spacing-2) var(--spacing-3);
    gap: var(--spacing-2);
    align-items: flex-start;
  }

  .authenticity-badge:hover .authenticity-badge-icon,
  .authenticity-badge:focus-visible .authenticity-badge-icon,
  .authenticity-badge:focus-within .authenticity-badge-icon,
  .authenticity-badge.expanded .authenticity-badge-icon {
    margin: 1px 0 0 0;
  }

  .authenticity-badge.fullscreen:hover,
  .authenticity-badge.fullscreen:focus-visible,
  .authenticity-badge.fullscreen:focus-within,
  .authenticity-badge.fullscreen.expanded {
    max-width: min(380px, calc(100% - 24px));
    padding: var(--spacing-3) var(--spacing-5) var(--spacing-3) var(--spacing-4);
  }

  .authenticity-badge:focus-visible {
    outline: 2px solid var(--color-grey-0);
    outline-offset: 2px;
  }

  .authenticity-badge-icon {
    display: block;
    flex: 0 0 auto;
    width: 14px;
    height: 14px;
    margin: auto;
    background: var(--color-grey-0);
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }

  .authenticity-badge.fullscreen .authenticity-badge-icon {
    width: 15px;
    height: 15px;
  }

  .authenticity-badge.authentic .authenticity-badge-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/check.svg');
    mask-image: url('@openmates/ui/static/icons/check.svg');
  }

  .authenticity-badge.ai-generated .authenticity-badge-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
  }

  .authenticity-badge.failed .authenticity-badge-icon {
    -webkit-mask-image: url('@openmates/ui/static/icons/question.svg');
    mask-image: url('@openmates/ui/static/icons/question.svg');
  }

  .authenticity-badge-details {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--spacing-1);
    max-width: 0;
    opacity: 0;
    overflow: hidden;
    white-space: normal;
    color: var(--color-grey-0);
    font-size: var(--font-size-tiny);
    font-weight: 600;
    line-height: 1;
    transition:
      max-width var(--duration-fast) var(--easing-default),
      opacity var(--duration-fast) var(--easing-default);
  }

  .authenticity-badge:hover .authenticity-badge-details,
  .authenticity-badge:focus-visible .authenticity-badge-details,
  .authenticity-badge:focus-within .authenticity-badge-details,
  .authenticity-badge.expanded .authenticity-badge-details {
    max-width: 290px;
    opacity: 1;
  }

  .authenticity-badge-summary {
    display: flex;
    align-items: center;
    gap: var(--spacing-2);
    white-space: nowrap;
  }

  .authenticity-badge-explanation {
    display: block;
    max-width: 100%;
    font-size: 10px;
    font-weight: 500;
    line-height: 1.25;
    opacity: 0.9;
  }

  .authenticity-badge-source {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    opacity: 0.9;
  }

  .authenticity-badge-source::before {
    content: '·';
    margin-right: 2px;
  }

  .authenticity-badge-source a {
    color: inherit;
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .authenticity-badge-source a:hover,
  .authenticity-badge-source a:focus-visible {
    opacity: 0.82;
  }
</style>
