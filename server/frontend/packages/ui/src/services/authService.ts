import { getApiUrl } from '../config/links';

/**
 * Service to handle authentication-related operations
 */
export class AuthService {
    /**
     * Attempt login with credentials
     */
    static async login(email: string, password: string): Promise<any> {
        try {
            const formData = new FormData();
            formData.append('username', email.trim());  // Trim whitespace
            formData.append('password', password);

            const response = await fetch(`${getApiUrl()}/v1/auth/login`, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: formData,
                credentials: 'include'
            });

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
                
                throw new Error(errorData.detail || 'Login failed');
            }

            const data = await response.json();
            console.log('Login successful');
            return {
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
            const response = await fetch(`${getApiUrl()}/v1/auth/refresh`, {
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
            await fetch(`${getApiUrl()}/v1/auth/logout`, {
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