<script lang="ts">
  import { tick } from 'svelte';
  import type { TeamViewModel } from '../../services/teamService';
  import { orderTeamsByRecent } from '../../stores/teamStore';
  import TeamAvatar from '../teams/TeamAvatar.svelte';
  import { text } from '../../i18n/translations';

  let {
    teams, activeTeamId, disabled = false, compact = false,
    testId = 'team-context-dropdown', avatarTestId = 'profile-open-active-team-avatar',
    onTeamContextChange, onCreateTeam,
  }: {
    teams: TeamViewModel[];
    activeTeamId: string | null;
    disabled?: boolean;
    compact?: boolean;
    testId?: string;
    avatarTestId?: string;
    onTeamContextChange: (contextId: string) => void;
    onCreateTeam: () => void;
  } = $props();

  let open = $state(false);
  let mounted = $state(false);
  let closeTimer: ReturnType<typeof setTimeout> | undefined;
  let expanded = $state(false);
  let recentVersion = $state(0);
  let trigger: HTMLButtonElement;
  let menu: HTMLElement | undefined = $state();
  let menuTop = $state(0);
  let menuLeft = $state(0);
  let menuWidth = $state(185);
  let orderedTeams = $derived.by(() => { void recentVersion; return orderTeamsByRecent(teams); });
  let visibleTeams = $derived(expanded ? orderedTeams : orderedTeams.slice(0, 5));
  let activeTeam = $derived(teams.find(team => team.team_id === activeTeamId) ?? null);

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy() { node.remove(); } };
  }

  function placeMenu() {
    if (!trigger) return;
    const bounds = trigger.getBoundingClientRect();
    menuWidth = Math.max(185, bounds.width);
    menuLeft = Math.max(8, Math.min(bounds.left, window.innerWidth - menuWidth - 8));
    const roomBelow = window.innerHeight - bounds.bottom;
    const expectedHeight = menu?.offsetHeight ?? 157;
    menuTop = roomBelow >= expectedHeight || bounds.top < expectedHeight
      ? bounds.bottom + 6 : Math.max(8, bounds.top - expectedHeight - 6);
  }

  async function openMenu(focusFirst = false) {
    if (disabled) return;
    if (closeTimer) clearTimeout(closeTimer);
    expanded = false;
    recentVersion++;
    mounted = true;
    open = true;
    await tick();
    placeMenu();
    if (focusFirst) menu?.querySelector<HTMLButtonElement>('[role="menuitemradio"]')?.focus();
  }

  function closeMenu(returnFocus = false) {
    open = false;
    expanded = false;
    if (closeTimer) clearTimeout(closeTimer);
    const duration = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180;
    closeTimer = setTimeout(() => { mounted = false; closeTimer = undefined; }, duration);
    if (returnFocus) trigger?.focus();
  }

  $effect(() => () => { if (closeTimer) clearTimeout(closeTimer); });

  function select(contextId: string) {
    if (contextId !== (activeTeamId ?? 'personal')) onTeamContextChange(contextId);
    recentVersion++;
    closeMenu(true);
  }

  function onDocumentPointer(event: PointerEvent) {
    if (open && !trigger?.contains(event.target as Node) && !menu?.contains(event.target as Node)) closeMenu();
  }

  function onDocumentKey(event: KeyboardEvent) {
    if (!open) return;
    if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); return; }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const options = [...(menu?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])];
    if (!options.length) return;
    event.preventDefault();
    const index = options.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
      : event.key === 'ArrowDown' ? (index + 1) % options.length
        : (index - 1 + options.length) % options.length;
    options[next].focus();
  }

  $effect(() => {
    if (!open) return;
    document.addEventListener('pointerdown', onDocumentPointer);
    document.addEventListener('keydown', onDocumentKey);
    window.addEventListener('resize', placeMenu);
    window.addEventListener('scroll', placeMenu, true);
    return () => {
      document.removeEventListener('pointerdown', onDocumentPointer);
      document.removeEventListener('keydown', onDocumentKey);
      window.removeEventListener('resize', placeMenu);
      window.removeEventListener('scroll', placeMenu, true);
    };
  });

  $effect(() => { if (disabled && open) closeMenu(); });
</script>

<button
  bind:this={trigger}
  type="button"
  class="team-context-trigger"
  class:compact
  data-testid={testId}
  aria-label={$text('settings.switch_team_context')}
  aria-haspopup="menu"
  aria-expanded={open}
  disabled={disabled}
  onclick={event => open ? closeMenu(true) : void openMenu(event.detail === 0)}
  onkeydown={event => { if (event.key === 'ArrowDown' && !open) { event.preventDefault(); void openMenu(true); } }}
