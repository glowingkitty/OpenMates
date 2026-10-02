<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Header, Settings, NotificationStack, Login, text, authStore, userProfile, setAuthenticatedState, panelState, settingsDeepLink, isInSignupProcess, currentSignupStep, STEP_ALPHA_DISCLAIMER, focusTrap } from '@repo/ui';
  import { loginInterfaceOpen } from '@repo/ui/stores/uiStateStore';
  import AppsWorkspace from '@repo/ui/components/apps/AppsWorkspace.svelte';
  import { readAppsWorkspaceRoute } from '@repo/ui/utils/appsWorkspaceRoute';

  let authReturnHash: string | null = null;

  function rememberAuthReturn(): void {
    const hash = window.location.hash;
    if (readAppsWorkspaceRoute(hash)) authReturnHash = hash;
  }

  function navigate(hash: string): void {
    // A pending fullscreen close or request must not restore Apps after the
    // user has selected another workspace.
    if (!readAppsWorkspaceRoute(window.location.hash)) return;
    void goto(`/${hash}`, { noScroll: true, keepFocus: true });
  }
  function signup(): void { rememberAuthReturn(); currentSignupStep.set(STEP_ALPHA_DISCLAIMER); isInSignupProcess.set(true); loginInterfaceOpen.set(true); }
  function login(): void { rememberAuthReturn(); isInSignupProcess.set(false); loginInterfaceOpen.set(true); }
  function closeAuth(): void { authReturnHash = null; loginInterfaceOpen.set(false); isInSignupProcess.set(false); }
  function handleLoginSuccess(event: CustomEvent<{ user?: { id?: string }; inSignupFlow?: boolean }>): void {
    // Login's passkey path relies on its parent to publish the new session.
    // Use the same handoff as ActiveChat for every successful login method.
    // Password login hydrates the rest of the profile asynchronously after
    // this event. Publish its verified identity before direct requests unlock.
    const userId = event.detail.user?.id;
    if (userId) userProfile.update(profile => ({ ...profile, user_id: userId }));
    if (!event.detail.inSignupFlow) isInSignupProcess.set(false);
    setAuthenticatedState();
    if (event.detail.inSignupFlow) return;

    const returnHash = authReturnHash;
    closeAuth();
    if (returnHash && window.location.hash !== returnHash) {
      void goto(`/${returnHash}`, { replaceState: true, noScroll: true, keepFocus: true });
    }
  }
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

<div class="apps-route" class:settings-open={$panelState.isSettingsOpen} data-authenticated={$authStore.isAuthenticated}>
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
      <Login on:loginSuccess={handleLoginSuccess} />
    </div>
  {/if}
</div>
<NotificationStack />

<style>
  /* This frame never scrolls. Unlike hidden, clip prevents focus restoration
     during a viewport resize from scrolling the whole workspace sideways. */
  .apps-route { position: relative; display: grid; grid-template-rows: auto minmax(0, 1fr); grid-template-columns: minmax(0, 1fr) auto; width: 100%; height: 100dvh; overflow: clip; container: main-content / inline-size; }
  .apps-route-header { grid-column: 1 / -1; min-width: 0; }
  .apps-route-body { display: flex; position: relative; grid-row: 2; grid-column: 1; min-width: 0; min-height: 0; box-sizing: border-box; padding: 10px 20px 10px 10px; }
  main { flex: 1; min-width: 0; min-height: 0; position: relative; }
  .settings-pane { grid-row: 2; grid-column: 2; min-height: 0; width: 0; overflow: hidden; }
  .apps-auth-layer { position: absolute; inset: 0; z-index: var(--z-index-modal,200); overflow: auto; background: var(--color-grey-0); }
  .auth-close { position: absolute; top: var(--spacing-4); right: var(--spacing-4); z-index: 1; border: 0; border-radius: 50%; background: var(--color-grey-10); color: var(--color-font-primary); font-size: 1.5rem; width: 2.5rem; height: 2.5rem; cursor: pointer; }
  @media(min-width: 1101px) {
    .apps-route.settings-open { column-gap: 20px; }
    .settings-open .apps-route-body { padding-inline-end: 0; }
    .settings-open .settings-pane { box-sizing: border-box; width: 343px; padding: 10px 20px 10px 0; }
  }
  @media(max-width: 600px) { .apps-route-body { padding-inline-end: 10px; } }
</style>
