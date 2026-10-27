<script lang="ts">
  import { onDestroy, onMount, setContext } from 'svelte';
  import { get, writable } from 'svelte/store';
  import ActiveChat from '../ActiveChat.svelte';
  import Settings from '../Settings.svelte';
  import VoiceCallContextHeaderChild from './VoiceCallContextHeaderChild.svelte';
  import { VOICE_CALL_PILL_CONTEXT } from './voiceCallHeaderContext';
  import NotificationStack from '../NotificationStack.svelte';
  import { getExampleChat } from '../../demo_chats';
  import { activeChatStore } from '../../stores/activeChatStore';
  import { authStore } from '../../stores/authStore';
  import { userProfile } from '../../stores/userProfile';
  import { webSocketService } from '../../services/websocketService';
  import { userDB } from '../../services/userDB';
  import type { Chat } from '../../types/chat';
  import { demoMode } from '../../stores/demoModeStore';
  import { showSignupFooter } from '../../stores/signupState';
  import { initialVoiceCallState, voiceCallController, type VoiceCallState } from '../../services/voiceCall';

  let { direction = 'ltr', withHeader = false, viewportAligned = false }: { direction?: 'ltr' | 'rtl'; withHeader?: boolean; viewportAligned?: boolean } = $props();
  const focusedDraftFixture = typeof window !== 'undefined' &&
    ['focusedDraft', 'focusedDraftRtl'].includes(new URLSearchParams(window.location.search).get('variant') ?? '');
  let startCount = $state(0);
  let startedChatId = $state<string | null>(null);
  const privateChatFixture = typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('variant') === 'privateCall';
  const demoCallFixture = typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).get('variant') === 'demoCall';
  // Account-free composition: real toolbar and Settings profile with a local
  // synthetic account; no credentials or backend session are used.
  // Intro/demo legacy arrays can be empty. The public example registry exposes
  // a synchronous lookup after its static module imports have completed.
  const publicChat = getExampleChat('example-building-maintenance-email');
  if (!publicChat) throw new Error('Call header preview requires its registered public example');
  const chatId = privateChatFixture ? 'preview-private-voice-call' : publicChat.chat_id;
  const now = Math.floor(Date.now() / 1000);
  const localPrivateChat: Chat = {
    chat_id: chatId, user_id: 'preview-user', encrypted_title: null, messages_v: 0,
    title_v: 0, draft_v: 0, encrypted_draft_md: null, encrypted_draft_preview: null,
    last_edited_overall_timestamp: now, unread_count: 0, created_at: now, updated_at: now,
    processing_metadata: false, waiting_for_metadata: false, category: 'general_knowledge', icon: 'sparkles',
  };
  const call = writable<VoiceCallState>(focusedDraftFixture ? { ...initialVoiceCallState } : { ...initialVoiceCallState, status: 'live', chatId,
    callId: 'preview-public-call', minimized: false, cameraAvailable: true });
  const originalSubscribe = voiceCallController.subscribe;
  const originalHangup = voiceCallController.hangup;
  const originalStart = voiceCallController.start;
  const originalMinimize = voiceCallController.setMinimized;
  const originalMuted = voiceCallController.setMuted;
  const originalCamera = voiceCallController.setCameraEnabled;
  let cameraStream: MediaStream | null = null;
  const stopCamera = () => { cameraStream?.getTracks().forEach(track => track.stop()); cameraStream = null; };
  const originalDemoMode = demoMode.get();
  const originalSignupFooter = get(showSignupFooter);
  const originalActiveChatId = activeChatStore.get();
  const originalAuth = get(authStore);
  const originalProfile = get(userProfile);
  const originalGetUserProfile = userDB.getUserProfile;
  const originalConnect = webSocketService.connect;
  let activeChat: ActiveChat;
  voiceCallController.subscribe = call.subscribe;
  voiceCallController.hangup = () => {
    stopCamera();
    call.update(state => ({ ...state, status: 'ended', cameraEnabled: false, cameraStream: null, mediaExpanded: false }));
  };
  // This variant proves only the real focused toolbar's event delivery. It
  // intentionally performs no capture, registration, navigation or inference.
  if (focusedDraftFixture) voiceCallController.start = async (targetChatId) => {
    startCount += 1;
    startedChatId = targetChatId ?? null;
    call.set({ ...initialVoiceCallState, status: 'connecting', chatId: targetChatId ?? null });
  };
  else if (privateChatFixture) voiceCallController.start = async () => {
    call.update(state => ({ ...state, status: 'live', chatId, callId: 'preview-private-restarted-call' }));
  };
  voiceCallController.setMinimized = minimized => call.update(state => ({ ...state, minimized }));
  voiceCallController.setMuted = muted => call.update(state => ({ ...state, muted }));
  voiceCallController.setCameraEnabled = async enabled => {
    stopCamera();
    if (enabled) {
      // Account-free device fixture: the real media component owns this browser
      // stream, without requesting a camera or contacting speech providers.
      const canvas = document.createElement('canvas');
      canvas.width = 640; canvas.height = 360;
      const context = canvas.getContext('2d');
      if (context) { context.fillStyle = '#3b82f6'; context.fillRect(0, 0, 640, 360); }
      cameraStream = canvas.captureStream(1);
    }
    call.update(state => ({ ...state, cameraEnabled: enabled, cameraStream, mediaExpanded: enabled }));
  };
  // Avoid the demo-mode Report suppression: this fixture proves normal account
  // action visibility while the WebSocket singleton has no real token to use.
  webSocketService.connect = () => Promise.resolve();
  // ActiveChat reloads the profile from IndexedDB on mount and checks chat
  // ownership through the same service. Keep this account-free preview's
  // identity stable without writing a synthetic account into persistent data.
  const previewProfile = { ...originalProfile, user_id: 'preview-user' };
  userDB.getUserProfile = async () => ({ ...previewProfile });
  authStore.set({ isAuthenticated: true, isInitialized: true });
  userProfile.set(previewProfile);
  activeChatStore.setWithoutHashUpdate(focusedDraftFixture ? null : chatId);
  demoMode.set(demoCallFixture);
  // Use the normal fixed-header profile state, rather than the signup footer.
  showSignupFooter.set(false);
  const showReturnPill = $derived(
    ($voiceCallController.status === 'connecting' || $voiceCallController.status === 'live') &&
    $activeChatStore !== chatId,
  );
  setContext(VOICE_CALL_PILL_CONTEXT, () => showReturnPill
    ? { onReturn: () => activeChat.handleReturnToVoiceCallChat(chatId) }
    : undefined);
  onMount(() => {
    if (privateChatFixture) void activeChat.loadChat(localPrivateChat);
  });
  onDestroy(() => {
    voiceCallController.subscribe = originalSubscribe;
    voiceCallController.hangup = originalHangup;
    voiceCallController.start = originalStart;
    voiceCallController.setMinimized = originalMinimize;
    voiceCallController.setMuted = originalMuted;
    voiceCallController.setCameraEnabled = originalCamera;
    stopCamera();
    demoMode.set(originalDemoMode);
    showSignupFooter.set(originalSignupFooter);
    activeChatStore.setWithoutHashUpdate(originalActiveChatId);
    webSocketService.connect = originalConnect;
    userDB.getUserProfile = originalGetUserProfile;
    authStore.set(originalAuth);
    userProfile.set(originalProfile);
  });
</script>

<div class="call-header-preview" class:viewport-aligned={viewportAligned} dir={direction}
  data-testid="active-chat-call-header-preview" data-start-count={startCount}
  data-start-target={startedChatId ?? "new-chat"} data-call-status={$call.status}>
  <div class="preview-chat-layout">
    {#if withHeader}<VoiceCallContextHeaderChild />{/if}
    <div class="preview-chat-pane"><ActiveChat bind:this={activeChat} /></div>
  </div>
  <Settings isLoggedIn={false} />
  <NotificationStack />
</div>

<style>
  .call-header-preview { position: relative; width: 100%; height: 844px; }
  .call-header-preview.viewport-aligned { position: fixed; inset: 0; width: auto; height: auto; }
  .preview-chat-layout { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  .preview-chat-layout :global(header.webapp) { flex: none; }
  .preview-chat-pane { flex: 1; min-height: 0; }
</style>
