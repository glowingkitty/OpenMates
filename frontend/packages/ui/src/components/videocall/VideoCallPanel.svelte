<!--
  Standalone call surface shared by the route and bare component preview.
  The controller owns live media and usage; this component owns playback layout.
  Detached local video decoding supplies bounded continuation frames to Gemini.
  Mobile visuals fill the viewport while transcript controls stay reachable.
-->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { text } from '../../i18n/translations';
  import { type CallClip, type CallControllerLike, type CallState, initialCallState } from './callController';

  interface Props { controller: CallControllerLike; onLeave: () => void }
  let { controller, onLeave }: Props = $props();
  let state = $state<CallState>({ ...initialCallState });
  let drawerOpen = $state(false);
  let activeClipId = $state<string | null>(null);
  let lastPlayedClipId = $state<string | null>(null);
  let visibleVideo = $state<HTMLVideoElement | null>(null);
  let playbackBlocked = $state(false);
  let heldFrame = $state<string | null>(null);
  let drawerCloseButton = $state<HTMLButtonElement | null>(null);
  let drawerToggleButton = $state<HTMLButtonElement | null>(null);
  let frameTimer: ReturnType<typeof setInterval> | null = null;
  const continuationSent = new Set<string>();
  const decoders = new Set<AbortController>();
  const fallbackVideoRate = Date.now() < Date.UTC(2026, 9, 16) ? 1080 : 1800;
  let captureEpoch = 0;
  let activeClip = $derived(state.clips.find((clip) => clip.id === activeClipId) ?? null);
  let nextClip = $derived(state.clips[state.clips.findIndex((clip) => clip.id === activeClip?.id) + 1] ?? null);
  let audioRate = $derived(state.usage?.audio_credits_per_minute ?? 27.6);
  let videoRate = $derived(state.usage?.video_credits_per_minute ?? fallbackVideoRate);
  let activeRate = $derived(audioRate + (state.videoStatus === 'off' ? 0 : videoRate));
  let remaining = $derived(Math.max(0, state.maxDurationSeconds - state.elapsedSeconds));

  function takeFrame(video: HTMLVideoElement): string | null {
    if (!video.videoWidth || !video.videoHeight || video.readyState < 2) return null;
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 512 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.65).split(',', 2)[1] ?? null;
  }

  function waitForVideo(video: HTMLVideoElement, eventName: string, signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timeout);
        video.removeEventListener(eventName, succeed);
        video.removeEventListener('error', fail);
        signal.removeEventListener('abort', abort);
      };
      const succeed = () => { cleanup(); resolve(); };
      const fail = () => { cleanup(); reject(new Error('Video frame unavailable')); };
      const abort = () => { cleanup(); reject(new Error('Video frame cancelled')); };
      const timeout = setTimeout(fail, 5_000);
      video.addEventListener(eventName, succeed, { once: true });
      video.addEventListener('error', fail, { once: true });
      signal.addEventListener('abort', abort, { once: true });
      if (signal.aborted) abort();
    });
  }

  function cancelDecoders(): void {
    captureEpoch += 1;
    for (const decoder of decoders) decoder.abort();
    decoders.clear();
  }

  async function sendContinuation(clip: CallClip): Promise<void> {
    const epoch = captureEpoch;
    const abort = new AbortController();
    decoders.add(abort);
    const video = document.createElement('video');
    video.preload = 'auto';
    video.muted = true;
    try {
      const metadata = waitForVideo(video, 'loadedmetadata', abort.signal);
      video.src = clip.url;
      await metadata;
      if (epoch !== captureEpoch) return;
      const seeked = waitForVideo(video, 'seeked', abort.signal);
      video.currentTime = Math.max(0, (Number.isFinite(video.duration) ? video.duration : clip.durationSeconds) - 0.08);
      await seeked;
      const frame = takeFrame(video);
      if (frame && epoch === captureEpoch) controller.sendContinuationFrame(clip.id, frame);
    } catch { /* A failed snapshot cannot stop voice or video playback. */ }
    finally { decoders.delete(abort); video.removeAttribute('src'); video.load(); }
  }

  function onClipEnded(): void {
    const index = state.clips.findIndex((clip) => clip.id === activeClip?.id);
    const following = state.clips[index + 1];
    if (visibleVideo) {
      const frame = takeFrame(visibleVideo);
      if (frame) heldFrame = frame;
    }
    lastPlayedClipId = activeClip?.id ?? null;
    if (following) activeClipId = following.id;
    else activeClipId = null;
  }

  onMount(() => {
    const unsubscribe = controller.subscribe((value) => {
      state = value;
      if (!value.clips.length) {
        cancelDecoders(); continuationSent.clear();
        activeClipId = null; lastPlayedClipId = null; heldFrame = null; playbackBlocked = false;
      }
      else if (!activeClipId || !value.clips.some((clip) => clip.id === activeClipId)) {
        const playedIndex = value.clips.findIndex((clip) => clip.id === lastPlayedClipId);
        activeClipId = value.clips[playedIndex + 1]?.id ?? (playedIndex < 0 ? value.clips[0].id : null);
      }
      for (const clip of value.clips) {
        if (!continuationSent.has(clip.id)) {
          continuationSent.add(clip.id);
          void sendContinuation(clip);
        }
      }
    });
    frameTimer = setInterval(() => {
      if (state.status !== 'live' || state.videoStatus !== 'playing' || !visibleVideo) return;
      const frame = takeFrame(visibleVideo);
      if (frame) controller.sendVideoFrame(frame);
    }, 1000);
    return () => {
      unsubscribe();
      if (frameTimer) clearInterval(frameTimer);
      cancelDecoders();
      controller.dispose();
    };
  });

  function leave(): void { controller.hangup(); onLeave(); }
  async function openDrawer(): Promise<void> { drawerOpen = true; await tick(); drawerCloseButton?.focus(); }
  async function closeDrawer(): Promise<void> { drawerOpen = false; await tick(); drawerToggleButton?.focus(); }
  function drawerKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') { event.preventDefault(); void closeDrawer(); }
    if (event.key !== 'Tab') return;
    const elements = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button,summary,[href]')).filter((element) => element.offsetParent !== null);
    if (!elements.length) return;
    if (event.shiftKey && document.activeElement === elements[0]) { event.preventDefault(); elements.at(-1)?.focus(); }
    else if (!event.shiftKey && document.activeElement === elements.at(-1)) { event.preventDefault(); elements[0].focus(); }
  }
  async function resumeVideo(): Promise<void> {
    try { await visibleVideo?.play(); playbackBlocked = false; }
    catch { playbackBlocked = true; }
  }
  function seconds(value: number): string { return `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, '0')}`; }
  function number(value: number): string { return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value); }
  function roundedRate(perMinute: number): string { return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(perMinute); }
