<!--
  SettingsMainHeader.svelte

  Gradient banner for the main settings page (activeSettingsView === 'main').
  Mirrors the collapsing animation of AppDetailsHeader but shows the user's
  profile picture + username instead of an app icon + title.

  Visual structure:
  EXPANDED (scrollTop = 0):
  ┌──────────────────────────────────────────────┐  200px (mobile: 170px)
  │          [avatar 56×56]                      │  ← user avatar (centered)
  │          Username (20px bold, white)         │  ← name centered below avatar
  │          ● 1 234 credits (clickable)         │  ← credits clickable → billing
  └──────────────────────────────────────────────┘

  COLLAPSED (scrollTop ≥ COLLAPSE_THRESHOLD):
  ┌──────────────────────────────────────────────┐  72px
  │  [avatar 32px]  Username (17px, left)        │  ← avatar + name in a row
  └──────────────────────────────────────────────┘

  Props:
    username          - display name of the logged-in user
    profileImageUrl   - URL of the user's profile image (optional)
    isAuthenticated   - true when user is logged in
    credits           - credits count (hidden when paymentEnabled=false)
    paymentEnabled    - whether credits/billing are available
    scrollTop         - current scroll position of .settings-content-wrapper
    onBillingClick    - callback fired when the user clicks the credits count
-->
<script lang="ts">
    import { text } from '@repo/ui';

    // ─── Props ────────────────────────────────────────────────────────────────

    interface Props {
        username?: string;
        profileImageUrl?: string;
        isAuthenticated?: boolean;
        credits?: number;
        paymentEnabled?: boolean;
        scrollTop?: number;
        onBillingClick?: () => void;
        /** Callback fired when the user clicks their profile image → deep links to profile picture settings */
        onAvatarClick?: () => void;
        /** Callback fired when the user clicks their username → deep links to username settings */
        onUsernameClick?: () => void;
    }

    let {
        username = 'Guest',
        profileImageUrl = '',
        isAuthenticated = false,
        credits = 0,
        paymentEnabled = true,
        scrollTop = 0,
        onBillingClick,
        onAvatarClick,
        onUsernameClick,
    }: Props = $props();

    // ─── Collapse animation ───────────────────────────────────────────────────

    /** Scroll distance (px) after which the header is fully collapsed. */
    const COLLAPSE_THRESHOLD = 60;

    /** Smooth ease-in-out cubic progress: 0 = expanded, 1 = collapsed */
    let collapseProgress = $derived.by(() => {
        const raw = Math.min(1, Math.max(0, scrollTop / COLLAPSE_THRESHOLD));
        return raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
    });

    /** Expanded height: 240px desktop / 190px mobile (matches AppDetailsHeader). Collapsed: 72px. */
    const COLLAPSED_HEIGHT = 72;
    const EXPANDED_HEIGHT_DESKTOP = 240;
    const EXPANDED_HEIGHT_MOBILE = 190;

    let expandedHeight = $derived.by(() => {
        if (typeof window === 'undefined') return EXPANDED_HEIGHT_DESKTOP;
        return window.innerWidth <= 730 ? EXPANDED_HEIGHT_MOBILE : EXPANDED_HEIGHT_DESKTOP;
    });

    /** Height: expandedHeight → 72px */
    let headerHeight = $derived(
        Math.round(expandedHeight - (expandedHeight - COLLAPSED_HEIGHT) * collapseProgress)
    );

    /** Whether the header is in collapsed (row) layout. */
    let isCollapsed = $derived(collapseProgress > 0.5);

    /** Avatar size: 56px (expanded) → 32px (collapsed). */
    let avatarSize = $derived(Math.round(56 - 24 * collapseProgress));

    /** Name font size: 20px (expanded) → 17px (collapsed). */
    let nameFontSize = $derived(Math.round(20 - 3 * collapseProgress));

    // ─── Credits formatting ───────────────────────────────────────────────────

    /** Format credits with dots as thousand separators, e.g. 1.234.567 */
    let formattedCredits = $derived(
        credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.')
    );
