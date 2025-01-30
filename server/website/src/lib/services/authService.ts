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
            console.log('Attempting login with email:', email);
            const formData = new FormData();
            formData.append('username', email);
            formData.append('password', password);

            console.log('Making fetch request to:', `${API_BASE_URL}/v1/auth/login`);
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
            console.log('Response headers:', [...response.headers.entries()]);

            if (!response.ok) {
                const error = await response.json().catch(e => ({ detail: 'Could not parse error response' }));
                console.error('Error response:', error);
                throw new Error(error.detail || 'Login failed');
            }

            const data = await response.json();
            console.log('Login successful, received data:', data);
            return {
                user: {
                    email: email
                }
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