<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { VoiceCallDisplayedMedia } from '../../services/voiceCallMedia';
  import type { VoiceCallCameraFacing } from '../../services/voiceCallCamera';

  interface Props {
    cameraStream: MediaStream | null;
    cameraEnabled: boolean;
    cameraFacing: VoiceCallCameraFacing;
    expanded: boolean;
    displayedMedia: VoiceCallDisplayedMedia | null;
    mediaCount?: number;
    mediaIndex?: number;
    error?: string | null;
    onExpandedChange: (expanded: boolean) => void;
    onShowCamera: () => void;
    onFlipCamera: () => void;
    onPrevious: () => void;
    onNext: () => void;
  }
  let { cameraStream, cameraEnabled, cameraFacing, expanded, displayedMedia,
    mediaCount = 0, mediaIndex = 0, error = null,
    onExpandedChange, onShowCamera, onFlipCamera, onPrevious, onNext }: Props = $props();
  let cameraVideo = $state<HTMLVideoElement>();
  $effect(() => {
    const video = cameraVideo;
    if (!video) return;
    // Cleanup belongs to this video element's lifetime, not each parent call
    // state replacement (audio levels, timer, mute and facing updates).
    return () => { video.srcObject = null; };
  });
  $effect(() => {
    const video = cameraVideo;
    const stream = cameraStream;
    if (!video || video.srcObject === stream) return;
    video.srcObject = stream;
    if (stream) void video.play().catch(() => { /* Capture service reports device errors. */ });
  });
</script>

