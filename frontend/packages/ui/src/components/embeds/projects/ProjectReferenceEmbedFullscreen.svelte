<script lang="ts">
  import { onDestroy } from 'svelte';
  import { get } from 'svelte/store';
  import { text } from '@repo/ui';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import ChildEmbedOverlay from '../ChildEmbedOverlay.svelte';
  import CodeEmbedFullscreen from '../code/CodeEmbedFullscreen.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { userProfile } from '../../../stores/userProfile';
  import { getProject, listProjectSources, readEncryptedProjectFile, requestProjectRemoteAccess, type ProjectRemoteTextResult } from '../../../services/projectService';
  import { buildVirtualRemoteFullscreenDetail, classifyRemotePreviewPath, normalizeRemoteFilePreview, type VirtualRemoteFullscreenDetail } from '../../../services/projectRemoteSources';
  import { hasFullscreenComponent, loadFullscreenComponent, resolveRegistryKey } from '../../../services/embedFullscreenResolver';
  import { projectFileReferences, stringField, type ProjectFileReference } from './projectReferenceData';
  import { connectedReferenceSource, hostedReferenceContentHash, referenceRevisionStatus } from './projectReferenceRevision';

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
  let { data, onClose, embedId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat }: Props = $props();
  let currentContent = $state<Record<string, unknown>>({});
  let status = $state('finished');
  let selected = $state<ProjectFileReference | null>(null);
  let hosted = $state<{ embedId: string; type: string; content: Record<string, unknown>; projectId: string; teamId: string | null } | null>(null);
  let remote = $state<VirtualRemoteFullscreenDetail | null>(null);
  let error = $state('');
  let loading = $state(false);
  let revisionStatus = $state<'same' | 'changed' | 'unknown'>('unknown');
  let controller: AbortController | null = null;
  let openGeneration = 0;
  $effect(() => { currentContent = data.decodedContent || {}; status = String(data.embedData?.status || data.decodedContent?.status || 'finished'); });
  onDestroy(() => { openGeneration++; controller?.abort(); });

  const refs = $derived(projectFileReferences(currentContent));
  const query = $derived(stringField(currentContent.query) || $text('embeds.projects.references.files_fallback'));
  const projectName = $derived(refs[0]?.project_name || stringField(currentContent.project_name) || '');
  const skillId = $derived(stringField(currentContent.skill_id) === 'read' ? 'read' : 'search');
  const title = $derived(projectName
    ? $text('embeds.projects.references.query_in_project', { values: { query, project: projectName } })
    : $text('embeds.projects.references.query_only', { values: { query } }));
  const selectedIndex = $derived(selected ? refs.findIndex((ref) =>
    ref.project_id === selected?.project_id && ref.source_id === selected?.source_id
    && ref.embed_id === selected?.embed_id && ref.path === selected?.path
    && ref.line === selected?.line) : -1);

  async function openReference(ref: ProjectFileReference): Promise<void> {
    controller?.abort();
    controller = new AbortController();
    const generation = ++openGeneration;
    selected = ref;
    hosted = null;
    remote = null;
    error = '';
    loading = true;
    revisionStatus = 'unknown';
    try {
      const project = await getProject(ref.project_id, { teamId: ref.team_id });
      if (ref.source_id) {
        const source = await connectedReferenceSource(ref.source_id,
          () => listProjectSources(project, { teamId: ref.team_id }));
        if (!source) throw new Error($text('embeds.projects.references.source_unavailable'));
        const ownerId = get(userProfile).user_id;
        if (!ownerId) throw new Error($text('embeds.projects.references.source_unavailable'));
        const classification = classifyRemotePreviewPath(ref.path);
        if (classification.kind === 'unsupported') throw new Error($text('embeds.projects.references.preview_unavailable'));
        // The connected source is read only when the user opens this row. No
        // copy of its text is persisted as an embed or uploaded to the server.
        const result = await requestProjectRemoteAccess<ProjectRemoteTextResult>(
          project, source, { ownerId, teamId: ref.team_id }, 'read_text', { path: ref.path }, controller.signal);
        if (generation !== openGeneration) return;
        revisionStatus = referenceRevisionStatus(ref.expected_base, result.expectedBase);
        const preview = normalizeRemoteFilePreview({
          sourceId: ref.source_id, path: ref.path, displayName: ref.path.split('/').pop() || ref.path,
          language: classification.language, snippet: result.content.slice(0, 20_000),
          snippetTruncated: result.truncated || result.content.length > 20_000,
          baseHash: result.expectedBase ?? undefined, sizeBytes: result.sizeBytes,
          lineCount: result.lineCount, previewPolicy: result.truncated ? 'bounded_truncated_text' : 'bounded_full_text',
          safetyFlags: result.truncated ? ['truncated'] : [],
        });
        remote = buildVirtualRemoteFullscreenDetail(preview, result.content);
      } else if (ref.embed_id) {
        const file = await readEncryptedProjectFile(project, ref.embed_id, { teamId: ref.team_id });
        if (generation !== openGeneration) return;
        const currentHash = await hostedReferenceContentHash(file.content);
        if (generation !== openGeneration) return;
        revisionStatus = referenceRevisionStatus(ref.expected_base, currentHash);
        const type = stringField(file.content.type) || 'code-code';
        hosted = { embedId: ref.embed_id, type, content: file.content, projectId: ref.project_id, teamId: ref.team_id ?? null };
      }
    } catch (cause) {
      if (generation === openGeneration && !(cause instanceof DOMException && cause.name === 'AbortError')) {
        error = cause instanceof Error ? cause.message : $text('embeds.projects.references.open_failed');
      }
    } finally {
      if (generation === openGeneration) loading = false;
    }
  }

  function closeSelected(): void {
    controller?.abort();
    openGeneration++;
    selected = null;
    hosted = null;
    remote = null;
    error = '';
    loading = false;
    revisionStatus = 'unknown';
  }
  function moveSelection(offset: number): void {
    const next = refs[selectedIndex + offset];
    if (next) void openReference(next);
  }
