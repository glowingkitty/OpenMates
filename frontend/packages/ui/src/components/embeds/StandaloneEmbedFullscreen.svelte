<script lang="ts">
  import { onMount, setContext } from 'svelte';
  import AppsResultFullscreen from '../apps/AppsResultFullscreen.svelte';
  import { text } from '../../i18n/translations';
  import { activeTeamId } from '../../stores/teamStore';
  import { EMBED_FULLSCREEN_LIFETIME_CONTEXT, type EmbedFullscreenLifetimeContext } from '../../types/embedFullscreen';

  let { embedId, appId, onClose }: {
    embedId: string;
    appId: string;
    onClose: () => void;
  } = $props();
  let dialog: HTMLDialogElement;
  setContext<EmbedFullscreenLifetimeContext>(EMBED_FULLSCREEN_LIFETIME_CONTEXT, { closeOnChatSelection: false });

  // The top layer escapes Settings' transformed/clipped panel and makes the
  // underlying workspace inert, without navigating away or mounting a chat.
  onMount(() => { dialog.showModal(); });
</script>

<dialog bind:this={dialog} data-testid="standalone-embed-fullscreen" aria-label={$text('common.details')}
  oncancel={(event) => { event.preventDefault(); onClose(); }}>
  <AppsResultFullscreen {embedId} {appId} {onClose} teamId={$activeTeamId ?? undefined} hydrateGraph={false} />
</dialog>

<style>
  dialog {
    position: fixed;
    inset: 0;
    width: 100%;
    height: 100dvh;
    max-width: none;
    max-height: none;
    margin: 0;
    padding: 0;
    border: 0;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
  }
</style>
