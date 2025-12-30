/**
 * Unified Deep Link Handler
 * 
 * Centralizes all deep link processing to avoid collisions and ensure consistent behavior.
 * Handles all URL hash-based deep links:
 * - #chat-id={id} / #chat_id={id} - Chat deep links
 * - #settings/{path} - Settings deep links (including newsletter, email block, refunds)
 * - #signup/{step} - Signup flow deep links
 * - #embed-id={id} / #embed_id={id} - Embed deep links
 */

import { replaceState } from '$app/navigation';

export type DeepLinkType = 
    | 'chat'
    | 'settings'
    | 'signup'
    | 'embed'
    | 'unknown';

export interface DeepLinkResult {
    type: DeepLinkType;
    processed: boolean;
    requiresAuth?: boolean;
    data?: any;
}

export interface DeepLinkHandlers {
    onChat?: (chatId: string) => Promise<void>;
    onSettings?: (path: string, hash: string) => void;
    onSignup?: (step: string) => void;
    onEmbed?: (embedId: string) => Promise<void>;
    onNoHash?: () => Promise<void>; // Handler for when no hash is present
    requiresAuthentication?: (settingsPath: string) => boolean;
    isAuthenticated?: () => boolean;
    openSettings?: () => void;
    openLogin?: () => void;
    setSettingsDeepLink?: (path: string) => void;
}

/**
 * Parse a hash string to extract deep link information
 */
export function parseDeepLink(hash: string): { type: DeepLinkType; data: any } | null {
    if (!hash || !hash.startsWith('#')) {
        return null;
    }

    // Chat deep links: #chat-id={id} or #chat_id={id}
    const chatMatch = hash.match(/^#chat[-_]id=(.+)$/);
    if (chatMatch) {
        return {
            type: 'chat',
            data: { chatId: chatMatch[1] }
        };
    }

    // Settings deep links: #settings/{path}
    if (hash.startsWith('#settings')) {
        const settingsPath = hash.substring('#settings'.length);
        return {
            type: 'settings',
            data: { path: settingsPath, fullHash: hash }
        };
    }

    // Signup deep links: #signup/{step}
    if (hash.startsWith('#signup/')) {
        const step = hash.substring('#signup/'.length);
        return {
            type: 'signup',
            data: { step }
        };
    }

    // Embed deep links: #embed-id={id} or #embed_id={id}
    const embedMatch = hash.match(/^#embed[-_]id=(.+)$/);
    if (embedMatch) {
        const embedId = embedMatch[1].split('&')[0].split('?')[0]; // Remove query params
        return {
            type: 'embed',
            data: { embedId }
        };
    }

    return { type: 'unknown', data: null };
}

/**
 * Process a deep link with the provided handlers
 */
export async function processDeepLink(
    hash: string,
    handlers: DeepLinkHandlers
): Promise<DeepLinkResult> {
    // Handle empty/no hash case
    if (!hash || hash === '#') {
        if (handlers.onNoHash) {
            await handlers.onNoHash();
            return { type: 'unknown', processed: true }; // Successfully processed "no hash" case
        }
        return { type: 'unknown', processed: false };
    }

    const parsed = parseDeepLink(hash);

    if (!parsed) {
        // Still try onNoHash if hash exists but is unknown format
        if (handlers.onNoHash) {
            await handlers.onNoHash();
            return { type: 'unknown', processed: true };
        }
        return { type: 'unknown', processed: false };
    }

    switch (parsed.type) {
        case 'chat':
            if (handlers.onChat) {
                await handlers.onChat(parsed.data.chatId);
                return { type: 'chat', processed: true };
            }
            break;

        case 'settings':
            if (handlers.onSettings) {
                const settingsPath = parsed.data.path;
                
                // Check if authentication is required
                if (handlers.requiresAuthentication && handlers.isAuthenticated) {
                    const needsAuth = handlers.requiresAuthentication(settingsPath);
                    if (needsAuth && !handlers.isAuthenticated()) {
                        // Store for processing after login
                        if (typeof window !== 'undefined') {
                            sessionStorage.setItem('pendingDeepLink', hash);
                        }
                        if (handlers.openLogin) {
                            handlers.openLogin();
                        }
                        // Clear hash to keep URL clean
                        if (typeof window !== 'undefined') {
                            replaceState(window.location.pathname + window.location.search, {});
                        }
                        return { type: 'settings', processed: false, requiresAuth: true };
                    }
                }
                
                // Process settings deep link
                handlers.onSettings(settingsPath, parsed.data.fullHash);
                return { type: 'settings', processed: true, requiresAuth: false };
            }
            break;

        case 'signup':
            if (handlers.onSignup) {
                handlers.onSignup(parsed.data.step);
                return { type: 'signup', processed: true };
            }
            break;

        case 'embed':
            if (handlers.onEmbed) {
                await handlers.onEmbed(parsed.data.embedId);
                return { type: 'embed', processed: true };
            }
            break;
    }

    return { type: parsed.type, processed: false };
}

/**
 * Process settings deep link with specific logic for different settings paths
 * Similar to the original processSettingsDeepLink function
 */
export function processSettingsDeepLink(
    hash: string,
    handlers: {
        openSettings: () => void;
        setSettingsDeepLink: (path: string) => void;
    }
): void {
    const settingsPath = hash.substring('#settings'.length);
    
    handlers.openSettings();
    
    // Check for special deep links that need to keep hash in URL (like refund, newsletter confirm, etc.)
    const refundMatch = settingsPath.match(/^\/billing\/invoices\/[^\/]+\/refund$/);
    const newsletterConfirmMatch = settingsPath.match(/^\/newsletter\/confirm\/(.+)$/);
    const newsletterUnsubscribeMatch = settingsPath.match(/^\/newsletter\/unsubscribe\/(.+)$/);
    const emailBlockMatch = settingsPath.match(/^\/email\/block\/(.+)$/);
    
    if (refundMatch || newsletterConfirmMatch || newsletterUnsubscribeMatch || emailBlockMatch) {
        // These deep links keep the hash for component processing
        // Navigate to the base settings page
        if (refundMatch) {
            handlers.setSettingsDeepLink('billing/invoices');
        } else if (newsletterConfirmMatch || newsletterUnsubscribeMatch || emailBlockMatch) {
            handlers.setSettingsDeepLink('newsletter');
        }
        // Don't clear hash - component will process it
        return;
    }
    
    // Regular settings paths
    if (settingsPath.startsWith('/')) {
        let path = settingsPath.substring(1); // Remove leading slash
        // Map common aliases
        if (path === 'appstore') {
            path = 'app_store';
        }
        // Normalize hyphens to underscores for consistency (e.g., report-issue -> report_issue)
        path = path.replace(/-/g, '_');
        handlers.setSettingsDeepLink(path);
        
        // Clear the hash after processing
        if (typeof window !== 'undefined') {
            replaceState(window.location.pathname + window.location.search, {});
        }
    } else if (settingsPath === '') {
        handlers.setSettingsDeepLink('main');
        
        // Clear the hash after processing
        if (typeof window !== 'undefined') {
            replaceState(window.location.pathname + window.location.search, {});
        }
    } else {
        console.warn(`[deepLinkHandler] Invalid settings deep link hash: ${hash}`);
        handlers.setSettingsDeepLink('main');
        
        // Clear the hash after processing
        if (typeof window !== 'undefined') {
            replaceState(window.location.pathname + window.location.search, {});
        }
    }
}

