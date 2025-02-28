import { writable } from 'svelte/store';
// Remove the problematic import
// import { getTranslation } from '@repo/ui';

export type BreadcrumbItem = {
    path: string;
    title: string;
    icon?: string;
    translationKey?: string;
};

export type SettingsNavigationState = {
    breadcrumbs: BreadcrumbItem[];
    currentPath: string;
    history: string[];
};

const initialState: SettingsNavigationState = {
    breadcrumbs: [
        {
            path: 'settings',
            title: 'Settings',
            translationKey: 'settings.settings'
        }
    ],
    currentPath: 'settings',
    history: ['settings']
};

export const settingsNavigationStore = writable<SettingsNavigationState>(initialState);

// Update this function to use the text from the component instead
export function updateBreadcrumbsWithLanguage(textStore) {
    if (!textStore) return;

    settingsNavigationStore.update(state => {
        const updatedBreadcrumbs = state.breadcrumbs.map(crumb => {
            if (crumb.translationKey) {
                return {
                    ...crumb,
                    // Use the text store directly to get translations
                    title: textStore(crumb.translationKey + '.text')
                };
            }
            return crumb;
        });

        return {
            ...state,
            breadcrumbs: updatedBreadcrumbs
        };
    });
}

/**
 * Navigate to a settings page with its breadcrumb path
 */
export function navigateToSettings(path: string, title: string, icon?: string, translationKey?: string): void {
    settingsNavigationStore.update(state => {
        const newBreadcrumb = {
            path,
            title,
            icon,
            translationKey
        };

        // Find if this path already exists in breadcrumbs
        const existingIndex = state.breadcrumbs.findIndex(crumb => crumb.path === path);
        
        if (existingIndex >= 0) {
            // If it exists, truncate the array to this point (remove any deeper paths)
            const updatedBreadcrumbs = state.breadcrumbs.slice(0, existingIndex + 1);
            return {
                ...state,
                breadcrumbs: updatedBreadcrumbs,
                currentPath: path,
                history: [...state.history, path]
            };
        }
        
        // Otherwise add this new breadcrumb
        return {
            ...state,
            breadcrumbs: [...state.breadcrumbs, newBreadcrumb],
            currentPath: path,
            history: [...state.history, path]
        };
    });
}

/**
 * Go back in the settings navigation history
 */
export function navigateBackInSettings(): void {
    settingsNavigationStore.update(state => {
        if (state.breadcrumbs.length <= 1) {
            return state;
        }
        
        // Remove the last item from breadcrumbs
        const updatedBreadcrumbs = state.breadcrumbs.slice(0, -1);
        const previousPath = updatedBreadcrumbs[updatedBreadcrumbs.length - 1].path;
        
        return {
            ...state,
            breadcrumbs: updatedBreadcrumbs,
            currentPath: previousPath,
            history: [...state.history, previousPath]
        };
    });
}
