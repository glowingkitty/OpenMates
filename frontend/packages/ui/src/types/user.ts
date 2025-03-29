/**
 * User interface representing the authenticated user
 */
export interface User {
    id?: string;
    username?: string;
    is_admin?: boolean;
    profile_image_url?: string | null;
    last_opened?: string;
    tfa_app_name?: string | null; // Explicitly define
    tfa_enabled?: boolean; // Explicitly define
    [key: string]: any; // Allow additional properties (can be kept or removed if strict typing is desired)
}
