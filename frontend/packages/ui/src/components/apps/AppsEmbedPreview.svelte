<script lang="ts">
  import { type Component } from 'svelte';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';
  import { getAppsResult, type AppsResultStatus } from '../../services/appsWorkspaceResultsService';
  import GenericAppSkillEmbedPreview from '../embeds/app_skill/GenericAppSkillEmbedPreview.svelte';

  let { embedId, appId, skillId, status = 'finished', teamId, hydrate = false, content, embedType = 'app-skill-use', onFullscreen }: {
    embedId: string; appId: string; skillId: string; status?: AppsResultStatus;
    teamId?: string; hydrate?: boolean; content?: Record<string, unknown>; embedType?: string; onFullscreen: () => void;
  } = $props();
  let preview = $state<{ component: unknown; props: Record<string, unknown> } | null>(null);
  $effect(() => {
    // A processing result can acquire children or finish without remounting.
    const context = { embedId, appId, skillId, status, teamId, hydrate, content, embedType, onFullscreen };
    preview = null;
    let cancelled = false;
    void (async ({ embedId, appId, skillId, status, teamId, hydrate, content, embedType, onFullscreen }) => {
      try {
        // Temporary recommendations never enter the durable saved-embed store.
        if (content) {
          const resolved = await embedPreviewRegistry.resolve({ embedId,
            embedData: { type: embedType, status, app_id: appId, skill_id: skillId },
            decodedContent: content, onFullscreen });
          if (!cancelled) preview = resolved;
          return;
        }
        if (hydrate) await getAppsResult(embedId, teamId);
        const data = await resolveEmbed(embedId);
        if (!data || cancelled) return;
        const resolvedContent = await decodeToonContent(data.content);
        if (!resolvedContent || cancelled) return;
        const resolved = await embedPreviewRegistry.resolve({ embedId, embedData: { ...data, app_id: appId, skill_id: skillId }, decodedContent: resolvedContent, onFullscreen });
        if (!cancelled) preview = resolved;
      } catch { /* The saved parent remains openable with a truthful status. */ }
    })(context);
    return () => { cancelled = true; };
  });
  // Registry components have distinct prop contracts, matching Projects' renderer.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderable = (value: unknown): Component<any> => value as Component<any>;
</script>

{#if preview}
  {@const Preview = renderable(preview.component)}
  <Preview {...preview.props} />
{:else}
  <GenericAppSkillEmbedPreview id={embedId} {appId} {skillId} {status} {onFullscreen} />
{/if}
