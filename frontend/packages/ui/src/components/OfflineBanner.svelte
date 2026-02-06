<script lang="ts">
    /**
     * OfflineBanner.svelte
     *
     * A slim, fixed banner shown at the top of the viewport when the browser
     * reports that the device has lost network connectivity.
     *
     * It subscribes to the `isOnline` store from networkStatusStore and
     * auto-hides once the connection is restored.
     *
     * Uses the i18n translation system for user-facing text so that the
     * banner is displayed in the user's selected language.
     */
    import { isOnline } from '../stores/networkStatusStore';
    import { text } from '../i18n/translations';

    /**
     * Reactive derived value: true when the browser is offline.
     * Uses $isOnline (auto-subscribed store value).
     */
    let visible = $derived(!$isOnline);
</script>

{#if visible}
    <div class="offline-banner" role="alert" aria-live="assertive">
        <svg class="offline-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <!-- Wi-Fi off icon -->
            <line x1="1" y1="1" x2="23" y2="23"></line>
            <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"></path>
            <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"></path>
            <path d="M10.71 5.05A16 16 0 0 1 22.56 9"></path>
            <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"></path>
            <path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path>
            <line x1="12" y1="20" x2="12.01" y2="20"></line>
        </svg>
        <span class="offline-text">
            {$text('notifications.connection.offline_banner.text', { default: 'You are offline. Your chats are still available.' })}
        </span>
    </div>
{/if}

<style>
    .offline-banner {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        z-index: 10000;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        padding: 8px 16px;
        background-color: var(--color-grey-90);
        color: var(--color-grey-0);
        font-size: 13px;
        font-weight: 500;
        line-height: 1.4;
        text-align: center;
        /* Slide-down entrance animation */
        animation: slideDown 0.3s ease-out;
    }

    .offline-icon {
        flex-shrink: 0;
        opacity: 0.85;
    }

    .offline-text {
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    @keyframes slideDown {
        from {
            transform: translateY(-100%);
        }
        to {
            transform: translateY(0);
        }
    }
</style>
