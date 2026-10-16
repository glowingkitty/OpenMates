<!--
  Direct authenticated entry point for the call experiment.
  The existing auth store gates media controller mounting.
  A caller can leave through normal app navigation.
  No ordinary chat state is created by this route.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { text } from '@repo/ui';
  import { authStore, initialize } from '@repo/ui';
  import { VideoCallController } from '@repo/ui/components/videocall/callController';
  import VideoCallPanel from '@repo/ui/components/videocall/VideoCallPanel.svelte';

  const controller = new VideoCallController();
  let authFailed = $state(false);
  onMount(() => {
    void initialize().catch(() => { authFailed = true; });
    return () => controller.dispose();
  });
</script>

{#if !$authStore.isInitialized && !authFailed}
  <main class="auth-state" data-testid="call-auth-loading">{$text('videocall.auth_loading')}</main>
{:else if !$authStore.isAuthenticated}
  <main class="auth-state" data-testid="call-auth-required"><h1>{$text('videocall.auth_title')}</h1><p>{$text('videocall.auth_detail')}</p><a href="/">{$text('videocall.auth_link')}</a></main>
{:else}
  <VideoCallPanel {controller} onLeave={() => void goto('/')} />
{/if}

<style>
  .auth-state { min-height:100dvh; display:flex; flex-direction:column; justify-content:center; align-items:center; gap:var(--spacing-8); background:var(--color-grey-10); color:var(--color-font-primary); text-align:center; padding:var(--spacing-12); font-family:'Lexend Deca Variable',sans-serif; }
  .auth-state h1 { font-size:var(--font-size-h2); }.auth-state p { margin:0; }.auth-state a { color:var(--color-primary); }
</style>
