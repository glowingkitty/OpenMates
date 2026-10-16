<script lang="ts">
  import type { TeamViewModel } from '../../services/teamService';
  import { getApiEndpoint } from '../../config/api';
  import { getTeamAvatarBackground } from '../../utils/teamAvatar';

  const iconAssets = import.meta.glob('../../../static/icons/*.svg', {
    eager: true, query: '?url', import: 'default',
  }) as Record<string, string>;

  let { team, size = 28, testId }: { team: TeamViewModel; size?: number | string; testId?: string } = $props();
  const cssSize = $derived(typeof size === 'number' ? `${size}px` : size);
  let imageUrl = $state<string | null>(null);
  let iconName = $derived(typeof team.profileImageMetadata?.icon_name === 'string'
    && /^[a-z0-9_-]+$/.test(team.profileImageMetadata.icon_name)
    ? team.profileImageMetadata.icon_name : 'team');
  let iconUrl = $derived(iconAssets[`../../../static/icons/${iconName}.svg`]
    ?? iconAssets['../../../static/icons/team.svg']);
  let iconColor = $derived(typeof team.profileImageMetadata?.icon_color === 'string'
    && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(team.profileImageMetadata.icon_color)
    ? team.profileImageMetadata.icon_color : '#ffffff');

  // Team images are private. Fetch with the current session, then release the blob URL
  // when a Team/account switch changes the avatar or removes this component.
  $effect(() => {
    const metadata = team.profileImageMetadata;
    const expectedPath = `/v1/teams/${encodeURIComponent(team.team_id)}/profile-image`;
    const path = metadata?.mode === 'uploaded' && metadata.content_safety_status === 'accepted'
      && metadata.team_id === team.team_id
      && metadata.image_url === expectedPath ? expectedPath : null;
    imageUrl = null;
    if (!path) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    void fetch(getApiEndpoint(path), { credentials: 'include', signal: controller.signal })
      .then(async response => {
        if (!response.ok || !response.headers.get('content-type')?.startsWith('image/')) return;
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        imageUrl = objectUrl;
      })
      .catch(() => { /* Generated avatar remains the safe fallback. */ });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  });
</script>

<span
  class="team-avatar"
  data-testid={testId}
  aria-hidden="true"
  style:width={cssSize}
  style:height={cssSize}
  style:background={getTeamAvatarBackground(team)}
>
  {#if imageUrl}
    <img src={imageUrl} alt="" />
  {:else}
    <span class="team-avatar-icon" style:background={iconColor} style:mask-image={`url("${iconUrl}")`}></span>
  {/if}
</span>

<style>
  .team-avatar {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    overflow: hidden;
    border-radius: var(--radius-full);
    box-shadow: var(--shadow-xs);
  }
  .team-avatar img { width: 100%; height: 100%; object-fit: cover; }
  .team-avatar-icon {
    width: 58%; height: 58%; mask-size: contain; mask-position: center; mask-repeat: no-repeat;
  }
</style>
