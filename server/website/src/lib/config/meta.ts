// Define interfaces for type safety
export interface MetaTagConfig {
    title: string;
    description: string;
    image: string;
    url: string;
    type: string;
}

interface PageMetaTags {
    [key: string]: MetaTagConfig;
}

// Default meta values
export const defaultMeta: MetaTagConfig = {
    title: "OpenMates",
    description: "Your personalized AI team mates can answer your questions, fulfil your tasks and use apps that can transform your personal life & work. Build with a focus on privacy and safety.",
    image: "/images/og-image.png", // TODO
    url: "https://openmates.org",
    type: "website"
};

// Page-specific meta tags
export const pageMeta: PageMetaTags = {
    home: {
        ...defaultMeta,
        title: "For all of us  OpenMates"
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
        title: "Docs: API | OpenMates",
        description: "API documentation for integrating AI Team Mates into your applications.",
    },
    docsDesignGuidelines: {
        ...defaultMeta,
        title: "Docs: Design Guidelines | OpenMates",
        description: "Design guidelines for using AI Team Mates effectively.",
    },
    docsDesignSystem: {
        ...defaultMeta,
        title: "Docs: Design System | OpenMates",
        description: "Design system for using AI Team Mates effectively.",
    },
    docsRoadmap: {
        ...defaultMeta,
        title: "Docs: Roadmap | OpenMates",
        description: "Roadmap for using AI Team Mates effectively.",
    },
    docsUserGuide: {
        ...defaultMeta,
        title: "Docs: User Guide | OpenMates",
        description: "User guide for using AI Team Mates effectively.",
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
    type: string = 'article'
): MetaTagConfig {
    return {
        ...defaultMeta,
        title: `${title} - AI Team Mates`,
        description,
        url: `${defaultMeta.url}/${slug}`,
        type
    };
} 