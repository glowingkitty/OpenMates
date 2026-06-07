<!--
  frontend/packages/ui/src/components/embeds/code/ApplicationEmbedPreview.svelte

  Preview component for generated application embeds.
  Shows project metadata, latest screenshot/placeholder, and an explicit play
  affordance. Rendering this component must never start a live preview by itself.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  interface FileRef {
    path?: string;
    embed_id?: string;
    role?: string;
  }

  interface Props {
    id: string;
    name?: string;
    framework?: string;
    runtime?: string;
    file_refs?: FileRef[];
    entrypoints?: Array<Record<string, unknown>>;
    latest_screenshot_url?: string;
    status: 'processing' | 'finished' | 'error';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    name = '',
    framework = '',
    runtime = '',
    file_refs = [],
    entrypoints = [],
    latest_screenshot_url,
    status,
    taskId,
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  const skillIconName = 'coding';
  let fileCount = $derived(Array.isArray(file_refs) ? file_refs.length : 0);
  let entrypointCount = $derived(Array.isArray(entrypoints) ? entrypoints.length : 0);
  let skillName = $derived(name || $text('embeds.application_title'));
  let statusText = $derived.by(() => {
    if (status === 'processing') return $text('embeds.processing');
    if (status === 'error') return $text('embeds.application_preview_failed');
    const facts = [framework, runtime, fileCount ? $text('embeds.application_file_count', { values: { count: String(fileCount) } }) : ''].filter(Boolean);
    return facts.join(' · ') || $text('embeds.application_ready');
  });

  function handleStop() {
    // Live preview sessions are started/stopped from fullscreen in this slice.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="code"
  skillId="application"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="application-preview" class:mobile={isMobileLayout}>
      <div class="screenshot-frame" data-testid="application-preview-screenshot">
        {#if latest_screenshot_url}
          <img src={latest_screenshot_url} alt="" class="screenshot" />
        {:else}
          <div class="placeholder" aria-hidden="true">
            <span class="app-window-dot"></span>
            <span class="app-window-line wide"></span>
            <span class="app-window-line"></span>
            <span class="app-window-card"></span>
          </div>
        {/if}
        <div class="play-overlay" data-testid="application-preview-play-overlay" aria-hidden="true">▶</div>
      </div>
      <div class="meta-row">
        <span>{fileCount} {$text(fileCount === 1 ? 'embeds.application_file_singular' : 'embeds.application_file_plural')}</span>
        {#if entrypointCount}
          <span>{entrypointCount} {$text(entrypointCount === 1 ? 'embeds.application_entrypoint_singular' : 'embeds.application_entrypoint_plural')}</span>
        {/if}
      </div>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .application-preview {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    height: 100%;
    min-height: 0;
  }

  .screenshot-frame {
    position: relative;
    flex: 1;
    min-height: 0;
    border-radius: var(--radius-3);
    overflow: hidden;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-20);
  }

  .screenshot {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .placeholder {
    display: grid;
    grid-template-columns: 1fr;
    gap: var(--spacing-2);
    padding: var(--spacing-3);
    height: 100%;
    align-content: start;
  }

  .app-window-dot,
  .app-window-line,
  .app-window-card {
    display: block;
    border-radius: var(--radius-full);
    background: var(--color-grey-30);
  }

  .app-window-dot {
    width: 34px;
    height: 8px;
  }

  .app-window-line {
    width: 55%;
    height: 10px;
  }

  .app-window-line.wide {
    width: 80%;
  }

  .app-window-card {
    width: 100%;
    height: 54px;
    border-radius: var(--radius-3);
    opacity: 0.7;
  }

  .play-overlay {
    position: absolute;
    inset: 50% auto auto 50%;
    transform: translate(-50%, -50%);
    width: 42px;
    height: 42px;
    display: grid;
    place-items: center;
    border-radius: var(--radius-full);
    color: var(--color-font-button);
    background: var(--color-app-code);
    box-shadow: 0 4px 14px rgb(0 0 0 / 20%);
    font-size: 15px;
  }

  .meta-row {
    display: flex;
    gap: var(--spacing-2);
    flex-wrap: wrap;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }
</style>
