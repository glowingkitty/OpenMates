// Constants for storage keys
const AUTH_TOKEN_KEY = 'auth_token';
const USER_DATA_KEY = 'user_data';

/**
 * Service to handle authentication-related operations
 */
export class AuthService {
    /**
     * Store authentication data securely
     */
    static persistAuth(token: string, userData: any): void {
        // Store token in httpOnly cookie (should be done by backend)
        // Here we'll use localStorage as a fallback, but in production
        // you should use secure httpOnly cookies set by the server
        try {
            localStorage.setItem(AUTH_TOKEN_KEY, token);
            localStorage.setItem(USER_DATA_KEY, JSON.stringify(userData));
        } catch (error) {
            console.error('Failed to persist auth data:', error);
        }
    }

    /**
     * Load stored authentication data
     */
    static loadStoredAuth(): { token: string | null; userData: any | null } {
        try {
            const token = localStorage.getItem(AUTH_TOKEN_KEY);
            const userDataStr = localStorage.getItem(USER_DATA_KEY);
            const userData = userDataStr ? JSON.parse(userDataStr) : null;
            return { token, userData };
        } catch (error) {
            console.error('Failed to load stored auth data:', error);
            return { token: null, userData: null };
        }
    }

    /**
     * Clear stored authentication data
     */
    static clearAuth(): void {
        try {
            localStorage.removeItem(AUTH_TOKEN_KEY);
            localStorage.removeItem(USER_DATA_KEY);
        } catch (error) {
            console.error('Failed to clear auth data:', error);
        }
    }

    /**
     * Validate stored token (implement proper validation logic)
     */
    static isTokenValid(token: string): boolean {
        try {
            // Basic check if token exists
            if (!token) return false;

            // If using JWT, decode and check expiration
            const tokenParts = token.split('.');
            if (tokenParts.length !== 3) return false;

            const payload = JSON.parse(atob(tokenParts[1]));
            const expirationTime = payload.exp * 1000; // Convert to milliseconds
            
            // Check if token is expired
            if (Date.now() >= expirationTime) {
                console.log('Token expired');
                return false;
            }

            return true;
        } catch (error) {
            console.error('Error validating token:', error);
            return false;
        }
    }
} 