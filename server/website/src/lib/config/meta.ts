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
    siteName: "OpenMates",
    logo: "/images/logo.png",
    logoWidth: 436,
    logoHeight: 92,
};

// Page-specific meta tags
export let pageMeta: PageMetaTags;

// Function to load metatags dynamically based on the current language
async function loadMetaTags() {
    const currentLanguage = getCurrentLanguage();
    const metaData = await import(`../../locales/${currentLanguage}.json`);
    defaultMeta = {
        title: metaData.metadata.default.title.text,
        description: metaData.metadata.default.description.text,
        image: "/images/og-image.jpg",
        imageWidth: 1200,
        imageHeight: 630,
        url: "https://openmates.org",
        type: "website",
        keywords: metaData.metadata.default.keywords.text.split(', '),
        author: "OpenMates Team",
        locale: "en_US",
        siteName: "OpenMates",
        logo: "/images/logo.png",
        logoWidth: 436,
        logoHeight: 92,
    };

    // Update pageMeta after loading
    pageMeta = {
        for_all_of_us: {
            ...defaultMeta,
            title: metaData.metadata.for_all_of_us.title.text,
        },
        for_developers: {
            ...defaultMeta,
            title: metaData.metadata.for_developers.title.text,
            description: metaData.metadata.for_developers.description.text,
        },
        docs: {
            ...defaultMeta,
            title: metaData.metadata.docs.title.text,
            description: metaData.metadata.docs.description.text,
            type: "article"
        },
        docsApi: {
            ...defaultMeta,
            title: metaData.metadata.docs_api.title.text,
            description: metaData.metadata.docs_api.description.text,
        },
        docsDesignGuidelines: {
            ...defaultMeta,
            title: metaData.metadata.docs_design_guidelines.title.text,
            description: metaData.metadata.docs_design_guidelines.description.text,
        },
        docsDesignSystem: {
            ...defaultMeta,
            title: metaData.metadata.docs_design_system.title.text,
            description: metaData.metadata.docs_design_system.description.text,
        },
        docsRoadmap: {
            ...defaultMeta,
            title: metaData.metadata.docs_roadmap.title.text,
            description: metaData.metadata.docs_roadmap.description.text,
        },
        docsUserGuide: {
            ...defaultMeta,
            title: metaData.metadata.docs_user_guide.title.text,
            description: metaData.metadata.docs_user_guide.description.text,
        },
        legalImprint: {
            ...defaultMeta,
            title: metaData.metadata.legal_imprint.title.text,
            description: metaData.metadata.legal_imprint.description.text,
        },
        legalPrivacy: {
            ...defaultMeta,
            title: metaData.metadata.legal_privacy.title.text,
            description: metaData.metadata.legal_privacy.description.text,
        },
        legalTerms: {
            ...defaultMeta,
            title: metaData.metadata.legal_terms.title.text,
            description: metaData.metadata.legal_terms.description.text,
        }
    };
}

// Load meta tags dynamically
loadMetaTags();

// Helper function to get meta tags for a specific page
export function getMetaTags(page: string = 'home'): MetaTagConfig {
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