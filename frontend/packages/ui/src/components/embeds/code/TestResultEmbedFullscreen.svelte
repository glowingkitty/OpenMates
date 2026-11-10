<!--
  frontend/packages/ui/src/components/embeds/code/TestResultEmbedFullscreen.svelte

  Fullscreen view for `code-test-result` embeds.
  - browser: playable run video beside a vertical step timeline; clicking a step
    seeks the video to the step start; the step being played is highlighted.
  - cli: terminal-styled step list (command entered + output) without video.
  - unit: counts and per-test list with status and error text.
  Evidence is resolved through the encrypted Code Run artifact embed (asset_id).
-->
<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import TestResultStatusBadge from './TestResultStatusBadge.svelte';
  import { text } from '../../../i18n/translations';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    activeStepIndex,
    findEvidence,
    formatDuration,
    parseTestResult,
    resolveArtifactEvidenceUrl,
    rowStatus,
    type EvidenceUrlResolver,
  } from './testResultContent';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    resolveEvidenceUrl?: EvidenceUrlResolver;
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
    resolveEvidenceUrl = resolveArtifactEvidenceUrl,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  let view = $derived(parseTestResult(data.decodedContent));
  let title = $derived(view.target || $text('embeds.code.test_result.title'));
  let statusLabel = $derived($text(`embeds.code.test_result.status_${view.runStatus}`));
  let subtitle = $derived([statusLabel, formatDuration(view.durationMs)].filter(Boolean).join(' · '));

  let videoEl = $state<HTMLVideoElement | undefined>();
  let videoUrl = $state<string | null>(null);
  let frameUrl = $state<string | null>(null);
  let currentMs = $state(0);

  $effect(() => {
    const videoId = findEvidence(view, 'video')?.assetId;
    const frameId = findEvidence(view, 'preview_frame')?.assetId;
    videoUrl = null;
    frameUrl = null;
    let cancelled = false;
    const load = (assetId: string | undefined, assign: (url: string | null) => void) => {
      if (!assetId) return;
      resolveEvidenceUrl(assetId).then((url) => { if (!cancelled) assign(url); }).catch(() => { if (!cancelled) assign(null); });
    };
    load(videoId, (url) => { videoUrl = url; });
    load(frameId, (url) => { frameUrl = url; });
    return () => { cancelled = true; };
  });

  let activeIndex = $derived(activeStepIndex(view.steps, currentMs));

  function seekToStep(startMs: number) {
    currentMs = startMs;
    if (!videoEl) return;
    videoEl.currentTime = startMs / 1000;
  }

  function onTimeUpdate() {
    if (videoEl) currentMs = videoEl.currentTime * 1000;
  }

  function stepStatusLabel(status: string): string {
    return $text(`embeds.code.test_result.status_${rowStatus(status)}`);
  }
</script>

