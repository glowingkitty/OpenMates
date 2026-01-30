// frontend/packages/ui/src/data/modelsMetadata.ts
//
// Static metadata for AI models available for user selection.
// This data is used for the @ mention dropdown to allow users to select specific AI models.
//
// NOTE: This file could be auto-generated from backend/providers/*.yml in the future,
// similar to how appsMetadata.ts is generated from backend/apps/*/app.yml files.
//
// Models included here should have allow_auto_select: true in their provider YAML,
// indicating they are ready for production use.

/**
 * AI model metadata structure for frontend display.
 */
export interface AIModelMetadata {
    /** Unique model identifier (matches provider YAML) */
    id: string;
    /** Display name for the model */
    name: string;
    /** Brief description of the model's capabilities */
    description: string;
    /** Provider ID (anthropic, openai, google, mistral, etc.) */
    provider_id: string;
    /** Provider display name */
    provider_name: string;
    /** Path to provider logo SVG (relative to static/logos/) */
    logo_svg: string;
    /** ISO 3166-1 alpha-2 country code for model origin */
    country_origin: string;
    /** Supported input types */
    input_types: ('text' | 'image' | 'video' | 'audio')[];
    /** Supported output types */
    output_types: ('text' | 'image')[];
    /** Whether this is a reasoning/thinking model */
    reasoning?: boolean;
    /** Model tier for cost indication: economy, standard, premium */
    tier: 'economy' | 'standard' | 'premium';
}

/**
 * Static models metadata for the @ mention dropdown.
 * 
 * Models are ordered by typical usage popularity.
 * Only production-ready models are included.
 */
export const modelsMetadata: AIModelMetadata[] = [
    // Anthropic Claude models
    {
        id: 'claude-opus-4-5-20251101',
        name: 'Claude 4.5 Opus',
        description: 'Most powerful Claude model for complex tasks and research',
        provider_id: 'anthropic',
        provider_name: 'Anthropic',
        logo_svg: 'logos/anthropic.svg',
        country_origin: 'US',
        input_types: ['text', 'image'],
        output_types: ['text'],
        tier: 'premium',
    },
    {
        id: 'claude-sonnet-4-5-20250929',
        name: 'Claude 4.5 Sonnet',
        description: 'Optimal balance of intelligence, cost, and speed',
        provider_id: 'anthropic',
        provider_name: 'Anthropic',
        logo_svg: 'logos/anthropic.svg',
        country_origin: 'US',
        input_types: ['text', 'image'],
        output_types: ['text'],
        tier: 'standard',
    },
    {
        id: 'claude-haiku-4-5-20251001',
        name: 'Claude 4.5 Haiku',
        description: 'Fastest and most affordable Claude model',
        provider_id: 'anthropic',
        provider_name: 'Anthropic',
        logo_svg: 'logos/anthropic.svg',
        country_origin: 'US',
        input_types: ['text', 'image'],
        output_types: ['text'],
        tier: 'economy',
    },

    // OpenAI GPT models
    {
        id: 'gpt-5.2',
        name: 'GPT 5.2',
        description: 'Most advanced OpenAI model with enhanced reasoning',
        provider_id: 'openai',
        provider_name: 'OpenAI',
        logo_svg: 'logos/openai.svg',
        country_origin: 'US',
        input_types: ['text', 'image'],
        output_types: ['text'],
        reasoning: true,
        tier: 'premium',
    },

    // Google Gemini models
    {
        id: 'gemini-3-pro-preview',
        name: 'Gemini 3 Pro',
        description: 'Most intelligent Google model with SOTA reasoning',
        provider_id: 'google',
        provider_name: 'Google',
        logo_svg: 'logos/google.svg',
        country_origin: 'US',
        input_types: ['text', 'image', 'video', 'audio'],
        output_types: ['text'],
        reasoning: true,
        tier: 'premium',
    },
    {
        id: 'gemini-3-flash-preview',
        name: 'Gemini 3 Flash',
        description: 'Fast Gemini 3 model for quick responses',
        provider_id: 'google',
        provider_name: 'Google',
        logo_svg: 'logos/google.svg',
        country_origin: 'US',
        input_types: ['text', 'image', 'video', 'audio'],
        output_types: ['text'],
        reasoning: true,
        tier: 'standard',
    },
    {
        id: 'gemini-flash-latest',
        name: 'Gemini Flash Latest',
        description: 'Hybrid reasoning model with 1M token context',
        provider_id: 'google',
        provider_name: 'Google',
        logo_svg: 'logos/google.svg',
        country_origin: 'US',
        input_types: ['text', 'image', 'video', 'audio'],
        output_types: ['text'],
        reasoning: true,
        tier: 'economy',
    },
];

/**
 * Get models metadata as a record keyed by model ID.
 */
export function getModelsById(): Record<string, AIModelMetadata> {
    return modelsMetadata.reduce((acc, model) => {
        acc[model.id] = model;
        return acc;
    }, {} as Record<string, AIModelMetadata>);
}

/**
 * Get the top N most popular models for default display.
 * @param count - Number of models to return (default: 4)
 */
export function getTopModels(count: number = 4): AIModelMetadata[] {
    return modelsMetadata.slice(0, count);
}