</script>

<svelte:head><title>Video call experiment · OpenMates</title></svelte:head>

<main class="call-page" class:visual-active={state.videoStatus !== 'off'} data-testid="video-call-panel">
  <header class="top-bar" data-testid="call-top-bar">
    <div class="brand"><span class="brand-mark" aria-hidden="true">●</span><span>OpenMates</span><span class="experiment-tag">{$text('videocall.experiment')}</span></div>
    <button class="plain-button exit" type="button" onclick={leave} data-testid="call-exit">{$text('videocall.close')}</button>
  </header>

  <div class="heading" data-testid="call-heading">
    <div><p class="eyebrow">{$text('videocall.provider')}</p><h1>{$text('videocall.title')}</h1><p class="subtitle">{$text('videocall.subtitle')}</p></div>
    <div class="timer" data-testid="call-timer"><span>{$text('videocall.elapsed', { values: { time: seconds(state.elapsedSeconds) } })}</span><span>{$text('videocall.remaining', { values: { time: seconds(remaining) } })}</span></div>
  </div>
  {#if state.error && state.status === 'live'}<p class="notice" role="status">{state.error}</p>{/if}

  <div class="call-layout">
    <section class="stage" aria-label={$text('videocall.visual')} data-testid="video-call-stage">
      {#if activeClip && state.videoStatus === 'playing'}
        {#key activeClip.id}<video bind:this={visibleVideo} src={activeClip.url} autoplay playsinline preload="auto" volume={state.userSpeaking || state.modelSpeaking ? 0.04 : 0.2} onloadeddata={() => void resumeVideo()} onended={onClipEnded} aria-label="Generated visual" data-testid="call-video"><track kind="captions" src="data:text/vtt,WEBVTT" srclang="en" label="No speech" /></video>{/key}
        {#if nextClip}<video src={nextClip.url} preload="auto" muted class="preload" aria-hidden="true"><track kind="captions" src="data:text/vtt,WEBVTT" srclang="en" label="No speech" /></video>{/if}
        <span class="visual-badge">{$text('videocall.generated_visual')}</span>
        {#if state.videoPending}<span class="pending-badge">{$text('videocall.next_visual')}</span>{/if}
        {#if playbackBlocked}<button class="resume-button" type="button" onclick={() => void resumeVideo()} data-testid="call-resume-video">{$text('videocall.play_visual')}</button>{/if}
      {:else if heldFrame && state.visualsAllowed}
        <img class="held-frame" src={`data:image/jpeg;base64,${heldFrame}`} alt={$text('videocall.waiting_visual')} />
        <span class="visual-badge">{$text('videocall.waiting_visual')}</span>
      {:else}
        <div class="portrait" aria-label="OpenMates AI call portrait"><span class="orb" aria-hidden="true">✦</span><span>{state.videoStatus === 'queued' ? $text('videocall.creating_visual') : $text('videocall.voice_call')}</span></div>
      {/if}
      <div class="stage-controls">
        {#if state.status === 'live' || state.status === 'connecting'}
          {#if state.visualsAllowed}
            <button class="secondary-button" type="button" onclick={() => controller.stopVisuals()} data-testid="call-stop-video">{$text('videocall.stop_video')}</button>
          {:else}
            <button class="secondary-button" type="button" onclick={() => controller.allowVisuals()} data-testid="call-allow-video">{$text('videocall.allow_video')}</button>
          {/if}
          <button class="danger-button" type="button" onclick={() => controller.hangup()} data-testid="call-hangup">{$text('videocall.hangup')}</button>
        {/if}
        <button bind:this={drawerToggleButton} class="secondary-button mobile-chat" type="button" onclick={() => void openDrawer()} aria-expanded={drawerOpen} data-testid="call-chat-toggle">{$text('videocall.transcript')}</button>
      </div>
    </section>

    <aside class="context-panel" class:drawer-open={drawerOpen} role={drawerOpen ? 'dialog' : undefined} aria-modal={drawerOpen ? 'true' : undefined} aria-label={$text('videocall.conversation')} onkeydown={drawerKeydown} data-testid="call-context-panel">
      <div class="context-heading"><h2>{$text('videocall.conversation')}</h2><div class="drawer-actions">{#if state.status === 'live' || state.status === 'connecting'}<button class="danger-button drawer-hangup" type="button" onclick={() => controller.hangup()} data-testid="call-drawer-hangup">{$text('videocall.hangup')}</button>{/if}<button bind:this={drawerCloseButton} class="plain-button drawer-close" type="button" onclick={() => void closeDrawer()}>{$text('videocall.close_transcript')}</button></div></div>
      <div class="transcript" role="log" aria-live="polite" data-testid="call-transcript">
        {#if state.transcripts.length === 0}<p class="empty">{$text('videocall.transcript_empty')}</p>{/if}
        {#each state.transcripts as entry}
          <p class="line"><strong>{entry.role === 'user' ? $text('videocall.you') : 'Gemini'}</strong><span>{entry.text}</span></p>
        {/each}
      </div>
      <div class="usage" data-testid="call-usage">
        <h3>{$text('videocall.live_cost')}</h3>
        <div class="rate" data-testid="call-active-rate"><span>{state.videoStatus === 'off' ? $text('videocall.audio_only') : $text('videocall.audio_video')}</span><strong>{$text('videocall.credits_per_minute', { values: { count: roundedRate(activeRate) } })}</strong></div>
        <p class="billing-note" data-testid="call-billing-note">{$text('videocall.billing_note')}</p>
        <div class="usage-row"><span>{$text('videocall.credits_accrued')}</span><strong>{number(state.usage?.credits_accrued ?? 0)}</strong></div>
        <div class="usage-row"><span>{$text('videocall.credits_charged')}</span><strong>{number(state.usage?.credits_charged ?? 0)}</strong></div>
        <div class="usage-row"><span>{$text('videocall.gemini_audio')}</span><span>{$text('videocall.credits', { values: { count: number(state.usage?.audio_credits ?? 0) } })}</span></div>
        <div class="usage-row"><span>{$text('videocall.generated_visuals')}</span><span>{$text('videocall.credits', { values: { count: number(state.usage?.video_credits ?? 0) } })} · {number(state.usage?.h3_generated_seconds ?? 0)}s</span></div>
        <details><summary>{$text('videocall.token_usage')}</summary><p>{$text('videocall.input')} {number(state.usage?.gemini_input_tokens ?? 0)} · {$text('videocall.output')} {number(state.usage?.gemini_output_tokens ?? 0)} · {$text('videocall.billed_context')} {number(state.usage?.gemini_context_tokens ?? 0)}</p><p>{$text('videocall.audio_rate')} {$text('videocall.credits_per_minute', { values: { count: roundedRate(audioRate) } })} · {$text('videocall.video_rate')} {$text('videocall.credits_per_minute', { values: { count: roundedRate(videoRate) } })}</p></details>
      </div>
    </aside>
  </div>

  {#if state.status === 'idle' || state.status === 'ended' || state.status === 'error'}
    <div class="start-area">
      {#if state.status === 'ended'}<p role="status">{$text('videocall.ended')}</p>{/if}
      {#if state.error}<p class="error" role="alert">{state.error}</p>{/if}
      <button class="start-button" type="button" onclick={() => void controller.start()} data-testid="call-start">{state.status === 'idle' ? $text('videocall.start') : $text('videocall.restart')}</button>
      <p class="privacy">{$text('videocall.privacy')}</p>
    </div>
  {:else if state.status === 'connecting'}
    <p class="connection" role="status">{$text('videocall.connecting')}</p>
  {/if}
</main>

<style>
  .call-page { box-sizing: border-box; min-height: 100dvh; padding: var(--spacing-8); background: var(--color-grey-10); color: var(--color-font-primary); font-family: 'Lexend Deca Variable', sans-serif; }
  .top-bar,.heading,.call-layout,.start-area { max-width: 1400px; margin-inline: auto; }
  .top-bar,.heading,.brand,.timer,.stage-controls,.context-heading,.usage-row,.rate { display:flex; align-items:center; justify-content:space-between; gap:var(--spacing-8); }
  .top-bar { min-height:48px; }.brand { justify-content:flex-start; font-weight:700; }.brand-mark { color:var(--color-button-primary); font-size:1.5rem; }.experiment-tag { border-radius:var(--radius-full); padding:var(--spacing-2) var(--spacing-6); background:var(--color-grey-20); font-size:var(--font-size-xxs); font-weight:500; }
  .heading { padding-block:var(--spacing-12); align-items:end; }.eyebrow { color:var(--color-primary); font-size:var(--font-size-small); margin:0 0 var(--spacing-2); }h1 { font-size:var(--font-size-h2); margin:0; }.subtitle { color:var(--color-font-tertiary); margin:var(--spacing-4) 0 0; line-height:1.5; }.timer { flex-direction:column; align-items:flex-end; gap:0; font-size:var(--font-size-small); font-variant-numeric:tabular-nums; }.timer span:last-child { color:var(--color-font-tertiary); }
  .call-layout { display:grid; grid-template-columns:minmax(0, 1.8fr) minmax(280px, 1fr); gap:var(--spacing-8); min-height: min(70dvh, 700px); }.stage,.context-panel { border-radius:var(--radius-6); overflow:hidden; background:var(--color-grey-0); box-shadow:var(--shadow-sm); }.stage { position:relative; display:grid; place-items:center; min-height:400px; background:var(--color-grey-20); }.stage video:not(.preload) { width:100%; height:100%; object-fit:contain; position:absolute; inset:0; background:var(--color-grey-20); }.preload { display:none; }.portrait { display:flex; flex-direction:column; align-items:center; gap:var(--spacing-8); font-size:var(--font-size-h3); }.orb { display:grid; place-items:center; width:140px; height:140px; border-radius:50%; background:var(--gradient-primary); color:var(--color-grey-0); font-size:4rem; box-shadow:var(--shadow-lg); }.visual-badge { position:absolute; inset-block-start:var(--spacing-8); inset-inline-start:var(--spacing-8); background:var(--color-grey-0); border-radius:var(--radius-full); padding:var(--spacing-4) var(--spacing-6); font-size:var(--font-size-xs); }.stage-controls { position:absolute; inset-inline:var(--spacing-8); inset-block-end:var(--spacing-8); justify-content:center; flex-wrap:wrap; }.stage-controls button,.start-button { min-height:44px; border:0; border-radius:var(--radius-full); padding:var(--spacing-4) var(--spacing-10); cursor:pointer; font:inherit; }.secondary-button { background:var(--color-grey-0); color:var(--color-font-primary); }.danger-button { background:var(--color-error); color:var(--color-grey-0); }.mobile-chat,.drawer-close { display:none; }
  .held-frame { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; }.pending-badge { position:absolute; inset-block-start:var(--spacing-8); inset-inline-end:var(--spacing-8); background:var(--color-grey-0); border-radius:var(--radius-full); padding:var(--spacing-4) var(--spacing-6); font-size:var(--font-size-xs); }.resume-button { position:relative; z-index:2; border:0; border-radius:var(--radius-full); padding:var(--spacing-6) var(--spacing-10); background:var(--color-button-primary); color:var(--color-grey-0); font:inherit; cursor:pointer; }.drawer-actions { display:flex; align-items:center; gap:var(--spacing-4); }.drawer-hangup { display:none; border:0; border-radius:var(--radius-full); padding:var(--spacing-4) var(--spacing-6); font:inherit; }
  .context-panel { display:flex; flex-direction:column; min-height:0; }.context-heading { padding:var(--spacing-8); border-bottom:1px solid var(--color-grey-25); }h2 { font-size:var(--font-size-h4); margin:0; }.transcript { flex:1; overflow-y:auto; padding:var(--spacing-8); user-select:text; min-height:180px; }.empty { color:var(--color-font-tertiary); }.line { display:grid; gap:var(--spacing-2); margin:0 0 var(--spacing-10); line-height:1.5; overflow-wrap:anywhere; }.line strong { font-size:var(--font-size-xs); color:var(--color-font-tertiary); }.usage { border-top:1px solid var(--color-grey-25); padding:var(--spacing-8); font-size:var(--font-size-small); }h3 { margin:0 0 var(--spacing-6); font-size:var(--font-size-h4); }.rate { background:var(--color-grey-20); border-radius:var(--radius-3); padding:var(--spacing-6); margin-bottom:var(--spacing-8); }.usage-row { margin-block:var(--spacing-4); }.usage-row span:first-child { color:var(--color-font-tertiary); }.usage details { margin-top:var(--spacing-8); line-height:1.5; }.usage summary { cursor:pointer; }.usage p { margin:var(--spacing-4) 0 0; }
  .usage .billing-note { color:var(--color-font-tertiary); font-size:var(--font-size-xs); line-height:1.5; margin:0 0 var(--spacing-8); }
  .start-area { text-align:center; padding:var(--spacing-12); }.start-button { background:var(--color-button-primary); color:var(--color-grey-0); font-weight:700; }.privacy,.connection { color:var(--color-font-tertiary); font-size:var(--font-size-small); line-height:1.5; }.connection { text-align:center; }.error { color:var(--color-error); }.plain-button { border:0; background:none; color:var(--color-font-primary); font:inherit; cursor:pointer; min-height:40px; }button:focus-visible,summary:focus-visible { outline:3px solid var(--color-button-primary); outline-offset:2px; }
  .notice { max-width:1400px; margin:0 auto var(--spacing-8); padding:var(--spacing-6); border-radius:var(--radius-3); background:var(--color-warning-bg); color:var(--color-font-primary); font-size:var(--font-size-small); }
  @media(max-width:730px) { .call-page { padding:var(--spacing-6); }.top-bar,.heading { flex-wrap:wrap; }.brand { flex-wrap:wrap; min-width:0; }.heading { align-items:start; gap:var(--spacing-6); }.heading > div:first-child { min-width:0; }.heading h1 { overflow-wrap:anywhere; }.subtitle { font-size:var(--font-size-small); }.timer { white-space:nowrap; flex-shrink:0; }.call-layout { display:block; min-height:0; }.stage { min-height: min(65dvh, 630px); }.call-page.visual-active .stage { position:fixed; z-index:10; inset:0; width:100vw; height:100dvh; min-height:100dvh; border-radius:0; }.call-page.visual-active .top-bar,.call-page.visual-active .heading { position:relative; z-index:11; background:var(--color-grey-0); border-radius:var(--radius-3); padding:var(--spacing-4); }.call-page.visual-active .heading { margin-top:var(--spacing-4); }.call-page.visual-active .subtitle { display:none; }.call-page.visual-active .call-layout { min-height:calc(100dvh - 150px); }.context-panel { display:none; }.context-panel.drawer-open { display:flex; position:fixed; z-index:20; inset-inline:0; inset-block-end:0; max-height:65dvh; border-radius:var(--radius-6) var(--radius-6) 0 0; box-shadow:var(--shadow-xl); }.drawer-close,.mobile-chat,.drawer-hangup { display:block; }.stage-controls { gap:var(--spacing-4); inset-inline:var(--spacing-4); inset-block-end:var(--spacing-4); z-index:12; }.stage-controls button { padding-inline:var(--spacing-6); }.transcript { min-height:100px; }.portrait .orb { width:108px; height:108px; } }
</style>