</script>

<div
    class="settings-main-header app-details-header"
    style="height: {headerHeight}px; background: var(--color-app-openmates, var(--color-primary)); --orb-color-a: #3b4fbf; --orb-color-b: #7ba0f7;"
>
    <!-- Living gradient orbs — three morphing radial-gradient blobs.
         Uses the banner-sized orbDrift keyframes (same as ChatHeader, 240px banner). -->
    <div class="settings-header-orbs" aria-hidden="true">
        <div class="orb orb-1"></div>
        <div class="orb orb-2"></div>
        <div class="orb orb-3"></div>
    </div>

    <!-- ── Identity block: column (expanded) ↔ row (collapsed) ── -->
    <div
        class="identity-block"
        class:collapsed={collapseProgress > 0.5}
        style="
            flex-direction: {collapseProgress > 0.5 ? 'row' : 'column'};
            justify-content: {collapseProgress > 0.5 ? 'flex-start' : 'center'};
            padding: {collapseProgress > 0.5 ? '0 16px' : '16px 16px 4px'};
            gap: {collapseProgress > 0.5 ? '12px' : '8px'};
        "
    >
        <!-- User avatar — clickable for authenticated users (deep links to profile picture settings) -->
        {#if isAuthenticated}
            <button
                class="avatar-slot avatar-slot-clickable"
                style="width: {avatarSize}px; height: {avatarSize}px;"
                type="button"
                onclick={onAvatarClick}
                aria-label={$text('settings.account.profile_picture')}
            >
                {#if profileImageUrl}
                    <div
                        class="avatar-circle avatar-circle-img"
                        style="width: {avatarSize}px; height: {avatarSize}px;"
                    >
                        <img
                            class="avatar-img"
                            src={profileImageUrl}
                            alt="Profile"
                            style="width: {avatarSize}px; height: {avatarSize}px;"
                        />
                    </div>
                {:else}
                    <div class="avatar-circle default-avatar" style="width: {avatarSize}px; height: {avatarSize}px;">
                        <div class="default-user-icon"></div>
                    </div>
                {/if}
            </button>
        {:else}
            <div
                class="avatar-slot"
                style="width: {avatarSize}px; height: {avatarSize}px;"
            >
                <!-- Guest: user icon with primary-color background -->
                <div class="avatar-circle guest-avatar" style="width: {avatarSize}px; height: {avatarSize}px;">
                    <div class="guest-user-icon"></div>
                </div>
            </div>
        {/if}

        <!-- Name + credits stacked vertically when expanded -->
        <div
            class="name-credits-block"
            class:name-credits-block-row={collapseProgress > 0.5}
        >
            {#if isAuthenticated}
                <button
                    class="username-label username-label-clickable"
                    class:username-label-row={collapseProgress > 0.5}
                    style="font-size: {nameFontSize}px;"
                    type="button"
                    onclick={onUsernameClick}
                    aria-label={$text('settings.account.username')}
                >{username || 'Guest'}</button>
            {:else}
                <span
                    class="username-label"
                    class:username-label-row={collapseProgress > 0.5}
                    style="font-size: {nameFontSize}px;"
                >{username || 'Guest'}</span>
            {/if}

            <!-- Credits: always visible when authenticated AND payment is enabled.
                 Expanded: centered below username. Collapsed: inline next to username. -->
            {#if isAuthenticated && paymentEnabled}
                <div class="credits-row credits-container" class:credits-row-collapsed={isCollapsed}>
                    <button
                        class="credits-button"
                        class:credits-button-collapsed={isCollapsed}
                        onclick={onBillingClick}
                        type="button"
                        aria-label={$text('settings.billing')}
                    >
                        <span class="credits-coin-icon" class:credits-coin-icon-collapsed={isCollapsed}></span>
                        <span class="credits-amount" class:credits-amount-collapsed={isCollapsed}>{$text('settings.credits_amount').replace('{credits_amount}', formattedCredits)}</span>
                    </button>
                </div>
            {/if}
        </div>
    </div>
</div>

<style>
    /* ─── Container ─────────────────────────────────────────────────────────── */

    .settings-main-header {
        /* Height driven by inline style */
        position: relative;
        width: 100%;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        border-radius: 0 0 14px 14px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
        flex-shrink: 0;
        user-select: none;
        pointer-events: none;
        /* Smooth height animation as user scrolls */
        transition: height 0.15s cubic-bezier(0.4, 0, 0.2, 1);
    }

    /* ─── Living gradient orbs ─────────────────────────────────────────────── */
    /* Shared keyframes (orbMorph1/2/3, orbDrift1/2/3) in animations.css.        */

    .settings-header-orbs {
        position: absolute;
        inset: 0;
        z-index: var(--z-index-base);
        pointer-events: none;
        overflow: hidden;
        border-radius: 0 0 14px 14px; /* match banner border-radius */
    }

    .orb {
        position: absolute;
        width: 220px;
        height: 220px;
        opacity: 0.75;
        filter: blur(24px);
    }

    /* Orb 1 — color-b (end), top-left anchor */
    .orb-1 {
        top: -60px;
        left: -40px;
        background: radial-gradient(
            ellipse at center,
            var(--orb-color-b, #fff) 0%,
            var(--orb-color-b, #fff) 40%,
            transparent 85%
        );
        animation:
            orbMorph1 11s ease-in-out infinite,
            orbDrift1 19s ease-in-out infinite;
    }

    /* Orb 2 — color-a (start), bottom-right anchor */
    .orb-2 {
        bottom: -60px;
        right: -40px;
        background: radial-gradient(
            ellipse at center,
            var(--orb-color-a, #fff) 0%,
            var(--orb-color-a, #fff) 40%,
            transparent 85%
        );
        animation:
            orbMorph2 13s ease-in-out infinite,
            orbDrift2 23s ease-in-out infinite;
    }

    /* Orb 3 — color-b (end), center-right for depth */
    .orb-3 {
        top: 20px;
        right: 20%;
        background: radial-gradient(
            ellipse at center,
            var(--orb-color-b, #fff) 0%,
            var(--orb-color-b, #fff) 40%,
            transparent 85%
        );
        animation:
            orbMorph3 17s ease-in-out infinite,
            orbDrift3 29s ease-in-out infinite;
    }

    @media (prefers-reduced-motion: reduce) {
        .orb { animation: none; }
    }

    /* ─── Identity block ─────────────────────────────────────────────────────── */

    .identity-block {
        display: flex;
        flex: 1;
        align-items: center;
        position: relative;
        z-index: var(--z-index-raised);
        transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .avatar-slot {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: width var(--duration-fast), height var(--duration-fast);
    }

    /* Clickable avatar: reset button styles and add hover highlight ring */
    .avatar-slot-clickable {
        all: unset;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        pointer-events: auto;
        border-radius: 50%;
        padding: 3px;
        margin: -3px;
        transition: width var(--duration-fast), height var(--duration-fast), background-color var(--duration-fast) var(--easing-default);
    }

    .avatar-slot-clickable:hover {
        background-color: rgba(255, 255, 255, 0.15);
    }

    .avatar-slot-clickable:active {
        background-color: rgba(255, 255, 255, 0.25);
    }

    /* ─── Avatar variants ─────────────────────────────────────────────────────── */

    .avatar-circle {
        border-radius: 50%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        /* Semi-transparent white overlay so profile image reads well on the gradient */
        background-color: rgba(255, 255, 255, 0.2);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: width var(--duration-fast), height var(--duration-fast);
    }

    /* Profile image avatar: overflow hidden so the <img> is clipped to the circle */
    .avatar-circle-img {
        overflow: hidden;
    }

    .avatar-img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 50%;
    }

    /* Guest avatar: slightly more opaque white so the icon shows */
    .guest-avatar {
        background-color: rgba(255, 255, 255, 0.25);
    }

    .guest-user-icon {
        width: 55%;
        height: 55%;
        -webkit-mask-image: url('@openmates/ui/static/icons/user.svg');
        -webkit-mask-size: contain;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-image: url('@openmates/ui/static/icons/user.svg');
        mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        background-color: rgba(255, 255, 255, 0.9);
    }

    .default-avatar {
        background-color: rgba(255, 255, 255, 0.2);
    }

    .default-user-icon {
        width: 55%;
        height: 55%;
        -webkit-mask-image: url('@openmates/ui/static/icons/user.svg');
        -webkit-mask-size: contain;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-image: url('@openmates/ui/static/icons/user.svg');
        mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        background-color: rgba(255, 255, 255, 0.9);
    }

    /* ─── Name + credits stack ────────────────────────────────────────────────── */

    .name-credits-block {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--spacing-2);
    }

    /* In row (collapsed) mode, align left */
    .name-credits-block-row {
        align-items: flex-start;
        justify-content: center;
    }

    .username-label {
        font-weight: 700;
        color: var(--color-grey-0);
        line-height: 1.25;
        text-align: center;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 260px;
        transition: font-size var(--duration-fast);
    }

    /* Clickable username: reset button styles and add hover highlight */
    .username-label-clickable {
        all: unset;
        font-weight: 700;
        color: var(--color-grey-0);
        line-height: 1.25;
        text-align: center;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 260px;
        transition: font-size var(--duration-fast), background-color var(--duration-fast) var(--easing-default);
        cursor: pointer;
        pointer-events: auto;
        border-radius: var(--radius-2);
        padding: var(--spacing-1) var(--spacing-4);
        margin: -2px -8px;
    }

    .username-label-clickable:hover {
        background-color: rgba(255, 255, 255, 0.15);
    }

    .username-label-clickable:active {
        background-color: rgba(255, 255, 255, 0.25);
    }

    /* In row mode: left-aligned, single line */
    .username-label-row {
        text-align: left;
    }

    /* ─── Credits ──────────────────────────────────────────────────────────────── */

    .credits-row {
        display: flex;
        align-items: center;
        pointer-events: auto; /* Re-enable despite parent pointer-events:none */
    }

    /* Collapsed: tighter spacing so it fits in the 72px-high row layout */
    .credits-row-collapsed {
        margin-top: -2px;
    }

    .credits-button {
        all: unset;
        display: flex;
        align-items: center;
        gap: var(--spacing-3);
        cursor: pointer;
        pointer-events: auto;
        border-radius: var(--radius-2);
        padding: 3px 6px;
        transition: background-color var(--duration-fast) var(--easing-default);
    }

    .credits-button-collapsed {
        gap: var(--spacing-2);
        padding: 2px 5px;
    }

    .credits-button:hover {
        background-color: rgba(255, 255, 255, 0.15);
    }

    .credits-button:active {
        background-color: rgba(255, 255, 255, 0.25);
    }

    .credits-coin-icon {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
        -webkit-mask-image: url('@openmates/ui/static/icons/coins.svg');
        -webkit-mask-size: cover;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-image: url('@openmates/ui/static/icons/coins.svg');
        mask-size: cover;
        mask-position: center;
        mask-repeat: no-repeat;
        /* White icon on the gradient background */
        background: rgba(255, 255, 255, 0.9);
    }

    .credits-coin-icon-collapsed {
        width: 13px;
        height: 13px;
    }

    .credits-amount {
        color: var(--color-grey-0);
        font-size: null;
        font-weight: 600;
        line-height: 1.2;
        text-decoration: none;
    }

    .credits-amount-collapsed {
        font-size: var(--font-size-xs);
    }

    /* ─── Mobile adjustments ─────────────────────────────────────────────────── */

    @media (max-width: 730px) {
        .username-label {
            max-width: 200px;
        }
    }
</style>
