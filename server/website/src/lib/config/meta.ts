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
export const defaultMeta: MetaTagConfig = {
    title: "OpenMates",
    description: "Your personalized AI team mates can answer your questions, fulfil your tasks and use apps that can transform your personal life & work. Build with a focus on privacy and safety.",
    image: "/images/og-image.png", // TODO
    imageWidth: 1200,
    imageHeight: 630,
    url: "https://openmates.org",
    type: "website",
    keywords: ["AI", "artificial intelligence", "team mates", "automation", "productivity", "privacy", "safety"],
    author: "OpenMates Team",
    locale: "en_US",
    siteName: "OpenMates",
    logo: "/images/logo.jpg", // TODO
    logoWidth: 500,
    logoHeight: 500,
};

// Page-specific meta tags

// TODO change descriptions
export const pageMeta: PageMetaTags = {
    home: {
        ...defaultMeta,
        title: "For all of us | OpenMates"
    },
    developers: {
        ...defaultMeta,
        title: "For developers | OpenMates",
        description: "Technical documentation and API references for integrating AI Team Mates into your applications.",
    },
    docs: {
        ...defaultMeta,
        title: "Docs | OpenMates",
        description: "Comprehensive guides and documentation for using AI Team Mates effectively.",
        type: "article"
    },
    docsApi: {
        ...defaultMeta,
        title: "API docs | OpenMates",
        description: "API documentation for integrating AI Team Mates into your applications.",
    },
    docsDesignGuidelines: {
        ...defaultMeta,
        title: "Design guidelines | OpenMates",
        description: "Design guidelines for using AI Team Mates effectively.",
    },
    docsDesignSystem: {
        ...defaultMeta,
        title: "Design system | OpenMates",
        description: "Design system for using AI Team Mates effectively.",
    },
    docsRoadmap: {
        ...defaultMeta,
        title: "Roadmap | OpenMates",
        description: "Roadmap for using AI Team Mates effectively.",
    },
    docsUserGuide: {
        ...defaultMeta,
        title: "User guide | OpenMates",
        description: "User guide for using AI Team Mates effectively.",
    },
    legalImprint: {
        ...defaultMeta,
        title: "Imprint | OpenMates",
        description: "Imprint for OpenMates.",
    },
    legalPrivacy: {
        ...defaultMeta,
        title: "Privacy | OpenMates",
        description: "Privacy policy for OpenMates.",
    },
    legalTerms: {
        ...defaultMeta,
        title: "Terms and Conditions | OpenMates",
        description: "Terms of service for OpenMates.",
    },
};

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