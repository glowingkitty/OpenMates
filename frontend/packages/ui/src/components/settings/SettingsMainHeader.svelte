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
    }

    let {
        username = 'Guest',
        profileImageUrl = '',
        isAuthenticated = false,
        credits = 0,
        paymentEnabled = true,
        scrollTop = 0,
        onBillingClick,
    }: Props = $props();

    // ─── Collapse animation ───────────────────────────────────────────────────

    /** Scroll distance (px) after which the header is fully collapsed. */
    const COLLAPSE_THRESHOLD = 60;

    /** Smooth ease-in-out cubic progress: 0 = expanded, 1 = collapsed */
    let collapseProgress = $derived.by(() => {
        const raw = Math.min(1, Math.max(0, scrollTop / COLLAPSE_THRESHOLD));
        return raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
    });

    /** Expanded height: 200px desktop / 170px mobile. Collapsed: 72px. */
    const COLLAPSED_HEIGHT = 72;
    const EXPANDED_HEIGHT_DESKTOP = 200;
    const EXPANDED_HEIGHT_MOBILE = 170;

    let expandedHeight = $derived.by(() => {
        if (typeof window === 'undefined') return EXPANDED_HEIGHT_DESKTOP;
        return window.innerWidth <= 730 ? EXPANDED_HEIGHT_MOBILE : EXPANDED_HEIGHT_DESKTOP;
    });

    /** Height: expandedHeight → 72px */
    let headerHeight = $derived(
        Math.round(expandedHeight - (expandedHeight - COLLAPSED_HEIGHT) * collapseProgress)
    );

    /**
     * Opacity for the credits row: fades out in the second half of collapse
     * (stays visible longer than the description in AppDetailsHeader).
     */
    let creditsOpacity = $derived(Math.max(0, 1 - collapseProgress * 2.5));

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
    style="height: {headerHeight}px; background: var(--color-app-openmates, var(--color-primary));"
>
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
        <!-- User avatar -->
        <div
            class="avatar-slot"
            style="width: {avatarSize}px; height: {avatarSize}px;"
        >
            {#if !isAuthenticated}
                <!-- Guest: user icon with primary-color background -->
                <div class="avatar-circle guest-avatar" style="width: {avatarSize}px; height: {avatarSize}px;">
                    <div class="guest-user-icon"></div>
                </div>
            {:else if profileImageUrl}
                <!-- Authenticated with profile image -->
                <div
                    class="avatar-circle"
                    style="width: {avatarSize}px; height: {avatarSize}px; background-image: url({profileImageUrl});"
                ></div>
            {:else}
                <!-- Authenticated without profile image: default user icon -->
                <div class="avatar-circle default-avatar" style="width: {avatarSize}px; height: {avatarSize}px;">
                    <div class="default-user-icon"></div>
                </div>
            {/if}
        </div>

        <!-- Name + credits stacked vertically when expanded -->
        <div
            class="name-credits-block"
            class:name-credits-block-row={collapseProgress > 0.5}
        >
            <span
                class="username-label"
                class:username-label-row={collapseProgress > 0.5}
                style="font-size: {nameFontSize}px;"
            >{username || 'Guest'}</span>

            <!-- Credits: only shown when payment is enabled, fades out on collapse -->
            {#if paymentEnabled}
                <div
                    class="credits-row"
                    style="opacity: {creditsOpacity}; pointer-events: {creditsOpacity < 0.05 ? 'none' : 'auto'};"
                    aria-hidden={creditsOpacity < 0.05}
                >
                    <button
                        class="credits-button"
                        onclick={onBillingClick}
                        type="button"
                        aria-label={$text('settings.billing')}
                    >
                        <span class="credits-coin-icon"></span>
                        <mark class="credits-amount">{$text('settings.credits_amount').replace('{credits_amount}', formattedCredits)}</mark>
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

    /* ─── Identity block ─────────────────────────────────────────────────────── */

    .identity-block {
        display: flex;
        flex: 1;
        align-items: center;
        transition: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .avatar-slot {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: width 0.15s, height 0.15s;
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
        transition: width 0.15s, height 0.15s;
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
        gap: 4px;
    }

    /* In row (collapsed) mode, align left */
    .name-credits-block-row {
        align-items: flex-start;
        justify-content: center;
    }

    .username-label {
        font-weight: 700;
        color: #ffffff;
        line-height: 1.25;
        text-align: center;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 260px;
        transition: font-size 0.15s;
    }

    /* In row mode: left-aligned, single line */
    .username-label-row {
        text-align: left;
    }

    /* ─── Credits ──────────────────────────────────────────────────────────────── */

    .credits-row {
        display: flex;
        align-items: center;
        transition: opacity 0.1s ease;
        pointer-events: auto; /* Re-enable despite parent pointer-events:none */
    }

    .credits-button {
        all: unset;
        display: flex;
        align-items: center;
        gap: 6px;
        cursor: pointer;
        pointer-events: auto;
        border-radius: 6px;
        padding: 3px 6px;
        transition: background-color 0.15s ease;
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

    .credits-amount {
        /* Override <mark> default yellow background */
        background: none;
        color: rgba(255, 255, 255, 0.9);
        font-size: 15px;
        font-weight: 600;
        line-height: 1.2;
        text-decoration: underline;
        text-decoration-color: rgba(255, 255, 255, 0.4);
        text-underline-offset: 2px;
    }

    /* ─── Mobile adjustments ─────────────────────────────────────────────────── */

    @media (max-width: 730px) {
        .username-label {
            max-width: 200px;
        }
    }
</style>
