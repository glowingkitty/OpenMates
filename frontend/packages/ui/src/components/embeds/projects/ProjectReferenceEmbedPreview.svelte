<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { projectFileReferences, stringField } from './projectReferenceData';

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
    : refs.length ? $text('embeds.projects.references.count', { values: { count: refs.length } })
      : $text('embeds.projects.references.empty'));
</script>

<UnifiedEmbedPreview
  {id} appId="projects" {skillId} skillIconName={skillId === 'read' ? 'project' : 'search'}
  appIconName="project" {skillName}
  status={currentStatus} {isMobile} {onFullscreen} showStatus={true} showSkillIcon={true}
  onEmbedDataUpdated={(update) => { currentContent = update.decodedContent; currentStatus = update.status as Props['status']; }}
>
  {#snippet details()}
    <div class="reference-preview" data-testid="project-reference-preview">
      <strong>{title}</strong>
      <span>{summary}</span>
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .reference-preview { display: flex; width: 100%; min-width: 0; flex-direction: column; justify-content: center; gap: var(--spacing-3); }
  strong { overflow: hidden; color: var(--color-font-primary); font-size: var(--font-size-sm); font-weight: 600; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; word-break: break-word; }
  span { color: var(--color-font-secondary); font-size: var(--font-size-xs); }
</style>