>
  {#if activeTeam}<TeamAvatar team={activeTeam} size={24} testId={avatarTestId} />
  {:else if compact}<span class="personal-avatar" aria-hidden="true"></span>{/if}
  <span class="team-context-name">{activeTeam?.name || $text('settings.personal_context')}</span>
  <span class="chevron" aria-hidden="true"></span>
</button>

{#if mounted}
  <div
    use:portal
    bind:this={menu}
    class="team-context-menu"
    class:closing={!open}
    data-testid="team-context-menu"
    role="menu"
    aria-label={$text('settings.switch_team_context')}
    style:top={`${menuTop}px`}
    style:left={`${menuLeft}px`}
    style:width={`${menuWidth}px`}
  >
    {#each visibleTeams as team (team.team_id)}
      <button type="button" role="menuitemradio" aria-checked={activeTeamId === team.team_id} data-testid={`team-context-option-${team.team_id}`} onclick={() => select(team.team_id)}>
        <TeamAvatar {team} size={39} /><span>{team.name || $text('settings.teams_ui.untitled_team')}</span>
      </button>
    {/each}
    <button type="button" role="menuitemradio" aria-checked={activeTeamId === null} data-testid="team-context-personal" onclick={() => select('personal')}>
      <span class="personal-avatar" aria-hidden="true"></span><span>{$text('settings.personal_context')}</span>
    </button>
    {#if orderedTeams.length > 5 && !expanded}
      <button type="button" role="menuitem" data-testid="team-context-show-more" onclick={() => { expanded = true; void tick().then(placeMenu); }}>{$text('settings.show_more_teams')}</button>
    {/if}
    <button class="new-team-option" type="button" role="menuitem" data-testid="team-context-new-team" onclick={() => { closeMenu(); onCreateTeam(); }}>
      <span class="new-team-icon" aria-hidden="true"></span><span>{$text('settings.teams_ui.new_team')}</span>
    </button>
  </div>
{/if}

<style>
  .team-context-trigger {
    display: inline-flex; align-items: center; gap: var(--spacing-2);
    max-width: 15rem; min-height: var(--spacing-16); padding: var(--spacing-1) var(--spacing-5);
    color: var(--color-font-button); background: var(--color-primary);
    border: 1px solid color-mix(in srgb, var(--color-font-button) 42%, transparent);
    border-radius: var(--radius-full); font: inherit; font-size: var(--font-size-xs); font-weight: 700;
    cursor: pointer;
  }
  .team-context-trigger:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
  .team-context-trigger.compact { min-width: var(--spacing-24); justify-content: center; padding: var(--spacing-1); background: var(--color-primary); border-color: transparent; }
  .team-context-trigger.compact .team-context-name { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
  .team-context-name { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .chevron { width: 0.45rem; height: 0.45rem; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: translateY(-2px) rotate(45deg); }
  .team-context-menu {
    position: fixed; z-index: 10000; box-sizing: border-box;
    max-height: min(30rem, calc(100vh - 1rem)); overflow-y: auto;
    display: flex; flex-direction: column; gap: 12px;
    padding: 13px 13px 17px; border: 0;
    border-radius: 22px; background: var(--color-primary); color: var(--color-font-button);
    font-family: var(--font-primary); font-size: 16px; font-weight: 700; line-height: 1.25;
    box-shadow: var(--shadow-picker);
    transform-origin: top; animation: picker-open 180ms ease-out both;
  }
  .team-context-menu > button { min-width: 0; margin: 0; filter: none; scale: 1; box-sizing: border-box; height: auto;
    display: flex; align-items: center; justify-content: flex-start; gap: 7px; width: 100%; min-height: 39px;
    padding: 0; border: 0; border-radius: 10px;
    color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer;
  }
  .team-context-menu > button > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .team-context-menu button:hover, .team-context-menu button:focus-visible { background: color-mix(in srgb, var(--color-font-button) 13%, transparent); outline: none; }
  .team-context-menu button[aria-checked="true"] { color: var(--color-font-button); }
  .team-context-menu.closing { pointer-events: none; animation: picker-close 180ms ease-in both; }
  .team-context-menu > button.new-team-option { margin-top: 3px; min-height: 22px; padding-left: 8px; gap: 16px; color: color-mix(in srgb, var(--color-font-button) 70%, transparent); }
  .new-team-icon { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; flex: none; }
  .new-team-icon::before { content: ''; width: 22px; height: 22px; background: currentColor; mask: url('@openmates/ui/static/icons/create.svg') center / contain no-repeat; }
  .personal-avatar { display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; flex: none; border-radius: 50%; background: color-mix(in srgb, var(--color-font-button) 15%, transparent); }
  .personal-avatar::before { content: ''; width: 70%; height: 70%; background: var(--color-font-button); mask: url('@openmates/ui/static/icons/user.svg') center / contain no-repeat; }
  .team-context-menu .personal-avatar { width: 39px; height: 39px; }
  @keyframes picker-open { from { opacity: 0; transform: translateY(-4px) scale(0.98); } to { opacity: 1; transform: none; } }
  @keyframes picker-close { from { opacity: 1; transform: none; } to { opacity: 0; transform: translateY(-4px) scale(0.98); } }
  @media (prefers-reduced-motion: reduce) { .team-context-menu, .team-context-menu.closing { animation: none; } }
</style>
