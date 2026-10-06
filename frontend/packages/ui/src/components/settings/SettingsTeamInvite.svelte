<script lang="ts">
  import { get } from 'svelte/store';
  import { text } from '@repo/ui';
  import { userProfile } from '../../stores/userProfile';
  import { acceptTeamInviteFromFragment, declineTeamInvite } from '../../services/teamService';
  import { TEAMS_UPDATED_EVENT } from '../../stores/teamStore';
  import TeamInviteForm from './TeamInviteForm.svelte';
  let { activeSettingsView }: { activeSettingsView: string } = $props();
  let status = $state<'ready' | 'accepting' | 'joined' | 'pending' | 'missing-key' | 'error' | 'declined'>('ready');
  let email = $state('');
  let error = $state('');
  let secret: string | null = null;
  let generation = 0;
  const inviteId = $derived(activeSettingsView.split('/')[2] ?? '');
  const storageKey = $derived(`openmates:team-invite:${inviteId}`);

  $effect(() => {
    if (typeof sessionStorage === 'undefined') return;
    secret = sessionStorage.getItem(storageKey);
    status = secret ? 'ready' : 'missing-key';
    email = '';
    error = '';
    return () => { generation += 1; secret = null; };
  });

  async function respond(accept: boolean): Promise<void> {
    if (!secret || status === 'accepting') return;
    const operation = ++generation;
    const accountId = get(userProfile).user_id;
    const operationStorageKey = storageKey;
    status = 'accepting';
    error = '';
    try {
      let nextStatus: 'declined' | 'joined' | 'pending' = 'declined';
      if (accept) {
        const result = await acceptTeamInviteFromFragment(inviteId, secret, email);
        nextStatus = ['joined', 'active', 'accepted'].includes(result.status) ? 'joined' : 'pending';
      } else await declineTeamInvite(inviteId, email);
      if (operation !== generation || accountId !== get(userProfile).user_id) return;
      status = nextStatus;
      sessionStorage.removeItem(operationStorageKey);
      secret = null;
      window.dispatchEvent(new Event(TEAMS_UPDATED_EVENT));
    } catch (caught) {
      if (operation !== generation || accountId !== get(userProfile).user_id) return;
      console.error('[TeamInvite] Acceptance or decline failed');
      status = 'error';
      error = caught instanceof Error ? caught.message : $text('settings.team_invitation.failed');
    }
  }
</script>

<TeamInviteForm {status} {error} bind:email onAccept={() => void respond(true)} onDecline={() => void respond(false)} />
