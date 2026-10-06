<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  onMount(() => {
    const inviteId = page.params.inviteId;
    const params = new URLSearchParams(window.location.hash.slice(1));
    const secret = params.get('key') ?? params.get('invite_token');
    // The invite fragment is kept only in this tab for the authenticated settings handoff.
    // It never enters a URL query, REST body, server log, or persistent localStorage.
    if (secret && /^[A-Za-z0-9_-]{43}$/.test(secret)) {
      sessionStorage.setItem(`openmates:team-invite:${inviteId}`, secret);
    }
    history.replaceState(null, '', window.location.pathname);
    void goto(`/#settings/teams/invites/${encodeURIComponent(inviteId)}`, { replaceState: true });
  });
</script>
