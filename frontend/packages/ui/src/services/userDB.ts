import type { User } from '../types/user';
// Import UserProfile type which will include the new consent fields
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

            // console.debug(userData);

            // CRITICAL: Preserve local last_opened if server value is empty/null/undefined
            // This prevents server sync from overwriting the user's current chat selection on tab reload
            // Only update last_opened from server if it has a meaningful value
            const lastOpenedRequest = store.get('last_opened');
            let localLastOpened: string = '';
            
            lastOpenedRequest.onsuccess = () => {
                localLastOpened = lastOpenedRequest.result || '';
                
                // Only store essential fields
                // Store user ID (required for hidden chat salt generation and other features)
                if (userData.id) {
                    store.put(userData.id, 'id');
                }
                store.put(userData.username || '', 'username');
                store.put(!!userData.is_admin, 'is_admin');  // Convert to boolean
                 store.put(userData.profile_image_url || null, 'profile_image_url');
                 store.put(userData.credits || 0, 'credits');
                 store.put(userData.tfa_app_name || null, 'tfa_app_name');
                 store.put(!!userData.tfa_enabled, 'tfa_enabled'); // Store 2FA enabled status
                 // Use boolean flags from backend
                 store.put(!!userData.consent_privacy_and_apps_default_settings, 'consent_privacy_and_apps_default_settings');
                 store.put(!!userData.consent_mates_default_settings, 'consent_mates_default_settings');
                 // Add language and darkmode
                 store.put(userData.language || 'en', 'language');
                 store.put(!!userData.darkmode, 'darkmode');
                 store.put(userData.currency || '', 'currency'); // Save currency
                 store.put(userData.last_sync_timestamp || 0, 'last_sync_timestamp');
                 
                 // CRITICAL: Preserve local last_opened if server value is empty/null/undefined
                 // Only update from server if server has a meaningful value (not null, undefined, or empty string)
                 // This ensures tab reload uses the user's current chat selection, not stale server data
                 const serverLastOpened = userData.last_opened;
                 if (serverLastOpened && serverLastOpened.trim() !== '') {
                     // Server has a meaningful value, use it (for cross-device sync)
                     store.put(serverLastOpened, 'last_opened');
                     console.debug(`[UserDatabase] Updated last_opened from server: ${serverLastOpened}`);
                 } else if (localLastOpened) {
                     // Server value is empty/null, preserve local value
                     store.put(localLastOpened, 'last_opened');
                     console.debug(`[UserDatabase] Preserved local last_opened (server value was empty): ${localLastOpened}`);
                 } else {
                     // Both are empty, store empty string
                     store.put('', 'last_opened');
                 }
                 
                 // Save top recommended apps (encrypted)
                 if (userData.encrypted_top_recommended_apps !== undefined) {
                     store.put(userData.encrypted_top_recommended_apps, 'encrypted_top_recommended_apps');
                 }
                 // Save top recommended apps (decrypted, for local use)
                 if (userData.top_recommended_apps !== undefined) {
                     store.put(JSON.stringify(userData.top_recommended_apps || []), 'top_recommended_apps');
                 }
                 // Save random explore apps and timestamp
                 if (userData.random_explore_apps !== undefined) {
                     store.put(JSON.stringify(userData.random_explore_apps || []), 'random_explore_apps');
                 }
                 if (userData.random_explore_apps_timestamp !== undefined) {
                     store.put(userData.random_explore_apps_timestamp || 0, 'random_explore_apps_timestamp');
                 }
                 // Save auto top-up fields - log error if missing from backend response
                 if ('auto_topup_low_balance_enabled' in userData) {
                     store.put(!!userData.auto_topup_low_balance_enabled, 'auto_topup_low_balance_enabled');
                 } else {
                     console.error('[UserDatabase] ERROR: auto_topup_low_balance_enabled missing from backend response! Available keys:', Object.keys(userData));
                 }
                 if ('auto_topup_low_balance_threshold' in userData) {
                     store.put(userData.auto_topup_low_balance_threshold ?? null, 'auto_topup_low_balance_threshold');
                 } else {
                     console.error('[UserDatabase] ERROR: auto_topup_low_balance_threshold missing from backend response!');
                 }
                 if ('auto_topup_low_balance_amount' in userData) {
                     store.put(userData.auto_topup_low_balance_amount ?? null, 'auto_topup_low_balance_amount');
                 } else {
                     console.error('[UserDatabase] ERROR: auto_topup_low_balance_amount missing from backend response!');
                 }
                 if ('auto_topup_low_balance_currency' in userData) {
                     store.put(userData.auto_topup_low_balance_currency ?? null, 'auto_topup_low_balance_currency');
                 } else {
                     console.error('[UserDatabase] ERROR: auto_topup_low_balance_currency missing from backend response!');
                 }
            };
            
            lastOpenedRequest.onerror = () => {
                // If we can't read local last_opened, fall back to server value or empty string
                console.warn('[UserDatabase] Could not read local last_opened, using server value');
                const serverLastOpened = userData.last_opened;
                store.put(serverLastOpened || '', 'last_opened');
                
                // Still save other fields
                store.put(userData.username || '', 'username');
                store.put(!!userData.is_admin, 'is_admin');
                store.put(userData.profile_image_url || null, 'profile_image_url');
                store.put(userData.credits || 0, 'credits');
                store.put(userData.tfa_app_name || null, 'tfa_app_name');
                store.put(!!userData.tfa_enabled, 'tfa_enabled');
                store.put(!!userData.consent_privacy_and_apps_default_settings, 'consent_privacy_and_apps_default_settings');
                store.put(!!userData.consent_mates_default_settings, 'consent_mates_default_settings');
                store.put(userData.language || 'en', 'language');
                store.put(!!userData.darkmode, 'darkmode');
                store.put(userData.currency || '', 'currency');
                store.put(userData.last_sync_timestamp || 0, 'last_sync_timestamp');
                
                if (userData.encrypted_top_recommended_apps !== undefined) {
                    store.put(userData.encrypted_top_recommended_apps, 'encrypted_top_recommended_apps');
                }
                if (userData.top_recommended_apps !== undefined) {
                    store.put(JSON.stringify(userData.top_recommended_apps || []), 'top_recommended_apps');
                }
                if (userData.random_explore_apps !== undefined) {
                    store.put(JSON.stringify(userData.random_explore_apps || []), 'random_explore_apps');
                }
                if (userData.random_explore_apps_timestamp !== undefined) {
                    store.put(userData.random_explore_apps_timestamp || 0, 'random_explore_apps_timestamp');
                }
                // Save auto top-up fields - log error if missing from backend response
                if ('auto_topup_low_balance_enabled' in userData) {
                    store.put(!!userData.auto_topup_low_balance_enabled, 'auto_topup_low_balance_enabled');
                } else {
                    console.error('[UserDatabase] ERROR: auto_topup_low_balance_enabled missing from backend response (error path)! Available keys:', Object.keys(userData));
                }
                if ('auto_topup_low_balance_threshold' in userData) {
                    store.put(userData.auto_topup_low_balance_threshold ?? null, 'auto_topup_low_balance_threshold');
                } else {
                    console.error('[UserDatabase] ERROR: auto_topup_low_balance_threshold missing from backend response (error path)!');
                }
                if ('auto_topup_low_balance_amount' in userData) {
                    store.put(userData.auto_topup_low_balance_amount ?? null, 'auto_topup_low_balance_amount');
                } else {
                    console.error('[UserDatabase] ERROR: auto_topup_low_balance_amount missing from backend response (error path)!');
                }
                if ('auto_topup_low_balance_currency' in userData) {
                    store.put(userData.auto_topup_low_balance_currency ?? null, 'auto_topup_low_balance_currency');
                } else {
                    console.error('[UserDatabase] ERROR: auto_topup_low_balance_currency missing from backend response (error path)!');
                }
            };

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
            const profileImageRequest = store.get('profile_image_url');
            const creditsRequest = store.get('credits');
            const is_adminRequest = store.get('is_admin');
            const tfa_app_nameRequest = store.get('tfa_app_name');
            const tfaEnabledRequest = store.get('tfa_enabled'); // Get tfa_enabled
            const lastOpenedRequest = store.get('last_opened'); // Get last_opened
            const lastSyncTimestampRequest = store.get('last_sync_timestamp');
            // Add requests for boolean consent flags
            const consentPrivacyRequest = store.get('consent_privacy_and_apps_default_settings');
            const consentMatesRequest = store.get('consent_mates_default_settings');
            // Add requests for language and darkmode
            const languageRequest = store.get('language');
            const darkmodeRequest = store.get('darkmode');
            
            let profile: UserProfile = {
                username: '',
                profile_image_url: null,
                credits: 0,
                is_admin: false,
                last_opened: '', // Initialize last_opened
                last_sync_timestamp: 0,
                tfa_app_name: null,
                tfa_enabled: false, // Initialize tfa_enabled
                // Initialize boolean flags
                consent_privacy_and_apps_default_settings: false,
                consent_mates_default_settings: false,
                language: 'en', // Initialize language
                darkmode: false, // Initialize darkmode
                currency: '' // Initialize currency
            };

            const currencyRequest = store.get('currency'); // Add request for currency
            const topRecommendedAppsRequest = store.get('top_recommended_apps'); // Get top recommended apps (decrypted)
            const encryptedTopRecommendedAppsRequest = store.get('encrypted_top_recommended_apps'); // Get encrypted version
            const randomExploreAppsRequest = store.get('random_explore_apps'); // Get random explore apps
            const randomExploreAppsTimestampRequest = store.get('random_explore_apps_timestamp'); // Get timestamp
            // Add requests for auto top-up fields
            const autoTopupLowBalanceEnabledRequest = store.get('auto_topup_low_balance_enabled');
            const autoTopupLowBalanceThresholdRequest = store.get('auto_topup_low_balance_threshold');
            const autoTopupLowBalanceAmountRequest = store.get('auto_topup_low_balance_amount');
            const autoTopupLowBalanceCurrencyRequest = store.get('auto_topup_low_balance_currency');

            usernameRequest.onsuccess = () => {
                profile.username = usernameRequest.result || '';
            };

            profileImageRequest.onsuccess = () => {
                profile.profile_image_url = profileImageRequest.result || null;
            };

            creditsRequest.onsuccess = () => {
                profile.credits = creditsRequest.result || 0;
            };

            is_adminRequest.onsuccess = () => {
                profile.is_admin = !!is_adminRequest.result;
            };

            tfa_app_nameRequest.onsuccess = () => {
                profile.tfa_app_name = tfa_app_nameRequest.result || null;
            };

            tfaEnabledRequest.onsuccess = () => { // Handle tfa_enabled retrieval
                profile.tfa_enabled = !!tfaEnabledRequest.result;
            };

            lastOpenedRequest.onsuccess = () => { // Handle last_opened retrieval
                profile.last_opened = lastOpenedRequest.result || '';
            };

            lastSyncTimestampRequest.onsuccess = () => {
                profile.last_sync_timestamp = lastSyncTimestampRequest.result || 0;
            };

            // Handle boolean flag retrieval
            consentPrivacyRequest.onsuccess = () => {
                profile.consent_privacy_and_apps_default_settings = !!consentPrivacyRequest.result;
            };
            consentMatesRequest.onsuccess = () => {
                profile.consent_mates_default_settings = !!consentMatesRequest.result;
            };

            // Handle language and darkmode retrieval
            languageRequest.onsuccess = () => {
                profile.language = languageRequest.result || 'en';
            };
            darkmodeRequest.onsuccess = () => {
                profile.darkmode = !!darkmodeRequest.result;
            };

            currencyRequest.onsuccess = () => { // Handle currency retrieval
                profile.currency = currencyRequest.result || '';
            };

            topRecommendedAppsRequest.onsuccess = () => { // Handle top recommended apps retrieval
                try {
                    profile.top_recommended_apps = topRecommendedAppsRequest.result 
                        ? JSON.parse(topRecommendedAppsRequest.result) 
                        : undefined;
                } catch (e) {
                    console.warn('[UserDatabase] Failed to parse top_recommended_apps:', e);
                    profile.top_recommended_apps = undefined;
                }
            };

            encryptedTopRecommendedAppsRequest.onsuccess = () => { // Handle encrypted top recommended apps retrieval
                profile.encrypted_top_recommended_apps = encryptedTopRecommendedAppsRequest.result || null;
            };

            randomExploreAppsRequest.onsuccess = () => { // Handle random explore apps retrieval
                try {
                    profile.random_explore_apps = randomExploreAppsRequest.result 
                        ? JSON.parse(randomExploreAppsRequest.result) 
                        : undefined;
                } catch (e) {
                    console.warn('[UserDatabase] Failed to parse random_explore_apps:', e);
                    profile.random_explore_apps = undefined;
                }
            };

            randomExploreAppsTimestampRequest.onsuccess = () => { // Handle random explore apps timestamp retrieval
                profile.random_explore_apps_timestamp = randomExploreAppsTimestampRequest.result || undefined;
            };

            // Handle auto top-up fields retrieval
            autoTopupLowBalanceEnabledRequest.onsuccess = () => {
                profile.auto_topup_low_balance_enabled = autoTopupLowBalanceEnabledRequest.result !== undefined 
                    ? !!autoTopupLowBalanceEnabledRequest.result 
                    : undefined;
            };
            autoTopupLowBalanceThresholdRequest.onsuccess = () => {
                profile.auto_topup_low_balance_threshold = autoTopupLowBalanceThresholdRequest.result !== undefined 
                    ? autoTopupLowBalanceThresholdRequest.result 
                    : undefined;
            };
            autoTopupLowBalanceAmountRequest.onsuccess = () => {
                profile.auto_topup_low_balance_amount = autoTopupLowBalanceAmountRequest.result !== undefined 
                    ? autoTopupLowBalanceAmountRequest.result 
                    : undefined;
            };
            autoTopupLowBalanceCurrencyRequest.onsuccess = () => {
                profile.auto_topup_low_balance_currency = autoTopupLowBalanceCurrencyRequest.result || undefined;
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
            
            const clearRequest = store.clear();
            
            clearRequest.onsuccess = () => {
                console.debug("[UserDatabase] User data cleared successfully");
                resolve();
            };

            clearRequest.onerror = () => { // Correct placement
                console.error("[UserDatabase] Error clearing user data:", clearRequest.error);
                reject(clearRequest.error);
            };
        });
    }
    // Removed duplicated closing brackets and incorrect onerror block from here

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
                    (newUserData.profile_image_url !== undefined && storedData.profile_image_url !== newUserData.profile_image_url) ||
                    (newUserData.credits !== undefined && storedData.credits !== newUserData.credits) ||
                    (newUserData.is_admin !== undefined && storedData.is_admin !== newUserData.is_admin) ||
                    (newUserData.tfa_app_name !== undefined && storedData.tfa_app_name !== newUserData.tfa_app_name) || // Check tfa_app_name
                    (newUserData.currency !== undefined && storedData.currency !== newUserData.currency); // Check currency
                
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
            
            const id = store.get('id');
            const username = store.get('username');
            const is_admin = store.get('is_admin');
            const profile_image_url = store.get('profile_image_url');
            const credits = store.get('credits');
            const tfa_app_name = store.get('tfa_app_name'); // Get tfa_app_name
            const currency = store.get('currency'); // Get currency
            const last_sync_timestamp = store.get('last_sync_timestamp');
            
            let userData: User = {
                username: '',
                is_admin: false,
                profile_image_url: null,
                credits: 0,
                tfa_app_name: null, // Initialize tfa_app_name
                currency: '', // Initialize currency
                last_sync_timestamp: 0
            };

            id.onsuccess = () => userData.id = id.result || undefined;
            username.onsuccess = () => userData.username = username.result || '';
            is_admin.onsuccess = () => userData.is_admin = !!is_admin.result;
            profile_image_url.onsuccess = () => userData.profile_image_url = profile_image_url.result;
            credits.onsuccess = () => userData.credits = credits.result || 0;
            tfa_app_name.onsuccess = () => userData.tfa_app_name = tfa_app_name.result; // Assign tfa_app_name
            currency.onsuccess = () => userData.currency = currency.result || ''; // Assign currency
            last_sync_timestamp.onsuccess = () => userData.last_sync_timestamp = last_sync_timestamp.result || 0;

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
            
            if (partialData.profile_image_url !== undefined) {
                store.put(partialData.profile_image_url, 'profile_image_url');
            }
            
            if (partialData.credits !== undefined) {
                store.put(partialData.credits, 'credits');
            }
            
            if (partialData.is_admin !== undefined) {
                store.put(partialData.is_admin, 'is_admin');
            }

             if (partialData.tfa_app_name !== undefined) {
                 store.put(partialData.tfa_app_name, 'tfa_app_name');
             }

             if (partialData.tfa_enabled !== undefined) { // Handle tfa_enabled update
                 store.put(!!partialData.tfa_enabled, 'tfa_enabled');
             }

             // Handle boolean flag updates
             if (partialData.consent_privacy_and_apps_default_settings !== undefined) {
                 store.put(!!partialData.consent_privacy_and_apps_default_settings, 'consent_privacy_and_apps_default_settings');
             }
             if (partialData.consent_mates_default_settings !== undefined) {
                 store.put(!!partialData.consent_mates_default_settings, 'consent_mates_default_settings');
             }
             // Add explicit handling for language and darkmode
             if (partialData.language !== undefined) {
                 store.put(partialData.language, 'language');
             }
             if (partialData.darkmode !== undefined) {
                 store.put(!!partialData.darkmode, 'darkmode');
             }
             if (partialData.currency !== undefined) { // Handle currency update
                 store.put(partialData.currency, 'currency');
             }
             if (partialData.last_sync_timestamp !== undefined) {
                store.put(partialData.last_sync_timestamp, 'last_sync_timestamp');
             }
             
             if (partialData.last_opened !== undefined) {
                store.put(partialData.last_opened, 'last_opened');
             }
             
             // Handle auto top-up fields updates
             if (partialData.auto_topup_low_balance_enabled !== undefined) {
                 store.put(!!partialData.auto_topup_low_balance_enabled, 'auto_topup_low_balance_enabled');
             }
             if (partialData.auto_topup_low_balance_threshold !== undefined) {
                 store.put(partialData.auto_topup_low_balance_threshold, 'auto_topup_low_balance_threshold');
             }
             if (partialData.auto_topup_low_balance_amount !== undefined) {
                 store.put(partialData.auto_topup_low_balance_amount, 'auto_topup_low_balance_amount');
             }
             if (partialData.auto_topup_low_balance_currency !== undefined) {
                 store.put(partialData.auto_topup_low_balance_currency, 'auto_topup_low_balance_currency');
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

    /**
     * Deletes the entire user database.
     */
    async deleteDatabase(): Promise<void> {
        console.debug(`[UserDatabase] Attempting to delete database: ${this.DB_NAME}`);
        return new Promise((resolve, reject) => {
            if (this.db) {
                this.db.close(); // Close the connection before deleting
                this.db = null;
                console.debug(`[UserDatabase] Database connection closed for ${this.DB_NAME}.`);
            }

            const request = indexedDB.deleteDatabase(this.DB_NAME);

            request.onsuccess = () => {
                console.debug(`[UserDatabase] Database ${this.DB_NAME} deleted successfully.`);
                resolve();
            };

            request.onerror = (event) => {
                console.error(`[UserDatabase] Error deleting database ${this.DB_NAME}:`, (event.target as IDBOpenDBRequest).error);
                reject((event.target as IDBOpenDBRequest).error);
            };

            request.onblocked = (event) => {
                console.warn(`[UserDatabase] Deletion of database ${this.DB_NAME} blocked. Close other tabs/connections.`, event);
                reject(new Error(`Database ${this.DB_NAME} deletion blocked. Please close other tabs using the application and try again.`));
            };
        });
    }
}

export const userDB = new UserDatabaseService();
