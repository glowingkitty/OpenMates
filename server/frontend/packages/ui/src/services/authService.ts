import { getApiEndpoint, apiEndpoints } from '../config/api';

/**
 * Service to handle authentication-related operations
 */
export class AuthService {
    /**
     * Attempt login with credentials
     */
    static async login(email: string, password: string): Promise<{status: number, user?: {email: string}}> {
        try {
            const formData = new FormData();
            formData.append('username', email.trim());  // Trim whitespace
            formData.append('password', password);

            const response = await fetch(getApiEndpoint(apiEndpoints.login.login), {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: formData,
                credentials: 'include'
            });

            // Return status 429 immediately if rate limited
            if (response.status === 429) {
                return { status: 429 };
            }

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ 
                    detail: 'Could not parse error response' 
                }));
                
                // Log more details about the error
                console.error('Login failed:', {
                    status: response.status,
                    statusText: response.statusText,
                    error: errorData
                });
                
                return { status: response.status };
            }

            await response.json();
            return {
                status: 200,
                user: { email }
            };
        } catch (error) {
            console.error('Login error:', error);
            throw error;
        }
    }

    /**
     * Refresh the access token
     */
    static async refreshToken(): Promise<{success: boolean, email?: string}> {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.login.token_refresh), {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Accept': 'application/json'
                }
            });

            if (!response.ok) {
                console.log('Token refresh failed - response not ok');
                return { success: false };
            }

            const data = await response.json();
            
            return { 
                success: true,
                email: data.email
            };
        } catch (error) {
            console.error('Token refresh failed with error:', error);
            return { success: false };
        }
    }

    /**
     * Logout user
     */
    static async logout(): Promise<void> {
        try {
            await fetch(getApiEndpoint(apiEndpoints.login.logout), {
                method: 'POST',
                credentials: 'include'
            });
        } catch (error) {
            console.error('Logout error:', error);
        }
    }

    /**
     * Check if user is authenticated
     */
    static async checkAuth(): Promise<{isAuthenticated: boolean, email?: string}> {
        try {
            // Try refresh token - let server determine if there's a valid session
            const refreshResult = await this.refreshToken();
            
            return {
                isAuthenticated: refreshResult.success,
                email: refreshResult.email
            };
        } catch (error) {
            console.error('Auth check failed:', error);
            return { isAuthenticated: false };
        }
    }
}