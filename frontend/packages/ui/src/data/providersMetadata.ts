// frontend/packages/ui/src/data/providersMetadata.ts
//
// WARNING: THIS FILE IS AUTO-GENERATED - DO NOT EDIT MANUALLY
//
// Generated from backend/providers/*.yml by:
//   frontend/packages/ui/scripts/generate-providers-metadata.js
//
// To modify provider metadata, edit the source YAML files.
//
// **Generated**: 2026-02-27T15:47:26.854Z
// **Providers included**: 15

/**
 * Provider metadata for the provider detail pages in the App Store settings.
 */
export interface ProviderMetadata {
    /** Unique provider identifier (matches provider YAML provider_id) */
    id: string;
    /** Display name for the provider */
    name: string;
    /** Short description of the provider */
    description: string;
    /** Path to provider logo SVG (e.g., "icons/anthropic.svg") */
    logo_svg: string;
    /** ISO 3166-1 alpha-2 country code for provider origin, or "EU" */
    country: string;
}

/**
 * Static provider metadata included in the build.
 * Keyed by provider_id for O(1) lookup.
 */
export const providersMetadata: Record<string, ProviderMetadata> = {
    "alibaba": {
        id: "alibaba",
        name: "Alibaba",
        description: "Alibaba Cloud AI - Qwen models",
        logo_svg: "icons/alibaba.svg",
        country: "CN",
    },
    "anthropic": {
        id: "anthropic",
        name: "Anthropic",
        description: "AI models and services from Anthropic, including Claude family models.",
        logo_svg: "icons/anthropic.svg",
        country: "US",
    },
    "bfl": {
        id: "bfl",
        name: "Black Forest Labs",
        description: "High-performance image generation models including FLUX.2.",
        logo_svg: "icons/bfl.svg",
        country: "US",
    },
    "brave": {
        id: "brave",
        name: "Brave Search",
        description: "Privacy-preserving web search API with independent index.",
        logo_svg: "icons/brave.svg",
        country: "US",
    },
    "context7": {
        id: "context7",
        name: "Context7",
        description: "Documentation retrieval API for programming libraries and frameworks. Provides up-to-date documentation from official sources.",
        logo_svg: "icons/context7.svg",
        country: "US",
    },
    "deepseek": {
        id: "deepseek",
        name: "DeepSeek",
        description: "DeepSeek AI - High-performance reasoning and agent models",
        logo_svg: "icons/deepseek.svg",
        country: "CN",
    },
    "firecrawl": {
        id: "firecrawl",
        name: "Firecrawl",
        description: "Web scraping and crawling API for extracting content from websites.",
        logo_svg: "icons/firecrawl.svg",
        country: "US",
    },
    "google": {
        id: "google",
        name: "Google",
        description: "AI models and services from Google.",
        logo_svg: "icons/google.svg",
        country: "US",
    },
    "google_maps": {
        id: "google_maps",
        name: "Google Maps",
        description: "Google Maps Platform Places API for location-based search and place information.",
        logo_svg: "icons/google_maps.svg",
        country: "US",
    },
    "mistral": {
        id: "mistral",
        name: "Mistral AI",
        description: "AI models and services from Mistral AI.",
        logo_svg: "icons/mistral.svg",
        country: "FR",
    },
    "moonshot": {
        id: "moonshot",
        name: "Moonshot AI",
        description: "Moonshot AI - Kimi multimodal thinking and agent models",
        logo_svg: "icons/moonshot.svg",
        country: "CN",
    },
    "openai": {
        id: "openai",
        name: "OpenAI",
        description: "AI models and services from OpenAI.",
        logo_svg: "icons/openai.svg",
        country: "US",
    },
    "recraft": {
        id: "recraft",
        name: "Recraft",
        description: "State-of-the-art image generation for both raster (PNG/JPG) and vector (SVG) output. The only AI capable of producing true SVG vector graphics from text prompts.",
        logo_svg: "icons/recraft.svg",
        country: "US",
    },
    "youtube": {
        id: "youtube",
        name: "YouTube",
        description: "YouTube video transcript extraction via proxy service.",
        logo_svg: "icons/youtube.svg",
        country: "US",
    },
    "zai": {
        id: "zai",
        name: "Z.ai",
        description: "Z.ai - GLM large language models",
        logo_svg: "icons/zai.svg",
        country: "CN",
    },
};

/**
 * Look up a provider by name (case-insensitive).
 * Used to match app skill provider name strings (e.g. "Anthropic") to their metadata.
 */
export function findProviderByName(name: string): ProviderMetadata | undefined {
    const lowerName = name.toLowerCase().trim();
    return Object.values(providersMetadata).find(
        (p) => p.name.toLowerCase() === lowerName,
    );
}
