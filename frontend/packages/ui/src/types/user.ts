/**
 * User interface representing the authenticated user
 */
export interface User {
    id?: string;
    username?: string;
    isAdmin?: boolean;
    profileImageUrl?: string | null;
    last_opened?: string;
    tfaAppName?: string | null; // Explicitly define
    tfa_enabled?: boolean; // Explicitly define
    [key: string]: any; // Allow additional properties (can be kept or removed if strict typing is desired)
}
