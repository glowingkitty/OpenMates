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
    static async refreshToken(): Promise<boolean> {
        try {
            const response = await fetch(`${API_BASE_URL}/v1/auth/refresh`, {
                method: 'POST',
                credentials: 'include'
            });

            if (!response.ok) {
                throw new Error('Token refresh failed');
            }

            return true;
        } catch (error) {
            console.error('Token refresh failed:', error);
            return false;
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
    static async checkAuth(): Promise<boolean> {
        try {
            // Try to refresh token
            return await this.refreshToken();
        } catch {
            return false;
        }
    }
} 