<script lang="ts">
  import { onMount } from 'svelte';
  import EmbedHeader from './EmbedHeader.svelte';
  import EmbedTopBar from './EmbedTopBar.svelte';
  import { EMBED_METADATA, normalizeEmbedType } from '../../data/embedRegistry.generated';
  import { text } from '@repo/ui';

  interface Props {
    data: { embedType?: string; decodedContent?: unknown; embedData?: unknown; attrs?: unknown } | null;
    failed: boolean;
    onClose: () => void;
  }
  let { data, failed, onClose }: Props = $props();
  const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const firstText = (...values: unknown[]): string => values.find((value): value is string => typeof value === 'string' && value.trim().length > 0)?.trim() ?? '';
  const presentation = $derived.by(() => {
    const content = record(data?.decodedContent), attrs = record(data?.attrs), embed = record(data?.embedData);
    const app = firstText(content.app_id, attrs.appId, attrs.app_id, embed.app_id);
    const skill = firstText(content.skill_id, attrs.skillId, attrs.skill_id, embed.skill_id);
    const type = normalizeEmbedType(firstText(data?.embedType, embed.type));
    const metadata = EMBED_METADATA[app && skill ? `app:${app}:${skill}` : type];
    return {
      appId: metadata?.appId ?? app,
      skillIconName: metadata?.icon ?? '',
      title: firstText(content.query, content.title, content.name, attrs.title, attrs.query, embed.title),
      subtitle: firstText(content.provider, content.source_provider, attrs.provider),
    };
  });
  let showPlaceholder = $state(false);
  onMount(() => {
    const timer = setTimeout(() => { showPlaceholder = true; }, 150);
    return () => clearTimeout(timer);
  });
</script>

<div class="loading-frame" data-testid="embed-fullscreen-loading" aria-busy={!failed}>
  {#if presentation.appId}
    <EmbedHeader {...presentation} staticPresentation />
  {/if}
  <EmbedTopBar {onClose} showShare={false} />
  <span class="status" role="status">{$text(failed ? 'common.detail_load_error' : 'common.loading')}</span>
  {#if failed}
    <p class="error">{$text('common.detail_load_error')}</p>
  {:else if showPlaceholder}
    <div class="placeholder" aria-hidden="true"><div></div><div></div><div></div></div>
  {/if}
</div>

<style>
  .loading-frame { position: relative; width: 100%; height: 100%; overflow: hidden; background: var(--color-grey-20); border-radius: inherit; }
  .status { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
  .placeholder { display: grid; gap: 1rem; padding: 2rem; }
  .placeholder div { height: 1rem; border-radius: .5rem; background: var(--color-grey-30); }
  .placeholder div:last-child { width: 60%; }
  .error { padding: 2rem; color: var(--color-font-secondary); }
</style>
