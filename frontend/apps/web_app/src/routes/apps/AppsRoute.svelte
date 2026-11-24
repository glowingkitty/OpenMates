<script lang="ts">
  import { page } from '$app/state';
  import { goto } from '$app/navigation';
  import { Header, Settings, NotificationStack, authStore, panelState, settingsDeepLink } from '@repo/ui';
  import AppsWorkspace from '@repo/ui/components/apps/AppsWorkspace.svelte';
  import { readAppsWorkspaceRoute, withAppsWorkspaceOrigin } from '@repo/ui/utils/appsWorkspaceRoute';
  import { openGuestAccountEntry } from '@repo/ui/utils/guestAccountEntry';
  let { activeHash = page.url.hash }: { activeHash?: string } = $props();

  function navigate(hash: string): void {
    // A pending fullscreen close or request must not restore Apps after the
    // user has selected another workspace.
    if (!readAppsWorkspaceRoute(window.location.hash)) return;
    const target = withAppsWorkspaceOrigin(hash, window.location.hash);
    if (!readAppsWorkspaceRoute(target)) {
      if (target.startsWith('#')) window.location.hash = target;
      else void goto(target, { noScroll: true, keepFocus: true });
      return;
    }
    void goto(`/${target}`, { noScroll: true, keepFocus: true });
  }
  function openSettings(path: string): void { settingsDeepLink.set(path); panelState.openSettings(); }
</script>

<div class="apps-route" class:settings-open={$panelState.isSettingsOpen} data-authenticated={$authStore.isAuthenticated}>
  <div class="apps-route-header" data-testid="apps-route-header"><Header context="webapp" isLoggedIn={$authStore.isAuthenticated} onToggleSidebar={panelState.toggleChats} isSidebarOpen={$panelState.isActivityHistoryOpen} /></div>
  <div class="apps-route-body">
    <main><AppsWorkspace hash={activeHash} onNavigate={navigate} onSignup={openGuestAccountEntry} onSettings={openSettings} sidebarOpen={$panelState.isActivityHistoryOpen} onSidebarClose={panelState.closeChats} /></main>
  </div>
  <!-- Settings owns header controls as well as its panel. Keep its absolute
       header controls relative to the whole route, rather than the body. -->
  <aside class="settings-pane"><Settings isLoggedIn={$authStore.isAuthenticated} /></aside>
</div>
<NotificationStack />

<style>
  /* This frame never scrolls. Unlike hidden, clip prevents focus restoration
     during a viewport resize from scrolling the whole workspace sideways. */
  .apps-route { position: relative; display: grid; grid-template-rows: auto minmax(0, 1fr); grid-template-columns: minmax(0, 1fr) auto; width: calc(100% - 10px); margin-inline-start: 10px; height: 100dvh; overflow: clip; container: main-content / inline-size; }
  .apps-route-header { grid-column: 1 / -1; min-width: 0; }
  .apps-route-body { display: flex; position: relative; grid-row: 2; grid-column: 1; min-width: 0; min-height: 0; box-sizing: border-box; padding: 10px 20px 20px 10px; }
  main { flex: 1; min-width: 0; min-height: 0; position: relative; }
  .settings-pane { grid-row: 2; grid-column: 2; min-height: 0; width: 0; overflow: hidden; }
  @media(min-width: 1101px) {
    .apps-route.settings-open { column-gap: 20px; }
    .settings-open .apps-route-body { padding-inline-end: 0; }
    .settings-open .settings-pane { box-sizing: border-box; width: 343px; padding: 10px 20px 10px 0; }
  }
  @media(max-width: 600px) { .apps-route { width: 100%; margin-inline-start: 0; } .apps-route-body { padding-inline-end: 10px; padding-bottom: 10px; } }
</style>
