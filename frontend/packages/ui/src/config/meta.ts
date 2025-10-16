import { getCurrentLanguage } from '../i18n/setup';

// Define interfaces for type safety
export interface MetaTagConfig {
    title: string;
    description: string;
    image: string;
    imageWidth: number;
    imageHeight: number;
    url: string;
    type: string;
    keywords: string[];
    author: string;
    locale: string;
    siteName: string;
    logo: string;
    logoWidth: number;
    logoHeight: number;
}

interface PageMetaTags {
    [key: string]: MetaTagConfig;
}

// Default meta values
export let defaultMeta: MetaTagConfig = {
    title: '',
    description: '',
    image: "/images/og-image.jpg",
    imageWidth: 1200,
    imageHeight: 630,
    url: "https://openmates.org",
    type: "website",
    keywords: [],
    author: "OpenMates Team",
    locale: "en_US",
    siteName: "OpenMates™",
    logo: "/images/logo.png",
    logoWidth: 436,
    logoHeight: 92,
};

// Page-specific meta tags
export let pageMeta: PageMetaTags = {
    // Add a default fallback structure
    for_all_of_us: { ...defaultMeta },
    for_developers: { ...defaultMeta },
    docs: { ...defaultMeta },
    docsApi: { ...defaultMeta },
    docsDesignGuidelines: { ...defaultMeta },
    docsDesignSystem: { ...defaultMeta },
    docsRoadmap: { ...defaultMeta },
    docsUserGuide: { ...defaultMeta },
    legalImprint: { ...defaultMeta },
    legalPrivacy: { ...defaultMeta },
    legalTerms: { ...defaultMeta },
    webapp: { ...defaultMeta },
};

// Function to load metatags dynamically based on the current language
export async function loadMetaTags(): Promise<void> {
    try {
        const currentLanguage = getCurrentLanguage();
        let metaData;
        
        // Try to load the current language's metadata
        try {
            metaData = await import(`../i18n/locales/${currentLanguage}.json`);
        } catch (e) {
            console.warn(`Metadata for language ${currentLanguage} not found, falling back to English`);
            // Fallback to English if current language metadata is not available
            metaData = await import(`../i18n/locales/en.json`);
        }
        
        // Check if metadata exists in the language file
        if (!metaData.metadata || !metaData.metadata.default) {
            console.warn(`Metadata structure missing in language ${currentLanguage}, falling back to English`);
            // Fallback to English metadata
            metaData = await import(`../i18n/locales/en.json`);
            
            // If English also doesn't have the metadata structure, use hardcoded defaults
            if (!metaData.metadata || !metaData.metadata.default) {
                throw new Error('Metadata structure missing in English language file');
            }
        }

        // Update defaultMeta
        defaultMeta = {
            title: metaData.metadata.default.title?.text || "OpenMates",
            description: metaData.metadata.default.description?.text || "",
            image: "/images/og-image.jpg",
            imageWidth: 1200,
            imageHeight: 630,
            url: "https://openmates.org",
            type: "website",
            keywords: (metaData.metadata.default.keywords?.text || "").split(', ').filter(Boolean),
            author: "OpenMates Team",
            locale: `${currentLanguage}_${currentLanguage.toUpperCase()}`,
            siteName: "OpenMates™",
            logo: "/images/logo.png",
            logoWidth: 436,
            logoHeight: 92,
        };

        // Safe function to get nested properties with fallback
        const getMetaProperty = (path: string[], fallback: string = ""): string => {
            let obj = metaData.metadata;
            for (const key of path) {
                if (!obj || typeof obj !== 'object') return fallback;
                obj = obj[key];
            }
            return obj?.text || fallback;
        };

        // Update pageMeta with safe property access
        pageMeta = {
            for_all_of_us: {
                ...defaultMeta,
                title: getMetaProperty(['for_all_of_us', 'title'], defaultMeta.title),
            },
            for_developers: {
                ...defaultMeta,
                title: getMetaProperty(['for_developers', 'title'], defaultMeta.title),
                description: getMetaProperty(['for_developers', 'description'], defaultMeta.description),
            },
            docs: {
                ...defaultMeta,
                title: getMetaProperty(['docs', 'title'], defaultMeta.title),
                description: getMetaProperty(['docs', 'description'], defaultMeta.description),
                type: "article"
            },
            docsApi: {
                ...defaultMeta,
                title: getMetaProperty(['docs_api', 'title'], defaultMeta.title),
                description: getMetaProperty(['docs_api', 'description'], defaultMeta.description),
            },
            docsDesignGuidelines: {
                ...defaultMeta,
                title: getMetaProperty(['docs_design_guidelines', 'title'], defaultMeta.title),
                description: getMetaProperty(['docs_design_guidelines', 'description'], defaultMeta.description),
            },
            docsDesignSystem: {
                ...defaultMeta,
                title: getMetaProperty(['docs_design_system', 'title'], defaultMeta.title),
                description: getMetaProperty(['docs_design_system', 'description'], defaultMeta.description),
            },
            docsRoadmap: {
                ...defaultMeta,
                title: getMetaProperty(['docs_roadmap', 'title'], defaultMeta.title),
                description: getMetaProperty(['docs_roadmap', 'description'], defaultMeta.description),
            },
            docsUserGuide: {
                ...defaultMeta,
                title: getMetaProperty(['docs_user_guide', 'title'], defaultMeta.title),
                description: getMetaProperty(['docs_user_guide', 'description'], defaultMeta.description),
            },
            legalImprint: {
                ...defaultMeta,
                title: getMetaProperty(['legal_imprint', 'title'], defaultMeta.title),
                description: getMetaProperty(['legal_imprint', 'description'], defaultMeta.description),
            },
            legalPrivacy: {
                ...defaultMeta,
                title: getMetaProperty(['legal_privacy', 'title'], defaultMeta.title),
                description: getMetaProperty(['legal_privacy', 'description'], defaultMeta.description),
            },
            legalTerms: {
                ...defaultMeta,
                title: getMetaProperty(['legal_terms', 'title'], defaultMeta.title),
                description: getMetaProperty(['legal_terms', 'description'], defaultMeta.description),
            },
            webapp: {
                ...defaultMeta,
                title: getMetaProperty(['webapp', 'title'], defaultMeta.title),
                description: getMetaProperty(['webapp', 'description'], defaultMeta.description),
                type: "website"
            },
        };
    } catch (error) {
        console.error('Failed to load meta tags:', error);
        // Keep using default values if loading fails
    }
}

// Load meta tags dynamically
loadMetaTags();

// Helper function to get meta tags for a specific page
export function getMetaTags(page: string = 'home'): MetaTagConfig {
    // Ensure we always return a valid meta config even if pageMeta[page] is undefined
    return pageMeta[page] || defaultMeta;
}

// Helper function to generate dynamic meta tags (e.g., for blog posts or docs)
export function generateMetaTags(
    title: string,
    description: string,
    slug: string,
    type: string = 'article',
    keywords?: string[]
): MetaTagConfig {
    return {
        ...defaultMeta,
        title: `${title} | ${defaultMeta.siteName}`,
        description,
        url: `${defaultMeta.url}/${slug}`,
        type,
        keywords: keywords || defaultMeta.keywords
    };
}