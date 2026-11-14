<!--
  Fullscreen for the plans.specification skill result: the draft Specification
  rendered by the shared reader. "Save to Project" stores it as a new encrypted
  Specification in the Project the source chat belongs to; a chat outside any
  Project shows why saving is unavailable. Nothing is kept in browser storage.
-->
<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { text } from '../../../i18n/translations';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedFullscreenCommonProps, type EmbedFullscreenRawData, type EmbedSourceChatContext } from '../../../types/embedFullscreen';
  import { loadChatProjectIndex, openChatProjectScreen } from '../../../services/chatProjectService';
  import { getProject, type ProjectViewModel } from '../../../services/projectService';
  import { createProjectSpecification } from '../../../services/projectSpecificationService';
  import SpecificationEmbedFullscreen from './SpecificationEmbedFullscreen.svelte';
  import { specificationDocumentFromSkill } from './specificationSkillDocument';

  interface Props extends EmbedFullscreenCommonProps {
    data: EmbedFullscreenRawData;
  }
  let { data, onClose }: Props = $props();
  const document = $derived(specificationDocumentFromSkill(data.decodedContent ?? {}));
  const sourceChat = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);

  let project = $state<ProjectViewModel | null>(null);
  let resolved = $state(false);
  let saving = $state(false);
  let status = $state<{ kind: 'saved' | 'error'; text: string } | null>(null);

  onMount(() => {
    let cancelled = false;
    const chatId = sourceChat?.chatId ?? null;
    void (async () => {
      try {
        const index = chatId ? await loadChatProjectIndex() : [];
        const match = index.find((entry) => entry.chats.some((chat) => chat.chatId === chatId));
        const found = match ? await getProject(match.id) : null;
        if (!cancelled) project = found;
      } catch (error) {
        console.error('[SpecificationSkillEmbedFullscreen] Project lookup failed:', error);
        if (!cancelled) project = null;
      } finally {
        if (!cancelled) resolved = true;
      }
    })();
    return () => { cancelled = true; };
  });

  async function save(): Promise<void> {
    if (!project || saving) return;
    saving = true;
    status = null;
    try {
      await createProjectSpecification(project, document);
      status = { kind: 'saved', text: $text('specifications.save.saved', { values: { project: project.name } }) };
    } catch (error) {
      console.error('[SpecificationSkillEmbedFullscreen] Saving the Specification failed:', error);
      status = { kind: 'error', text: $text('specifications.save.failed') };
    } finally {
      saving = false;
    }
  }

  const notice = $derived(resolved && !project ? `${$text('plan_embeds.skill.draft_not_saved')}. ${$text('specifications.save.no_project')}` : $text('plan_embeds.skill.draft_not_saved'));
</script>

<SpecificationEmbedFullscreen {document} {onClose}
  draftNotice={notice}
  saveLabel={saving ? $text('specifications.save.saving') : $text('plan_embeds.skill.save_to_project')}
  onSaveToProject={project ? () => void save() : undefined}
  saveDisabled={saving}
  saveStatus={status}
  openProjectLabel={$text('specifications.save.open_project')}
  onOpenProject={project ? () => { const id = project?.project_id; if (id) openChatProjectScreen(id); } : undefined} />
