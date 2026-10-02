<script lang="ts">
  import { onMount, type Component } from 'svelte';
  import { resolveEmbed, decodeToonContent } from '../../services/embedResolver';
  import { embedPreviewRegistry } from '../../services/embedPreviewRegistry';
  import { getAppsResult, type AppsResultStatus } from '../../services/appsWorkspaceResultsService';
  import GenericAppSkillEmbedPreview from '../embeds/app_skill/GenericAppSkillEmbedPreview.svelte';

  let { embedId, appId, skillId, status = 'finished', teamId, hydrate = false, onFullscreen }: {
    embedId: string; appId: string; skillId: string; status?: AppsResultStatus;
    teamId?: string; hydrate?: boolean; onFullscreen: () => void;
  } = $props();
  let preview = $state<{ component: unknown; props: Record<string, unknown> } | null>(null);
  onMount(() => {
    let cancelled = false;
    void (async () => {
      try {
        if (hydrate) await getAppsResult(embedId, teamId);
        const data = await resolveEmbed(embedId);
        if (!data || cancelled) return;
        const content = await decodeToonContent(data.content);
        if (!content || cancelled) return;
        const resolved = await embedPreviewRegistry.resolve({ embedId, embedData: { ...data, app_id: appId, skill_id: skillId }, decodedContent: content, onFullscreen });
        if (!cancelled) preview = resolved;
      } catch { /* The saved parent remains openable with a truthful status. */ }
    })();
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
