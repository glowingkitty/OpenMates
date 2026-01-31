// frontend/packages/ui/src/data/matesMetadata.ts
//
// Static metadata for AI mates (personas) available for user selection.
// This data is used for the @ mention dropdown to allow users to select specific mates.
//
// Mates are AI personas with expertise in specific domains.
// Their display names are localized via translation keys (e.g., 'mates.software_development.text').

/**
 * Mate metadata structure for frontend display.
 */
export interface MateMetadata {
    /** Unique mate identifier (matches CSS class and translation key) */
    id: string;
    /** Translation key for the mate's display name */
    name_translation_key: string;
    /** Translation key for the mate's expertise description */
    description_translation_key: string;
    /** CSS class suffix for the mate's profile image */
    profile_class: string;
    /** Icon class suffix for the mate's expertise area */
    expertise_icon?: string;
    /** Search names for the mate (includes display name and expertise keywords) */
    search_names: string[];
}

/**
 * Static mates metadata for the @ mention dropdown.
 * 
 * Mates are ordered by typical usage popularity.
 * The id matches:
 * - CSS class: `.mate-profile.{id}` for profile images
 * - Translation key: `mates.{id}.text` for display name
 */
export const matesMetadata: MateMetadata[] = [
    {
        id: 'software_development',
        name_translation_key: 'mates.software_development.text',
        description_translation_key: 'mate_descriptions.software_development.text',
        profile_class: 'software_development',
        expertise_icon: 'code',
        search_names: ['sophia', 'software', 'development', 'coding', 'programming', 'developer'],
    },
    {
        id: 'business_development',
        name_translation_key: 'mates.business_development.text',
        description_translation_key: 'mate_descriptions.business_development.text',
        profile_class: 'business_development',
        expertise_icon: 'business',
        search_names: ['burton', 'business', 'development', 'strategy', 'entrepreneur'],
    },
    {
        id: 'life_coach_psychology',
        name_translation_key: 'mates.life_coach_psychology.text',
        description_translation_key: 'mate_descriptions.life_coach_psychology.text',
        profile_class: 'life_coach_psychology',
        expertise_icon: 'psychology',
        search_names: ['lisa', 'life', 'coach', 'psychology', 'mental', 'therapist', 'counselor'],
    },
    {
        id: 'medical_health',
        name_translation_key: 'mates.medical_health.text',
        description_translation_key: 'mate_descriptions.medical_health.text',
        profile_class: 'medical_health',
        expertise_icon: 'health',
        search_names: ['melvin', 'medical', 'health', 'doctor', 'medicine', 'healthcare'],
    },
    {
        id: 'legal_law',
        name_translation_key: 'mates.legal_law.text',
        description_translation_key: 'mate_descriptions.legal_law.text',
        profile_class: 'legal_law',
        expertise_icon: 'law',
        search_names: ['leon', 'legal', 'law', 'lawyer', 'attorney', 'contract'],
    },
    {
        id: 'finance',
        name_translation_key: 'mates.finance.text',
        description_translation_key: 'mate_descriptions.finance.text',
        profile_class: 'finance',
        expertise_icon: 'finance',
        search_names: ['finn', 'finance', 'financial', 'investment', 'money', 'accounting'],
    },
    {
        id: 'design',
        name_translation_key: 'mates.design.text',
        description_translation_key: 'mate_descriptions.design.text',
        profile_class: 'design',
        expertise_icon: 'design',
        search_names: ['denise', 'design', 'designer', 'ui', 'ux', 'graphic', 'creative'],
    },
    {
        id: 'marketing_sales',
        name_translation_key: 'mates.marketing_sales.text',
        description_translation_key: 'mate_descriptions.marketing_sales.text',
        profile_class: 'marketing_sales',
        expertise_icon: 'marketing',
        search_names: ['mark', 'marketing', 'sales', 'advertising', 'promotion'],
    },
    {
        id: 'science',
        name_translation_key: 'mates.science.text',
        description_translation_key: 'mate_descriptions.science.text',
        profile_class: 'science',
        expertise_icon: 'science',
        search_names: ['scarlett', 'science', 'scientist', 'research', 'physics', 'chemistry', 'biology'],
    },
    {
        id: 'history',
        name_translation_key: 'mates.history.text',
        description_translation_key: 'mate_descriptions.history.text',
        profile_class: 'history',
        expertise_icon: 'history',
        search_names: ['hiro', 'history', 'historian', 'historical', 'past', 'ancient'],
    },
    {
        id: 'cooking_food',
        name_translation_key: 'mates.cooking_food.text',
        description_translation_key: 'mate_descriptions.cooking_food.text',
        profile_class: 'cooking_food',
        expertise_icon: 'cooking',
        search_names: ['colin', 'cooking', 'food', 'chef', 'recipe', 'cuisine', 'kitchen'],
    },
    {
        id: 'electrical_engineering',
        name_translation_key: 'mates.electrical_engineering.text',
        description_translation_key: 'mate_descriptions.electrical_engineering.text',
        profile_class: 'electrical_engineering',
        expertise_icon: 'engineering',
        search_names: ['elton', 'electrical', 'engineering', 'electronics', 'circuits', 'engineer'],
    },
    {
        id: 'maker_prototyping',
        name_translation_key: 'mates.maker_prototyping.text',
        description_translation_key: 'mate_descriptions.maker_prototyping.text',
        profile_class: 'maker_prototyping',
        expertise_icon: 'maker',
        search_names: ['makani', 'maker', 'prototyping', 'diy', 'fabrication', '3d printing'],
    },
    {
        id: 'movies_tv',
        name_translation_key: 'mates.movies_tv.text',
        description_translation_key: 'mate_descriptions.movies_tv.text',
        profile_class: 'movies_tv',
        expertise_icon: 'entertainment',
        search_names: ['monika', 'movies', 'tv', 'television', 'film', 'cinema', 'entertainment'],
    },
    {
        id: 'activism',
        name_translation_key: 'mates.activism.text',
        description_translation_key: 'mate_descriptions.activism.text',
        profile_class: 'activism',
        expertise_icon: 'activism',
        search_names: ['ace', 'activism', 'activist', 'social', 'change', 'advocacy'],
    },
    {
        id: 'general_knowledge',
        name_translation_key: 'mates.general_knowledge.text',
        description_translation_key: 'mate_descriptions.general_knowledge.text',
        profile_class: 'general_knowledge',
        expertise_icon: 'general',
        search_names: ['george', 'general', 'knowledge', 'trivia', 'facts', 'information'],
    },
];

/**
 * Get mates metadata as a record keyed by mate ID.
 */
export function getMatesById(): Record<string, MateMetadata> {
    return matesMetadata.reduce((acc, mate) => {
        acc[mate.id] = mate;
        return acc;
    }, {} as Record<string, MateMetadata>);
}

/**
 * Get the list of valid mate IDs for mention detection.
 * This replaces the hardcoded VALID_MATES array in mateHelpers.ts
 */
export function getValidMateIds(): string[] {
    return matesMetadata.map(mate => mate.id);
}
