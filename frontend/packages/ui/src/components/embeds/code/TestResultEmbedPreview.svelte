<!--
  frontend/packages/ui/src/components/embeds/code/TestResultEmbedPreview.svelte

  Preview card for `code-test-result` embeds. Browser runs show the preview frame
  (status-styled placeholder when no frame is available); cli and unit runs show a
  compact status card. Evidence bytes are resolved through the encrypted Code Run
  artifact embed referenced by asset_id.
-->
<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import TestResultStatusBadge from './TestResultStatusBadge.svelte';
  import { text } from '../../../i18n/translations';
  import {
    findEvidence,
    formatDuration,
    parseTestResult,
    resolveArtifactEvidenceUrl,
    type EvidenceUrlResolver,
  } from './testResultContent';

  interface Props {
    id: string;
    kind?: string;
    target?: string;
    run_status?: string;
    exit_code?: number;
    duration_ms?: number;
    passed?: number;
    failed?: number;
    skipped?: number;
    error?: string;
    preview_step_index?: number;
    steps?: unknown[];
    evidence?: unknown[];
    tests?: unknown[];
    is_current?: boolean;
    stale_reason?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    isMobile?: boolean;
    presentationOnly?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
    resolveEvidenceUrl?: EvidenceUrlResolver;
    onFullscreen: () => void;
  }

  let {
    id,
    status = 'finished',
    taskId,
    isMobile = false,
    presentationOnly = false,
    resultContext = 'auto',
    resolveEvidenceUrl = resolveArtifactEvidenceUrl,
    onFullscreen,
    kind, target, run_status, exit_code, duration_ms, passed, failed, skipped, error,
    preview_step_index, steps, evidence, tests, is_current, stale_reason,
  }: Props = $props();

  let view = $derived(parseTestResult({
    kind, target, run_status, exit_code, duration_ms, passed, failed, skipped, error,
    preview_step_index, steps, evidence, tests, is_current, stale_reason,
  }));
  let frame = $derived(view.kind === 'browser' ? findEvidence(view, 'preview_frame') : undefined);
  let frameUrl = $state<string | null>(null);
  let frameFailed = $state(false);

  $effect(() => {
    const assetId = frame?.assetId;
    frameUrl = null;
    frameFailed = false;
    if (!assetId) return;
    let cancelled = false;
    resolveEvidenceUrl(assetId).then((url) => {
      if (!cancelled) frameUrl = url;
    }).catch(() => {
      if (!cancelled) frameFailed = true;
    });
    return () => { cancelled = true; };
  });

  let statusLabel = $derived($text(`embeds.code.test_result.status_${view.runStatus}`));
  let title = $derived(view.target || $text('embeds.code.test_result.title'));
  let showFrame = $derived(Boolean(frameUrl) && !frameFailed);
</script>

<UnifiedEmbedPreview
  resultPreview={true}
  {presentationOnly}
  {resultContext}
  {id}
  appId="code"
  skillId="test_result"
  skillIconName="coding"
  {status}
  skillName={title}
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={statusLabel}
  showSkillIcon={true}
>
  {#snippet details()}
    <div class="tr-preview tr-{view.runStatus}" data-testid="test-result-preview" data-kind={view.kind} data-run-status={view.runStatus}>
      {#if view.kind === 'browser'}
        <div class="tr-frame" data-testid="test-result-preview-frame-area">
          {#if showFrame}
            <img class="tr-frame-img" data-testid="test-result-preview-frame" src={frameUrl} alt={title} loading="lazy" onerror={() => (frameFailed = true)} />
          {:else}
            <div class="tr-placeholder" data-testid="test-result-preview-placeholder">
              <span class="tr-placeholder-status">{statusLabel}</span>
            </div>
          {/if}
        </div>
      {/if}
      <div class="tr-info">
        <p class="tr-target" data-testid="test-result-preview-title">{title}</p>
        <div class="tr-row">
          <TestResultStatusBadge status={view.runStatus} label={statusLabel} testId="test-result-preview-status" />
          {#if !view.isCurrent}
            <TestResultStatusBadge status="stale" label={$text('embeds.code.test_result.stale')} testId="test-result-preview-stale" />
          {/if}
        </div>
        <p class="tr-counts" data-testid="test-result-preview-counts">
          <span class="tr-count-passed">{view.passed} {$text('embeds.code.test_result.status_passed')}</span>
          <span class="tr-count-failed">{view.failed} {$text('embeds.code.test_result.status_failed')}</span>
          {#if view.skipped > 0}<span>{view.skipped} {$text('embeds.code.test_result.status_skipped')}</span>{/if}
          {#if view.durationMs !== undefined}<span>{formatDuration(view.durationMs)}</span>{/if}
        </p>
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .tr-preview { display: flex; flex-direction: column; width: 100%; height: 100%; min-width: 0; box-sizing: border-box; }
  .tr-frame { position: relative; flex: 1 1 auto; min-height: 0; background: var(--color-media-letterbox); }
  .tr-frame-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
  .tr-placeholder { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: var(--color-grey-10); }
  .tr-passed .tr-placeholder { background: var(--color-grey-10); border-bottom: 4px solid var(--color-app-code-start); }
  .tr-failed .tr-placeholder, .tr-error .tr-placeholder, .tr-timed_out .tr-placeholder { background: var(--color-error-light); border-bottom: 4px solid var(--color-error); }
  .tr-placeholder-status { font-size: var(--font-size-p); font-weight: 600; color: var(--color-font-secondary); }
  .tr-info { display: flex; flex-direction: column; gap: var(--spacing-3); padding: var(--spacing-6) var(--spacing-12); flex: 0 0 auto; justify-content: center; }
  .tr-preview:not(:has(.tr-frame)) .tr-info { flex: 1 1 auto; }
  .tr-target { margin: 0; font-size: var(--font-size-p); font-weight: 600; color: var(--color-font-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tr-row { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  .tr-counts { margin: 0; display: flex; flex-wrap: wrap; gap: var(--spacing-4); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .tr-count-failed { color: var(--color-error); }
</style>
