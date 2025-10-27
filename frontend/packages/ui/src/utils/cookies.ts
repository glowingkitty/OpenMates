/**
 * @file cookies.ts
 * @description Utility functions for managing cookies in the browser
 */

/**
 * Get a cookie value by name
 * @param name - The name of the cookie
 * @returns The cookie value or null if not found
 */
export function getCookie(name: string): string | null {
    if (typeof document === 'undefined') {
        console.warn('[Cookies] Cannot get cookie: document is undefined (SSR context)');
        return null; // Server-side rendering guard
    }

    const allCookies = document.cookie;
    console.debug(`[Cookies] All cookies: "${allCookies.substring(0, 100)}${allCookies.length > 100 ? '...' : ''}"`);

    const value = `; ${allCookies}`;
    const parts = value.split(`; ${name}=`);

    if (parts.length === 2) {
        const cookieValue = parts.pop()?.split(';').shift();
        console.debug(`[Cookies] Found cookie "${name}": ${cookieValue ? `"${cookieValue.substring(0, 20)}..."` : 'null'}`);
        return cookieValue || null;
    }

    console.warn(`[Cookies] Cookie "${name}" not found in document.cookie`);
    return null;
}

/**
 * Get the auth refresh token from cookies
 * NOTE: This will return null for httponly cookies (like auth_refresh_token)
 * Use getWebSocketToken() instead for WebSocket authentication
 * @returns The auth refresh token or null if not found
 */
export function getAuthRefreshToken(): string | null {
    return getCookie('auth_refresh_token');
}

/**
 * Store the WebSocket token in sessionStorage
 * This is used as a fallback for Safari iOS which doesn't send httponly cookies in WebSocket connections
 * @param token - The WebSocket auth token
 */
export function setWebSocketToken(token: string): void {
    if (typeof sessionStorage !== 'undefined') {
        sessionStorage.setItem('ws_token', token);
        console.debug('[Cookies] WebSocket token stored in sessionStorage');
    }
}

/**
 * Get the WebSocket token from sessionStorage
 * @returns The WebSocket token or null if not found
 */
export function getWebSocketToken(): string | null {
    if (typeof sessionStorage !== 'undefined') {
        const token = sessionStorage.getItem('ws_token');
        console.debug(`[Cookies] WebSocket token from sessionStorage: ${token ? 'found' : 'not found'}`);
        return token;
    }
    return null;
}

/**
 * Clear the WebSocket token from sessionStorage
 */
export function clearWebSocketToken(): void {
    if (typeof sessionStorage !== 'undefined') {
        sessionStorage.removeItem('ws_token');
        console.debug('[Cookies] WebSocket token cleared from sessionStorage');
    }
}
