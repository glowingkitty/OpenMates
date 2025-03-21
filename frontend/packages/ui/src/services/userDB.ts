import type { User } from '../types/user';
import type { UserProfile } from '../stores/userProfile';

class UserDatabaseService {
    public db: IDBDatabase | null = null;
    public readonly DB_NAME = 'user_db';
    public readonly STORE_NAME = 'user_data';
    private readonly VERSION = 1;
    
    /**
     * Initialize the database
     */
    async init(): Promise<void> {
        console.debug("[UserDatabase] Initializing user database");
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.DB_NAME, this.VERSION);

            request.onerror = () => {
                console.error("[UserDatabase] Error opening database:", request.error);
                reject(request.error);
            };

            request.onsuccess = () => {
                console.debug("[UserDatabase] Database opened successfully");
                this.db = request.result;
                resolve();
            };

            request.onupgradeneeded = (event) => {
                console.debug("[UserDatabase] Database upgrade needed");
                const db = (event.target as IDBOpenDBRequest).result;
                
                if (!db.objectStoreNames.contains(this.STORE_NAME)) {
                    db.createObjectStore(this.STORE_NAME);
                }
            };
        });
    }

    /**
     * Save user data to IndexedDB
     */
    async saveUserData(userData: User): Promise<void> {
        if (!this.db) {
            await this.init();
        }

        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction([this.STORE_NAME], 'readwrite');
            const store = transaction.objectStore(this.STORE_NAME);
            
            console.debug("[UserDatabase] Saving user data:", {
                id: userData.id,
                username: userData.username,
                isAdmin: userData.isAdmin,
                profileImage: userData.profileImageUrl ? 'present' : 'none',
                credits: userData.credits
            });
            
            // Only store essential fields
            store.put(userData.username || '', 'username');
            store.put(!!userData.isAdmin, 'isAdmin');  // Convert to boolean
            store.put(userData.profileImageUrl || null, 'profileImageUrl');
            store.put(userData.credits || 0, 'credits');

            transaction.oncomplete = () => {
                console.debug("[UserDatabase] User data saved successfully");
                resolve();
            };

            transaction.onerror = () => {
                console.error("[UserDatabase] Error saving user data:", transaction.error);
                reject(transaction.error);
            };
        });
    }

    /**
     * Get user profile data from IndexedDB
     */
    async getUserProfile(): Promise<UserProfile | null> {
        if (!this.db) {
            await this.init();
        }

        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction([this.STORE_NAME], 'readonly');
            const store = transaction.objectStore(this.STORE_NAME);
            
            // Get username
            const usernameRequest = store.get('username');
            const profileImageRequest = store.get('profileImageUrl');
            
            let profile: UserProfile = {
                username: '',
                profileImageUrl: null
            };

            usernameRequest.onsuccess = () => {
                profile.username = usernameRequest.result || '';
            };

            profileImageRequest.onsuccess = () => {
                profile.profileImageUrl = profileImageRequest.result || null;
            };

            transaction.oncomplete = () => {
                console.debug("[UserDatabase] User profile retrieved:", profile);
                resolve(profile);
            };

            transaction.onerror = () => {
                console.error("[UserDatabase] Error retrieving user profile:", transaction.error);
                reject(transaction.error);
            };
        });
    }

    /**
     * Get user credits from IndexedDB
     */
    async getUserCredits(): Promise<number> {
        if (!this.db) {
            await this.init();
        }

        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction([this.STORE_NAME], 'readonly');
            const store = transaction.objectStore(this.STORE_NAME);
            
            const request = store.get('credits');
            
            request.onsuccess = () => {
                resolve(request.result || 0);
            };

            request.onerror = () => {
                console.error("[UserDatabase] Error retrieving user credits:", request.error);
                reject(request.error);
            };
        });
    }

    /**
     * Clear all user data from IndexedDB
     */
    async clearUserData(): Promise<void> {
        if (!this.db) {
            await this.init();
        }

        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction([this.STORE_NAME], 'readwrite');
            const store = transaction.objectStore(this.STORE_NAME);
            
            const request = store.clear();
            
            request.onsuccess = () => {
                console.debug("[UserDatabase] User data cleared successfully");
                resolve();
            };

            request.onerror = () => {
                console.error("[UserDatabase] Error clearing user data:", request.error);
                reject(request.error);
            };
        });
    }

    /**
     * Compare stored user data with new data and return if there are differences
     * @param newUserData User data to compare with stored data
     */
    async hasUserDataChanged(newUserData: Partial<User>): Promise<boolean> {
        if (!this.db) {
            await this.init();
        }

        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction([this.STORE_NAME], 'readonly');
            const store = transaction.objectStore(this.STORE_NAME);
            
            const userRequest = store.get('userData');
            
            userRequest.onsuccess = () => {
                const storedData = userRequest.result || {};
                
                const hasChanges = 
                    (newUserData.username !== undefined && storedData.username !== newUserData.username) ||
                    (newUserData.profileImageUrl !== undefined && storedData.profileImageUrl !== newUserData.profileImageUrl) ||
                    (newUserData.credits !== undefined && storedData.credits !== newUserData.credits) ||
                    (newUserData.isAdmin !== undefined && storedData.isAdmin !== newUserData.isAdmin);
                
                resolve(hasChanges);
            };

            userRequest.onerror = () => {
                console.error("[UserDatabase] Error checking user data changes:", userRequest.error);
                reject(userRequest.error);
            };
        });
    }

    /**
     * Get complete user data from IndexedDB
     */
    async getUserData(): Promise<User | null> {
        if (!this.db) {
            await this.init();
        }

        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction([this.STORE_NAME], 'readonly');
            const store = transaction.objectStore(this.STORE_NAME);
            
            const username = store.get('username');
            const isAdmin = store.get('isAdmin');
            const profileImageUrl = store.get('profileImageUrl');
            const credits = store.get('credits');
            
            let userData: User = {
                username: '',
                isAdmin: false,
                profileImageUrl: null,
                credits: 0
            };

            username.onsuccess = () => userData.username = username.result || '';
            isAdmin.onsuccess = () => userData.isAdmin = !!isAdmin.result;
            profileImageUrl.onsuccess = () => userData.profileImageUrl = profileImageUrl.result;
            credits.onsuccess = () => userData.credits = credits.result || 0;

            transaction.oncomplete = () => {
                console.debug("[UserDatabase] User data retrieved:", userData);
                resolve(userData);
            };

            transaction.onerror = () => {
                console.error("[UserDatabase] Error retrieving user data:", transaction.error);
                reject(transaction.error);
            };
        });
    }

    /**
     * Update specific fields of the user data
     */
    async updateUserData(partialData: Partial<User>): Promise<void> {
        if (!this.db) {
            await this.init();
        }

        return new Promise((resolve, reject) => {
            const transaction = this.db!.transaction([this.STORE_NAME], 'readwrite');
            const store = transaction.objectStore(this.STORE_NAME);
            
            if (partialData.username !== undefined) {
                store.put(partialData.username, 'username');
            }
            
            if (partialData.profileImageUrl !== undefined) {
                store.put(partialData.profileImageUrl, 'profileImageUrl');
            }
            
            if (partialData.credits !== undefined) {
                store.put(partialData.credits, 'credits');
            }
            
            if (partialData.isAdmin !== undefined) {
                store.put(partialData.isAdmin, 'isAdmin');
            }
            
            transaction.oncomplete = () => {
                console.debug("[UserDatabase] User data updated successfully");
                resolve();
            };
            
            transaction.onerror = () => {
                console.error("[UserDatabase] Error updating user data:", transaction.error);
                reject(transaction.error);
            };
        });
    }
}

export const userDB = new UserDatabaseService();
