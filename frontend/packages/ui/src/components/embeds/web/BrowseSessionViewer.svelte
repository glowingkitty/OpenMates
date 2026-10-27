<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '../../../i18n/translations';
  import { BrowseHttpError, type BrowseClient, type BrowseCommand, type BrowseInput, type BrowseSession } from '../../../services/webBrowseService';
  import { browseStatusKey } from './browseContent';
  interface Props {
    sessionId: string;
    client: BrowseClient;
    onContinue: (session: BrowseSession) => Promise<void>;
    savedFrame?: string;
  }
  let { sessionId, client, onContinue, savedFrame = '' }: Props = $props();
  const inputId = $props.id();
  let session = $state<BrowseSession | null>(null);
  let frame = $state('');
  let busy = $state(false);
  let error = $state('');
  let consentOrigin = $state('');
  let input = $state('');
  let ending = $state(false);
  let revision = 0;
  let controller: AbortController;
  let live = true;
  let manual = $derived(session?.status === 'user' && !busy && !consentOrigin && !ending);
  let terminal = $derived(session?.status === 'closed' || session?.status === 'expired');
  function clearFrame() {
    if (frame) URL.revokeObjectURL(frame);
    frame = '';
  }
  function failure(cause: unknown) {
    if (!live || controller.signal.aborted) return;
    if (cause instanceof BrowseHttpError && cause.status === 410) {
      session = session ? { ...session, status: 'expired' } : null;
      ending = true; clearFrame(); input = ''; consentOrigin = '';
      error = 'embeds.browse.expired';
    } else if (cause instanceof BrowseHttpError && [401, 403, 404].includes(cause.status)) {
      ending = true; clearFrame(); input = ''; consentOrigin = '';
      session = null;
      error = 'embeds.browse.unavailable';
    } else error = 'embeds.browse.connection_error';
  }
  async function refreshFrame() {
    const current = revision;
    try {
      const blob = await client.frame(sessionId, controller.signal);
      if (!live || current !== revision || controller.signal.aborted) return;
      clearFrame(); frame = URL.createObjectURL(blob);
    } catch (cause) {
      // A pending first frame is expected, not an access grant or resume request.
      if (cause instanceof BrowseHttpError && [404, 409].includes(cause.status)) return;
      failure(cause);
    }
  }
  async function command(value: BrowseCommand) {
    if (busy || ending || terminal) return;
    busy = true; error = ''; revision++;
    try {
      const next = await client.control(sessionId, value, controller.signal);
      if (!live || controller.signal.aborted) return;
      session = next;
      if (next.status !== 'user') input = '';
      consentOrigin = next.needs_sign_in_consent ? next.sign_in_origin || '' : '';
      if (value.operation === 'close') { ending = true; input = ''; clearFrame(); }
      else if (value.operation === 'resume') await onContinue(next);
      else await refreshFrame();
    } catch (cause) { failure(cause); }
    finally { if (live) busy = false; }
  }
  function send(action: BrowseInput) { if (manual) void command({ operation: 'input', action }); }
  function click(event: MouseEvent) {
    if (!manual) return;
    // Keyboard activation sends Enter to the focused website element; it must
    // never turn the browser-generated (0,0) click into a remote pointer action.
    if (event.detail === 0) { send({ kind: 'key', key: 'Enter' }); return; }
    const image = event.currentTarget as HTMLButtonElement;
    const rect = image.getBoundingClientRect();
    // The runtime viewport is fixed at 1280x800. The image uses its natural
    // aspect ratio, so coordinates never include letterboxing or toolbar space.
    if (!rect.width || !rect.height) return;
    send({ kind: 'click', x: Math.min(1279, Math.max(0, (event.clientX - rect.left) * 1280 / rect.width)),
      y: Math.min(799, Math.max(0, (event.clientY - rect.top) * 800 / rect.height)) });
  }
  function type() {
    if (!manual || !input) return;
    const value = input; input = '';
    send({ kind: 'type', text: value });
  }
  onMount(() => {
    live = true; controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (!live || ending || terminal) return;
      if (!document.hidden && !busy) {
        const current = revision;
        try {
          const next = await client.state(sessionId, controller.signal);
          if (live && current === revision && !controller.signal.aborted) {
            session = next;
            if (next.status !== 'user') { input = ''; consentOrigin = ''; }
            if (!terminal) await refreshFrame();
          }
        } catch (cause) { failure(cause); }
      }
      // At most 40 requests/minute per route. Observing never extends idle time.
      if (live && !ending && !terminal) timer = setTimeout(() => { void poll(); }, 1500);
    }
    void poll();
    return () => { live = false; controller.abort(); clearTimeout(timer); clearFrame(); input = ''; };
  });
</script>

