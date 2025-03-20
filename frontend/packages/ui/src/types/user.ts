/**
 * User interface representing the authenticated user
 */
export interface User {
    id?: string;
    username?: string;
    isAdmin?: boolean;
    profileImageUrl?: string | null;
    last_opened?: string;
    [key: string]: any; // Allow additional properties
}
