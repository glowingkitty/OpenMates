<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Header, Settings, NotificationStack, Login, text, authStore, panelState, settingsDeepLink, isInSignupProcess, currentSignupStep, STEP_ALPHA_DISCLAIMER, focusTrap } from '@repo/ui';
  import { loginInterfaceOpen } from '@repo/ui/stores/uiStateStore';
  import AppsWorkspace from '@repo/ui/components/apps/AppsWorkspace.svelte';
  import { readAppsWorkspaceRoute } from '@repo/ui/utils/appsWorkspaceRoute';

  function navigate(hash: string): void {
    // A pending fullscreen close or request must not restore Apps after the
    // user has selected another workspace.
    if (!readAppsWorkspaceRoute(window.location.hash)) return;
    void goto(`/${hash}`, { noScroll: true, keepFocus: true });
  }
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

<div class="apps-route" class:settings-open={$panelState.isSettingsOpen}>
  <div class="apps-route-header"><Header context="webapp" isLoggedIn={$authStore.isAuthenticated} /></div>
  <div class="apps-route-body">
    <main inert={$loginInterfaceOpen}><AppsWorkspace hash={page.url.hash} onNavigate={navigate} onSignup={signup} onSettings={openSettings} /></main>
  </div>
  <!-- Settings owns header controls as well as its panel. Keep its absolute
       header controls relative to the whole route, rather than the body. -->
  <aside class="settings-pane"><Settings isLoggedIn={$authStore.isAuthenticated} /></aside>
  {#if $loginInterfaceOpen}
    <div class="apps-auth-layer" role="dialog" aria-modal="true" aria-label={$text($isInSignupProcess ? 'apps.skill_form.signup' : 'login.login')} tabindex="-1" use:focusTrap={{ onEscape: closeAuth }}>
      <button class="auth-close" aria-label={$text('common.close')} onclick={closeAuth}>×</button>
      <Login on:loginSuccess={(event: CustomEvent<{ inSignupFlow?: boolean }>) => { if (!event.detail.inSignupFlow) { loginInterfaceOpen.set(false); isInSignupProcess.set(false); } }} />
    </div>
  {/if}
</div>
<NotificationStack />

<style>
  .apps-route { position: relative; display: grid; grid-template-rows: auto minmax(0, 1fr); grid-template-columns: minmax(0, 1fr) auto; width: 100%; height: 100dvh; overflow: hidden; container: main-content / inline-size; }
  .apps-route-header { grid-column: 1 / -1; }
  .apps-route-body { display: flex; position: relative; grid-row: 2; grid-column: 1; min-height: 0; }
  main { flex: 1; min-width: 0; min-height: 0; position: relative; }
  .settings-pane { grid-row: 2; grid-column: 2; min-height: 0; width: 0; overflow: hidden; }
  .settings-open .settings-pane { width: 400px; }
  .apps-auth-layer { position: absolute; inset: 0; z-index: var(--z-index-modal,200); overflow: auto; background: var(--color-grey-0); }
  .auth-close { position: absolute; top: var(--spacing-4); right: var(--spacing-4); z-index: 1; border: 0; border-radius: 50%; background: var(--color-grey-10); color: var(--color-font-primary); font-size: 1.5rem; width: 2.5rem; height: 2.5rem; cursor: pointer; }
  @media(max-width: 1100px) { .settings-open .settings-pane { width: 0; } }
</style>