</script>

<UnifiedEmbedFullscreen
  testId="project-reference-fullscreen" appId="projects" {skillId} appIconName="project"
  skillIconName={skillId === 'read' ? 'project' : 'search'} showSkillIcon={true}
  embedHeaderTitle={title} embedHeaderSubtitle={$text('embeds.projects.references.subtitle')}
  currentEmbedId={embedId} {onClose} {hasPreviousEmbed} {hasNextEmbed}
  {onNavigatePrevious} {onNavigateNext} {navigateDirection} {showChatButton} {onShowChat}
  onEmbedDataUpdated={(update) => { currentContent = update.decodedContent; status = update.status; }}
>
  {#snippet content()}
    <div class="reference-list" data-testid="project-reference-list">
      {#if refs.length}
        {#each refs as ref, index (`${ref.project_id}:${ref.source_id || ref.embed_id}:${ref.path}:${index}`)}
          <button type="button" class="reference-row" data-testid="project-reference-row"
            onclick={() => void openReference(ref)}>
            <span class="file-icon" aria-hidden="true"></span>
            <span class="reference-text"><strong>{ref.path}</strong><small>{ref.project_name || projectName}{ref.line ? ` · L${ref.line}` : ''}</small></span>
            <span class="open-icon" aria-hidden="true">›</span>
          </button>
        {/each}
      {:else if status === 'processing'}
        <p class="empty" aria-busy="true">{$text('embeds.projects.references.waiting')}</p>
      {:else}
        <p class="empty" data-testid="project-reference-empty">{$text('embeds.projects.references.empty')}</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

{#if selected}
  <ChildEmbedOverlay>
    {#if loading}
      <div class="child-state" aria-busy="true">{$text('embeds.projects.references.opening')}</div>
    {:else if error}
      <div class="child-state" role="alert"><p>{error}</p><button type="button" onclick={closeSelected}>{$text('common.close')}</button></div>
    {:else if remote}
      {#if revisionStatus === 'changed'}<p class="revision-notice" data-testid="project-reference-changed" role="status">{$text('embeds.projects.references.changed_since_answer')}</p>{/if}
      <CodeEmbedFullscreen data={{ decodedContent: remote.decodedContent, attrs: remote.attrs, embedData: remote.embedData,
          focusLineRange: selected.line ? { start: selected.line, end: selected.line } : null }}
        embedId={remote.embedId} onClose={closeSelected}
        hasPreviousEmbed={selectedIndex > 0} hasNextEmbed={selectedIndex < refs.length - 1}
        onNavigatePrevious={() => moveSelection(-1)} onNavigateNext={() => moveSelection(1)} />
    {:else if hosted}
      {#if revisionStatus === 'changed'}<p class="revision-notice" data-testid="project-reference-changed" role="status">{$text('embeds.projects.references.changed_since_answer')}</p>{/if}
      {@const registryKey = resolveRegistryKey(hosted.type, hosted.content)}
      {#if registryKey && hasFullscreenComponent(registryKey)}
        {#await loadFullscreenComponent(registryKey) then FullscreenComponent}
          {#if FullscreenComponent}
            <FullscreenComponent data={{ decodedContent: hosted.content, embedData: { type: hosted.type, status: 'finished' },
              focusLineRange: selected.line ? { start: selected.line, end: selected.line } : null }}
              embedId={hosted.embedId} projectId={hosted.projectId} teamId={hosted.teamId} onClose={closeSelected}
              hasPreviousEmbed={selectedIndex > 0} hasNextEmbed={selectedIndex < refs.length - 1}
              onNavigatePrevious={() => moveSelection(-1)} onNavigateNext={() => moveSelection(1)} />
          {:else}<div class="child-state" role="alert">{$text('embeds.projects.references.preview_unavailable')}</div>{/if}
        {/await}
      {:else}<div class="child-state" role="alert">{$text('embeds.projects.references.preview_unavailable')}</div>{/if}
    {/if}
  </ChildEmbedOverlay>
{/if}

<style>
  .reference-list { max-width: 50rem; margin: 0 auto; padding: var(--spacing-6) var(--spacing-4) 7.5rem; display: flex; flex-direction: column; gap: var(--spacing-3); }
  .reference-row { width: 100%; min-height: 4.25rem; display: flex; align-items: center; gap: var(--spacing-3); padding: var(--spacing-3) var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-5); background: var(--color-grey-10); color: var(--color-font-primary); text-align: start; cursor: pointer; }
  .reference-row:hover { background: var(--color-grey-20); }
  .reference-row:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .file-icon { width: 1.5rem; height: 1.5rem; flex: none; background: var(--color-font-secondary); -webkit-mask: var(--icon-url-files) center / contain no-repeat; mask: var(--icon-url-files) center / contain no-repeat; }
  .reference-text { display: flex; flex: 1; flex-direction: column; min-width: 0; gap: var(--spacing-1); }
  strong { font-size: var(--font-size-sm); font-weight: 600; overflow-wrap: anywhere; }
  small { font-size: var(--font-size-xs); color: var(--color-font-secondary); }
  .open-icon { font-size: 1.5rem; color: var(--color-font-secondary); }
  .empty { padding: var(--spacing-8); text-align: center; color: var(--color-font-secondary); }
  .child-state { min-height: 100%; display: grid; place-content: center; justify-items: center; gap: var(--spacing-4); padding: var(--spacing-6); background: var(--color-grey-0); color: var(--color-font-primary); }
  .child-state button { cursor: pointer; color: var(--color-button-primary); }
  .revision-notice { position: absolute; z-index: 110; top: 4.5rem; left: 50%; transform: translateX(-50%); max-width: calc(100% - 2rem); margin: 0; padding: var(--spacing-2) var(--spacing-4); border: 1px solid var(--color-warning); border-radius: var(--radius-3); background: var(--color-grey-0); color: var(--color-font-primary); font-size: var(--font-size-sm); box-shadow: 0 2px 12px #0002; }
  @container fullscreen (max-width: 500px) { .reference-list { padding-inline: var(--spacing-3); } }
</style>
