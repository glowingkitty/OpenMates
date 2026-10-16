<!-- Account-free fixture using the actual header and collapsing status component. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import Header from './Header.svelte';
  import ConnectionStatusSlot from './ConnectionStatusSlot.svelte';
  import profileImage from '../../static/images/placeholders/userprofileimage.jpeg';
  import { externalLinks } from '../config/links';
  import type { ConnectionFeedbackState } from '../stores/connectionFeedbackStore';

  interface Props {
    state: ConnectionFeedbackState;
    label: string;
    retryLabel: string;
    onReconnect: () => void;
    companion?: 'github' | 'referral';
  }

  let { state: initialState, label, retryLabel, onReconnect, companion = 'github' }: Props = $props();
  let animatedState = $state<Props['state'] | undefined>();
  let displayedState = $derived(animatedState ?? initialState);
  let displayedLabel = $derived(animatedState === 'offline' ? 'You are offline' : animatedState === 'syncing' ? 'Syncing chats' : animatedState === 'reconnecting' ? 'Reconnecting to server' : label);

  // The fixture event exercises transitions without a navigation/reload between states.
  onMount(() => {
    const changeState = (event: Event) => {
      const next = (event as CustomEvent<Props['state']>).detail;
      if (['idle', 'offline', 'reconnecting', 'syncing'].includes(next)) animatedState = next;
    };
    window.addEventListener('openmates-preview-connection-state', changeState);
    return () => window.removeEventListener('openmates-preview-connection-state', changeState);
  });
</script>

<div class="connection-status-preview" data-testid="connection-status-preview">
  <Header context="webapp" isLoggedIn={true} connectionStatusVisible={displayedState !== 'idle'} />
  <div class="profile-actions">
    {#if companion === 'github'}
      <a
        class="companion-control"
        href={externalLinks.github}
        aria-label="Open OpenMates GitHub repository"
        data-testid="preview-companion-control"
      ><span class="companion-icon github-icon" aria-hidden="true"></span></a>
    {:else}
      <!-- Existing compact referral control represented without a server action. -->
      <span class="companion-control" role="img" aria-label="Get free credits" data-testid="preview-companion-control">
        <span class="companion-icon referral-icon" aria-hidden="true"></span>
      </span>
    {/if}
    <ConnectionStatusSlot state={displayedState} label={displayedLabel} {retryLabel} {onReconnect} />
    <img class="profile-image" src={profileImage} alt="Profile" data-testid="preview-profile-image" />
  </div>
</div>

<style>
  .connection-status-preview {
    position: relative;
    width: 100%;
    height: 100%;
    background: var(--color-grey-0);
  }

  /* Keep the bare recording at the actual viewport width, including phone layouts. */
  :global(.capture-mode .preview-container:has(.connection-status-preview)) {
    padding: 0;
  }

  .profile-actions {
    position: absolute;
    top: 8px;
    inset-inline-end: 10px;
    display: flex;
    align-items: center;
    gap: 0;
    z-index: var(--z-index-popover-above);
  }

  .profile-image {
    margin-inline-start: 8px;
    width: 50px;
    height: 50px;
    border-radius: 50%;
    object-fit: cover;
    box-shadow: var(--shadow-xs);
  }

  .companion-control {
    width: 42px;
    height: 42px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-full);
  }

  .companion-control:focus-visible {
    outline: 2px solid var(--color-warning);
    outline-offset: 2px;
  }

  .companion-icon {
    width: 22px;
    height: 22px;
    background: var(--color-primary);
    mask-position: center;
    mask-size: contain;
    mask-repeat: no-repeat;
  }

  .github-icon { mask-image: url('@openmates/ui/static/icons/github.svg'); }
  .referral-icon { mask-image: url('@openmates/ui/static/icons/gift.svg'); }

</style>