{#if cameraEnabled || displayedMedia || error}
  <section class="call-media" class:expanded class:collapsed={!expanded} data-testid="voice-call-media" data-expanded={expanded} aria-label={$text('voicecall.generated_media')}>
    {#if cameraEnabled}
      <div class="camera" class:inset={!!displayedMedia} data-testid="voice-call-camera-preview">
        <!-- Camera remains a native video stream even while a generated result is displayed. -->
        <video bind:this={cameraVideo} autoplay muted playsinline class:mirror={cameraFacing === 'user'} aria-label={$text('voicecall.camera_preview')}></video>
        {#if displayedMedia}
          <button class="camera-return" type="button" data-testid="voice-call-show-camera" aria-label={$text('voicecall.show_camera')} onclick={onShowCamera}></button>
        {/if}
      </div>
    {/if}
    {#if displayedMedia}
      {#key displayedMedia.embedId}
        {#if displayedMedia.kind === 'image'}
          <img class="generated" data-testid="voice-call-generated-image" src={displayedMedia.url} alt={$text('voicecall.generated_media')} />
        {:else}
          <!-- No loop: a generated clip plays once, then remains available with controls. -->
          <video class="generated" data-testid="voice-call-generated-video" src={displayedMedia.url} autoplay muted playsinline controls aria-label={$text('voicecall.generated_media')}></video>
        {/if}
      {/key}
      <span class="ai-badge" data-testid="voice-call-media-ai" aria-label={$text('voicecall.ai_generated')}><span class="call-media-icon ai-icon" aria-hidden="true"></span></span>
      {#if mediaCount > 1}
        <nav class="media-navigation" aria-label={$text('voicecall.generated_media')}>
          <button type="button" data-testid="voice-call-media-previous" aria-label={$text('voicecall.previous_media')} disabled={mediaIndex <= 0} onclick={onPrevious}><span class="call-media-icon back" aria-hidden="true"></span></button>
          <span aria-live="polite">{mediaIndex + 1} / {mediaCount}</span>
          <button type="button" data-testid="voice-call-media-next" aria-label={$text('voicecall.next_media')} disabled={mediaIndex >= mediaCount - 1} onclick={onNext}><span class="call-media-icon next" aria-hidden="true"></span></button>
        </nav>
      {/if}
    {/if}
    {#if cameraEnabled}
      <button class="round flip" type="button" data-testid="voice-call-camera-flip" aria-label={$text('voicecall.flip_camera')} onclick={onFlipCamera}><span class="call-media-icon camera-icon" aria-hidden="true"></span></button>
    {/if}
    {#if error}<span class="media-error" role="alert">{error}</span>{/if}
    <button class="round expand" type="button" data-testid="voice-call-media-expand" aria-label={$text(expanded ? 'voicecall.minimize' : 'voicecall.expand')} aria-expanded={expanded} onclick={() => onExpandedChange(!expanded)}><span class="call-media-icon up" class:down={!expanded} aria-hidden="true"></span></button>
  </section>
{/if}

<style>
  .call-media { position:relative; width:100%; height:min(60dvh,32rem,var(--voice-call-stage-max-height,32rem)); overflow:hidden; border-radius:var(--radius-6); background:var(--color-grey-90); color:var(--color-font-button); isolation:isolate; }
  .call-media.collapsed { height:6rem; }
  .camera, .generated { position:absolute; inset:0; width:100%; height:100%; }
  .camera video { width:100%; height:100%; object-fit:contain; }
  .camera .mirror { transform:scaleX(-1); }
  .generated { object-fit:contain; }
  .camera.inset { inset:auto auto var(--spacing-4) var(--spacing-4); z-index:2; width:6rem; height:4.5rem; overflow:hidden; border:2px solid var(--color-grey-0); border-radius:var(--radius-4); box-shadow:var(--shadow-md); }
  .camera-return { position:absolute; inset:0; width:100%; height:100%; padding:0; border:0; background:transparent; cursor:pointer; }
  .call-media button { box-sizing:border-box; min-width:0; margin:0; filter:none; scale:1; font:inherit; color:inherit; cursor:pointer; }
  .call-media button:hover, .call-media button:active { filter:none; scale:1; }
  .call-media button:focus-visible { outline:2px solid var(--color-primary-start); outline-offset:-3px; }
  .round { position:absolute; z-index:3; display:flex; align-items:center; justify-content:center; width:2.5rem; height:2.5rem; padding:var(--spacing-4); border:0; border-radius:var(--radius-full); background:var(--color-grey-0); color:var(--color-font-primary) !important; box-shadow:var(--shadow-md); }
  .round:hover { background:var(--color-grey-20); }
  .expand { right:var(--spacing-4); bottom:var(--spacing-4); }
  .flip { left:var(--spacing-4); top:var(--spacing-4); }
  .call-media-icon { display:block; width:1.25rem; height:1.25rem; background:currentColor; mask:var(--media-icon) center / contain no-repeat; -webkit-mask:var(--media-icon) center / contain no-repeat; }
  .up { --media-icon:url('@openmates/ui/static/icons/up.svg'); }
  .up.down { transform:rotate(180deg); }
  .camera-icon { --media-icon:url('@openmates/ui/static/icons/camera.svg'); }
  .ai-icon { --media-icon:url('@openmates/ui/static/icons/ai.svg'); }
  .back { --media-icon:url('@openmates/ui/static/icons/back.svg'); }
  .next { --media-icon:url('@openmates/ui/static/icons/back.svg'); transform:rotate(180deg); }
  .ai-badge { position:absolute; top:var(--spacing-4); right:var(--spacing-4); z-index:2; padding:var(--spacing-2) var(--spacing-4); background:var(--color-grey-0); color:var(--color-font-primary); border-radius:var(--radius-4); font-size:var(--font-size-small); font-weight:var(--font-weight-bold); }
  .media-navigation { position:absolute; left:50%; bottom:var(--spacing-4); transform:translateX(-50%); z-index:2; display:flex; align-items:center; gap:var(--spacing-2); background:var(--color-grey-0); color:var(--color-font-primary); border-radius:var(--radius-full); font-size:var(--font-size-small); }
  .media-navigation button { display:flex; flex:0 0 2.5rem; align-items:center; justify-content:center; width:2.5rem; height:2.5rem; padding:var(--spacing-4); border:0; border-radius:var(--radius-full); background:transparent; }
  .media-navigation > span { flex:none; white-space:nowrap; line-height:1.25; }
  .media-navigation button:disabled { opacity:.35; cursor:default; }
  .media-error { position:absolute; left:var(--spacing-4); right:3.5rem; top:50%; transform:translateY(-50%); z-index:3; pointer-events:none; padding:var(--spacing-4); border-radius:var(--radius-4); color:var(--color-error); background:var(--color-error-light); font-size:var(--font-size-small); }
  @media (max-width:480px) { .camera.inset { width:4.5rem; height:3.375rem; } .media-navigation { gap:0; } }
  @media (prefers-reduced-motion:no-preference) { .call-media { transition:height 180ms ease; } }
</style>
