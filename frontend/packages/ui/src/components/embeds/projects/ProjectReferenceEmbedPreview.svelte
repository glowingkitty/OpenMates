<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { projectFileReferences, stringField } from './projectReferenceData';
  import { buildProjectReferenceTree } from './projectReferenceTree';

  interface Props {
    id: string;
    content?: Record<string, unknown>;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    skillId?: 'search' | 'read';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let { id, content = {}, status, skillId = 'search', isMobile = false, onFullscreen }: Props = $props();
  let currentContent = $state<Record<string, unknown>>({});
  let currentStatus = $state<Props['status']>('processing');
  $effect(() => { currentContent = content; currentStatus = status; });
  const query = $derived(stringField(currentContent.query) || $text('embeds.projects.references.files_fallback'));
  const searchTarget = $derived(stringField(currentContent.search_target));
  const skillName = $derived(skillId === 'search' && (searchTarget === 'files' || searchTarget === 'content')
    ? $text(`app_skills.projects.skills.search_${searchTarget === 'files' ? 'files' : 'text'}`)
    : $text(`app_skills.projects.skills.${skillId}`));
  const refs = $derived(projectFileReferences(currentContent));
  const projectName = $derived(refs[0]?.project_name || stringField(currentContent.project_name) || '');
  const title = $derived(projectName
    ? $text('embeds.projects.references.query_in_project', { values: { query, project: projectName } })
    : $text('embeds.projects.references.query_only', { values: { query } }));
  const summary = $derived(currentStatus === 'processing'
    ? $text('embeds.projects.references.waiting')
    : refs.length ? $text(refs.length === 1 ? 'embeds.projects.references.count_singular' : 'embeds.projects.references.count', { values: { count: refs.length } })
      : $text('embeds.projects.references.empty'));
  const tree = $derived(buildProjectReferenceTree(refs.map((ref) => ref.path)));
  const showTree = $derived(skillId === 'read' && currentStatus !== 'processing' && refs.length > 0);
</script>

<UnifiedEmbedPreview
  {id} appId="projects" {skillId} skillIconName={skillId === 'read' ? 'visible' : 'search'}
  appIconName="project" {skillName}
  status={currentStatus} {isMobile} {onFullscreen} showStatus={true} showSkillIcon={true}
  onEmbedDataUpdated={(update) => { currentContent = update.decodedContent; currentStatus = update.status as Props['status']; }}
>
  {#snippet details()}
    {#if showTree}
      <div class="reference-preview" data-testid="project-reference-preview">
        <strong data-testid="project-reference-project">{projectName || title}</strong>
        <div class="tree" data-testid="project-reference-tree">
          {#each tree.rows as row}
            <span class="tree-row" data-testid="project-reference-row" style:padding-inline-start={`${row.depth * 0.9}rem`}>
              <span class="tree-icon" class:folder={row.kind === 'folder'} aria-hidden="true"></span>
              <span class="tree-name">{row.name}</span>
            </span>
          {/each}
          {#if tree.hiddenFiles > 0}
            <span class="tree-more" data-testid="project-reference-more">{$text('embeds.projects.references.more', { values: { count: tree.hiddenFiles } })}</span>
          {/if}
        </div>
      </div>
    {:else}
      <div class="reference-preview" data-testid="project-reference-preview">
        <strong>{title}</strong>
        <span>{summary}</span>
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .reference-preview { display: flex; width: 100%; min-width: 0; flex-direction: column; justify-content: center; gap: var(--spacing-3); }
  strong { overflow: hidden; color: var(--color-font-primary); font-size: var(--font-size-sm); font-weight: 600; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; word-break: break-word; }
  .tree { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
  .tree-row { display: flex; min-width: 0; align-items: center; gap: var(--spacing-2); color: var(--color-font-secondary); font-size: var(--font-size-xs); }
  .tree-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .tree-icon { display: inline-block; flex: 0 0 auto; width: 0.9rem; height: 0.9rem; background: currentColor; -webkit-mask: var(--icon-url-docs, var(--icon-url-files)) center / contain no-repeat; mask: var(--icon-url-docs, var(--icon-url-files)) center / contain no-repeat; }
  .tree-icon.folder { -webkit-mask: var(--icon-url-files) center / contain no-repeat; mask: var(--icon-url-files) center / contain no-repeat; }
  .tree-more { color: var(--color-font-secondary); font-size: var(--font-size-xs); font-weight: 700; }
  span { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
</style>
