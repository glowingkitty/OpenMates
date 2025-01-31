import { API_BASE_URL } from '../constants';

/**
 * Service to handle authentication-related operations
 */
export class AuthService {
    /**
     * Attempt login with credentials
     */
    static async login(email: string, password: string): Promise<any> {
        try {
            console.log('Attempting login...');
            const formData = new FormData();
            formData.append('username', email.trim());  // Trim whitespace
            formData.append('password', password);

            const response = await fetch(`${API_BASE_URL}/v1/auth/login`, {
                method: 'POST',
                headers: {
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: formData,
                credentials: 'include'
            });

            console.log('Response status:', response.status);

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
            console.log('Attempting to refresh token...');
            const response = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Accept': 'application/json'
                }
            });

            console.log('Refresh response status:', response.status);

            if (!response.ok) {
                console.log('Token refresh failed - response not ok');
                return { success: false };
            }

            const data = await response.json();
            console.log('Refresh token response data:', data);
            
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
            await fetch(`${API_BASE_URL}/v1/auth/logout`, {
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
            console.log('Checking authentication...');
            
            // Add delay to ensure loading state is visible for better UX
            await new Promise(resolve => setTimeout(resolve, 500));
            
            const refreshResult = await this.refreshToken();
            console.log('Auth check result:', refreshResult);
            
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