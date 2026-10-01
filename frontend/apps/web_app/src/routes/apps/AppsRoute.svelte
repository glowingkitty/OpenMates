<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Header, Settings, NotificationStack, Login, text, authStore, panelState, settingsDeepLink, isInSignupProcess, currentSignupStep, STEP_ALPHA_DISCLAIMER, focusTrap } from '@repo/ui';
  import { loginInterfaceOpen } from '@repo/ui/stores/uiStateStore';
  import AppsWorkspace from '@repo/ui/components/apps/AppsWorkspace.svelte';
  import { readAppsWorkspaceRoute } from '@repo/ui/utils/appsWorkspaceRoute';

  const detailOpen = $derived(Boolean(readAppsWorkspaceRoute(page.url.hash)?.appId));

  function navigate(hash: string): void { void goto(`/${hash}`, { noScroll: true, keepFocus: true }); }
  function signup(): void { currentSignupStep.set(STEP_ALPHA_DISCLAIMER); isInSignupProcess.set(true); loginInterfaceOpen.set(true); }
  function login(): void { isInSignupProcess.set(false); loginInterfaceOpen.set(true); }
  function closeAuth(): void { loginInterfaceOpen.set(false); isInSignupProcess.set(false); }
  function openSettings(path: string): void { settingsDeepLink.set(path); panelState.openSettings(); }
  onMount(() => {
    window.addEventListener('openSignupInterface', signup);
    window.addEventListener('openLoginInterface', login);
    window.addEventListener('closeLoginInterface', closeAuth);
    return () => {
      window.removeEventListener('openSignupInterface', signup);
      window.removeEventListener('openLoginInterface', login);
      window.removeEventListener('closeLoginInterface', closeAuth);
    };
  });
</script>

<div class="apps-route">
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <div class="apps-route-body" class:settings-open={$panelState.isSettingsOpen}>
    <main inert={$loginInterfaceOpen}><AppsWorkspace hash={page.url.hash} onNavigate={navigate} onSignup={signup} onSettings={openSettings} /></main>
    <aside class="settings-pane" hidden={detailOpen && !$panelState.isSettingsOpen}><Settings isLoggedIn={$authStore.isAuthenticated} /></aside>
  </div>
  {#if $loginInterfaceOpen}
    <div class="apps-auth-layer" role="dialog" aria-modal="true" aria-label={$text($isInSignupProcess ? 'apps.skill_form.signup' : 'login.login')} tabindex="-1" use:focusTrap={{ onEscape: closeAuth }}>
      <button class="auth-close" aria-label={$text('common.close')} onclick={closeAuth}>×</button>
      <Login on:loginSuccess={(event: CustomEvent<{ inSignupFlow?: boolean }>) => { if (!event.detail.inSignupFlow) { loginInterfaceOpen.set(false); isInSignupProcess.set(false); } }} />
    </div>
  {/if}
</div>
<NotificationStack />

<style>
  .apps-route { display: flex; flex-direction: column; width: 100%; height: 100dvh; overflow: hidden; container: main-content / inline-size; }
  .apps-route-body { display: flex; position: relative; flex: 1; min-height: 0; }
  main { flex: 1; min-width: 0; min-height: 0; position: relative; }
  .settings-pane { width: 0; overflow: hidden; }
  .settings-open .settings-pane { width: 400px; flex-shrink: 0; }
  .apps-auth-layer { position: absolute; inset: 0; z-index: var(--z-index-modal,200); overflow: auto; background: var(--color-grey-0); }
  .auth-close { position: absolute; top: var(--spacing-4); right: var(--spacing-4); z-index: 1; border: 0; border-radius: 50%; background: var(--color-grey-10); color: var(--color-font-primary); font-size: 1.5rem; width: 2.5rem; height: 2.5rem; cursor: pointer; }
  @media(max-width: 1100px) { .settings-open .settings-pane { position: absolute; inset: 0; width: 100%; z-index: var(--z-index-overlay,100); } }
</style>
