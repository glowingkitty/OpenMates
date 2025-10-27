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
        return null; // Server-side rendering guard
    }

    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);

    if (parts.length === 2) {
        const cookieValue = parts.pop()?.split(';').shift();
        return cookieValue || null;
    }

    return null;
}

/**
 * Get the auth refresh token from cookies
 * @returns The auth refresh token or null if not found
 */
export function getAuthRefreshToken(): string | null {
    return getCookie('auth_refresh_token');
}
