/**
 * Configuration file to manage page visibility across different environments
 * 
 * @property path - The route path for the page
 * @property title - The page title
 * @property inDev - Whether the page should be visible in development
 * @property inProd - Whether the page should be visible in production
 */
export interface PageConfig {
    path: string;
    title: string;
    inDev: boolean;
    inProd: boolean;
}

/**
 * Central configuration object for all pages in the application
 */
export const pages: Record<string, PageConfig> = {
    home: {
        path: '/',
        title: 'Home',
        inDev: true,
        inProd: true
    },
    developers: {
        path: '/developers',
        title: 'For Developers',
        inDev: true,
        inProd: false
    },
    docs: {
        path: '/docs',
        title: 'Documentation',
        inDev: true,
        inProd: false
    },
    apiDocs: {
        path: '/docs/api',
        title: 'API Documentation',
        inDev: true,
        inProd: false
    },
    designGuidelines: {
        path: '/docs/design_guidelines',
        title: 'Design Guidelines',
        inDev: true,
        inProd: false
    },
    designSystem: {
        path: '/docs/design_system',
        title: 'Design System',
        inDev: true,
        inProd: false
    },
    roadmap: {
        path: '/docs/roadmap',
        title: 'Roadmap',
        inDev: true,
        inProd: false
    },
    imprint: {
        path: '/legal/imprint',
        title: 'Imprint',
        inDev: true,
        inProd: true
    },
    privacy: {
        path: '/legal/privacy',
        title: 'Privacy Policy',
        inDev: true,
        inProd: true
    },
    terms: {
        path: '/legal/terms',
        title: 'Terms and Conditions',
        inDev: true,
        inProd: true
    }
};

/**
 * Helper function to get visible pages based on current environment
 */
export function getVisiblePages(): PageConfig[] {
    const isDev = import.meta.env.DEV;
    return Object.values(pages).filter(page => 
        isDev ? page.inDev : page.inProd
    );
}

/**
 * Helper function to check if a page should be visible
 */
export function isPageVisible(path: string): boolean {
    const isDev = import.meta.env.DEV;
    const page = Object.values(pages).find(p => p.path === path);
    if (!page) return false;
    return isDev ? page.inDev : page.inProd;
} 