<UnifiedEmbedFullscreen
  testId="test-result-fullscreen"
  appId="code"
  skillId="test_result"
  skillIconName="coding"
  embedHeaderTitle={title}
  embedHeaderSubtitle={subtitle}
  showSkillIcon={true}
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
    <div class="tr-fs" data-testid="test-result-fullscreen-body" data-kind={view.kind} data-run-status={view.runStatus}>
      <header class="tr-summary">
        <TestResultStatusBadge status={view.runStatus} label={statusLabel} testId="test-result-status" />
        {#if !view.isCurrent}
          <span data-testid="test-result-stale">
            <TestResultStatusBadge status="stale" label={view.staleReason ? `${$text('embeds.code.test_result.stale')}: ${view.staleReason}` : $text('embeds.code.test_result.stale')} />
          </span>
        {/if}
        <span class="tr-count tr-count-passed" data-testid="test-result-count-passed">{view.passed} {$text('embeds.code.test_result.status_passed')}</span>
        <span class="tr-count tr-count-failed" data-testid="test-result-count-failed">{view.failed} {$text('embeds.code.test_result.status_failed')}</span>
        <span class="tr-count" data-testid="test-result-count-skipped">{view.skipped} {$text('embeds.code.test_result.status_skipped')}</span>
      </header>
      {#if view.error}<p class="tr-error-text" data-testid="test-result-error">{view.error}</p>{/if}

      {#if view.kind === 'browser'}
        <div class="tr-browser">
          <div class="tr-video-wrap">
            {#if videoUrl}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video bind:this={videoEl} class="tr-video" data-testid="test-result-video" src={videoUrl} controls preload="metadata" ontimeupdate={onTimeUpdate} onseeked={onTimeUpdate}></video>
            {:else if frameUrl}
              <img class="tr-video" data-testid="test-result-video-fallback" src={frameUrl} alt={title} />
            {:else}
              <div class="tr-video tr-video-missing" data-testid="test-result-video-missing">{$text('embeds.code.test_result.no_video')}</div>
            {/if}
          </div>
          <ol class="tr-timeline" data-testid="test-result-timeline" aria-label={$text('embeds.code.test_result.steps')}>
            {#each view.steps as step, index (index)}
              <li>
                <button
                  type="button"
                  class="tr-step tr-step-{rowStatus(step.status)}"
                  class:tr-step-active={index === activeIndex}
                  data-testid="test-result-step-{index}"
                  data-status={rowStatus(step.status)}
                  data-start-ms={step.startMs}
                  aria-current={index === activeIndex ? 'step' : undefined}
                  onclick={() => seekToStep(step.startMs)}
                >
                  <i class="tr-step-dot" aria-hidden="true"></i>
                  <span class="tr-step-main">
                    <span class="tr-step-name">{step.name}</span>
                    <span class="tr-step-status">{stepStatusLabel(step.status)}</span>
                    {#if step.error}<span class="tr-step-error">{step.error}</span>{/if}
                  </span>
                </button>
              </li>
            {/each}
          </ol>
        </div>
      {:else if view.kind === 'cli'}
        <div class="tr-terminal" data-testid="test-result-terminal">
          {#each view.steps as step, index (index)}
            <section class="tr-term-step tr-term-{rowStatus(step.status)}" data-testid="test-result-term-step-{index}" data-status={rowStatus(step.status)}>
              {#if step.command}
                <div class="tr-term-cmd" data-testid="test-result-term-command-{index}"><span class="tr-prompt" aria-hidden="true">$</span> {step.command}</div>
              {:else}
                <div class="tr-term-cmd">{step.name}</div>
              {/if}
              {#if step.output}<pre class="tr-term-out" data-testid="test-result-term-output-{index}">{step.output}</pre>{/if}
              {#if step.error}<pre class="tr-term-out tr-term-err">{step.error}</pre>{/if}
              <div class="tr-term-status" data-testid="test-result-term-status-{index}">{stepStatusLabel(step.status)}</div>
            </section>
          {/each}
        </div>
      {:else}
        <ul class="tr-tests" data-testid="test-result-tests">
          {#each view.tests as test, index (index)}
            <li class="tr-test tr-test-{rowStatus(test.status)}" data-testid="test-result-test-{index}" data-status={rowStatus(test.status)}>
              <div class="tr-test-head">
                <TestResultStatusBadge status={rowStatus(test.status)} label={stepStatusLabel(test.status)} />
                <span class="tr-test-name">{test.name}</span>
                {#if test.durationMs !== undefined}<span class="tr-test-time">{formatDuration(test.durationMs)}</span>{/if}
              </div>
              {#if test.error}<pre class="tr-test-error">{test.error}</pre>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .tr-fs { container-type: inline-size; display: flex; flex-direction: column; gap: var(--spacing-8); width: 100%; max-width: 72rem; margin: 0 auto; padding: var(--spacing-8) var(--spacing-12); box-sizing: border-box; color: var(--color-font-primary); }
  .tr-summary { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-6); }
  .tr-count { font-size: var(--font-size-small); font-weight: 500; color: var(--color-font-secondary); }
  .tr-count-failed { color: var(--color-error); }
  .tr-error-text { margin: 0; color: var(--color-error); font-size: var(--font-size-small); white-space: pre-wrap; }

  .tr-browser { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--spacing-8); }
  @container (min-width: 700px) { .tr-browser { grid-template-columns: minmax(0, 2fr) minmax(16rem, 1fr); align-items: start; } }
  .tr-video-wrap { background: var(--color-media-letterbox); border-radius: var(--radius-5); overflow: hidden; }
  .tr-video { display: block; width: 100%; max-height: 70vh; object-fit: contain; }
  .tr-video-missing { display: flex; align-items: center; justify-content: center; min-height: 12rem; color: var(--color-font-secondary); background: var(--color-grey-10); }
  .tr-timeline { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-2); }
  .tr-step { display: flex; align-items: flex-start; gap: var(--spacing-6); width: 100%; text-align: left; padding: var(--spacing-5) var(--spacing-6); border: 1px solid transparent; border-radius: var(--radius-3); background: var(--color-grey-10); color: inherit; font: inherit; cursor: pointer; }
  .tr-step:hover { background: var(--color-grey-20); }
  .tr-step-active { border-color: var(--color-app-code-start); background: var(--color-grey-20); }
  .tr-step-dot { flex: 0 0 auto; width: 10px; height: 10px; margin-top: 6px; border-radius: 50%; background: var(--color-app-code-start); }
  .tr-step-failed .tr-step-dot, .tr-step-error .tr-step-dot { background: var(--color-error); }
  .tr-step-skipped .tr-step-dot { background: var(--color-grey-50); }
  .tr-step-main { display: flex; flex-direction: column; min-width: 0; gap: var(--spacing-1); }
  .tr-step-name { font-weight: 600; overflow-wrap: anywhere; }
  .tr-step-status { font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .tr-step-error { font-size: var(--font-size-small); color: var(--color-error); overflow-wrap: anywhere; }

  .tr-terminal { display: flex; flex-direction: column; gap: var(--spacing-6); padding: var(--spacing-8); border-radius: var(--radius-5); background: var(--color-grey-100); color: var(--color-grey-0); font-family: var(--font-mono, ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace); font-size: var(--font-size-small); }
  .tr-term-step { display: flex; flex-direction: column; gap: var(--spacing-2); }
  .tr-term-cmd { font-weight: 600; overflow-wrap: anywhere; }
  .tr-prompt { color: var(--color-app-code-start); }
  .tr-term-out { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; color: var(--color-grey-30); }
  .tr-term-err { color: var(--color-error); }
  .tr-term-status { font-size: var(--font-size-xs, var(--font-size-small)); color: var(--color-grey-50); }
  .tr-term-failed .tr-term-status, .tr-term-error .tr-term-status { color: var(--color-error); }

  .tr-tests { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--spacing-4); }
  .tr-test { padding: var(--spacing-6); border-radius: var(--radius-3); background: var(--color-grey-10); }
  .tr-test-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-5); }
  .tr-test-name { font-weight: 600; overflow-wrap: anywhere; flex: 1 1 auto; min-width: 0; }
  .tr-test-time { font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .tr-test-error { margin: var(--spacing-4) 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: var(--font-size-small); color: var(--color-error); font-family: var(--font-mono, ui-monospace, Menlo, Consolas, monospace); }
</style>
