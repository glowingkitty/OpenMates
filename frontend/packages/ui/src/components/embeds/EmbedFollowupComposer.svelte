<!-- figma-visual-proof: not-required. The shared result composer is reused inside the fullscreen shell. -->
<script lang="ts">
  import { getContext, onDestroy } from 'svelte';
  import AppsRequestComposer from '../apps/AppsRequestComposer.svelte';
  import { text } from '../../i18n/translations';
  import { notificationStore } from '@repo/ui';
  import { normalizeEmbedType } from '../../data/embedRegistry.generated';
  import { EMBED_SOURCE_CHAT_CONTEXT, type EmbedSourceChatContext } from '../../types/embedFullscreen';
  import { APPS_RESULTS_ACTIONS_CONTEXT, type AppsResultsActionsContext } from '../../services/appsWorkspaceContext';
  import { captureAppsWorkspaceHandoffGuard, queueAppsWorkspaceChatHandoff } from '../../services/appsWorkspaceChatHandoffService';

  let { appId, skillId, embedId, submit, externalSubmitting = false, onClose }: {
    appId: string; skillId?: string; embedId?: string;
    submit?: (value: string, attachments: File[]) => Promise<boolean>;
    externalSubmitting?: boolean; onClose: () => void;
  } = $props();

  const source = getContext<EmbedSourceChatContext | undefined>(EMBED_SOURCE_CHAT_CONTEXT);
  const actions = getContext<AppsResultsActionsContext | undefined>(APPS_RESULTS_ACTIONS_CONTEXT);
  const ownerCurrent = captureAppsWorkspaceHandoffGuard();
  const canSend = $derived(!!submit || !!embedId && (source?.isReadOnly !== true || !!actions));
  let sending = $state(false);
  let alive = true;
  onDestroy(() => { alive = false; });

  async function send(value: string, attachments: File[]): Promise<boolean> {
    if (submit) return submit(value, attachments);
    const id = embedId;
    if (!id || !canSend || sending || !ownerCurrent()) return false;
    const chatId = source?.isReadOnly === false ? source.chatId ?? undefined : undefined;
    const lookupChatId = source?.lookupChatId ?? chatId;
    const isCurrent = () => alive && id === embedId && ownerCurrent();
    sending = true;
    try {
      const context = { chat_id: chatId, embed_id: id };
      if (actions) return (await actions.onSubmit(value, attachments, context)) !== false && isCurrent();
      const { resolveEmbed } = await import('../../services/embedResolver');
      const embed = await resolveEmbed(id, { chatId: lookupChatId ?? null });
      if (!isCurrent()) return false;
      if (!embed?.type) throw new Error('followup_embed_unavailable');
      const request = { text: value, attachments, context,
        embedReference: { embedId: id, type: normalizeEmbedType(embed.type), appId, skillId } };
      onClose();
      await queueAppsWorkspaceChatHandoff(request);
      return true;
    } catch {
      if (isCurrent()) notificationStore.error($text('apps_workspace.request_error'));
      return false;
    } finally {
      if (alive) sending = false;
    }
  }
</script>

<div class="followup" data-testid="embed-followup-composer">
  {#key embedId}
    <AppsRequestComposer presentation="embed" {appId} disabled={!canSend} submitting={sending || externalSubmitting}
      placeholder={$text('apps_workspace.followup_placeholder')} onSubmit={send} />
  {/key}
</div>

<style>
  .followup { width: min(100%, 58rem); margin-inline: auto; }
</style>