<section class="viewer" data-testid="browse-session-viewer" aria-label={$text('embeds.browse.title')}>
  <div class="status" role="status">
    <strong>{$text(browseStatusKey(session?.status || (ending ? (error === 'embeds.browse.expired' ? 'expired' : 'unavailable') : 'processing')))}</strong>
    {#if session}<span>{$text('embeds.browse.credits', { values: { used: String(session.accrued_credits), limit: String(session.max_credits) } })}</span>{/if}
  </div>
  {#if error}<p role="alert">{$text(error)}</p>{/if}
  {#if session && !terminal && !ending}
    <div class="controls">
      {#if session.status !== 'user'}
        <button disabled={busy} onclick={() => command({ operation: 'take_control' })}>{$text('embeds.browse.take_control')}</button>
      {:else}
        <button class="primary" disabled={busy || !!consentOrigin} onclick={() => command({ operation: 'resume' })}>{$text('embeds.browse.continue')}</button>
      {/if}
      <button disabled={busy || session.status === 'paused'} onclick={() => command({ operation: 'stop' })}>{$text('embeds.browse.pause')}</button>
      <button disabled={busy} onclick={() => command({ operation: 'close' })}>{$text('embeds.browse.close')}</button>
    </div>
  {/if}
  {#if consentOrigin && session}
    <div class="notice" role="region" aria-label={$text('embeds.browse.sign_in_title')}>
      <strong>{$text('embeds.browse.sign_in_title')}</strong>
      <p>{consentOrigin}</p>
      <p>{$text('embeds.browse.sign_in_notice')}</p>
      <div class="controls">
        <button class="primary" disabled={busy} onclick={() => command({ operation: 'sign_in', sign_in_origin: consentOrigin })}>{$text('embeds.browse.sign_in_confirm')}</button>
        <button disabled={busy} onclick={() => { consentOrigin = ''; }}>{$text('common.cancel')}</button>
      </div>
    </div>
  {/if}
  <div class="screen" class:manual>
    {#if frame || savedFrame}
      <button class="viewport" type="button" disabled={!manual} onclick={click}
        aria-label={$text(frame ? 'embeds.browse.live_frame' : 'embeds.browse.saved_frame')}>
        <img src={frame || savedFrame} alt={$text(frame ? 'embeds.browse.live_frame' : 'embeds.browse.saved_frame')} draggable="false" data-testid="browse-frame" />
      </button>
    {:else}<p>{$text('embeds.browse.waiting_frame')}</p>{/if}
  </div>
  {#if session?.status === 'user' && !ending}
    <p class="hint">{$text('embeds.browse.manual_hint')}</p>
    <form onsubmit={(event) => { event.preventDefault(); type(); }}>
      <label for={inputId}>{$text('embeds.browse.text_input')}</label>
      <div class="input-row">
        <input id={inputId} type="password" bind:value={input} maxlength="2000" autocomplete="off" disabled={!manual} />
        <button type="submit" disabled={!manual || !input}>{$text('embeds.browse.send_text')}</button>
      </div>
    </form>
    <div class="controls keys">
      {#each ['Tab', 'Shift+Tab', 'Enter', 'Backspace', 'Escape', 'Control+A'] as key}
        <button disabled={!manual} onclick={() => send({ kind: 'key', key: key as 'Tab' })}>{key}</button>
      {/each}
      <button disabled={!manual} onclick={() => send({ kind: 'scroll', delta: -600 })}>{$text('embeds.browse.scroll_up')}</button>
      <button disabled={!manual} onclick={() => send({ kind: 'scroll', delta: 600 })}>{$text('embeds.browse.scroll_down')}</button>
    </div>
  {:else if session && !ending}<p class="hint">{$text(session.status === 'paused' ? 'embeds.browse.paused_hint' : 'embeds.browse.watch_hint')}</p>{/if}
</section>

<style>
  .viewer { width: 100%; min-width: 0; display: flex; flex-direction: column; gap: var(--spacing-6); color: var(--color-font-primary); }
  .status, .controls, .input-row { display: flex; flex-wrap: wrap; gap: var(--spacing-4); align-items: center; }
  .status { justify-content: space-between; }
  .status span, .hint { color: var(--color-font-secondary); font-size: .875rem; }
  p { margin: 0; overflow-wrap: anywhere; }
  button { min-height: 40px; padding: var(--spacing-4) var(--spacing-8); border: 1px solid var(--color-grey-30); border-radius: var(--radius-full); font: inherit; font-size: .875rem; background: var(--color-grey-10); color: var(--color-font-primary); cursor: pointer; }
  button:hover:not(:disabled) { background: var(--color-grey-20); }
  /* Constant white contrast on the brand orange, matching EmbedHeaderCtaButton in both themes. */
  button.primary { background: var(--color-button-primary); color: white; }
  button:disabled { opacity: .5; cursor: default; }
  button:focus-visible, input:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .screen { border-radius: var(--radius-4); overflow: hidden; background: var(--color-grey-10); min-height: 10rem; display: grid; place-items: center; }
  .screen img { display: block; width: 100%; height: auto; user-select: none; }
  .screen button.viewport { display: block; width: 100%; height: auto; min-height: 0; min-width: 0; padding: 0; border: 0; border-radius: 0; opacity: 1; background: transparent; line-height: 0; }
  .screen button.viewport:focus-visible { outline-offset: -3px; }
  .manual img { cursor: crosshair; }
  .screen p { padding: var(--spacing-8); }
  .notice { display: flex; flex-direction: column; gap: var(--spacing-6); border: 1px solid var(--color-warning); background: var(--color-warning-bg); padding: var(--spacing-8); border-radius: var(--radius-4); }
  form { display: flex; flex-direction: column; gap: var(--spacing-3); }
  label { font-size: .875rem; }
  input { min-width: 0; flex: 1; min-height: 44px; padding: var(--spacing-4); border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); background: var(--color-grey-0); color: var(--color-font-primary); font-size: 1rem; }
  @container fullscreen (max-width: 500px) { .controls button { flex-grow: 1; } .input-row { flex-wrap: nowrap; } }
</style>
