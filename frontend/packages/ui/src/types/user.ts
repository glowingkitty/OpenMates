/**
 * User interface representing the authenticated user
 */
export interface User {
    id: string;
    username: string;
    isAdmin: boolean;
    profileImageUrl?: string | null;
    email?: string;
}
