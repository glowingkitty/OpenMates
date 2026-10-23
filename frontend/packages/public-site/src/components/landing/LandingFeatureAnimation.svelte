<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import generalKnowledgeAvatar from '../../assets/landing/general_knowledge.jpeg';
  import businessDevelopmentAvatar from '../../assets/landing/business_development.jpeg';
  import EmbedPreviewCorner from '../results/EmbedPreviewCorner.svelte';
  import eventIcon from '../../assets/results/event.svg?url';
  import eventImage from '../../assets/results/meetup.webp';
  import EventResultCard from '../results/EventResultCard.svelte';
  import { actionableStages, privacyStages, featureAnimationCopy } from './landingFeatureAnimationContent';

  interface Props {
    section: 'actionable' | 'privacy';
    active: boolean;
    language: string;
    onComplete: () => void;
  }

  let { section, active, language, onComplete }: Props = $props();
  let mounted = $state(false);
  let visible = $state(true);
  let reducedMotion = $state(false);
  let elapsedMs = $state(0);
  let sceneElement = $state<HTMLDivElement>();
  let sceneContent = $state<HTMLDivElement>();
  let sceneScale = $state(1);

  // Fit the natural content, not its animated/transformed bounds. ResizeObserver
  // also catches translated copy and font loading, without measuring every frame.
  $effect(() => {
    const frame = sceneElement;
    const content = sceneContent;
    if (!frame || !content) return;
    const fit = () => {
      const style = getComputedStyle(frame);
      const width = frame.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      const height = frame.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
      if (width <= 0 || height <= 0) return;
      sceneScale = Math.min(1, width / Math.max(1, content.scrollWidth), height / Math.max(1, content.scrollHeight));
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(frame);
    observer.observe(content);
    return () => observer.disconnect();
  });
  let completed = false;
  const eventDate = '2026-08-29T18:30:00+02:00';
  let copy = $derived(featureAnimationCopy[language === 'de' ? 'de' : 'en']);
  let stages = $derived(section === 'actionable' ? actionableStages : privacyStages);
  let durationMs = $derived(stages.reduce((sum, item) => sum + item.durationMs, 0));
  let scene = $derived.by(() => {
    let start = 0;
    for (const stage of stages) {
      if (elapsedMs < start + stage.durationMs) return { ...stage, timeMs: elapsedMs - start };
      start += stage.durationMs;
    }
    return { ...stages[stages.length - 1], timeMs: 0 };
  });
  let playing = $derived(active && visible && !reducedMotion);
  let interaction = $derived(scene.id === 'event-preview'
    ? (scene.timeMs >= 1800 ? 'preview-clicked' : scene.timeMs >= 1000 ? 'preview-targeted' : 'idle')
    : scene.id === 'luma-cta'
      ? (scene.timeMs >= 1450 ? 'cta-clicked' : scene.timeMs >= 700 ? 'cta-targeted' : 'idle')
      : 'idle');

  function finish(): void {
    if (completed) return;
    completed = true;
    untrack(onComplete);
  }

  onMount(() => {
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updateMotion = () => { reducedMotion = motionQuery.matches; };
    const updateVisibility = () => { visible = !document.hidden; };
    updateMotion();
    updateVisibility();
    motionQuery.addEventListener('change', updateMotion);
    document.addEventListener('visibilitychange', updateVisibility);
    mounted = true;
    return () => {
      motionQuery.removeEventListener('change', updateMotion);
      document.removeEventListener('visibilitychange', updateVisibility);
    };
  });

  // Accumulate visible playback only. Scrolling away and hidden tabs pause both
  // the sequence clock and CSS motion, rather than skipping unread scenes.
  $effect(() => {
    if (!mounted || !active) return;
    if (reducedMotion) { finish(); return; }
    if (!visible || completed) return;
    let frame = 0;
    let previous = performance.now();
    let elapsed = untrack(() => elapsedMs);
    const total = durationMs;
    const tick = (now: number) => {
      elapsed += now - previous;
      previous = now;
      elapsedMs = Math.min(elapsed, total);
      if (elapsed >= total) finish();
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  });
</script>

<div class="feature-animation" class:playing data-testid="landing-feature-animation" data-section={section} data-active-stage={scene.id} data-interaction-state={interaction} data-playing={playing ? 'true' : 'false'} aria-hidden="true">
  {#key scene.id}
    <div class="scene" bind:this={sceneElement} style={`--scene-duration: ${scene.durationMs}ms`}>
      <div class="scene-content" bind:this={sceneContent} style={`--scene-scale: ${sceneScale}`} data-scene-scale={sceneScale}>
      {#if scene.id === 'user-request' || scene.id === 'trip-request'}
        <div class="message user">{scene.id === 'user-request' ? copy.actionable_event_user_message : copy.privacy_trip_request}</div>
      {:else if scene.id === 'assistant-response' || scene.id === 'pii-reveal'}
        <div class="assistant-row">
          <img class="avatar" src={scene.id === 'assistant-response' ? generalKnowledgeAvatar : businessDevelopmentAvatar} alt="" width="42" height="42" />
          <div class="message assistant">
            <div class="mate-name">{scene.id === 'assistant-response' ? copy.generalKnowledge : copy.businessDevelopment}</div>
            {#if scene.id === 'assistant-response'}{copy.actionable_event_assistant_message}
            {:else}{copy.privacy_email_response} <span class="pii-value" class:revealed={scene.timeMs >= 1200}>{scene.timeMs >= 1200 ? 'alex@example.com' : '[EMAIL_1]'}</span>{/if}
          </div>
        </div>
      {:else if scene.id === 'event-preview'}
        <div class="event-preview" class:pressed={interaction === 'preview-clicked'} data-testid="landing-actionable-event-preview">
          <EmbedPreviewCorner background="var(--color-app-events, var(--color-primary))" iconUrl={`url(${JSON.stringify(eventIcon)})`} />
          <EventResultCard title={copy.actionable_event_title} imageUrl={eventImage} date={eventDate} timezone="Europe/Berlin" locale={language === 'de' ? 'de-DE' : 'en-US'} attribution={new Intl.DateTimeFormat(language === 'de' ? 'de-DE' : 'en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'Europe/Berlin' }).format(new Date(eventDate))} rsvpCount={460} rsvpLabel={copy.actionable_event_rsvps} />
        </div>
      {:else if scene.id === 'luma-cta'}
        <div class="luma-cta" class:pressed={interaction === 'cta-clicked'} data-testid="landing-actionable-luma-button">{copy.actionable_event_open_luma}</div>
      {:else if scene.id === 'encryption-lock'}
        <div class="data-orbit">
          {#each ['chat', 'file', 'folder', 'task'] as name, index}
            <span class={`data-icon orbit-${index}`}>{@render icon(name)}</span>
          {/each}
          <span class="lock-core"><span class="unlock">{@render icon('unlock')}</span><span class="locked">{@render icon('lock')}</span></span>
        </div>
      {:else if scene.id === 'pii-detection'}
        <div class="message user" data-pii-state={scene.timeMs >= 1500 ? 'placeholder' : scene.timeMs >= 600 ? 'highlighted' : 'plain'}>
          {copy.privacy_email_request} <span class="pii-value" class:highlighted={scene.timeMs >= 600 && scene.timeMs < 1500}>{scene.timeMs >= 1500 ? '[EMAIL_1]' : 'alex@example.com'}</span>
        </div>
      {:else if scene.id === 'memory-permission'}
        <div class="permission-card" data-testid="app-settings-memories-permission-card">
          <strong class="permission-heading">{@render icon('lock')} {copy.permissionTitle}</strong>
          <p>{copy.permissionQuestion}</p>
          <div class="memory-category"><span class="toggle"></span><span class="travel-icon">{@render icon('plane')}</span><span><strong>{copy.trips}</strong><small>2/2 {copy.entries}</small></span><span class="chevron">▸</span></div>
          <div class="permission-actions"><span class="include">{copy.includeSelected}</span><span>{copy.rejectAll}</span></div>
        </div>
      {:else}
        <p class="copy">{scene.id === 'saved-data-copy' ? copy.privacy_saved_data : scene.id === 'pii-copy' ? copy.privacy_pii : scene.id === 'originals-copy' ? copy.privacy_originals : copy.privacy_memory_result}</p>
      {/if}
      </div>
    </div>
  {/key}
  {#if scene.id === 'event-preview' || scene.id === 'luma-cta'}
    <div class="pointer" class:targeted={interaction !== 'idle'} class:clicked={interaction.endsWith('clicked')} data-testid="landing-actionable-pointer">{@render icon('pointer')}</div>
  {/if}
</div>

{#snippet icon(name: string)}
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    {#if name === 'pointer'}<path d="m4 3 7.07 17 2.51-7.39L21 10.1 4 3Z" />
    {:else if name === 'lock' || name === 'unlock'}<rect x="5" y="10" width="14" height="11" rx="2" /><path d={name === 'lock' ? 'M8 10V6a4 4 0 0 1 8 0v4' : 'M8 10V6a4 4 0 0 1 7.5-2'} /><path d="M12 15v2" />
    {:else if name === 'chat'}<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z" />
    {:else if name === 'folder'}<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
    {:else if name === 'task'}<path d="m3 6 1 1 2-2m-3 7 1 1 2-2m-3 7 1 1 2-2M10 6h11M10 12h11M10 18h11" />
    {:else if name === 'file'}<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Zm0 0v6h6M8 13h8M8 17h8" />
    {:else if name === 'plane'}<path d="m22 2-7 20-4-9-9-4 20-7ZM22 2 11 13" />
    {:else}<rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 11h18" />{/if}
  </svg>
{/snippet}

<style>
  .feature-animation { position: relative; display: grid; place-items: center; width: 100%; min-width: 0; height: var(--story-animation-height, clamp(18rem, 38vw, 23rem)); overflow: hidden; container-type: inline-size; color: var(--color-font-primary); pointer-events: none; }
  .scene-content { display: grid; place-items: center; width: 100%; min-width: 0; transform: scale(var(--scene-scale, 1)); transform-origin: center; }
  .scene { box-sizing: border-box; position: absolute; inset: 0; display: grid; grid-template: minmax(0, 1fr) / minmax(0, 1fr); place-items: center; padding: var(--spacing-8); animation: scene-flow var(--scene-duration) linear both; }
  .feature-animation:not(.playing) .scene, .feature-animation:not(.playing) .data-icon, .feature-animation:not(.playing) .unlock, .feature-animation:not(.playing) .locked { animation-play-state: paused; }
  .message { position: relative; max-width: min(88%, 28rem); padding: var(--spacing-8) var(--spacing-10); border-radius: var(--radius-6); box-shadow: var(--shadow-md); text-align: start; font-size: clamp(1rem, 2.6cqi, 1.2rem); line-height: 1.5; }
  .user { justify-self: end; margin-inline-end: 6%; background: var(--color-grey-blue); }
  .message::after { position: absolute; bottom: 4px; width: 14px; height: 16px; background: inherit; content: ''; }
  .user::after { right: -6px; clip-path: polygon(0 0, 100% 100%, 0 72%); }
  .assistant::after { left: -6px; clip-path: polygon(100% 0, 0 100%, 100% 72%); }
  .assistant-row { display: flex; align-items: start; gap: var(--spacing-6); width: min(100%, 32.5rem); }
  .avatar { flex: 0 0 42px; border-radius: var(--radius-full); object-fit: cover; }
  .assistant { background: var(--color-grey-10); }
  .mate-name { color: var(--color-font-tertiary); font-size: var(--font-size-xs); margin-bottom: var(--spacing-2); }
  .copy { max-width: 30rem; margin: 0; font-size: clamp(1.25rem, 3.8cqi, 1.7rem); font-weight: 800; line-height: 1.35; text-align: center; text-wrap: balance; }
  /* The app and public demo render the same pure event/card/calendar presentation. */
  .event-preview { position: relative; container: result-card / inline-size; width: 300px; max-width: 100%; height: 200px; border-radius: 30px; overflow: hidden; background: var(--color-grey-0); box-shadow: 0 8px 24px rgb(0 0 0 / 16%), 0 2px 6px rgb(0 0 0 / 10%); transition: transform 140ms ease; }
  .luma-cta { padding: var(--spacing-6) var(--spacing-12); border-radius: var(--radius-8); background: var(--color-button-primary); color: var(--color-font-button); box-shadow: var(--shadow-md); font-size: clamp(1rem, 2.8cqi, 1.3rem); font-weight: 800; transition: transform 140ms ease; }
  .pressed { transform: scale(0.97); }
  .pointer { position: absolute; left: 54%; top: calc(100% + 40px); width: 38px; height: 38px; color: var(--color-font-primary); opacity: 0; transform: translate(-15%, -12%) scale(0.82); transition: left 620ms cubic-bezier(0.16, 1, 0.3, 1), top 620ms cubic-bezier(0.16, 1, 0.3, 1), opacity 180ms ease, transform 140ms ease; }
  .pointer.targeted { top: 53%; left: 57%; opacity: 1; transform: translate(-15%, -12%) scale(1); }
  .pointer.clicked { transform: translate(-15%, -12%) scale(0.78); }
  .pointer::after { position: absolute; left: 4px; top: 4px; width: 18px; height: 18px; border: 2px solid currentColor; border-radius: var(--radius-full); content: ''; opacity: 0; }
  .pointer.clicked::after { animation: click-pulse 420ms ease-out; }
  svg { display: block; width: 26px; height: 26px; }
  .pointer :global(svg) { width: 100%; height: 100%; }
  .data-orbit { position: relative; width: 260px; height: 150px; }
  .data-icon, .lock-core { position: absolute; display: grid; place-items: center; border: 1px solid var(--color-grey-30); background: var(--color-grey-10); box-shadow: var(--shadow-md); border-radius: var(--radius-full); }
  .data-icon { width: 46px; height: 46px; animation: float-data 2.8s ease-in-out infinite; }
  .orbit-0 { inset: 4px auto auto 18px; } .orbit-1 { inset: 4px 18px auto auto; animation-delay: -0.7s; } .orbit-2 { inset: auto auto 4px 42px; animation-delay: -1.4s; } .orbit-3 { inset: auto 42px 4px auto; animation-delay: -2.1s; }
  .lock-core { inset: 38px 91px auto; width: 78px; height: 78px; overflow: hidden; }
  .unlock, .locked { position: absolute; } .unlock { animation: unlock-exit 3s both; } .locked { animation: lock-enter 3s both; }
  .pii-value { font-weight: 600; border-radius: var(--radius-2); } .highlighted { background: var(--color-highlight-yellow); } .revealed { color: var(--color-button-primary); }
  .permission-card { display: grid; gap: var(--spacing-6); width: min(100%, 33rem); padding: var(--spacing-10); border-radius: var(--radius-6); background: var(--color-grey-10); box-shadow: var(--shadow-md); font-size: var(--font-size-small); }
  .permission-card p { margin: 0; line-height: 1.5; } .permission-heading { display: flex; align-items: center; gap: var(--spacing-4); }
  .memory-category { display: flex; align-items: center; gap: var(--spacing-6); padding: var(--spacing-6); background: var(--color-grey-20); border-radius: var(--radius-5); }
  .memory-category small { display: block; color: var(--color-font-tertiary); } .chevron { margin-inline-start: auto; }
  .toggle { width: 32px; height: 19px; border-radius: var(--radius-full); background: var(--color-primary); }
  .toggle::after { content: ''; display: block; width: 15px; height: 15px; border-radius: var(--radius-full); margin: 2px 2px 2px auto; background: var(--color-grey-0); }
  .travel-icon { color: var(--color-primary); }
  .permission-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-6); } .permission-actions span { padding: var(--spacing-4) var(--spacing-8); border-radius: var(--radius-8); } .include { background: var(--color-primary); color: var(--color-font-button); }
  @keyframes scene-flow { 0% { opacity: 0; transform: translate3d(0, 24px, 0) scale(0.96); animation-timing-function: cubic-bezier(0.16, 1, 0.3, 1); } 30% { opacity: 1; transform: translate3d(0, 4px, 0) scale(0.96); } 68% { opacity: 1; transform: translate3d(0, -4px, 0) scale(1); animation-timing-function: cubic-bezier(0.7, 0, 1, 0.5); } 100% { opacity: 0; transform: translate3d(0, -36px, 0) scale(0.78); } }
  @keyframes click-pulse { from { opacity: 0.9; transform: scale(0.35); } to { opacity: 0; transform: scale(1.65); } }
  @keyframes float-data { 0%, 100% { transform: translateY(-3px); } 50% { transform: translateY(4px); } }
  @keyframes unlock-exit { 0%, 28% { opacity: 1; transform: translateY(0) rotate(-7deg); } 48%, 100% { opacity: 0; transform: translateY(-18px) rotate(5deg); } }
  @keyframes lock-enter { 0%, 32% { opacity: 0; transform: translateY(18px) scale(0.8); } 54%, 100% { opacity: 1; transform: translateY(0) scale(1); } }
  @container (max-width: 430px) {
    .scene { padding: var(--spacing-4); }
    .message { box-sizing: border-box; padding: var(--spacing-6) var(--spacing-8); }
    .permission-card { box-sizing: border-box; padding: var(--spacing-4); gap: var(--spacing-4); font-size: var(--font-size-xs); }
    .permission-heading, .memory-category { gap: var(--spacing-4); }
    .permission-card :global(svg) { width: 18px; height: 18px; }
    .memory-category { padding: var(--spacing-4); }
    .permission-actions { gap: var(--spacing-3); }
    .permission-actions span { padding: var(--spacing-2) var(--spacing-4); }
  }
  @media (prefers-reduced-motion: reduce) { .feature-animation { display: none; } .scene, .data-icon, .unlock, .locked { animation: none; } }
</style>
