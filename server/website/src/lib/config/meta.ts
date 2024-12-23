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
    description: "Your personalized digital team mates can answer complex questions, fulfil your tasks and use apps that can transform your everyday life & work. Build with a focus on privacy and safety.",
    image: "/images/og-image.png",
    imageWidth: 1200,
    imageHeight: 630,
    url: "https://openmates.org",
    type: "website",
    keywords: ["AI", "artificial intelligence", "team mates", "digital", "virtual assistant", "automation", "productivity", "privacy", "safety"],
    author: "OpenMates Team",
    locale: "en_US",
    siteName: "OpenMates",
    logo: "/images/logo.png",
    logoWidth: 436,
    logoHeight: 92,
};

// Page-specific meta tags

export const pageMeta: PageMetaTags = {
    for_all_of_us: {
        ...defaultMeta,
        title: "For all of us | OpenMates"
    },
    for_developers: {
        ...defaultMeta,
        title: "For developers | OpenMates",
        description: "The most versatile API for developers. For building AI agents, or simply integrating a wide range of existing APIs easily into your project.",
    },
    docs: {
        ...defaultMeta,
        title: "Docs | OpenMates",
        description: "Comprehensive documentation for OpenMates - from API documentation, to the Design Guidelines, Roadmap and more.",
        type: "article"
    },
    docsApi: {
        ...defaultMeta,
        title: "API docs | OpenMates",
        description: "API documentation for integrating OpenMates into your applications. Fronm building your own AI agent or chatbot, to integrating a wide range of existing APIs easily into your project.",
    },
    docsDesignGuidelines: {
        ...defaultMeta,
        title: "Design guidelines | OpenMates",
        description: "The Design Guidelines that define how OpenMates is designed and built.",
    },
    docsDesignSystem: {
        ...defaultMeta,
        title: "Design system | OpenMates",
        description: "The Design System that shows all the components that are used in OpenMates.",
    },
    docsRoadmap: {
        ...defaultMeta,
        title: "Roadmap | OpenMates",
        description: "Learn what is coming next for OpenMates. What the current state of the development is, and what the next milestones are.",
    },
    docsUserGuide: {
        ...defaultMeta,
        title: "User guide | OpenMates",
        description: "Learn how to use OpenMates.",
    },
    legalImprint: {
        ...defaultMeta,
        title: "Imprint | OpenMates",
        description: "Learn who is behind OpenMates.",
    },
    legalPrivacy: {
        ...defaultMeta,
        title: "Privacy | OpenMates",
        description: "Learn how OpenMates handles your personal data.",
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