<!--
  frontend/packages/ui/src/components/embeds/web/WebReadEmbedPreview.svelte
  
  Preview component for Web Read skill embeds.
  Uses UnifiedEmbedPreview as base and provides web read-specific details content.
  
  Supports both contexts:
  - Skill preview context: receives previewData from skillPreviewService
  - Embed context: receives results directly
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { chatSyncService } from '../../../services/chatSyncService';
  import type { BaseSkillPreviewData } from '../../../types/appSkills';
  // @ts-ignore - @repo/ui module exists at runtime
  import { text } from '@repo/ui';
  
  interface WebReadResult {
    type: string;
    url: string;
    title?: string;
    markdown?: string;
    language?: string;
    favicon?: string;
    og_image?: string;
    og_sitename?: string;
    hash?: string;
  }
  
  interface WebReadPreviewData extends BaseSkillPreviewData {
    results: WebReadResult[];
  }
  
  interface Props {
    id: string;
    status?: 'processing' | 'finished' | 'error';
    results?: WebReadResult[];
    taskId?: string;
    previewData?: WebReadPreviewData;
    isMobile?: boolean;
    onFullscreen?: () => void;
  }
  
  let {
    id,
    status: statusProp,
    results: resultsProp,
    taskId: taskIdProp,
    previewData,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  let status = $derived(previewData?.status || statusProp || 'processing');
  let results = $derived(previewData?.results || resultsProp || []);
  let taskId = $derived(previewData?.task_id || taskIdProp);
  
  let firstResult = $derived(results[0]);
  
  function safeHostname(url?: string): string {
    if (!url) return '';
    try {
      return new URL(url).hostname;
    } catch {
      // Fallback: try to strip scheme if present, then take host part.
      const withoutScheme = url.replace(/^[a-zA-Z]+:\/\//, '');
      return withoutScheme.split('/')[0] || '';
    }
  }
  
  let hostname = $derived(safeHostname(firstResult?.url));
  let displayTitle = $derived(firstResult?.title || hostname || ($text('embeds.web_read.text') || 'Web Read'));
  let pageCount = $derived(results.length);
  
  // Prefer favicon from result for BasicInfosBar title favicon.
  let faviconUrl = $derived(firstResult?.favicon || undefined);
  
  let snippetText = $derived(() => {
    const markdown = firstResult?.markdown || '';
    if (!markdown) return '';
    // First non-empty line as a tiny preview.
    const firstNonEmptyLine = markdown.split('\n').map(l => l.trim()).find(Boolean) || '';
    return firstNonEmptyLine.length > 140 ? `${firstNonEmptyLine.slice(0, 140)}…` : firstNonEmptyLine;
  });
  
  const skillIconName = 'book';
  let skillName = $derived($text('embeds.web_read.text') || 'Web Read');
  
  async function handleStop() {
    if (status === 'processing' && taskId) {
      try {
        await chatSyncService.sendCancelAiTask(taskId);
        console.debug(`[WebReadEmbedPreview] Sent cancel request for task ${taskId}`);
      } catch (error) {
        console.error(`[WebReadEmbedPreview] Failed to cancel task ${taskId}:`, error);
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="web"
  skillId="read"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  {faviconUrl}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="web-read-details" class:mobile={isMobileLayout}>
      <div class="read-title">{displayTitle}</div>
      <div class="read-subtitle">
        {#if hostname}
          {hostname}
        {:else}
          {$text('embeds.web_read.reading.text', { default: 'Reading page' })}
        {/if}
        {#if pageCount > 1}
          <span class="read-count">· {pageCount} {$text('embeds.pages.text', { default: 'pages' })}</span>
        {/if}
      </div>
      {#if status === 'finished' && snippetText}
        <div class="read-snippet">{snippetText}</div>
      {/if}
      {#if status === 'processing'}
        <div class="processing-text">{$text('embeds.processing.text')}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .web-read-details {
    display: flex;
    flex-direction: column;
    gap: 6px;
    height: 100%;
  }
  
  .web-read-details:not(.mobile) {
    justify-content: center;
  }
  
  .web-read-details.mobile {
    justify-content: flex-start;
  }
  
  .read-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-100);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .web-read-details.mobile .read-title {
    font-size: 14px;
    -webkit-line-clamp: 3;
    line-clamp: 3;
  }
  
  .read-subtitle {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.3;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
  }
  
  .web-read-details.mobile .read-subtitle {
    font-size: 12px;
  }
  
  .read-count {
    color: var(--color-grey-60);
    white-space: nowrap;
  }
  
  .read-snippet {
    font-size: 13px;
    color: var(--color-grey-80);
    line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }
  
  .processing-text {
    font-size: 13px;
    color: var(--color-grey-60);
  }
</style>

