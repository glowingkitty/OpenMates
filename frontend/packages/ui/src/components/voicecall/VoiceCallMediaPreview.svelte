<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { notificationStore } from '../../stores/notificationStore';
  import NotificationStack from '../NotificationStack.svelte';
  import VoiceCallMedia from './VoiceCallMedia.svelte';
  import type { VoiceCallDisplayedMedia } from '../../services/voiceCallMedia';
  import type { VoiceCallCameraFacing } from '../../services/voiceCallCamera';
  let { initialExpanded = true, initialCamera = false, initialKind = 'image', multiple = false, initialError = null }: {
    initialExpanded?: boolean; initialCamera?: boolean; initialKind?: 'image' | 'video' | 'camera'; multiple?: boolean; initialError?: string | null;
  } = $props();
  let expanded = $state(untrack(() => initialExpanded));
  let cameraEnabled = $state(untrack(() => initialCamera || initialKind === 'camera'));
  let cameraFacing = $state<VoiceCallCameraFacing>('environment');
  let index = $state(0);
  let showCamera = $state(untrack(() => initialKind === 'camera'));
  let cameraStream = $state<MediaStream | null>(null);
  // Reuse a real fixture clip as a deterministic smooth stream, without requesting a camera.
  onMount(() => {
    if (initialError) notificationStore.addNotificationWithOptions('error', { message: initialError, duration: 0, dedupeKey: 'voice-camera-preview-error' });
    if (!cameraEnabled) return;
    let disposed = false;
    const source = document.createElement('video') as HTMLVideoElement & {captureStream?: () => MediaStream};
    source.src = '/store-examples/video-generate-1.mp4';
    source.muted = true;
    source.playsInline = true;
    source.loop = true;
    void source.play().then(() => {
      if (!disposed && source.captureStream) cameraStream = source.captureStream();
    }).catch(() => { /* Browsers without fixture playback retain the camera-pending preview. */ });
    return () => {
      disposed = true;
      cameraStream?.getTracks().forEach(track => track.stop());
      cameraStream = null;
      source.pause();
      source.removeAttribute('src');
      source.load();
    };
  });
  const results: VoiceCallDisplayedMedia[] = [
    { embedId:'preview-image', kind:'image', url:'/images/examples/group1.jpg' },
    { embedId:'preview-video', kind:'video', url:'/store-examples/video-generate-1.mp4' },
  ];
  const displayedMedia = $derived(showCamera ? null : results[multiple ? index : initialKind === 'video' ? 1 : 0]);
</script>

<VoiceCallMedia {cameraStream} {cameraEnabled} {cameraFacing} {expanded} {displayedMedia}
  mediaCount={multiple ? results.length : 1} mediaIndex={index}
  onExpandedChange={value => { expanded = value; }}
  onShowCamera={() => { showCamera = true; }}
  onFlipCamera={() => { cameraFacing = cameraFacing === 'environment' ? 'user' : 'environment'; }}
  onPrevious={() => { index = Math.max(0, index - 1); }}
  onNext={() => { index = Math.min(results.length - 1, index + 1); }} />

<NotificationStack />
